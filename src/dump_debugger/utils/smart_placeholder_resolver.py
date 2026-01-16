"""Unified LLM-powered placeholder validation and resolution."""

import json
import re
from typing import Any

from rich.console import Console

console = Console()


class SmartPlaceholderResolver:
    """Intelligently validates and resolves command placeholders using LLM."""
    
    def __init__(self, llm):
        """Initialize resolver with local LLM.
        
        Args:
            llm: Local LLM instance (e.g., qwen2.5-coder)
        """
        self.llm = llm
    
    def has_placeholders(self, command: str) -> bool:
        """Quick check if command contains angle-bracket placeholders.
        
        Args:
            command: Command to check
            
        Returns:
            True if placeholders found
        """
        return bool(re.search(r'<[^>]+>', command))
    
    def resolve_command(
        self,
        command: str,
        evidence: list[dict],
        used_addresses: set[str] | None = None,
        invalid_addresses: set[str] | None = None
    ) -> tuple[str, bool, str, dict]:
        """Validate and resolve all placeholders in one pass.
        
        Args:
            command: Command with potential placeholders
            evidence: List of evidence dictionaries
            used_addresses: Set of addresses already used (to avoid duplicates)
            invalid_addresses: Set of addresses that returned errors
            
        Returns:
            Tuple of (resolved_command, success, message, details)
            - details includes: placeholders analyzed, values extracted, etc.
        """
        if not self.has_placeholders(command):
            return command, True, "No placeholders found", {}
        
        used_addresses = used_addresses or set()
        invalid_addresses = invalid_addresses or set()
        
        # Build evidence summary
        evidence_summary = self._build_evidence_summary(evidence)
        
        # Step 1 & 2: Validate and extract values in one LLM call
        prompt = f"""Analyze this Windows debugger command with placeholders and extract values from evidence.

COMMAND:
{command}

AVAILABLE EVIDENCE:
{evidence_summary}

TASK:
For EACH placeholder in angle brackets <...>:
1. Determine what type of value it needs
2. Check if we can extract it from the evidence
3. If YES: Extract the actual value(s) to use
4. If NO: Explain what's missing

EXTRACTION RULES:
- Method tables: Look for !dumpheap -stat output (MT column), use top entries
- Object addresses: Look for !dumpheap output (Address column), avoid high addresses (0x7ff...)
- Thread IDs: Look for !threads output (DBG# or OSID columns)
- Skip addresses in: {list(used_addresses)[:5]} (already used)
- Skip addresses in: {list(invalid_addresses)[:5]} (known invalid)

Return ONLY valid JSON:
{{
  "resolvable": true/false,
  "placeholders": [
    {{
      "text": "<placeholder_name>",
      "type": "mt|address|thread|etc",
      "resolvable": true/false,
      "values": ["0x123...", "0x456..."] OR [],
      "reason": "explanation",
      "prerequisite": "command to run first" OR null
    }}
  ]
}}"""

        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            
            messages = [
                SystemMessage(content="You are an expert Windows debugger analyst. Return ONLY valid JSON."),
                HumanMessage(content=prompt)
            ]
            
            response = self.llm.invoke(messages)
            analysis = self._extract_json(response.content)
            
            if not analysis:
                return command, False, "LLM analysis failed", {}
            
            # Check if overall resolvable
            if not analysis.get('resolvable', False):
                # Build detailed error message
                reasons = []
                prerequisites = []
                for ph in analysis.get('placeholders', []):
                    reasons.append(f"{ph['text']}: {ph.get('reason', 'unknown')}")
                    if ph.get('prerequisite'):
                        prerequisites.append(ph['prerequisite'])
                
                message = '; '.join(reasons)
                if prerequisites:
                    message += f"\nSuggested prerequisites: {', '.join(set(prerequisites))}"
                
                return command, False, message, analysis
            
            # Step 3: Replace placeholders with extracted values
            resolved_command = command
            replacements = {}
            
            for ph_info in analysis.get('placeholders', []):
                placeholder = ph_info['text']
                values = ph_info.get('values', [])
                
                if not values or not ph_info.get('resolvable', False):
                    continue
                
                # Use first available value
                value = values[0]
                
                # Clean up value format
                if ph_info.get('type') == 'mt' or ph_info.get('type') == 'address':
                    # Ensure 0x prefix for addresses
                    if not value.startswith('0x') and re.match(r'^[0-9a-f]+$', value, re.IGNORECASE):
                        value = '0x' + value
                
                resolved_command = resolved_command.replace(placeholder, value)
                replacements[placeholder] = value
            
            # Check if all placeholders were replaced
            if self.has_placeholders(resolved_command):
                unresolved = re.findall(r'<[^>]+>', resolved_command)
                return (
                    command,
                    False,
                    f"Failed to resolve: {', '.join(unresolved)}",
                    {'analysis': analysis, 'replacements': replacements}
                )
            
            return (
                resolved_command,
                True,
                f"Resolved {len(replacements)} placeholder(s)",
                {'analysis': analysis, 'replacements': replacements}
            )
            
        except Exception as e:
            console.print(f"[yellow]⚠ Smart resolution failed: {e}[/yellow]")
            return command, False, f"Resolution error: {str(e)}", {}
    
    def _build_evidence_summary(self, evidence: list[dict], max_items: int = 10) -> str:
        """Build concise evidence summary for LLM with smart extraction.
        
        Args:
            evidence: Evidence list
            max_items: Maximum items to include
            
        Returns:
            Formatted summary with relevant data for extraction
        """
        if not evidence:
            return "(No evidence available)"
        
        lines = []
        for i, ev in enumerate(evidence[:max_items], 1):
            cmd = ev.get('command', 'Unknown')
            
            # Smart extraction based on command type
            if ev.get('output'):
                output = ev['output']
                
                # For !dumpheap -stat: Extract method table lines (contains MT addresses)
                if 'dumpheap' in cmd.lower() and '-stat' in cmd.lower():
                    # Get last 30 lines (where top memory consumers are)
                    output_lines = output.split('\n')
                    relevant = '\n'.join(output_lines[-30:])
                    desc = f"Top memory consumers:\n{relevant}"
                
                # For !dumpheap without -stat: Extract address lines
                elif 'dumpheap' in cmd.lower():
                    # Get first 20 lines (sample addresses)
                    output_lines = output.split('\n')
                    relevant = '\n'.join(output_lines[:20])
                    desc = f"Sample addresses:\n{relevant}"
                
                # For !threads: Extract thread ID lines
                elif 'threads' in cmd.lower():
                    # Get first 20 lines (thread list)
                    output_lines = output.split('\n')
                    relevant = '\n'.join(output_lines[:20])
                    desc = f"Thread list:\n{relevant}"
                
                # For everything else: Use summary or first 1000 chars
                else:
                    if ev.get('summary'):
                        desc = ev['summary'][:500]
                    else:
                        desc = output[:1000]
            else:
                desc = ev.get('summary', 'No data')[:200]
            
            lines.append(f"{i}. Command: {cmd}")
            lines.append(f"   {desc}")
        
        if len(evidence) > max_items:
            lines.append(f"... and {len(evidence) - max_items} more")
        
        return '\n'.join(lines)
    
    def _extract_json(self, text: str) -> dict | None:
        """Extract JSON from LLM response.
        
        Args:
            text: Response text
            
        Returns:
            Parsed JSON or None
        """
        # Try direct parse
        try:
            return json.loads(text.strip())
        except:
            pass
        
        # Try extracting from code blocks
        if '```' in text:
            parts = text.split('```')
            for part in parts:
                cleaned = part.strip()
                if cleaned.startswith('json'):
                    cleaned = cleaned[4:].strip()
                
                try:
                    return json.loads(cleaned)
                except:
                    continue
        
        # Try finding JSON object
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end+1])
            except:
                pass
        
        return None


# Convenience function for backward compatibility
def detect_placeholders(command: str) -> bool:
    """Detect if command has placeholders.
    
    Args:
        command: Command to check
        
    Returns:
        True if placeholders found
    """
    return bool(re.search(r'<[^>]+>', command))
