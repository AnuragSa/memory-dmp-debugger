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
        # Match any <...address...> or <...addr...>
        'address': re.compile(r'<[^>]*(?:address|addr)[^>]*>', re.IGNORECASE),
        # Match any <...MT...> or <...MethodTable...> or <...method table...>
        'mt': re.compile(r'<[^>]*(?:MT\b|MethodTable|method table)[^>]*>', re.IGNORECASE),
        # Match any <...object...>
        'object': re.compile(r'<[^>]*object[^>]*>', re.IGNORECASE),
        # Match any <...thread...> or <...tid...>
        'thread': re.compile(r'<[^>]*(?:thread|tid)[^>]*>', re.IGNORECASE),
        # Match any <...module...>
        'module': re.compile(r'<[^>]*module[^>]*>', re.IGNORECASE),
        # Match any <...value...> or <...val...>
        'value': re.compile(r'<[^>]*(?:value|val)[^>]*>', re.IGNORECASE),
    }
    
    # Patterns to extract actual values from evidence
    EXTRACTION_PATTERNS = {
        'address': [
            # Hex addresses like 0x00007ff8a1234567 or 000001f2a3b4c5d6 (8-16 hex digits)
            re.compile(r'\b(?:0x)?[0-9a-f]{8,16}\b', re.IGNORECASE),
        ],
        'mt': [
            # MethodTable from dumpheap -stat output: MT    Count TotalSize Class Name
            re.compile(r'^([0-9a-f]{8,16})\s+\d+\s+\d+', re.IGNORECASE | re.MULTILINE),
            # MT from object inspection: MT: 0x00007ff8a1234567
            re.compile(r'MT:\s*(?:0x)?([0-9a-f]{8,16})', re.IGNORECASE),
            # Any hex address that might be an MT
            re.compile(r'\b(?:0x)?[0-9a-f]{8,16}\b', re.IGNORECASE),
        ],
        'object': [
            # Object addresses in various formats
            re.compile(r'(?:Object|Address):\s*(?:0x)?([0-9a-f]{8,16})', re.IGNORECASE),
            # Addresses in dumpheap output (one per line)
            re.compile(r'^(?:0x)?([0-9a-f]{8,16})$', re.IGNORECASE | re.MULTILINE),
            # Any hex address
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
        """Filter values based on context hint like 'largest', 'first', 'sample', 'ResolveOperation'.
        
        Args:
            values: List of extracted values
            context_hint: Context hint from placeholder
            source_text: The text where values were found
            
        Returns:
            Filtered list of values
        """
        context_hint_lower = context_hint.lower()
        
        # Check for class/type names in the context
        # E.g., "ResolveOperation", "SqlConnection", "String"
        type_name_match = re.search(r'\b([A-Z][a-zA-Z0-9_.]+)\b', context_hint)
        if type_name_match:
            type_name = type_name_match.group(1)
            # Filter values that appear on lines mentioning this type
            filtered = []
            for value in values:
                value_without_prefix = value.replace('0x', '')
                # Find lines containing both the value and the type name
                for line in source_text.split('\n'):
                    if value_without_prefix in line and type_name in line:
                        filtered.append(value)
                        break
            if filtered:
                return filtered[:5]
        
        # For "largest" or "biggest" or size-related hints (e.g., "6MB", "large")
        if any(word in context_hint_lower for word in ['largest', 'biggest', 'large', 'mb', 'gb', 'kb']):
            # In dumpheap output, look for lines with these addresses and their TotalSize
            value_scores = []
            for value in values:
                value_without_prefix = value.replace('0x', '')
                # Find lines containing this value
                for line in source_text.split('\n'):
                    if value_without_prefix in line:
                        # Extract numbers from the line (could be sizes, counts)
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
