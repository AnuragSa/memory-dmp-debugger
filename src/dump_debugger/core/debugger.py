"""WinDbg/CDB automation wrapper for executing debugger commands."""

import json
import re
import subprocess
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

    def __init__(self, dump_path: Path):
        """Initialize the debugger wrapper.
        
        Args:
            dump_path: Path to the memory dump file
        """
        self.dump_path = dump_path
        self.debugger_path = settings.get_debugger_path(prefer_cdb=True)
        self.symbol_path = settings.symbol_path
        
        if not self.dump_path.exists():
            raise FileNotFoundError(f"Dump file not found: {dump_path}")

    def execute_command(self, command: str, timeout: int | None = None) -> dict[str, Any]:
        """Execute a debugger command and return the result.
        
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

        try:
            # Build the command line
            # -z: open crash dump
            # -y: symbol path
            # -c: execute command and quit
            # -lines: enable source line support
            cmd_args = [
                str(self.debugger_path),
                "-z", str(self.dump_path),
                "-y", self.symbol_path,
                "-lines",
                "-c", f"{command}; q"  # Execute command then quit
            ]

            console.print(f"[dim]Executing: {command}[/dim]")

            result = subprocess.run(
                cmd_args,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace"
            )

            output = result.stdout + result.stderr
            
            # Check for common errors
            if "Symbol search path is:" in output:
                # This is normal, symbols are loading
                pass
            
            error = self._extract_error(output)
            success = result.returncode == 0 and error is None

            return {
                "command": command,
                "output": output,
                "parsed": self._parse_output(command, output),
                "success": success,
                "error": error
            }

        except subprocess.TimeoutExpired:
            return {
                "command": command,
                "output": "",
                "parsed": None,
                "success": False,
                "error": f"Command timed out after {timeout} seconds"
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
        error_patterns = [
            r"^Error:\s*(.+)$",
            r"^\^\^\^ Error:\s*(.+)$",
            r"Couldn't resolve error at '(.+)'",
            r"Unable to (.+)$",
            r"Failed to (.+)$",
        ]
        
        for line in output.split('\n'):
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
