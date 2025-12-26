"""Tier 1 analyzer for !dso command output - dump stack objects."""

import re
from collections import Counter
from typing import Any, Dict, List

from dump_debugger.analyzers.base import AnalysisResult, AnalyzerTier, BaseAnalyzer


class DSOAnalyzer(BaseAnalyzer):
    """Analyzes !dso (dump stack objects) command output.
    
    Tier 1: Pure code parsing for instant analysis.
    
    Extracts:
    - Thread ID
    - List of objects on stack with addresses and types
    - Type frequency statistics
    - Notable patterns (many of same type, exceptions, etc.)
    """
    
    name = "dso"
    description = "Stack object analysis and type frequency"
    tier = AnalyzerTier.TIER_1
    supported_commands = ["!dso", "!DumpStackObjects"]
    
    # Known interesting types to highlight
    INTERESTING_TYPES = {
        "Exception": "exception_on_stack",
        "SqlConnection": "database_connection",
        "SqlCommand": "database_query",
        "Lock": "synchronization_object",
        "Monitor": "synchronization_object",
        "Mutex": "synchronization_object",
        "Semaphore": "synchronization_object",
        "Task": "async_task",
        "Compiler": "compilation_activity",
        "HostedCompiler": "hosted_compilation"
    }
    
    def can_analyze(self, command: str) -> bool:
        """Check if this is a dso command."""
        cmd_lower = command.lower().strip()
        return cmd_lower.startswith("!dso") or cmd_lower.startswith("!dumpstackobjects")
    
    def analyze(self, command: str, output: str) -> AnalysisResult:
        """Analyze dso command output.
        
        Args:
            command: The dso command
            output: Command output
            
        Returns:
            Analysis result with stack objects
        """
        try:
            # Extract thread ID
            thread_id = self._extract_thread_id(output)
            
            # Parse stack objects
            stack_objects = self._parse_stack_objects(output)
            
            # Check for empty stack
            if not stack_objects:
                return AnalysisResult(
                    structured_data={
                        "thread_id": thread_id,
                        "object_count": 0,
                        "objects": []
                    },
                    summary=f"Thread {thread_id}: No managed objects on stack",
                    findings=["Thread may be in native code or idle"],
                    metadata={
                        "analyzer": self.name,
                        "tier": self.tier.value,
                        "command": command
                    },
                    success=True
                )
            
            # Calculate type statistics
            type_stats = self._calculate_type_stats(stack_objects)
            
            # Detect patterns
            patterns = self._detect_patterns(stack_objects, type_stats)
            
            # Build findings
            findings = self._build_findings(stack_objects, type_stats, patterns)
            
            # Create summary
            summary = self._create_summary(thread_id, len(stack_objects), type_stats, patterns)
            
            return AnalysisResult(
                structured_data={
                    "thread_id": thread_id,
                    "object_count": len(stack_objects),
                    "objects": stack_objects,
                    "type_statistics": type_stats,
                    "patterns": patterns
                },
                summary=summary,
                findings=findings,
                metadata={
                    "analyzer": self.name,
                    "tier": self.tier.value,
                    "command": command,
                    "has_patterns": len(patterns) > 0
                },
                success=True
            )
            
        except Exception as e:
            return AnalysisResult(
                structured_data={},
                summary="",
                findings=[],
                metadata={
                    "analyzer": self.name,
                    "tier": self.tier.value,
                    "command": command
                },
                error=f"Failed to analyze dso output: {str(e)}",
                success=False
            )
    
    def _extract_thread_id(self, output: str) -> str:
        """Extract thread ID from output."""
        # Pattern: OS Thread Id: 0x3fc (19)
        match = re.search(r'OS Thread Id:\s*0x([0-9a-fA-F]+)\s*\((\d+)\)', output)
        if match:
            hex_id = match.group(1)
            decimal_id = match.group(2)
            return f"0x{hex_id} ({decimal_id})"
        return "unknown"
    
    def _parse_stack_objects(self, output: str) -> List[Dict[str, str]]:
        """Parse stack objects from output.
        
        Output format:
        RSP/REG          Object           Name
        000000E7F80FDC28 0000027db4ceae58 Microsoft.Compiler.VisualBasic.CompilerResults
        """
        objects = []
        
        # Look for lines with stack pointer, object address, and type
        # Pattern: hex_address hex_address type_name
        pattern = r'^([0-9A-Fa-f]{16})\s+([0-9A-Fa-f]{16})\s+(.+)$'
        
        for line in output.split('\n'):
            match = re.match(pattern, line.strip())
            if match:
                stack_pointer = match.group(1)
                object_address = match.group(2)
                full_type = match.group(3).strip()
                
                # Extract short type name (last part after last dot)
                short_type = full_type.split('.')[-1].split('[')[0]  # Remove generic type parameters
                
                objects.append({
                    "stack_pointer": stack_pointer,
                    "address": object_address,
                    "full_type": full_type,
                    "short_type": short_type
                })
        
        return objects
    
    def _calculate_type_stats(self, stack_objects: List[Dict[str, str]]) -> Dict[str, Any]:
        """Calculate type frequency statistics."""
        # Count by short type name
        short_types = [obj["short_type"] for obj in stack_objects]
        full_types = [obj["full_type"] for obj in stack_objects]
        
        short_type_counts = Counter(short_types)
        full_type_counts = Counter(full_types)
        
        # Find most common
        most_common_short = short_type_counts.most_common(5)
        most_common_full = full_type_counts.most_common(5)
        
        # Count unique types
        unique_types = len(set(full_types))
        
        return {
            "total_objects": len(stack_objects),
            "unique_types": unique_types,
            "most_common_short": most_common_short,
            "most_common_full": most_common_full,
            "all_short_types": dict(short_type_counts),
            "all_full_types": dict(full_type_counts)
        }
    
    def _detect_patterns(self, stack_objects: List[Dict[str, str]], type_stats: Dict[str, Any]) -> List[str]:
        """Detect notable patterns in stack objects."""
        patterns = []
        
        # Check for exceptions
        exception_objects = [obj for obj in stack_objects if "Exception" in obj["full_type"]]
        if exception_objects:
            patterns.append(f"exception_on_stack: {len(exception_objects)} exception object(s)")
        
        # Check for repeated types (potential issue)
        for short_type, count in type_stats["most_common_short"]:
            if count >= 5:
                patterns.append(f"repeated_type: {short_type} appears {count} times")
        
        # Check for interesting types
        for obj in stack_objects:
            for pattern_name, category in self.INTERESTING_TYPES.items():
                if pattern_name in obj["full_type"]:
                    patterns.append(f"{category}: {obj['short_type']}")
                    break  # Only add once per object
        
        # Check for compilation activity
        compiler_objects = [obj for obj in stack_objects if "Compiler" in obj["full_type"]]
        if compiler_objects:
            patterns.append(f"compilation_activity: {len(compiler_objects)} compiler-related objects")
        
        # Check for database activity
        sql_objects = [obj for obj in stack_objects if "Sql" in obj["full_type"] or "Database" in obj["full_type"]]
        if sql_objects:
            patterns.append(f"database_activity: {len(sql_objects)} database-related objects")
        
        return patterns
    
    def _build_findings(
        self, 
        stack_objects: List[Dict[str, str]], 
        type_stats: Dict[str, Any],
        patterns: List[str]
    ) -> List[str]:
        """Build human-readable findings."""
        findings = []
        
        # Basic stats
        findings.append(f"📊 {type_stats['total_objects']} objects on stack, {type_stats['unique_types']} unique types")
        
        # Top types
        if type_stats["most_common_short"]:
            top_3 = type_stats["most_common_short"][:3]
            top_str = ", ".join([f"{name}({count})" for name, count in top_3])
            findings.append(f"🔝 Most common: {top_str}")
        
        # Pattern findings
        if patterns:
            findings.append("🔍 Notable patterns:")
            for pattern in patterns[:5]:  # Limit to 5 most important
                findings.append(f"  • {pattern}")
        
        # Specific warnings
        if any("exception" in p.lower() for p in patterns):
            findings.append("⚠️ Exception object on stack - thread may be handling error")
        
        if any("repeated_type" in p for p in patterns):
            findings.append("⚠️ Same type appears multiple times - possible recursion or tight loop")
        
        return findings
    
    def _create_summary(
        self, 
        thread_id: str, 
        object_count: int,
        type_stats: Dict[str, Any],
        patterns: List[str]
    ) -> str:
        """Create concise summary."""
        summary_parts = [f"Thread {thread_id}: {object_count} objects on stack"]
        
        # Add top type
        if type_stats["most_common_short"]:
            top_type, top_count = type_stats["most_common_short"][0]
            summary_parts.append(f"dominated by {top_type}({top_count})")
        
        # Add key pattern
        if patterns:
            # Prioritize certain patterns
            priority_patterns = [p for p in patterns if "exception" in p.lower() or "compilation" in p.lower()]
            if priority_patterns:
                summary_parts.append(f"- {priority_patterns[0]}")
            elif len(patterns) > 0:
                summary_parts.append(f"- {patterns[0]}")
        
        return ", ".join(summary_parts)
