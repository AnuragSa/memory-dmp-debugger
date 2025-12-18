"""Resolves placeholders in debugger commands by extracting values from previous evidence.

This module handles cases where the LLM suggests commands like:
- !gcroot <address_of_sample_object>
- !dumpheap -mt <MT_of_largest_objects>
- !objsize <address_of_large_object>

It parses previous evidence to extract actual addresses, method tables, etc.
"""

import re
from typing import Any

from rich.console import Console

console = Console()


class PlaceholderResolver:
    """Resolves placeholders in debugger commands using previous evidence."""
    
    # Patterns for different placeholder types
    PLACEHOLDER_PATTERNS = {
        'address': re.compile(r'<(?:address|addr)(?:_of_)?(?:\w+)?>', re.IGNORECASE),
        'mt': re.compile(r'<(?:MT|MethodTable)(?:_of_)?(?:\w+)?>', re.IGNORECASE),
        'object': re.compile(r'<object(?:_\w+)?>', re.IGNORECASE),
        'thread': re.compile(r'<(?:thread|tid)(?:_\w+)?>', re.IGNORECASE),
        'module': re.compile(r'<module(?:_\w+)?>', re.IGNORECASE),
        'value': re.compile(r'<(?:value|val)(?:_\w+)?>', re.IGNORECASE),
    }
    
    # Patterns to extract actual values from evidence
    EXTRACTION_PATTERNS = {
        'address': [
            # Hex addresses like 0x00007ff8a1234567 or 000001f2a3b4c5d6
            re.compile(r'\b(?:0x)?[0-9a-f]{8,16}\b', re.IGNORECASE),
        ],
        'mt': [
            # MethodTable column in dumpheap output: MT    Count TotalSize Class Name
            re.compile(r'^([0-9a-f]{8,16})\s+\d+\s+\d+', re.IGNORECASE | re.MULTILINE),
        ],
        'object': [
            # Object addresses in various formats
            re.compile(r'(?:Object|Address):\s*(?:0x)?([0-9a-f]{8,16})', re.IGNORECASE),
            re.compile(r'\b(?:0x)?[0-9a-f]{8,16}\b', re.IGNORECASE),
        ],
        'thread': [
            # Thread IDs in various formats
            re.compile(r'(?:Thread|TID):\s*(\d+)', re.IGNORECASE),
            re.compile(r'^\s*(\d+)\s+\d+\s+', re.MULTILINE),  # threads output format
        ],
    }
    
    def __init__(self, previous_evidence: list[dict[str, Any]]):
        """Initialize with previous evidence to search for values.
        
        Args:
            previous_evidence: List of evidence dictionaries with 'command', 'output', 'summary' keys
        """
        self.previous_evidence = previous_evidence
    
    def detect_placeholders(self, command: str) -> list[tuple[str, str]]:
        """Detect placeholders in a command.
        
        Args:
            command: The command to check
            
        Returns:
            List of (placeholder_text, placeholder_type) tuples
        """
        placeholders = []
        for ptype, pattern in self.PLACEHOLDER_PATTERNS.items():
            matches = pattern.findall(command)
            for match in matches:
                placeholders.append((match, ptype))
        return placeholders
    
    def extract_values(self, placeholder_type: str, context_hint: str = None) -> list[str]:
        """Extract values of a specific type from previous evidence.
        
        Args:
            placeholder_type: Type of value to extract (address, mt, object, etc.)
            context_hint: Optional hint from the placeholder name (e.g., "largest" from <address_of_largest_object>)
            
        Returns:
            List of extracted values
        """
        values = []
        extraction_patterns = self.EXTRACTION_PATTERNS.get(placeholder_type, [])
        
        if not extraction_patterns:
            return values
        
        # Search through evidence in reverse order (most recent first)
        for evidence in reversed(self.previous_evidence):
            # Check both output and summary
            text_sources = []
            
            # Prefer summary for external evidence (large outputs)
            if evidence.get('evidence_type') == 'external' and evidence.get('summary'):
                text_sources.append(evidence['summary'])
            
            # Always check output if available
            if evidence.get('output'):
                text_sources.append(evidence['output'])
            
            for text in text_sources:
                if not text:
                    continue
                
                for pattern in extraction_patterns:
                    matches = pattern.findall(text)
                    for match in matches:
                        # Handle tuple results from groups
                        value = match[0] if isinstance(match, tuple) else match
                        value = value.strip()
                        
                        # Normalize hex addresses (ensure 0x prefix)
                        if placeholder_type in ('address', 'mt', 'object'):
                            if value and not value.startswith('0x'):
                                value = '0x' + value
                        
                        if value and value not in values:
                            values.append(value)
                
                # If we found values and have a context hint, try to filter
                if values and context_hint:
                    filtered = self._filter_by_context(values, context_hint, text)
                    if filtered:
                        return filtered
                
                # Stop if we have enough values
                if len(values) >= 10:
                    return values[:10]
        
        return values
    
    def _filter_by_context(self, values: list[str], context_hint: str, source_text: str) -> list[str]:
        """Filter values based on context hint like 'largest', 'first', 'sample'.
        
        Args:
            values: List of extracted values
            context_hint: Context hint from placeholder
            source_text: The text where values were found
            
        Returns:
            Filtered list of values
        """
        context_hint_lower = context_hint.lower()
        
        # For "largest" or "biggest", try to find values with largest associated numbers
        if 'largest' in context_hint_lower or 'biggest' in context_hint_lower:
            # In dumpheap output, look for lines with these addresses and their TotalSize
            value_scores = []
            for value in values:
                # Find lines containing this value
                for line in source_text.split('\n'):
                    if value.replace('0x', '') in line:
                        # Extract numbers from the line
                        numbers = re.findall(r'\b(\d+)\b', line)
                        if numbers:
                            # Use the largest number as score (could be TotalSize or Count)
                            score = max(int(n) for n in numbers)
                            value_scores.append((value, score))
                            break
            
            if value_scores:
                # Sort by score descending and return top values
                value_scores.sort(key=lambda x: x[1], reverse=True)
                return [v for v, _ in value_scores[:5]]
        
        # For "first" or "sample", return first few
        if 'first' in context_hint_lower or 'sample' in context_hint_lower:
            return values[:3]
        
        return []
    
    def resolve_command(self, command: str) -> tuple[str, bool, str]:
        """Resolve all placeholders in a command.
        
        Args:
            command: Command with possible placeholders
            
        Returns:
            Tuple of (resolved_command, success, message)
        """
        placeholders = self.detect_placeholders(command)
        
        if not placeholders:
            # No placeholders, command is ready
            return command, True, "No placeholders found"
        
        resolved_command = command
        unresolved = []
        
        for placeholder_text, placeholder_type in placeholders:
            # Extract context hint from placeholder
            context_hint = self._extract_context_hint(placeholder_text)
            
            # Extract values of this type
            values = self.extract_values(placeholder_type, context_hint)
            
            if not values:
                unresolved.append(placeholder_text)
                continue
            
            # Replace placeholder with first extracted value
            # For commands that expect multiple values, we'll use the first one
            # (Future enhancement: could generate multiple commands)
            resolved_command = resolved_command.replace(placeholder_text, values[0])
        
        if unresolved:
            return resolved_command, False, f"Could not resolve: {', '.join(unresolved)}"
        
        return resolved_command, True, f"Resolved {len(placeholders)} placeholder(s)"
    
    def _extract_context_hint(self, placeholder_text: str) -> str:
        """Extract context hint from placeholder text.
        
        Args:
            placeholder_text: The placeholder like "<address_of_largest_object>"
            
        Returns:
            Context hint like "largest_object"
        """
        # Remove < > and common prefixes
        hint = placeholder_text.strip('<>')
        hint = re.sub(r'^(address|addr|mt|methodtable|object|thread|module|value)_', '', hint, flags=re.IGNORECASE)
        hint = re.sub(r'^of_', '', hint, flags=re.IGNORECASE)
        return hint


def detect_placeholders(command: str) -> bool:
    """Quick check if a command contains placeholders.
    
    Args:
        command: Command to check
        
    Returns:
        True if command contains placeholders
    """
    return bool(re.search(r'<[^>]+>', command))


def resolve_command_placeholders(
    command: str, 
    previous_evidence: list[dict[str, Any]]
) -> tuple[str, bool, str]:
    """Convenience function to resolve placeholders in a command.
    
    Args:
        command: Command with possible placeholders
        previous_evidence: List of previous evidence to search for values
        
    Returns:
        Tuple of (resolved_command, success, message)
    """
    if not detect_placeholders(command):
        return command, True, "No placeholders found"
    
    resolver = PlaceholderResolver(previous_evidence)
    return resolver.resolve_command(command)
