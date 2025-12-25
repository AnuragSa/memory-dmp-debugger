"""Heap dump analyzer (Tier 2 - Hybrid: code parsing + local LLM)."""

import re
from typing import Any, Dict, List

from dump_debugger.analyzers.base import AnalysisResult, AnalyzerTier, BaseAnalyzer, TaskComplexity


class DumpHeapAnalyzer(BaseAnalyzer):
    """Analyzer for !dumpheap command output.
    
    Tier 2: Hybrid approach - code parses structure, local LLM interprets patterns.
    Handles both -stat (statistics) and -type (object dumps).
    """
    
    name = "dumpheap"
    description = "Analyzes !dumpheap output for heap statistics and object analysis"
    tier = AnalyzerTier.TIER_2
    supported_commands = ["!dumpheap", "!dumpheap -stat", "!dumpheap -type"]
    
    def can_analyze(self, command: str) -> bool:
        """Check if this is a !dumpheap command."""
        cmd = command.strip().lower()
        return cmd.startswith("!dumpheap")
    
    def analyze(self, command: str, output: str) -> AnalysisResult:
        """Analyze !dumpheap output.
        
        Example -stat output:
        ```
        Statistics:
              MT    Count    TotalSize Class Name
        00007ff8a1b2c3d0        1           24 System.Collections.Generic.GenericEqualityComparer`1[[System.String, System.Private.CoreLib]]
        00007ff8a1b2c4e0      123         2952 System.String
        00007ff8a1b2c5f0       45         1080 System.Int32
        Total 169 objects
        ```
        
        Returns:
            AnalysisResult with heap statistics
        """
        try:
            # Determine command type
            is_stat = "-stat" in command.lower()
            is_type = "-type" in command.lower()
            
            if is_stat:
                return self._analyze_stat(output)
            elif is_type:
                return self._analyze_type(command, output)
            else:
                return self._analyze_full_dump(output)
        
        except Exception as e:
            return AnalysisResult(
                structured_data={},
                summary="",
                findings=[],
                metadata={"analyzer": self.name, "tier": self.tier.value},
                success=False,
                error=f"Failed to analyze heap dump: {str(e)}",
            )
    
    def _analyze_stat(self, output: str) -> AnalysisResult:
        """Analyze !dumpheap -stat output."""
        # Parse table structure (code parsing)
        heap_stats = self._parse_heap_stats(output)
        
        # Calculate aggregates
        total_count = sum(item["count"] for item in heap_stats)
        total_size = sum(item["total_size"] for item in heap_stats)
        
        # Identify top types
        top_by_count = sorted(heap_stats, key=lambda x: x["count"], reverse=True)[:10]
        top_by_size = sorted(heap_stats, key=lambda x: x["total_size"], reverse=True)[:10]
        
        # Use local LLM to interpret patterns (simple task)
        llm = self.get_llm(TaskComplexity.SIMPLE)
        interpretation = self._interpret_heap_patterns(llm, heap_stats, top_by_count, top_by_size)
        
        # Generate summary
        summary = (
            f"Heap contains {total_count:,} objects totaling {self._format_bytes(total_size)}. "
            f"{interpretation}"
        )
        
        # Generate findings
        findings = [
            f"Total objects: {total_count:,}",
            f"Total heap size: {self._format_bytes(total_size)}",
            f"Unique types: {len(heap_stats)}",
        ]
        
        # Add top types
        if top_by_count:
            top_type = top_by_count[0]
            findings.append(
                f"Most common type: {top_type['class_name']} ({top_type['count']:,} instances)"
            )
        
        if top_by_size:
            top_type = top_by_size[0]
            findings.append(
                f"Largest type by size: {top_type['class_name']} ({self._format_bytes(top_type['total_size'])})"
            )
        
        return AnalysisResult(
            structured_data={
                "total_count": total_count,
                "total_size": total_size,
                "unique_types": len(heap_stats),
                "heap_stats": heap_stats,
                "top_by_count": top_by_count[:5],
                "top_by_size": top_by_size[:5],
            },
            summary=summary,
            findings=findings,
            metadata={
                "analyzer": self.name,
                "tier": self.tier.value,
                "command_type": "stat",
            },
            success=True,
        )
    
    def _analyze_type(self, command: str, output: str) -> AnalysisResult:
        """Analyze !dumpheap -type output (specific type dump)."""
        # Extract type name from command
        type_name = self._extract_type_name(command)
        
        # Parse object addresses
        objects = self._parse_object_list(output)
        
        # Calculate statistics
        total_count = len(objects)
        total_size = sum(obj["size"] for obj in objects if "size" in obj)
        
        summary = (
            f"Found {total_count} instances of '{type_name}' "
            f"totaling {self._format_bytes(total_size)}."
        )
        
        findings = [
            f"Type: {type_name}",
            f"Instance count: {total_count}",
            f"Total size: {self._format_bytes(total_size)}",
        ]
        
        if total_count > 1000:
            findings.append(f"⚠️ High instance count may indicate memory leak")
        
        return AnalysisResult(
            structured_data={
                "type_name": type_name,
                "objects": objects[:100],  # Limit to first 100
                "total_count": total_count,
                "total_size": total_size,
            },
            summary=summary,
            findings=findings,
            metadata={
                "analyzer": self.name,
                "tier": self.tier.value,
                "command_type": "type",
            },
            success=True,
        )
    
    def _analyze_full_dump(self, output: str) -> AnalysisResult:
        """Analyze full heap dump (no filters)."""
        # Similar to -stat but with all objects
        return self._analyze_stat(output)
    
    def _parse_heap_stats(self, output: str) -> List[Dict[str, Any]]:
        """Parse heap statistics table."""
        stats = []
        lines = output.split('\n')
        
        # Pattern: MT    Count    TotalSize Class Name
        # Example: 00007ff8a1b2c4e0      123         2952 System.String
        pattern = re.compile(r'^([0-9a-fA-F]+)\s+(\d+)\s+(\d+)\s+(.+)$')
        
        for line in lines:
            match = pattern.match(line.strip())
            if match:
                stats.append({
                    "method_table": match.group(1),
                    "count": int(match.group(2)),
                    "total_size": int(match.group(3)),
                    "class_name": match.group(4).strip(),
                })
        
        return stats
    
    def _parse_object_list(self, output: str) -> List[Dict[str, Any]]:
        """Parse object address list."""
        objects = []
        lines = output.split('\n')
        
        # Pattern: Address       MT     Size
        # Example: 000001f2a3b4c5d6 00007ff8a1b2c4e0       24
        pattern = re.compile(r'^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+(\d+)')
        
        for line in lines:
            match = pattern.match(line.strip())
            if match:
                objects.append({
                    "address": match.group(1),
                    "method_table": match.group(2),
                    "size": int(match.group(3)),
                })
        
        return objects
    
    def _extract_type_name(self, command: str) -> str:
        """Extract type name from -type command."""
        # Example: !dumpheap -type System.String
        parts = command.split()
        for i, part in enumerate(parts):
            if part.lower() == "-type" and i + 1 < len(parts):
                return parts[i + 1]
        return "Unknown"
    
    def _interpret_heap_patterns(
        self,
        llm: Any,
        heap_stats: List[Dict[str, Any]],
        top_by_count: List[Dict[str, Any]],
        top_by_size: List[Dict[str, Any]],
    ) -> str:
        """Use local LLM to interpret heap patterns.
        
        This is a simple interpretation task suitable for local LLM.
        """
        # Build prompt with top types
        top_count_list = "\n".join(
            f"  - {item['class_name']}: {item['count']:,} instances"
            for item in top_by_count[:5]
        )
        
        top_size_list = "\n".join(
            f"  - {item['class_name']}: {self._format_bytes(item['total_size'])}"
            for item in top_by_size[:5]
        )
        
        prompt = f"""Analyze this heap snapshot and provide a brief 1-sentence interpretation:

Top types by count:
{top_count_list}

Top types by size:
{top_size_list}

Identify any concerning patterns (memory leaks, excessive allocations, etc.). Be concise."""
        
        try:
            response = llm.invoke(prompt)
            return response.content.strip()
        except Exception:
            # Fallback if LLM fails
            return "Heap analysis complete."
    
    def _format_bytes(self, size: int) -> str:
        """Format byte size for display."""
        if size < 1024:
            return f"{size} bytes"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f} GB"
