"""Command healer that automatically fixes failed debugger commands using LLM-powered dynamic analysis.

When a command fails, the healer sends the command, error output, and execution context
to an LLM which intelligently analyzes the failure and suggests a corrected command.
"""

import re
from typing import Optional
from rich.console import Console

console = Console()


class CommandHealer:
    """Heals failed debugger commands using LLM-powered dynamic analysis."""
    
    def __init__(self, use_llm: bool = True):
        """Initialize healer.
        
        Args:
            use_llm: Whether to use LLM for dynamic healing (default True)
        """
        self.use_llm = use_llm
        self.heal_count = 0
        self.failed_heals = 0
        self._llm = None
        self._healing_log = []  # Track all healings for learning and debugging
    
    @property
    def llm(self):
        """Lazy-load LLM to avoid import issues."""
        if self._llm is None and self.use_llm:
            try:
                from dump_debugger.llm import get_llm
                self._llm = get_llm(temperature=0.1)  # Low temp for precise fixes
            except Exception:
                self.use_llm = False
        return self._llm
    
    def heal_command(self, command: str, error_output: str, context: dict = None) -> Optional[str]:
        """Attempt to heal a failed command using LLM-powered analysis.
        
        Args:
            command: The failed command
            error_output: The error output
            context: Optional context (previous evidence, dump type, etc.)
            
        Returns:
            Healed command string, or None if can't heal
        """
        # Check for malformed thread placeholder syntax (e.g., ~~[ThreadId])
        # This is a common LLM mistake that can't be healed without evidence
        malformed_match = re.search(r'~~\[([A-Za-z_][A-Za-z0-9_]*)\]', command)
        if malformed_match:
            placeholder_name = malformed_match.group(1)
            # Check if it's clearly a placeholder (not a valid hex OSID)
            if not all(c in '0123456789abcdefABCDEF' for c in placeholder_name):
                # Try to resolve using placeholder resolver if we have context
                if context and 'previous_evidence' in context:
                    from dump_debugger.utils.placeholder_resolver import resolve_command_placeholders
                    resolved, success, msg = resolve_command_placeholders(
                        command, context['previous_evidence']
                    )
                    if success and resolved != command:
                        self.heal_count += 1
                        console.print(f"[cyan]🔧 Healed:[/cyan] {command}")
                        console.print(f"[cyan]   → {resolved}[/cyan]")
                        return resolved
                
                # Cannot heal without thread IDs
                console.print(f"[yellow]⚠ Cannot heal malformed thread placeholder: ~~[{placeholder_name}][/yellow]")
                console.print(f"[yellow]   Run !threads first to get actual thread IDs[/yellow]")
                self.failed_heals += 1
                return None
        
        # Use LLM-based healing - primary and most intelligent approach
        if self.use_llm and self.llm:
            healed = self._heal_with_llm(command, error_output, context)
            if healed and healed != command:
                self.heal_count += 1
                console.print(f"[cyan]🔧 Healed:[/cyan] {command}")
                console.print(f"[cyan]   → {healed}[/cyan]")
                # Log the healing for learning
                if hasattr(self, '_healing_log'):
                    self._healing_log.append({
                        'original': command,
                        'healed': healed,
                        'error': error_output[:200]
                    })
                return healed
        
        # If LLM is disabled or unavailable, fail gracefully
        self.failed_heals += 1
        return None
    
    def _heal_with_llm(self, command: str, error_output: str, context: dict = None) -> Optional[str]:
        """Use LLM to dynamically analyze and fix the command.
        
        Args:
            command: Failed command
            error_output: Error message
            context: Optional context with previous evidence
            
        Returns:
            Fixed command or None
        """
        # Build rich context for LLM
        context_info = ""
        used_addresses = set()
        invalid_addresses = set()
        
        if context:
            # Track addresses that have been used or are invalid
            used_addresses = context.get('used_addresses', set())
            invalid_addresses = context.get('invalid_addresses', set())
            
            # Recent command history for context
            if 'previous_evidence' in context and context['previous_evidence']:
                recent = context['previous_evidence'][-3:]  # Last 3 commands
                context_info = "\n\nRECENT COMMAND HISTORY:\n"
                for ev in recent:
                    cmd = ev.get('command', '')
                    output = ev.get('output', '')
                    # Include more output for better context
                    output_preview = output[:400] if len(output) > 400 else output
                    context_info += f"Command: {cmd}\nOutput: {output_preview}\n\n"
                    
            if invalid_addresses:
                context_info += f"\nINVALID ADDRESSES (avoid these): {', '.join(list(invalid_addresses)[:5])}\n"
        
        prompt = f"""You are a WinDbg/SOS debugger command repair expert. A command failed and you need to fix it dynamically.

FAILED COMMAND: {command}

ERROR OUTPUT:
{error_output}
{context_info}

Your task: Analyze the error and provide a corrected command that will work.

KEY DEBUGGING KNOWLEDGE:

1. COMMAND SUBSTITUTIONS:
   - !pe (PrintException) only works on Exception OBJECT addresses (low range: 0x00000000-0x3fffffff)
   - !do (DumpObject) works on object addresses (low range: 0x00000000-0x3fffffff)
   - Method Table addresses are high range (0x7ff...) and require !dumpmt or !dumpclass
   - If !pe or !do fails with "not a valid object/exception", the address is likely an MT, not an object
   - STOP trying other commands on the same address - it's the wrong address type

2. ADDRESS TYPES - CRITICAL:
   - Object addresses: 0x00000000xxxxxxxx to 0x3ffffffffffffff (low range)
   - Method Table addresses: 0x7ff... or higher (high range)
   - !pe and !do ONLY work on object addresses, NEVER on MT addresses
   - !dumpmt, !dumpclass ONLY work on MT addresses
   - If command fails because of address type mismatch, return "SKIP" to abort

3. COMMAND FLAGS - DO NOT CHANGE INTENT:
   - !dumpheap -type X → returns object addresses (good for !pe, !do)
   - !dumpheap -type X -stat → returns METHOD TABLE addresses (wrong for !pe, !do)
   - !dumpheap -type X -short → returns object addresses only (good for !pe, !do)
   - NEVER add -stat flag if original command didn't have it
   - NEVER change the output format flags

4. THREAD SYNTAX - CRITICAL:
   There are THREE different thread IDs:
   - DBG# = Debugger thread index (0, 1, 2...) shown first in !threads output
   - Managed ID = CLR's internal ID, shown in !syncblk "Owning Thread" column  
   - OSID = OS thread ID in hex (e.g., d78, 3fc) shown in !threads OSID column

   Command syntax:
   - ~<DBG#>e <cmd> = Execute on debugger thread index (e.g., ~18e !clrstack for DBG# 18)
   - ~~[<OSID>]e <cmd> = Execute on OSID (e.g., ~~[d78]e !clrstack for OSID d78)
   - OSID in brackets is HEX without 0x prefix (~~[d78]e NOT ~~[0xd78]e or ~~[3448]e)
   
   !syncblk output format: "ThreadObjAddr OSID DBG#" (e.g., "000002543dd83c70 d78  18")
   - To examine this thread: use ~24e !clrstack (DBG# 18 in hex = 24 decimal)
   - OR: ~~[d78]e !clrstack (OSID d78 stays as hex)
   
   PREFER ~<DBG#>e over ~~[OSID]e for reliability. Convert hex DBG# to decimal.

5. DATA MODEL vs SOS:
   - dx commands often fail → use SOS equivalents
   - dx @$curprocess.Threads → !threads

6. SYNTAX FIXES:
   - Add missing ! prefix for SOS commands
   - Fix spacing: !dumpheap-stat → !dumpheap -stat
   - Remove invalid flags or parameters

CRITICAL RULES:
1. Return ONLY the fixed command (one line)
2. NO explanations, NO markdown, NO commentary
3. PRESERVE the original intent - don't change what data the command returns
4. If address type is wrong (MT used with !do/!pe), return "SKIP" to stop healing
5. NEVER add -stat flag to commands that didn't have it
6. Don't try multiple different commands on the same bad address

Fixed command:"""
        
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            
            response = self.llm.invoke([
                SystemMessage(content="You are a debugger command repair expert. Return ONLY the fixed command, no explanations."),
                HumanMessage(content=prompt)
            ])
            
            fixed = response.content.strip()
            
            # Check if LLM says to skip (address type mismatch)
            if fixed.upper() == 'SKIP' or 'skip' in fixed.lower()[:20]:
                console.print(f"[dim yellow]⚠ LLM determined this command cannot be healed (wrong address type)[/dim yellow]")
                return None
            
            # Clean up response - extract just the command
            fixed = self._extract_command_from_response(fixed)
            
            # Validate healer didn't violate critical rules
            if fixed and command:
                # Rule 1: Don't add -stat flag if original didn't have it
                if '-stat' in fixed and '-stat' not in command:
                    console.print(f"[dim yellow]⚠ LLM added -stat flag (changes output type), rejecting[/dim yellow]")
                    return None
                
                # Rule 2: Don't remove -short flag
                if '-short' in command and '-short' not in fixed:
                    console.print(f"[dim yellow]⚠ LLM removed -short flag (changes output format), rejecting[/dim yellow]")
                    return None
                
                # Rule 3: Don't separate thread commands (e.g., ~3s from !clrstack)
                if fixed.startswith('~') and command.startswith('!') and ';' in fixed:
                    console.print(f"[dim yellow]⚠ LLM added thread switch to non-thread command, rejecting[/dim yellow]")
                    return None
            
            # Validate the fix isn't just repeating the error
            if fixed and fixed != command and len(fixed) > 0:
                # Basic sanity check - should look like a debugger command
                if (fixed.startswith('!') or fixed.startswith('~') or 
                    fixed.startswith('dx') or fixed.startswith('.')):
                    return fixed
            
            return None
            
        except Exception as e:
            console.print(f"[dim yellow]⚠ LLM healing failed: {e}[/dim yellow]")
            return None
    
    def _extract_command_from_response(self, response: str) -> str:
        """Extract just the command from LLM response.
        
        Args:
            response: LLM response text
            
        Returns:
            Cleaned command string
        """
        # Remove markdown code blocks
        response = re.sub(r'```[\w]*\n?', '', response)
        
        # Take first line only
        lines = [line.strip() for line in response.split('\n') if line.strip()]
        if not lines:
            return response.strip()
        
        # Find the first line that looks like a command
        for line in lines:
            if (line.startswith('!') or line.startswith('~') or 
                line.startswith('dx') or line.startswith('.')):
                return line
        
        # Fall back to first non-empty line
        return lines[0]
    
    def get_stats(self) -> dict:
        """Get healing statistics."""
        return {
            'successful_heals': self.heal_count,
            'failed_heals': self.failed_heals,
            'success_rate': self.heal_count / (self.heal_count + self.failed_heals) if (self.heal_count + self.failed_heals) > 0 else 0,
            'healing_log': self._healing_log
        }
