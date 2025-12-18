"""WinDbg/CDB automation wrapper for executing debugger commands."""

import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from rich.console import Console

from dump_debugger.config import settings

console = Console()


class DebuggerError(Exception):
    """Base exception for debugger-related errors."""
    pass


class DebuggerWrapper:
    """Wrapper for automating WinDbg/CDB commands."""

    def __init__(self, dump_path: Path, show_output: bool = False, session_dir: Path = None):
        """Initialize the debugger wrapper.
        
        Args:
            dump_path: Path to the memory dump file
            show_output: Whether to show command outputs (default: False)
            session_dir: Session directory for evidence storage (optional)
        """
        self.dump_path = dump_path
        self.symbol_path = settings.symbol_path
        self._symbols_loaded = False
        self.show_output = show_output
        self._process = None
        self._output_buffer = []
        self._output_lock = threading.Lock()
        self._reader_thread = None
        self._command_delimiter = f"===COMMAND_COMPLETE_{id(self)}==="
        
        # Evidence management
        self.session_dir = session_dir
        self.evidence_store = None
        self.evidence_analyzer = None
        self.embeddings_client = None
        if session_dir:
            from dump_debugger.evidence import EvidenceStore, EvidenceAnalyzer
            from dump_debugger.llm import get_llm
            
            self.evidence_store = EvidenceStore(session_dir)
            self.evidence_analyzer = EvidenceAnalyzer(get_llm())
            
            # Initialize embeddings client if enabled
            if settings.use_embeddings:
                self.embeddings_client = self._init_embeddings_client()

        if not self.dump_path.exists():
            raise FileNotFoundError(f"Dump file not found: {dump_path}")
        
        # Create symbol cache directory if it doesn't exist
        self._ensure_symbol_cache()

        # Resolve debugger executable preference (CDB first, then WinDbg)
        self.cdb_path = settings.cdb_path
        self.windbg_path = settings.windbg_path

        preferred_paths: list[Path] = []
        if self.cdb_path.exists():
            preferred_paths.append(self.cdb_path)
        if self.windbg_path.exists():
            preferred_paths.append(self.windbg_path)

        if not preferred_paths:
            raise FileNotFoundError(
                "No debugger executable found. Install Windows Debugging Tools and "
                "update CDB_PATH or WINDBG_PATH in your .env file."
            )

        self.debugger_path = preferred_paths[0]
        self.use_windbg = self.debugger_path == self.windbg_path

        # Data model commands are allowed only if enabled in settings
        self.supports_dx = settings.enable_data_model_commands
        
        # Start the persistent debugger session
        self._start_session()
    
    def _init_embeddings_client(self):
        """Initialize embeddings client based on configuration.
        
        Returns:
            OpenAI or AzureOpenAI client for embeddings
        """
        try:
            if settings.embeddings_provider == "azure":
                from openai import AzureOpenAI
                
                # Use embeddings-specific config or fall back to main Azure config
                endpoint = settings.azure_embeddings_endpoint or settings.azure_openai_endpoint
                api_key = settings.azure_embeddings_api_key or settings.azure_openai_api_key
                
                if not endpoint or not api_key:
                    console.print("[yellow]Azure OpenAI embeddings not configured, semantic search disabled[/yellow]")
                    return None
                
                return AzureOpenAI(
                    api_key=api_key,
                    api_version=settings.azure_openai_api_version,
                    azure_endpoint=endpoint
                )
            else:
                from openai import OpenAI
                
                if not settings.openai_api_key:
                    console.print("[yellow]OpenAI API key not set, semantic search disabled[/yellow]")
                    return None
                
                return OpenAI(api_key=settings.openai_api_key)
        except Exception as e:
            console.print(f"[yellow]Failed to initialize embeddings client: {e}[/yellow]")
            return None
    
    def _ensure_symbol_cache(self) -> None:
        """Ensure symbol cache directory exists."""
        # Extract cache path from symbol_path (e.g., SRV*c:\symbols*https://...)
        match = re.search(r'SRV\*([^*]+)\*', self.symbol_path, re.IGNORECASE)
        if match:
            cache_dir = Path(match.group(1))
            if not cache_dir.exists():
                console.print(f"[yellow]Creating symbol cache directory: {cache_dir}[/yellow]")
                cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _start_session(self) -> None:
        """Start a persistent debugger session."""
        try:
            if not self.debugger_path.exists():
                raise FileNotFoundError(
                    f"Debugger not found at {self.debugger_path}. Update CDB_PATH/WINDBG_PATH in .env"
                )
            
            # Build command to start persistent session
            # -z: open crash dump
            # -y: symbol path
            # -lines: enable source line support
            # -snul, -snc: reduce noisy output
            cmd_args = [
                str(self.debugger_path),
                "-z", str(self.dump_path),
                "-y", self.symbol_path,
                "-lines",
            ]
            
            console.print("[dim]Starting persistent debugger session...[/dim]")
            
            # Start the process with pipes for stdin/stdout/stderr
            self._process = subprocess.Popen(
                cmd_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1  # Line buffered
            )
            
            # Start background thread to read output
            self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
            self._reader_thread.start()
            
            # Load symbols on startup
            console.print("[dim]Loading symbols (this may take a minute)...")
            # Don't use .symfix+ since we already set symbol path via -y
            # Just reload symbols with the configured path
            self._send_command(".reload")
            
            # Detect CLR version in dump first
            console.print("[dim]Detecting CLR version in dump...[/dim]")
            self._send_command("lmvm clr")
            self._send_command("lmvm coreclr")
            time.sleep(1)
            version_output = self._get_buffer_output()
            
            # Extract CLR version
            clr_version_match = re.search(r'product:\s+Microsoft.*?\.NET.*?version\s+([0-9.]+)', version_output, re.IGNORECASE)
            if clr_version_match:
                clr_version = clr_version_match.group(1)
                console.print(f"[cyan]→ CLR Version in dump:[/cyan] {clr_version}")
            else:
                console.print("[yellow]⚠ Could not detect CLR version[/yellow]")
            
            # Load DAC (Data Access Component) - MUST be loaded before SOS
            console.print("[dim]Loading CLR Data Access Component (DAC)...[/dim]")
            if settings.mscordacwks_path and settings.mscordacwks_path.exists():
                # Use custom DAC path for exact version matching
                console.print(f"[cyan]→ Using custom DAC:[/cyan] {settings.mscordacwks_path}")
                self._send_command(f".cordll -lp {settings.mscordacwks_path}")
                time.sleep(1)
                # Verify which DAC loaded
                self._send_command(".cordll")
                time.sleep(0.5)
                output = self._get_buffer_output()
                console.print(f"[dim]DAC status output: {output[:200]}...[/dim]")
                
                # Extract DAC info
                dac_match = re.search(r'CLR DLL status:.*?([^\s]+(?:mscordacwks|mscordaccore)\.dll)', output, re.IGNORECASE | re.DOTALL)
                if dac_match:
                    console.print(f"[green]✓ DAC loaded:[/green] {dac_match.group(1)}")
                elif 'successfully loaded' in output.lower():
                    console.print(f"[green]✓ Custom DAC loaded[/green]")
                
                # VERIFY DAC is actually working by testing with a real SOS command that requires DAC
                console.print("[dim]Verifying DAC compatibility with !threads test...[/dim]")
                self._clear_buffer()
                self._send_command("!threads")
                time.sleep(2)
                verify_output = self._get_buffer_output()
                console.print(f"[dim]Verification output: {verify_output[:300]}...[/dim]")
                
                if "Failed to load data access DLL" in verify_output or "0x80004005" in verify_output:
                    console.print(f"[red]✗ DAC VERSION MISMATCH![/red]")
                    console.print(f"[red]  The DAC at {settings.mscordacwks_path} does not match the CLR version in the dump.[/red]")
                    if clr_version_match:
                        console.print(f"[yellow]  Dump requires CLR version: {clr_version}[/yellow]")
                    console.print(f"[yellow]  Either:[/yellow]")
                    console.print(f"[yellow]    1. Remove MSCORDACWKS_PATH from .env to auto-download correct version[/yellow]")
                    console.print(f"[yellow]    2. Or provide the exact DAC matching the runtime in this dump[/yellow]")
                    console.print(f"[yellow]  Hint: Run 'lmvm clr' or 'lmvm coreclr' in WinDbg to see exact version needed[/yellow]")
                    raise DebuggerError("DAC version mismatch - analysis cannot proceed")
                elif "ThreadCount" in verify_output or "Thr" in verify_output or "ID" in verify_output:
                    # !threads command produced output (thread list)
                    console.print("[green]✓ DAC is compatible and working[/green]")
                else:
                    console.print(f"[yellow]⚠ DAC verification unclear - continuing with caution[/yellow]")
            else:
                # Auto-download DAC from symbol server
                console.print("[cyan]→ Auto-downloading DAC from symbol server...[/cyan]")
                self._send_command(".cordll -ve -u -l")  # Verbose, reload, download
                time.sleep(2)
                # Check DAC status
                self._send_command(".cordll")
                time.sleep(0.5)
                output = self._get_buffer_output()
                # Extract DAC info
                dac_match = re.search(r'CLR DLL status:.*?([^\s]+(?:mscordacwks|mscordaccore)\.dll)', output, re.IGNORECASE | re.DOTALL)
                if dac_match:
                    dac_path = dac_match.group(1)
                    console.print(f"[green]✓ Auto-downloaded DAC:[/green] {dac_path}")
                elif 'successfully loaded' in output.lower():
                    console.print(f"[green]✓ DAC loaded from symbol server[/green]")
                else:
                    console.print("[yellow]⚠ DAC status unknown - attempting to continue[/yellow]")
                
                # Verify auto-downloaded DAC works
                console.print("[dim]Verifying DAC...[/dim]")
                self._send_command("!eeversion")
                time.sleep(1)
                verify_output = self._get_buffer_output()
                
                if "Failed to load data access DLL" in verify_output or "0x80004005" in verify_output:
                    console.print(f"[red]✗ DAC auto-download failed or version mismatch[/red]")
                    console.print(f"[yellow]  This can happen if:[/yellow]")
                    console.print(f"[yellow]    - Symbol server doesn't have this exact CLR version[/yellow]")
                    console.print(f"[yellow]    - Dump is from a private/internal .NET build[/yellow]")
                    if clr_version_match:
                        console.print(f"[yellow]  Required CLR version: {clr_version}[/yellow]")
                    console.print(f"[yellow]  Solution: Set MSCORDACWKS_PATH in .env to exact matching DAC[/yellow]")
                    raise DebuggerError("DAC version mismatch - cannot analyze this dump")
                else:
                    console.print("[green]✓ DAC is working[/green]")
            
            # Load SOS extension (custom path or auto-detect)
            console.print("[dim]Loading SOS extension...[/dim]")
            if settings.sos_dll_path and settings.sos_dll_path.exists():
                # Use custom SOS.dll path for cross-version dump analysis
                console.print(f"[cyan]→ Using custom SOS:[/cyan] {settings.sos_dll_path}")
                self._send_command(f".load {settings.sos_dll_path}")
                time.sleep(1)
                # Get confirmation of which SOS loaded
                self._send_command("lmm sos")
                time.sleep(0.5)
                output = self._get_buffer_output()
                # Extract SOS path from lmm output
                sos_match = re.search(r'sos\s+.*?\s+([^\s]+sos\.dll)', output, re.IGNORECASE)
                if sos_match:
                    console.print(f"[green]✓ Loaded SOS:[/green] {sos_match.group(1)}")
            else:
                # Auto-detect SOS from loaded runtime (try both Framework and Core)
                self._send_command(".loadby sos clr")
                self._send_command(".loadby sos coreclr")
                time.sleep(1)
                # Check which SOS was actually loaded
                self._send_command("lmm sos")
                time.sleep(0.5)
                output = self._get_buffer_output()
                # Extract SOS path from lmm output
                sos_match = re.search(r'sos\s+.*?\s+([^\s]+sos\.dll)', output, re.IGNORECASE)
                if sos_match:
                    sos_path = sos_match.group(1)
                    console.print(f"[green]✓ Auto-detected SOS:[/green] {sos_path}")
                else:
                    console.print("[yellow]⚠ SOS extension status unknown[/yellow]")
            
            # Wait for symbols to load
            time.sleep(1)
            self._clear_buffer()  # Clear symbol loading messages
            
            self._symbols_loaded = True
            console.print("[green]✓[/green] Debugger session started")
            
        except Exception as e:
            console.print(f"[red]Failed to start debugger session: {str(e)}[/red]")
            raise
    
    def _read_output(self) -> None:
        """Background thread to continuously read debugger output."""
        try:
            while self._process and self._process.poll() is None:
                line = self._process.stdout.readline()
                if line:
                    with self._output_lock:
                        self._output_buffer.append(line)
        except Exception:
            pass  # Process terminated
    
    def _send_command(self, command: str) -> None:
        """Send a command to the debugger without waiting for response.
        
        Args:
            command: Command to send
        """
        if self._process and self._process.stdin:
            self._process.stdin.write(f"{command}\n")
            self._process.stdin.flush()
    
    def _clear_buffer(self) -> None:
        """Clear the output buffer."""
        with self._output_lock:
            self._output_buffer.clear()
    
    def _get_buffer_output(self) -> str:
        """Get and clear the current buffer output.
        
        Returns:
            Accumulated output from buffer
        """
        with self._output_lock:
            output = "".join(self._output_buffer)
            self._output_buffer.clear()
            return output
    
    def __del__(self):
        """Cleanup: terminate the debugger session."""
        self.close()
    
    def close(self) -> None:
        """Close the persistent debugger session."""
        if self._process:
            try:
                # Try graceful quit
                self._send_command("q")
                self._process.wait(timeout=3)
            except:
                # Force terminate if needed
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except:
                    self._process.kill()
            finally:
                self._process = None
                if self.show_output:
                    console.print("[dim]Debugger session closed[/dim]")

    def execute_command(self, command: str, timeout: int | None = None) -> dict[str, Any]:
        """Execute a debugger command in the persistent session and return the result.
        
        Args:
            command: The debugger command to execute
            timeout: Timeout in seconds (defaults to settings.command_timeout)
            
        Returns:
            Dictionary with:
                - command: The executed command
                - output: Raw command output
                - parsed: Parsed output (if applicable)
                - success: Whether the command succeeded
                - error: Error message (if any)
        """
        if timeout is None:
            timeout = settings.command_timeout

        command_stripped = command.strip()

        try:
            # Check cache first - dumps are static, commands return same output
            if self.evidence_store:
                cached_evidence_id = self.evidence_store.find_by_command(command_stripped)
                if cached_evidence_id:
                    # Return cached result without executing
                    try:
                        output = self.evidence_store.retrieve_evidence(cached_evidence_id)
                        if self.show_output:
                            console.print(f"[dim]✓ Using cached result {cached_evidence_id}[/dim]")
                        return {
                            "command": command,
                            "output": output,
                            "parsed": self._parse_output(command, output),
                            "success": True,
                            "error": None,
                            "cached": True,
                            "evidence_id": cached_evidence_id
                        }
                    except Exception as e:
                        # Cache retrieval failed, fall through to execute
                        console.print(f"[yellow]⚠ Cache retrieval failed: {e}, executing command[/yellow]")
            
            if not self._process or self._process.poll() is not None:
                raise DebuggerError("Debugger session is not running")

            if not self.supports_dx and command_stripped.startswith("dx"):
                error_msg = (
                    "Data model commands (dx) are disabled. Set ENABLE_DATA_MODEL_COMMANDS=true in .env "
                    "to enable them."
                )
                console.print(f"[red]✗[/red] {error_msg}")
                return {
                    "command": command,
                    "output": "",
                    "parsed": None,
                    "success": False,
                    "error": error_msg,
                }

            if self.show_output:
                console.print(f"[dim]Executing: {command_stripped}[/dim]")
            
            # Clear buffer before sending command
            self._clear_buffer()
            
            # Send the command
            self._send_command(command_stripped)
            
            # Send delimiter command to mark end of output
            # Use .echo with a unique marker
            self._send_command(f".echo {self._command_delimiter}")
            
            # Wait for output with timeout
            start_time = time.time()
            output_lines = []
            delimiter_found = False
            
            while time.time() - start_time < timeout:
                with self._output_lock:
                    if self._output_buffer:
                        # Process buffer line by line to find delimiter
                        new_buffer = []
                        for line in self._output_buffer:
                            if self._command_delimiter in line:
                                delimiter_found = True
                                # Don't include the delimiter line or anything after it in this batch
                                break
                            output_lines.append(line)
                        
                        # If we found the delimiter, we can stop processing the buffer
                        # but we should clear it all since we've consumed what we needed
                        self._output_buffer.clear()
                
                if delimiter_found:
                    break
                    
                time.sleep(0.1)  # Small delay to avoid busy waiting
            
            if not delimiter_found:
                return {
                    "command": command,
                    "output": "",
                    "parsed": None,
                    "success": False,
                    "error": f"Command timed out after {timeout} seconds"
                }
            
            output = "".join(output_lines)
            
            # Check for errors
            error = self._extract_error(output)
            
            # Special handling for "not extension gallery command" error
            if "not extension gallery command" in output:
                error = "Command not found or extension not loaded"
                
            success = error is None
            
            # Store result in evidence cache for future reuse
            if success and self.evidence_store and output:
                # Generate embedding for semantic search (even for small outputs)
                embedding = None
                if self.embeddings_client and output:
                    try:
                        # Use truncated output for embedding (embeddings have token limits)
                        embedding_text = output[:8000] if len(output) > 8000 else output
                        embedding_response = self.embeddings_client.embeddings.create(
                            input=embedding_text,
                            model=settings.azure_embeddings_deployment if settings.embeddings_provider == 'azure' else 'text-embedding-3-small'
                        )
                        embedding = embedding_response.data[0].embedding
                    except Exception as e:
                        if self.show_output:
                            console.print(f"[yellow]⚠ Embedding generation failed: {e}[/yellow]")
                
                # Store with embedding (analysis added later if needed)
                evidence_id = self.evidence_store.store_evidence(
                    command=command_stripped,
                    output=output,
                    summary=None,  # Analysis happens in execute_command_with_analysis for large outputs
                    key_findings=None,
                    embedding=embedding
                )
                if self.show_output and len(output) > 10000:
                    console.print(f"[dim]Cached as {evidence_id}[/dim]")

            return {
                "command": command,
                "output": output,
                "parsed": self._parse_output(command, output),
                "success": success,
                "error": error,
                "cached": False
            }

        except Exception as e:
            return {
                "command": command,
                "output": "",
                "parsed": None,
                "success": False,
                "error": f"Failed to execute command: {str(e)}"
            }
    
    def execute_command_with_analysis(
        self,
        command: str,
        intent: str = "",
        timeout: int | None = None
    ) -> dict[str, Any]:
        """Execute command and automatically use evidence storage for large outputs.
        
        Args:
            command: Debugger command to execute
            intent: What we're looking for (for analysis)
            timeout: Timeout in seconds
            
        Returns:
            Dictionary with result, evidence_id (if stored), and analysis
        """
        result = self.execute_command(command, timeout)
        
        if not result['success'] or not self.evidence_store:
            return result
        
        output = result['output']
        output_size = len(output)
        threshold = settings.evidence_storage_threshold
        
        # Check if command was served from cache
        if result.get('cached'):
            # Already cached, check if it has analysis
            evidence_id = result.get('evidence_id')
            metadata = self.evidence_store.get_metadata(evidence_id)
            
            if metadata.get('summary'):
                # Has analysis, return it
                console.print(f"[dim]Using cached analysis from {evidence_id}[/dim]")
                result['evidence_type'] = 'external'
                result['evidence_id'] = evidence_id
                result['analysis'] = {
                    'summary': metadata.get('summary', ''),
                    'key_findings': metadata.get('key_findings', [])
                }
                result['output'] = metadata.get('summary', output)
                return result
            # else: no analysis yet, fall through to analyze
        
        # For large outputs, perform chunked analysis
        if output_size > threshold:
            # Check for session-wide duplicate (dumps are static, cache indefinitely)
            existing_evidence_id = self.evidence_store.find_recent_duplicate(
                command=command,
                output=output,
                max_age_seconds=None  # Session-wide cache for dump analysis
            )
            
            if existing_evidence_id:
                console.print(f"[dim]Reusing recent evidence {existing_evidence_id} (identical output)[/dim]")
                
                # Retrieve existing analysis
                metadata = self.evidence_store.get_metadata(existing_evidence_id)
                
                # Check if we have a summary - if not, need to analyze now
                if metadata.get('summary'):
                    # Has analysis, return it
                    result['evidence_type'] = 'external'
                    result['evidence_id'] = existing_evidence_id
                    result['analysis'] = {
                        'summary': metadata.get('summary', ''),
                        'key_findings': metadata.get('key_findings', [])
                    }
                    result['output_truncated'] = True
                    result['output'] = metadata.get('summary')
                    result['cached'] = True  # Mark as cached for display
                    
                    return result
                else:
                    # No analysis yet - fall through to analyze the output
                    console.print(f"[dim]Evidence {existing_evidence_id} has no analysis yet, analyzing now...[/dim]")
                    # Continue to analysis section below
            
            console.print(f"[dim]Output size {output_size} bytes exceeds threshold ({threshold}), analyzing...[/dim]")
            
            # Analyze the output
            analysis = self.evidence_analyzer.analyze_evidence(
                command=command,
                output=output,
                intent=intent or f"Analyzing {command}",
                chunk_size=settings.evidence_chunk_size
            )
            
            # Generate embedding from summary for better semantic search
            embedding = None
            if self.embeddings_client and analysis.get('summary'):
                try:
                    embedding_response = self.embeddings_client.embeddings.create(
                        input=analysis['summary'],
                        model=settings.azure_embeddings_deployment if settings.embeddings_provider == 'azure' else 'text-embedding-3-small'
                    )
                    embedding = embedding_response.data[0].embedding
                except Exception as e:
                    console.print(f"[yellow]⚠ Failed to generate embedding from summary: {e}[/yellow]")
            
            # Update existing evidence with analysis or create new if not cached
            if result.get('cached') or existing_evidence_id:
                # Update existing evidence with analysis
                evidence_id = result.get('evidence_id') or existing_evidence_id
                self.evidence_store.conn.execute("""
                    UPDATE evidence 
                    SET summary = ?, key_findings = ?, embedding = ?
                    WHERE id = ?
                """, [
                    analysis['summary'],
                    json.dumps(analysis['key_findings']),
                    json.dumps(embedding) if embedding else None,
                    evidence_id
                ])
                self.evidence_store.conn.commit()
                console.print(f"[dim]Updated {evidence_id} with analysis[/dim]")
            else:
                # Store new evidence with analysis
                evidence_id = self.evidence_store.store_evidence(
                    command=command,
                    output=output,
                    summary=analysis['summary'],
                    key_findings=analysis['key_findings'],
                    embedding=embedding
                )
            
            # Store chunk analyses
            if 'chunks' in analysis:
                self.evidence_store.store_chunks(evidence_id, analysis['chunks'])
            
            # Update result with evidence info
            result['evidence_type'] = 'external'
            result['evidence_id'] = evidence_id
            result['analysis'] = analysis
            result['output_truncated'] = True
            # Keep only summary in output to save tokens
            result['output'] = analysis['summary']
            
            console.print(f"[green]✓[/green] Analyzed and stored as evidence {evidence_id}")
        else:
            result['evidence_type'] = 'inline'
            result['evidence_id'] = None
            result['analysis'] = None
            result['output_truncated'] = False
        
        return result

    def _parse_output(self, command: str, output: str) -> Any:
        """Parse debugger output based on command type.
        
        Args:
            command: The executed command
            output: Raw output from the debugger
            
        Returns:
            Parsed output (dict for dx commands, cleaned string for others)
        """
        # For dx (data model) commands, try to extract structured data
        if command.strip().startswith("dx"):
            return self._parse_dx_output(output)
        
        # For other commands, clean up the output
        return self._clean_output(output)

    def _parse_dx_output(self, output: str) -> dict[str, Any] | str:
        """Parse data model (dx) command output.
        
        dx commands often return structured data that can be parsed.
        
        Args:
            output: Raw dx command output
            
        Returns:
            Parsed dictionary or cleaned string if parsing fails
        """
        try:
            # Try to find JSON-like structures in the output
            # dx output is not pure JSON but has a similar structure
            
            # Remove debugger preamble (symbol loading, etc.)
            lines = output.split('\n')
            relevant_lines = []
            capture = False
            
            for line in lines:
                # Start capturing after we see the actual dx output
                if line.strip().startswith('@$') or line.strip().startswith('[') or capture:
                    capture = True
                    relevant_lines.append(line)
            
            if not relevant_lines:
                return self._clean_output(output)
            
            dx_output = '\n'.join(relevant_lines)
            
            # Parse the dx structure (simplified)
            # For now, return the cleaned output
            # In a future enhancement, we could parse this into a proper dict
            return {
                "type": "data_model",
                "raw": dx_output.strip(),
                "structured": self._extract_dx_fields(dx_output)
            }
            
        except Exception:
            return self._clean_output(output)

    def _extract_dx_fields(self, dx_output: str) -> dict[str, Any]:
        """Extract field-value pairs from dx output.
        
        Args:
            dx_output: Cleaned dx output
            
        Returns:
            Dictionary of extracted fields
        """
        fields = {}
        
        # Pattern: fieldName : value
        pattern = r'(\w+)\s*:\s*(.+?)(?=\n\s*\w+\s*:|$)'
        matches = re.finditer(pattern, dx_output, re.MULTILINE | re.DOTALL)
        
        for match in matches:
            field_name = match.group(1)
            field_value = match.group(2).strip()
            fields[field_name] = field_value
        
        return fields

    def _clean_output(self, output: str) -> str:
        """Clean debugger output by removing noise.
        
        Args:
            output: Raw debugger output
            
        Returns:
            Cleaned output string
        """
        lines = output.split('\n')
        cleaned_lines = []
        
        # Skip common debugger preamble
        skip_patterns = [
            "Microsoft (R) Windows Debugger",
            "Copyright (c) Microsoft Corporation",
            "Loading Dump File",
            "User Mini Dump File",
            "Symbol search path is:",
            "Executable search path is:",
            "Windows 10 Version",
            "Loading unloaded module list",
            "quit:",
        ]
        
        for line in lines:
            # Skip empty lines and known noise
            if not line.strip():
                continue
            
            should_skip = False
            for pattern in skip_patterns:
                if pattern.lower() in line.lower():
                    should_skip = True
                    break
            
            if not should_skip:
                cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines).strip()

    def _extract_error(self, output: str) -> str | None:
        """Extract error messages from debugger output.
        
        Args:
            output: Raw debugger output
            
        Returns:
            Error message if found, None otherwise
        """
        # Patterns that indicate REAL errors (not warnings)
        error_patterns = [
            r"^Error:\s*(.+)$",
            r"^\^\^\^ Error:\s*(.+)$",
            r"Couldn't resolve error at '(.+)'",
            r"The operation attempted to access data outside the valid range",
            r"Unable to bind name",
            r"Expected '=' at",  # dx syntax errors
            r"The call to LoadLibrary\(sos\) failed",
            r"Failed to load extension sos",
            r"No export dumpheap found",
            r"dumpheap is not extension gallery command"
        ]
        
        # Patterns that are just warnings, not errors
        warning_patterns = [
            r"Unable to verify checksum",
            r"Unable to load image",
            r"WARNING:",
            r"DBGHELP:",
        ]
        
        for line in output.split('\n'):
            # Skip if it's just a warning
            is_warning = False
            for warn_pattern in warning_patterns:
                if re.search(warn_pattern, line, re.IGNORECASE):
                    is_warning = True
                    break
            
            if is_warning:
                continue
            
            # Check for real errors
            for pattern in error_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    return match.group(0)
        
        return None

    def validate_dump(self) -> dict[str, Any]:
        """Validate the dump file and get basic information.
        
        Returns:
            Dictionary with dump validation results and basic info
        """
        # Get dump info using .ecxr (exception context) or !analyze -v
        result = self.execute_command(".lastevent")
        
        if result["success"]:
            return {
                "valid": True,
                "info": result["output"],
                "error": None
            }
        else:
            return {
                "valid": False,
                "info": None,
                "error": result.get("error", "Unknown validation error")
            }

    def get_dump_type(self) -> str:
        """Determine if this is a user-mode or kernel-mode dump.
        
        Returns:
            "user" or "kernel"
        """
        # Try a user-mode command
        result = self.execute_command("!peb")
        
        if result["success"] and "PEB at" in result["output"]:
            return "user"
        else:
            return "kernel"
