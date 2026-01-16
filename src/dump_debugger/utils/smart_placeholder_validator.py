"""Smart placeholder validation using local LLM to understand command context."""

import json
import re
from typing import Any

from rich.console import Console

console = Console()


class SmartPlaceholderValidator:
    """Uses local LLM to intelligently validate and resolve command placeholders."""
    
    def __init__(self, llm):
        """Initialize validator with local LLM.
        
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
    
    def analyze_command(self, command: str, evidence: list[dict]) -> dict[str, Any]:
        """Analyze command to determine if placeholders can be resolved.
        
        Args:
            command: Command with potential placeholders
            evidence: List of evidence dictionaries with command, summary, output
            
        Returns:
            Analysis result with resolvability info
        """
        if not self.has_placeholders(command):
            return {
                'has_placeholders': False,
                'resolvable': True,
                'placeholders': []
            }
        
        # Build concise evidence summary for LLM
        evidence_summary = self._build_evidence_summary(evidence)
        
        prompt = f"""You are analyzing a Windows debugger command with placeholders.

COMMAND TO ANALYZE:
{command}

AVAILABLE EVIDENCE:
{evidence_summary}

TASK:
Identify each placeholder in angle brackets <...> and determine if we can resolve it.

For EACH placeholder:
1. What type of value does it need? (e.g., "method table address", "object address", "thread ID")
2. Can we extract this value from the available evidence? (yes/no)
3. If NO: What command should we run FIRST to get this data?
4. If YES: Which evidence piece contains it?

RULES:
- Method table addresses come from: !dumpheap -stat, !do output
- Object addresses come from: !dumpheap, !dumpheap -stat, !gcroot
- Thread IDs come from: !threads, !syncblk
- If evidence doesn't have the required data → resolvable = false

Return ONLY valid JSON:
{{
  "placeholders": [
    {{
      "text": "<placeholder_name>",
      "needs": "description of what value is needed",
      "resolvable": true/false,
      "evidence_source": "command that has the data" OR null,
      "prerequisite": "command to run first" OR null,
      "reason": "brief explanation"
    }}
  ],
  "overall_resolvable": true/false
}}"""

        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            
            messages = [
                SystemMessage(content="You are an expert Windows debugger analyst. Return ONLY valid JSON."),
                HumanMessage(content=prompt)
            ]
            
            response = self.llm.invoke(messages)
            result = self._extract_json(response.content)
            
            if result and 'placeholders' in result:
                return result
            else:
                # Fallback: assume unresolvable if parsing fails
                console.print(f"[yellow]⚠ LLM response parsing failed, treating as unresolvable[/yellow]")
                return self._create_fallback_result(command)
                
        except Exception as e:
            console.print(f"[yellow]⚠ Smart validation failed ({e}), using fallback[/yellow]")
            return self._create_fallback_result(command)
    
    def _build_evidence_summary(self, evidence: list[dict], max_items: int = 10) -> str:
        """Build concise evidence summary for LLM context.
        
        Args:
            evidence: Evidence list
            max_items: Maximum evidence items to include
            
        Returns:
            Formatted evidence summary
        """
        if not evidence:
            return "(No evidence available)"
        
        summary_lines = []
        for i, ev in enumerate(evidence[:max_items], 1):
            cmd = ev.get('command', 'Unknown')
            
            # Prefer summary over raw output
            if ev.get('summary'):
                desc = ev['summary'][:150]
            elif ev.get('finding'):
                desc = ev['finding'][:150]
            else:
                desc = "No summary available"
            
            summary_lines.append(f"{i}. {cmd}")
            summary_lines.append(f"   {desc}")
        
        if len(evidence) > max_items:
            summary_lines.append(f"... and {len(evidence) - max_items} more evidence pieces")
        
        return "\n".join(summary_lines)
    
    def _extract_json(self, text: str) -> dict | None:
        """Extract JSON from LLM response.
        
        Args:
            text: Response text that may contain JSON
            
        Returns:
            Parsed JSON dict or None
        """
        # Try direct parse first
        try:
            return json.loads(text.strip())
        except:
            pass
        
        # Try extracting from code blocks
        if '```' in text:
            parts = text.split('```')
            for part in parts:
                # Skip the language identifier
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
    
    def _create_fallback_result(self, command: str) -> dict:
        """Create fallback result when LLM analysis fails.
        
        Args:
            command: Original command
            
        Returns:
            Fallback analysis result marking as unresolvable
        """
        placeholders = re.findall(r'<[^>]+>', command)
        
        return {
            'has_placeholders': len(placeholders) > 0,
            'resolvable': False,
            'placeholders': [
                {
                    'text': ph,
                    'needs': 'unknown',
                    'resolvable': False,
                    'evidence_source': None,
                    'prerequisite': None,
                    'reason': 'LLM analysis failed, treating as unresolvable for safety'
                }
                for ph in placeholders
            ],
            'overall_resolvable': False
        }
