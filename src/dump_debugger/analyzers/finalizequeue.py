"""Finalizer queue analyzer (Tier 1 - Pure code parsing)."""

import re
from typing import Any, Dict, List

from dump_debugger.analyzers.base import AnalysisResult, AnalyzerTier, BaseAnalyzer


class FinalizeQueueAnalyzer(BaseAnalyzer):
    """Analyzer for !finalizequeue command output.
    
    Tier 1: Pure code parsing - extracts finalizer queue statistics.
    """
    
    name = "finalizequeue"
    description = "Analyzes !finalizequeue output for finalization backlog"
    tier = AnalyzerTier.TIER_1
    supported_commands = ["!finalizequeue"]
    
    def can_analyze(self, command: str) -> bool:
        """Check if this is a !finalizequeue command."""
        return "!finalizequeue" in command.strip().lower()
    
    def analyze(self, command: str, output: str) -> AnalysisResult:
        """Analyze !finalizequeue output."""
        try:
            # Parse per-heap statistics
            heaps = self._parse_heap_stats(output)
            
            # Calculate totals
            total_gen0 = sum(h["gen0_count"] for h in heaps)
            total_gen1 = sum(h["gen1_count"] for h in heaps)
            total_gen2 = sum(h["gen2_count"] for h in heaps)
            total_ready = sum(h["ready_count"] for h in heaps)
            total_finalizable = total_gen0 + total_gen1 + total_gen2
            
            # Parse cleanup stats
            syncblocks = self._extract_value(output, r'SyncBlocks to be cleaned up:\s*(\d+)')
            
            # Assess health
            issues = []
            if total_gen2 > 10000:
                issues.append(f"High Gen2 finalizable objects: {total_gen2:,}")
            if total_ready > 1000:
                issues.append(f"High ready-for-finalization count: {total_ready:,}")
            if total_finalizable > 50000:
                issues.append(f"Excessive total finalizable objects: {total_finalizable:,}")
            
            # Generate summary
            if issues:
                summary = f"Finalizer queue backup detected: {total_finalizable:,} total objects ({total_gen2:,} in Gen2)"
            else:
                summary = f"Finalizer queue normal: {total_finalizable:,} finalizable objects"
            
            # Generate findings
            findings = [
                f"Total finalizable objects: {total_finalizable:,}",
                f"Gen0: {total_gen0:,}, Gen1: {total_gen1:,}, Gen2: {total_gen2:,}",
                f"Ready for finalization: {total_ready:,}",
                f"GC heaps: {len(heaps)}",
            ]
            
            if syncblocks > 0:
                findings.append(f"SyncBlocks to clean: {syncblocks}")
            
            if issues:
                findings.append("⚠️ Finalizer issues:")
                findings.extend(f"  - {issue}" for issue in issues)
            else:
                findings.append("✓ Finalizer queue healthy")
            
            return AnalysisResult(
                structured_data={
                    "heaps": heaps,
                    "totals": {
                        "gen0": total_gen0,
                        "gen1": total_gen1,
                        "gen2": total_gen2,
                        "ready": total_ready,
                        "total": total_finalizable,
                    },
                    "syncblocks_to_clean": syncblocks,
                    "issues": issues,
                },
                summary=summary,
                findings=findings,
                metadata={
                    "analyzer": self.name,
                    "tier": self.tier.value,
                    "health_status": "unhealthy" if issues else "healthy",
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
                error=f"Failed to analyze finalizer queue: {str(e)}",
            )
    
    def _parse_heap_stats(self, output: str) -> List[Dict[str, Any]]:
        """Parse per-heap finalization statistics."""
        heaps = []
        lines = output.split('\n')
        
        current_heap = None
        for line in lines:
            # Heap N header
            heap_match = re.match(r'Heap\s+(\d+)', line)
            if heap_match:
                if current_heap is not None:
                    heaps.append(current_heap)
                current_heap = {
                    "heap_id": int(heap_match.group(1)),
                    "gen0_count": 0,
                    "gen1_count": 0,
                    "gen2_count": 0,
                    "ready_count": 0,
                }
                continue
            
            if current_heap is None:
                continue
            
            # generation N has X finalizable objects
            gen_match = re.search(r'generation\s+(\d+)\s+has\s+(\d+)\s+finalizable', line)
            if gen_match:
                gen = int(gen_match.group(1))
                count = int(gen_match.group(2))
                if gen == 0:
                    current_heap["gen0_count"] = count
                elif gen == 1:
                    current_heap["gen1_count"] = count
                elif gen == 2:
                    current_heap["gen2_count"] = count
            
            # Ready for finalization X objects
            ready_match = re.search(r'Ready for finalization\s+(\d+)', line)
            if ready_match:
                current_heap["ready_count"] = int(ready_match.group(1))
        
        # Add last heap
        if current_heap is not None:
            heaps.append(current_heap)
        
        return heaps
    
    def _extract_value(self, output: str, pattern: str) -> int:
        """Extract numeric value using regex pattern."""
        match = re.search(pattern, output)
        return int(match.group(1)) if match else 0
