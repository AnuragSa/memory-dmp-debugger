"""Resolves placeholders in debugger commands by extracting values from previous evidence.

This module handles cases where the LLM suggests commands like:
- !gcroot <address_of_sample_object>
- !dumpheap -mt <MT_of_largest_objects>
- !objsize <address_of_large_object>
- ~~[ThreadId]s (malformed placeholder - should be actual OSID)

It parses previous evidence to extract actual addresses, method tables, etc.
"""

import re
from typing import Any

from rich.console import Console

console = Console()


# Pattern to detect malformed thread placeholder in OSID syntax
# This catches ~~[ThreadId]s, ~~[thread]e, etc. where ThreadId/thread is a placeholder, not a real OSID
MALFORMED_THREAD_PLACEHOLDER = re.compile(r'~~\[([A-Za-z_][A-Za-z0-9_]*)\]', re.IGNORECASE)


class PlaceholderResolver:
    """Resolves placeholders in debugger commands using previous evidence."""
    
    # Patterns for different placeholder types (angle brackets)
    PLACEHOLDER_PATTERNS = {
        # Match any <...address...> or <...addr...>
        'address': re.compile(r'<[^>]*(?:address|addr)[^>]*>', re.IGNORECASE),
        # Match any <...MT...> or <...MethodTable...> or <...method table...>
        'mt': re.compile(r'<[^>]*(?:MT\b|MethodTable|method table)[^>]*>', re.IGNORECASE),
        # Match any <...object...>
        'object': re.compile(r'<[^>]*object[^>]*>', re.IGNORECASE),
        # Match any <...thread...> or <...tid...> (generic thread placeholder)
        'thread': re.compile(r'<[^>]*(?:thread|tid)[^>]*>', re.IGNORECASE),
        # Match placeholders specifically for DBG thread index (e.g., <DBG_THREAD_ID>, <OWNER_DBG>)
        'dbg_thread': re.compile(r'<[^>]*(?:dbg[^>]*thread|owner[^>]*dbg)[^>]*>', re.IGNORECASE),
        # Match placeholders specifically for OSID (e.g., <OSID>, <OWNER_OSID>)
        'osid': re.compile(r'<[^>]*osid[^>]*>', re.IGNORECASE),
        # Match any <...module...>
        'module': re.compile(r'<[^>]*module[^>]*>', re.IGNORECASE),
        # Match any <...value...> or <...val...>
        'value': re.compile(r'<[^>]*(?:value|val)[^>]*>', re.IGNORECASE),
    }
    
    # Patterns to extract actual values from evidence
    EXTRACTION_PATTERNS = {
        'address': [
            # Object addresses from dumpheap output: Address MT Size
            # Pattern: 16-digit hex address at start of line, followed by MT and Size
            # Use capturing group to get just the address (first column)
            re.compile(r'^(?:0x)?([0-9a-f]{12,16})\s+(?:0x)?[0-9a-f]{8,16}\s+\d+', re.IGNORECASE | re.MULTILINE),
            # Object addresses that are NOT high kernel/code addresses
            # True heap objects: 0x0000000000000000 to 0x0000003fffffffff (low 2GB range)
            # Avoid: 0x00007ff... (method tables), 0x00007ffe... (system DLLs)
            re.compile(r'\b(?:0x)?0{4,8}([0-3][0-9a-f]{7,11})\b', re.IGNORECASE),
        ],
        'mt': [
            # MethodTable from dumpheap -stat output: MT    Count TotalSize Class Name
            re.compile(r'^([0-9a-f]{8,16})\s+\d+\s+\d+', re.IGNORECASE | re.MULTILINE),
            # MT from object inspection: MT: 0x00007ff8a1234567
            re.compile(r'MT:\s*(?:0x)?([0-9a-f]{8,16})', re.IGNORECASE),
            # Any hex address that might be an MT (typically high addresses 0x7ff...)
            re.compile(r'\b(?:0x)?([4-9a-f][0-9a-f]{7,15})\b', re.IGNORECASE),
        ],
        'object': [
            # Object addresses from dumpheap: Address MT Size (at start of line)
            re.compile(r'^(?:0x)?([0-9a-f]{12,16})\s+(?:0x)?[0-9a-f]{8,16}\s+\d+', re.IGNORECASE | re.MULTILINE),
            # Object addresses after labels (ONLY true low range - require leading zeros)
            re.compile(r'(?:Object|Address):\s*(?:0x)?0{4,8}([0-3][0-9a-f]{7,11})', re.IGNORECASE),
            # Heap object addresses - must have leading zeros to avoid high addresses
            re.compile(r'\b(?:0x)?0{4,8}([0-3][0-9a-f]{7,11})\b', re.IGNORECASE),
        ],
        'thread': [
            # Thread IDs in various formats - returns (DBG#, OSID) tuples where available
            # Pattern for !threads output: "  DBG#  ManagedID  OSID  ThreadObj..."
            # Example: "  18    12  d78  000001234..."  -> DBG=18 (decimal), OSID=d78 (hex)
            re.compile(r'^\s*(\d+)\s+\d+\s+([0-9a-fA-F]+)\s+[0-9a-fA-F]{12,16}', re.MULTILINE),
            # Pattern for !syncblk "Owning Thread Info": "ThreadObjAddr OSID DBG#"
            # Example: "000002543dd83c70 d78  18" -> OSID=d78, DBG=18 (both hex here)
            re.compile(r'[0-9a-fA-F]{12,16}\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[0-9a-fA-F]{12,16}', re.IGNORECASE),
            # Simple thread ID patterns
            re.compile(r'(?:Thread|TID):\s*(\d+)', re.IGNORECASE),
        ],
        # New: Specific pattern for debugger thread index (for ~<num>e commands)
        'dbg_thread': [
            # From !threads: first column is DBG#
            re.compile(r'^\s*(\d+)\s+\d+\s+[0-9a-fA-F]+\s+[0-9a-fA-F]{12,16}', re.MULTILINE),
            # From !syncblk: last number before SyncBlock owner address is DBG# (in hex)
            re.compile(r'[0-9a-fA-F]{12,16}\s+[0-9a-fA-F]+\s+([0-9a-fA-F]+)\s+[0-9a-fA-F]{12,16}', re.IGNORECASE),
        ],
        # New: Specific pattern for OS thread ID (for ~~[osid]e commands)
        'osid': [
            # From !threads: third column is OSID (hex)
            re.compile(r'^\s*\d+\s+\d+\s+([0-9a-fA-F]+)\s+[0-9a-fA-F]{12,16}', re.MULTILINE),
            # From !syncblk: OSID is after ThreadObjAddr
            re.compile(r'[0-9a-fA-F]{12,16}\s+([0-9a-fA-F]+)\s+[0-9a-fA-F]+\s+[0-9a-fA-F]{12,16}', re.IGNORECASE),
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
    
    def resolve_command(self, command: str, used_addresses: set[str] = None, invalid_addresses: set[str] = None) -> tuple[str, bool, str]:
        """Resolve all placeholders in a command.
        
        Args:
            command: Command with possible placeholders
            used_addresses: Set of addresses already used (to avoid duplicates)
            invalid_addresses: Set of addresses that returned errors (to skip)
            
        Returns:
            Tuple of (resolved_command, success, message)
        """
        if used_addresses is None:
            used_addresses = set()
        if invalid_addresses is None:
            invalid_addresses = set()
        
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
            
            # Handle thread placeholders specially
            if placeholder_type in ('thread', 'dbg_thread', 'osid'):
                if not values:
                    unresolved.append(f"{placeholder_text} (no thread IDs found in evidence)")
                    continue
                
                value_to_insert = values[0]
                
                # Determine the correct format based on command syntax
                # For ~<num>e commands: use decimal DBG#
                # For ~~[osid]e commands: use hex OSID without 0x
                if '~[' in resolved_command or '~~[' in resolved_command:
                    # OSID syntax - keep as hex without 0x prefix
                    if value_to_insert.startswith('0x'):
                        value_to_insert = value_to_insert[2:]
                    # Don't convert - OSID should stay as hex
                elif resolved_command.startswith('~') and 'e ' in resolved_command:
                    # ~<num>e syntax - convert hex to decimal if needed
                    # Check if value looks like hex (from !syncblk DBG# column which is hex)
                    try:
                        # If all chars are valid hex and could be interpreted as hex
                        if all(c in '0123456789abcdefABCDEF' for c in value_to_insert):
                            # Convert from hex to decimal
                            decimal_val = int(value_to_insert, 16)
                            value_to_insert = str(decimal_val)
                    except ValueError:
                        pass  # Keep original value
                
                resolved_command = resolved_command.replace(placeholder_text, value_to_insert)
                continue
            
            # Filter out used and invalid addresses
            if placeholder_type in ('address', 'object', 'mt'):
                filtered_values = []
                for value in values:
                    # Normalize: ensure 0x prefix and pad to 16 digits for comparison
                    if not value.startswith('0x'):
                        value = '0x' + value
                    # Pad to 16 hex digits (64-bit address) for consistent comparison
                    if len(value) < 18:  # 0x + 16 digits = 18 chars
                        value = '0x' + value[2:].zfill(16)
                    
                    # Skip if already used or invalid
                    if value in used_addresses or value in invalid_addresses:
                        continue
                    
                    filtered_values.append(value)
                values = filtered_values
            
            if not values:
                # If all values were filtered out, try to get more from evidence
                unresolved.append(f"{placeholder_text} (all available addresses already used or invalid)")
                continue
            
            # Replace placeholder with first available unused value
            value_to_insert = values[0]
            
            # Avoid double 0x prefix: if command has "0x<placeholder>" and value starts with "0x", strip it
            if placeholder_text.startswith('<') and placeholder_text.endswith('>'):
                # Check if there's "0x" immediately before the placeholder
                placeholder_pos = resolved_command.find(placeholder_text)
                if placeholder_pos > 1 and resolved_command[placeholder_pos-2:placeholder_pos] == '0x':
                    # Command has "0x<placeholder>", strip 0x from value if present
                    if value_to_insert.startswith('0x'):
                        value_to_insert = value_to_insert[2:]
            
            resolved_command = resolved_command.replace(placeholder_text, value_to_insert)
        
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
        True if command contains placeholders (angle brackets or malformed thread syntax)
    """
    # Check for angle bracket placeholders: <address>, <thread>, etc.
    if re.search(r'<[^>]+>', command):
        return True
    
    # Check for malformed thread placeholders: ~~[ThreadId], ~~[thread], etc.
    # But NOT valid hex OSIDs like ~~[d78] or ~~[3fc]
    is_malformed, _ = detect_malformed_thread_command(command)
    if is_malformed:
        return True
    
    return False


def detect_malformed_thread_command(command: str) -> tuple[bool, str | None]:
    """Detect if a command has malformed thread placeholder syntax.
    
    WinDbg uses ~~[OSID] where OSID is a hex value like d78, 3fc.
    If the command has ~~[ThreadId] or ~~[thread] where the value is
    clearly a placeholder name (not hex), this is malformed.
    
    Args:
        command: Command to check
        
    Returns:
        Tuple of (is_malformed, placeholder_name or None)
    """
    match = MALFORMED_THREAD_PLACEHOLDER.search(command)
    if match:
        placeholder_value = match.group(1)
        # Check if it looks like a placeholder name vs a valid hex OSID
        # Valid OSIDs: d78, 3fc, 1234, abc
        # Placeholder names: ThreadId, thread, OWNER_THREAD, tid
        if not all(c in '0123456789abcdefABCDEF' for c in placeholder_value):
            # Contains non-hex chars, so it's a placeholder
            return True, placeholder_value
    return False, None


def resolve_command_placeholders(
    command: str, 
    previous_evidence: list[dict[str, Any]],
    used_addresses: set[str] = None,
    invalid_addresses: set[str] = None
) -> tuple[str, bool, str]:
    """Convenience function to resolve placeholders in a command.
    
    Args:
        command: Command with possible placeholders
        previous_evidence: List of previous evidence to search for values
        used_addresses: Set of addresses already used (to avoid duplicates)
        invalid_addresses: Set of addresses that returned errors (to skip)
        
    Returns:
        Tuple of (resolved_command, success, message)
    """
    # First check for malformed thread command syntax like ~~[ThreadId]
    is_malformed, placeholder_name = detect_malformed_thread_command(command)
    if is_malformed:
        # Try to resolve by finding thread IDs from evidence
        resolver = PlaceholderResolver(previous_evidence)
        
        # Extract thread IDs from evidence (try both DBG# and OSID patterns)
        dbg_threads = resolver.extract_values('dbg_thread')
        osids = resolver.extract_values('osid')
        
        if dbg_threads:
            # Prefer using ~<DBG#>e format - convert to decimal and replace
            dbg_num = dbg_threads[0]
            try:
                # Convert hex to decimal if needed
                if all(c in '0123456789abcdefABCDEF' for c in dbg_num):
                    dbg_decimal = int(dbg_num, 16)
                else:
                    dbg_decimal = int(dbg_num)
                
                # Replace ~~[placeholder]s/e with ~<num>s/e format
                # Match ~~[ThreadId]s or ~~[ThreadId]e patterns
                fixed_cmd = re.sub(
                    r'~~\[' + re.escape(placeholder_name) + r'\]([se])',
                    f'~{dbg_decimal}\\1',
                    command,
                    flags=re.IGNORECASE
                )
                console.print(f"[dim cyan]  → Resolved malformed thread: ~~[{placeholder_name}] → ~{dbg_decimal}[/dim cyan]")
                return fixed_cmd, True, f"Resolved malformed thread placeholder to DBG# {dbg_decimal}"
            except ValueError:
                pass
        
        if osids:
            # Fall back to ~~[OSID] format
            osid = osids[0]
            if osid.startswith('0x'):
                osid = osid[2:]
            
            fixed_cmd = re.sub(
                r'~~\[' + re.escape(placeholder_name) + r'\]',
                f'~~[{osid}]',
                command,
                flags=re.IGNORECASE
            )
            console.print(f"[dim cyan]  → Resolved malformed thread: ~~[{placeholder_name}] → ~~[{osid}][/dim cyan]")
            return fixed_cmd, True, f"Resolved malformed thread placeholder to OSID {osid}"
        
        # Could not resolve - return failure
        return command, False, f"Malformed thread placeholder ~~[{placeholder_name}] - no thread IDs found in evidence. Run !threads first."
    
    if not detect_placeholders(command):
        return command, True, "No placeholders found"
    
    if used_addresses is None:
        used_addresses = set()
    if invalid_addresses is None:
        invalid_addresses = set()
    
    resolver = PlaceholderResolver(previous_evidence)
    return resolver.resolve_command(command, used_addresses, invalid_addresses)
