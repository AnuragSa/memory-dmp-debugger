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

    def __init__(self, dump_path: Path, show_output: bool = False):
        """Initialize the debugger wrapper.
        
        Args:
            dump_path: Path to the memory dump file
            show_output: Whether to show command outputs (default: False)
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
            console.print("[dim]Loading symbols (this may take a minute)...[/dim]")
            self._send_command(f".symfix+ {self.symbol_path}")
            self._send_command(".reload")
            
            # Wait for symbols to load
            time.sleep(2)
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
                        for line in self._output_buffer:
                            if self._command_delimiter in line:
                                delimiter_found = True
                                break
                            output_lines.append(line)
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
            success = error is None
            
            # Only truncate extremely large outputs (>500KB) to prevent context overflow
            MAX_OUTPUT_SIZE = 500000  # ~500KB limit per command (very generous)
            if len(output) > MAX_OUTPUT_SIZE:
                keep_size = MAX_OUTPUT_SIZE // 2
                truncated_output = (
                    output[:keep_size] + 
                    f"\n\n... [WARNING: Output truncated - {len(output) - MAX_OUTPUT_SIZE} bytes removed] ..." +
                    f"\n... Use filtered queries (dx with .Where/.Select/.Take or specific thread IDs) to get focused data ...\n\n" +
                    output[-keep_size:]
                )
                console.print(f"[yellow]⚠ Output too large ({len(output)} bytes). Truncated to {len(truncated_output)} bytes.[/yellow]")
                console.print(f"[yellow]   Consider using filtered queries for more targeted results.[/yellow]")
                output = truncated_output

            return {
                "command": command,
                "output": output,
                "parsed": self._parse_output(command, output),
                "success": success,
                "error": error
            }

        except Exception as e:
            return {
                "command": command,
                "output": "",
                "parsed": None,
                "success": False,
                "error": f"Failed to execute command: {str(e)}"
            }

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
        ]
        
        # Patterns that are just warnings, not errors
        warning_patterns = [
            r"Unable to verify checksum",
            r"Unable to load image",
            r"No export",
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
