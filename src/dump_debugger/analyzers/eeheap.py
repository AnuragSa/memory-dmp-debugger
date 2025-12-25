"""EE Heap analyzer (Tier 1 - Pure code parsing)."""

import re
from typing import Any, Dict, List

from dump_debugger.analyzers.base import AnalysisResult, AnalyzerTier, BaseAnalyzer


class EEHeapAnalyzer(BaseAnalyzer):
    """Analyzer for !eeheap command output.
    
    Tier 1: Pure code parsing - extracts GC heap statistics.
    """
    
    name = "eeheap"
    description = "Analyzes !eeheap output for GC heap statistics"
    tier = AnalyzerTier.TIER_1
    supported_commands = ["!eeheap", "!eeheap -gc"]
    
    def can_analyze(self, command: str) -> bool:
        """Check if this is a !eeheap command."""
        cmd = command.strip().lower()
        return cmd.startswith("!eeheap")
    
    def analyze(self, command: str, output: str) -> AnalysisResult:
        """Analyze !eeheap output."""
        try:
            # Parse heap count
            num_heaps = self._extract_heap_count(output)
            
            # Parse per-heap statistics
            heaps = self._parse_heap_segments(output)
            
            # Calculate totals
            total_size = sum(h.get("total_size", 0) for h in heaps)
            total_segments = len(heaps)
            
            # Parse LOH statistics
            loh_segments = [h for h in heaps if h.get("is_loh", False)]
            loh_size = sum(h.get("total_size", 0) for h in loh_segments)
            
            # Generate summary
            summary = (
                f"GC has {num_heaps} heaps totaling {self._format_bytes(total_size)}. "
                f"LOH: {self._format_bytes(loh_size)}"
            )
            
            # Generate findings
            findings = [
                f"Number of GC heaps: {num_heaps}",
                f"Total heap size: {self._format_bytes(total_size)}",
                f"Total segments: {total_segments}",
                f"LOH size: {self._format_bytes(loh_size)}",
            ]
            
            # Check for issues
            if total_size > 2 * 1024 * 1024 * 1024:  # > 2 GB
                findings.append("⚠️ High memory usage (>2 GB)")
            
            if loh_size > total_size * 0.3:  # LOH > 30%
                findings.append("⚠️ High LOH percentage (>30% of total)")
            
            # Add per-heap summary
            if heaps:
                findings.append(f"Heap sizes range: {self._format_bytes(min(h['total_size'] for h in heaps if 'total_size' in h))} - {self._format_bytes(max(h['total_size'] for h in heaps if 'total_size' in h))}")
            
            return AnalysisResult(
                structured_data={
                    "num_heaps": num_heaps,
                    "heaps": heaps,
                    "total_size": total_size,
                    "loh_size": loh_size,
                    "segment_count": total_segments,
                },
                summary=summary,
                findings=findings,
                metadata={
                    "analyzer": self.name,
                    "tier": self.tier.value,
                    "total_size_mb": total_size // (1024 * 1024),
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
                error=f"Failed to analyze EE heap: {str(e)}",
            )
    
    def _extract_heap_count(self, output: str) -> int:
        """Extract number of GC heaps."""
        match = re.search(r'Number of GC Heaps:\s*(\d+)', output)
        return int(match.group(1)) if match else 1
    
    def _parse_heap_segments(self, output: str) -> List[Dict[str, Any]]:
        """Parse heap segment information."""
        segments = []
        lines = output.split('\n')
        
        is_loh = False
        for line in lines:
            # Check for LOH marker
            if 'Large object heap' in line or 'large object heap' in line:
                is_loh = True
                continue
            
            if 'ephemeral segment' in line.lower():
                is_loh = False
                continue
            
            # Pattern: segment    begin      allocated   size
            # Example: 000002e951e50000  000002e951e51000  000002e96948c298  0x1763b298(392409752)
            match = re.match(
                r'^\s*([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+0x([0-9a-fA-F]+)\((\d+)\)',
                line.strip()
            )
            
            if match:
                segments.append({
                    "segment_addr": match.group(1),
                    "begin": match.group(2),
                    "allocated": match.group(3),
                    "size_hex": match.group(4),
                    "total_size": int(match.group(5)),
                    "is_loh": is_loh,
                })
        
        return segments
    
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
