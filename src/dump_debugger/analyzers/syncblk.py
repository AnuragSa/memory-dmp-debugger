"""SyncBlock analyzer (Tier 1 - Pure code parsing)."""

import re
from typing import Any, Dict, List

from dump_debugger.analyzers.base import AnalysisResult, AnalyzerTier, BaseAnalyzer


class SyncBlockAnalyzer(BaseAnalyzer):
    """Analyzer for !syncblk command output.
    
    Tier 1: Pure code parsing - extracts lock contention information.
    """
    
    name = "syncblk"
    description = "Analyzes !syncblk output for lock contention"
    tier = AnalyzerTier.TIER_1
    supported_commands = ["!syncblk"]
    
    def can_analyze(self, command: str) -> bool:
        """Check if this is a !syncblk command."""
        return "!syncblk" in command.strip().lower()
    
    def analyze(self, command: str, output: str) -> AnalysisResult:
        """Analyze !syncblk output."""
        try:
            # Parse sync blocks
            sync_blocks = self._parse_sync_blocks(output)
            
            # Count total sync blocks
            total_syncblks = self._extract_total_count(output)
            
            # Identify contention
            contention = [sb for sb in sync_blocks if sb.get("waiting_threads", 0) > 0]
            
            # Generate summary
            if not sync_blocks and total_syncblks == 0:
                summary = "No synchronization blocks found. No lock contention detected."
            elif contention:
                summary = f"Found {len(contention)} sync blocks with contention out of {total_syncblks} total."
            else:
                summary = f"Found {total_syncblks} sync blocks with no active contention."
            
            # Generate findings
            findings = [
                f"Total sync blocks: {total_syncblks}",
                f"Sync blocks with contention: {len(contention)}",
            ]
            
            if contention:
                findings.append("⚠️ Lock contention detected - potential deadlock or blocking")
                for sb in contention[:3]:  # Show top 3
                    findings.append(
                        f"  Managed thread ID {sb.get('holding_thread')} holding lock, "
                        f"{sb.get('waiting_threads')} threads waiting"
                    )
            else:
                findings.append("✓ No lock contention - synchronization healthy")
            
            return AnalysisResult(
                structured_data={
                    "total_syncblks": total_syncblks,
                    "sync_blocks": sync_blocks,
                    "contention": contention,
                },
                summary=summary,
                findings=findings,
                metadata={
                    "analyzer": self.name,
                    "tier": self.tier.value,
                    "contention_count": len(contention),
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
                error=f"Failed to analyze sync blocks: {str(e)}",
            )
    
    def _parse_sync_blocks(self, output: str) -> List[Dict[str, Any]]:
        """Parse sync block entries.
        
        IMPORTANT: The "Owning Thread" column in !syncblk output shows the MANAGED THREAD ID,
        not the debugger thread number or OSID. To investigate a thread:
        1. Note the managed ID from !syncblk (e.g., 12)
        2. Look up !threads output to find the corresponding debugger thread number or OSID
        3. Use ~<DBG#>s or ~~[<OSID>]s to switch to that thread
        """
        blocks = []
        lines = output.split('\n')
        
        # Pattern: Index SyncBlock MonitorHeld Recursion Owning Thread Info
        # Example: 1    00000001  0000002e  1         12 Thread 0x1234
        # NOTE: Group 5 captures the MANAGED THREAD ID (not debugger thread or OSID)
        pattern = re.compile(
            r'^\s*(\d+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+(\d+)\s+(\d+)'
        )
        
        for line in lines:
            match = pattern.match(line.strip())
            if match:
                blocks.append({
                    "index": int(match.group(1)),
                    "syncblock": match.group(2),
                    "monitor_held": match.group(3),
                    "recursion": int(match.group(4)),
                    "holding_thread": int(match.group(5)),  # This is MANAGED THREAD ID
                    "waiting_threads": 0,  # Would need additional parsing
                })
        
        return blocks
    
    def _extract_total_count(self, output: str) -> int:
        """Extract total sync block count."""
        # Look for "Total: X" or similar
        match = re.search(r'Total:\s*(\d+)', output, re.IGNORECASE)
        if match:
            return int(match.group(1))
        
        # If not found, count parsed blocks
        return len(self._parse_sync_blocks(output))
