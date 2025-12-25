"""ThreadPool analyzer (Tier 1 - Pure code parsing)."""

import re
from typing import Any, Dict

from dump_debugger.analyzers.base import AnalysisResult, AnalyzerTier, BaseAnalyzer


class ThreadPoolAnalyzer(BaseAnalyzer):
    """Analyzer for !threadpool command output.
    
    Tier 1: Pure code parsing - extracts thread pool statistics.
    """
    
    name = "threadpool"
    description = "Analyzes !threadpool output for thread pool health"
    tier = AnalyzerTier.TIER_1
    supported_commands = ["!threadpool"]
    
    def can_analyze(self, command: str) -> bool:
        """Check if this is a !threadpool command."""
        return "!threadpool" in command.strip().lower()
    
    def analyze(self, command: str, output: str) -> AnalysisResult:
        """Analyze !threadpool output."""
        try:
            # Parse thread pool stats
            cpu_util = self._extract_cpu_utilization(output)
            worker_stats = self._extract_worker_stats(output)
            completion_stats = self._extract_completion_port_stats(output)
            queue_depth = self._extract_queue_depth(output)
            timers = self._extract_timer_count(output)
            
            # Assess health
            health_issues = []
            if queue_depth > 0:
                health_issues.append(f"Work queue backlog: {queue_depth} items")
            
            if worker_stats.get("idle", 0) == 0:
                health_issues.append("No idle worker threads - potential starvation")
            
            if worker_stats.get("running", 0) >= worker_stats.get("total", 0):
                health_issues.append("All worker threads busy")
            
            # Generate summary
            if health_issues:
                summary = f"Thread pool shows issues: {', '.join(health_issues[:2])}"
            else:
                summary = f"Thread pool healthy: {worker_stats.get('idle', 0)} idle workers, {queue_depth} queued items"
            
            # Generate findings
            findings = [
                f"CPU utilization: {cpu_util}%",
                f"Worker threads: {worker_stats.get('running', 0)} running, "
                f"{worker_stats.get('idle', 0)} idle, {worker_stats.get('total', 0)} total",
                f"Completion port threads: {completion_stats.get('free', 0)} free, "
                f"{completion_stats.get('total', 0)} total",
                f"Work queue depth: {queue_depth}",
            ]
            
            if health_issues:
                findings.append("⚠️ Thread pool issues detected:")
                findings.extend(f"  - {issue}" for issue in health_issues)
            else:
                findings.append("✓ Thread pool operating normally")
            
            return AnalysisResult(
                structured_data={
                    "cpu_utilization": cpu_util,
                    "worker_threads": worker_stats,
                    "completion_port_threads": completion_stats,
                    "queue_depth": queue_depth,
                    "timer_count": timers,
                    "health_issues": health_issues,
                },
                summary=summary,
                findings=findings,
                metadata={
                    "analyzer": self.name,
                    "tier": self.tier.value,
                    "health_status": "unhealthy" if health_issues else "healthy",
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
                error=f"Failed to analyze thread pool: {str(e)}",
            )
    
    def _extract_cpu_utilization(self, output: str) -> int:
        """Extract CPU utilization percentage."""
        match = re.search(r'CPU utilization:\s*(\d+)%', output)
        return int(match.group(1)) if match else 0
    
    def _extract_worker_stats(self, output: str) -> Dict[str, int]:
        """Extract worker thread statistics."""
        # Worker Thread: Total: 16 Running: 0 Idle: 8 MaxLimit: 32767 MinLimit: 8
        match = re.search(
            r'Worker Thread:\s*Total:\s*(\d+)\s*Running:\s*(\d+)\s*Idle:\s*(\d+)',
            output
        )
        if match:
            return {
                "total": int(match.group(1)),
                "running": int(match.group(2)),
                "idle": int(match.group(3)),
            }
        return {"total": 0, "running": 0, "idle": 0}
    
    def _extract_completion_port_stats(self, output: str) -> Dict[str, int]:
        """Extract completion port thread statistics."""
        # Completion Port Thread:Total: 11 Free: 10 MaxFree: 16
        match = re.search(
            r'Completion Port Thread:\s*Total:\s*(\d+)\s*Free:\s*(\d+)',
            output
        )
        if match:
            return {
                "total": int(match.group(1)),
                "free": int(match.group(2)),
            }
        return {"total": 0, "free": 0}
    
    def _extract_queue_depth(self, output: str) -> int:
        """Extract work request queue depth."""
        match = re.search(r'Work Request in Queue:\s*(\d+)', output)
        return int(match.group(1)) if match else 0
    
    def _extract_timer_count(self, output: str) -> int:
        """Extract number of timers."""
        match = re.search(r'Number of Timers:\s*(\d+)', output)
        return int(match.group(1)) if match else 0
