"""GC handles analyzer (Tier 2 - Hybrid: code + local LLM)."""

import re
from typing import Any, Dict, List

from dump_debugger.analyzers.base import AnalysisResult, AnalyzerTier, BaseAnalyzer, LLMInvocationError, TaskComplexity


class GCHandlesAnalyzer(BaseAnalyzer):
    """Analyzer for !gchandles command output.
    
    Tier 2: Hybrid - code parses handle table, local LLM identifies leak patterns.
    """
    
    name = "gchandles"
    description = "Analyzes !gchandles output for pinned objects and handle leaks"
    tier = AnalyzerTier.TIER_2
    supported_commands = ["!gchandles"]
    
    def can_analyze(self, command: str) -> bool:
        """Check if this is a !gchandles command."""
        return "!gchandles" in command.strip().lower()
    
    def analyze(self, command: str, output: str) -> AnalysisResult:
        """Analyze !gchandles output."""
        try:
            # Parse handle statistics
            stats = self._parse_handle_stats(output)
            
            # Parse handle entries (sample for performance)
            handles = self._parse_handles(output, max_entries=1000)
            
            # Count by type
            type_counts = self._count_by_type(handles)
            
            # Calculate totals
            total_handles = stats.get("total_handles", len(handles))
            
            # Generate summary using local LLM if significant handles
            if total_handles > 100:
                interpretation = self._interpret_handles(stats, type_counts, handles[:20])
            else:
                interpretation = "Low handle count, no concerns."
            
            summary = f"Found {total_handles:,} GC handles. {interpretation}"
            
            # Generate findings
            findings = [
                f"Total GC handles: {total_handles:,}",
                f"Handle types: {len(type_counts)}",
            ]
            
            # Add top handle types
            sorted_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
            for handle_type, count in sorted_types[:5]:
                findings.append(f"  {handle_type}: {count:,}")
            
            # Check for issues
            if stats.get("pinned", 0) > 1000:
                findings.append(f"⚠️ High pinned handle count: {stats['pinned']:,} (may prevent GC)")
            
            if total_handles > 10000:
                findings.append("⚠️ Very high handle count - potential leak")
            
            return AnalysisResult(
                structured_data={
                    "stats": stats,
                    "type_counts": type_counts,
                    "total_handles": total_handles,
                    "sample_handles": handles[:100],
                },
                summary=summary,
                findings=findings,
                metadata={
                    "analyzer": self.name,
                    "tier": self.tier.value,
                    "handle_count": total_handles,
                },
                success=True,
            )
        
        except Exception as e:
            return AnalysisResult(
                structured_data={},
                summary="",
                findings=[],
                metadata={"analyzer": self.name, "tier": self.tier.value},
                success=False,
                error=f"Failed to analyze GC handles: {str(e)}",
            )
    
    def _parse_handle_stats(self, output: str) -> Dict[str, int]:
        """Parse GC handle statistics."""
        stats = {}
        
        # Look for summary statistics
        patterns = {
            "strong": r'Strong\s+Handles:\s*(\d+)',
            "pinned": r'Pinned\s+Handles:\s*(\d+)',
            "weak_short": r'Weak\s+Short\s+Handles:\s*(\d+)',
            "weak_long": r'Weak\s+Long\s+Handles:\s*(\d+)',
            "total_handles": r'Total\s+Handles:\s*(\d+)',
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                stats[key] = int(match.group(1))
        
        return stats
    
    def _parse_handles(self, output: str, max_entries: int = 1000) -> List[Dict[str, Any]]:
        """Parse GC handle entries (limited for performance)."""
        handles = []
        lines = output.split('\n')
        
        # Pattern: Handle    Address    Object     Type
        # Example: 000002e9  0x12345678  0x87654321  Strong
        pattern = re.compile(r'^([0-9a-fA-F]+)\s+0x([0-9a-fA-F]+)\s+0x([0-9a-fA-F]+)\s+(\w+)')
        
        for line in lines:
            if len(handles) >= max_entries:
                break
            
            match = pattern.match(line.strip())
            if match:
                handles.append({
                    "handle": match.group(1),
                    "address": match.group(2),
                    "object": match.group(3),
                    "type": match.group(4),
                })
        
        return handles
    
    def _count_by_type(self, handles: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count handles by type."""
        counts = {}
        for handle in handles:
            handle_type = handle.get("type", "Unknown")
            counts[handle_type] = counts.get(handle_type, 0) + 1
        return counts
    
    def _interpret_handles(
        self,
        stats: Dict[str, int],
        type_counts: Dict[str, int],
        sample_handles: List[Dict[str, Any]],
    ) -> str:
        """Use local LLM to interpret handle patterns."""
        # Build concise prompt
        stats_str = ", ".join(f"{k}: {v:,}" for k, v in stats.items())
        types_str = ", ".join(f"{k}: {v:,}" for k, v in sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:5])
        
        prompt = f"""Analyze GC handles for potential issues:

Statistics: {stats_str}
Top types: {types_str}

Identify any concerning patterns (handle leaks, excessive pinning). One sentence."""
        
        try:
            response = self.invoke_llm_with_fallback(prompt, TaskComplexity.MODERATE)
            return response.content.strip()
        except LLMInvocationError:
            # Re-raise LLM errors - no silent fallback
            raise
