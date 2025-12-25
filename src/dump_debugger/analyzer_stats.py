"""Analyzer usage statistics tracker."""

from dataclasses import dataclass, field
from typing import Dict, List
from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class AnalyzerStats:
    """Statistics for analyzer usage."""
    
    command: str
    analyzer_used: str | None  # None means generic analysis
    tier: str | None
    success: bool
    analysis_time_ms: float = 0.0
    missed_opportunity: bool = False  # True if analyzer exists but wasn't used
    available_analyzer: str | None = None  # Name of analyzer that should have matched
    
    @property
    def was_specialized(self) -> bool:
        """Check if a specialized analyzer was used."""
        return self.analyzer_used is not None


class AnalyzerUsageTracker:
    """Tracks analyzer usage across a session."""
    
    def __init__(self):
        """Initialize the tracker."""
        self.stats: List[AnalyzerStats] = []
        self._enabled = True
    
    def record(
        self,
        command: str,
        analyzer_name: str | None,
        tier: str | None,
        success: bool,
        analysis_time_ms: float = 0.0,
        missed_opportunity: bool = False,
        available_analyzer: str | None = None
    ):
        """Record analyzer usage for a command.
        
        Args:
            command: Debugger command executed
            analyzer_name: Name of analyzer used (None for generic)
            tier: Tier of analyzer (None for generic)
            success: Whether analysis succeeded
            analysis_time_ms: Time taken for analysis in milliseconds
            missed_opportunity: True if analyzer exists but wasn't used
            available_analyzer: Name of available analyzer that wasn't used
        """
        if not self._enabled:
            console.print("[dim red]⚠ Analyzer tracking is disabled[/dim red]")
            return
        
        stat = AnalyzerStats(
            command=command,
            analyzer_used=analyzer_name,
            tier=tier,
            success=success,
            analysis_time_ms=analysis_time_ms,
            missed_opportunity=missed_opportunity,
            available_analyzer=available_analyzer,
        )
        self.stats.append(stat)
        
        # Debug output to confirm recording
        analyzer_desc = analyzer_name if analyzer_name else "generic"
        console.print(f"[dim]📊 Tracked: {analyzer_desc} analyzer for {command[:30]}...[/dim]")
    
    def get_summary(self) -> Dict[str, any]:
        """Get summary statistics.
        
        Returns:
            Dictionary with summary stats
        """
        if not self.stats:
            return {
                "total_commands": 0,
                "specialized_count": 0,
                "generic_count": 0,
                "missed_count": 0,
                "success_rate": 0.0,
                "avg_time_specialized": 0.0,
                "avg_time_generic": 0.0,
            }
        
        specialized = [s for s in self.stats if s.was_specialized]
        generic = [s for s in self.stats if not s.was_specialized]
        successful = [s for s in self.stats if s.success]
        missed = [s for s in self.stats if s.missed_opportunity]
        
        specialized_times = [s.analysis_time_ms for s in specialized if s.analysis_time_ms > 0]
        generic_times = [s.analysis_time_ms for s in generic if s.analysis_time_ms > 0]
        
        return {
            "total_commands": len(self.stats),
            "specialized_count": len(specialized),
            "generic_count": len(generic),
            "missed_count": len(missed),
            "success_count": len(successful),
            "success_rate": len(successful) / len(self.stats) if self.stats else 0.0,
            "avg_time_specialized": sum(specialized_times) / len(specialized_times) if specialized_times else 0.0,
            "avg_time_generic": sum(generic_times) / len(generic_times) if generic_times else 0.0,
            "tier_breakdown": self._get_tier_breakdown(),
            "analyzer_usage": self._get_analyzer_usage(),
            "missed_opportunities": self._get_missed_opportunities(),
        }
    
    def _get_tier_breakdown(self) -> Dict[str, int]:
        """Get count by tier."""
        breakdown = {}
        for stat in self.stats:
            tier = stat.tier or "generic"
            breakdown[tier] = breakdown.get(tier, 0) + 1
        return breakdown
    
    def _get_analyzer_usage(self) -> Dict[str, int]:
        """Get count by analyzer."""
        usage = {}
        for stat in self.stats:
            analyzer = stat.analyzer_used or "generic"
            usage[analyzer] = usage.get(analyzer, 0) + 1
        return usage
    
    def _get_missed_opportunities(self) -> List[Dict[str, str]]:
        """Get list of missed analyzer opportunities."""
        missed = []
        for stat in self.stats:
            if stat.missed_opportunity:
                missed.append({
                    "command": stat.command,
                    "available_analyzer": stat.available_analyzer or "unknown",
                })
        return missed
    
    def print_summary(self):
        """Print a formatted summary of analyzer usage."""
        console.print(f"\n[bold cyan]═══ Analyzer Usage Statistics ═══[/bold cyan]")
        console.print(f"[dim]Total stats collected: {len(self.stats)}[/dim]\n")
        
        if not self.stats:
            console.print("[yellow]⚠ No analyzer usage data collected[/yellow]")
            console.print("[dim]This means either:[/dim]")
            console.print("[dim]  • The analysis workflow didn't execute any commands[/dim]")
            console.print("[dim]  • Commands were executed but tracking wasn't triggered[/dim]")
            console.print("[dim]  • Stats were reset before print_summary() was called[/dim]")
            return
        
        summary = self.get_summary()
        
        # Create summary table
        table = Table(title="🔍 Analyzer Usage Summary", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Total Commands", str(summary["total_commands"]))
        table.add_row(
            "Specialized Analyzers",
            f"{summary['specialized_count']} ({summary['specialized_count']/summary['total_commands']*100:.1f}%)"
        )
        table.add_row(
            "Generic Analysis",
            f"{summary['generic_count']} ({summary['generic_count']/summary['total_commands']*100:.1f}%)"
        )
        table.add_row("Success Rate", f"{summary['success_rate']*100:.1f}%")
        
        console.print(table)
        
        # Tier breakdown
        if summary["tier_breakdown"]:
            tier_table = Table(title="Analysis by Tier", show_header=True)
            tier_table.add_column("Tier", style="cyan")
            tier_table.add_column("Count", style="yellow")
            tier_table.add_column("Description", style="dim")
            
            tier_descriptions = {
                "tier1": "Pure code parsing (instant, free)",
                "tier2": "Code + local LLM (fast, free)",
                "tier3": "Cloud LLM (slower, paid)",
                "generic": "Generic chunked analysis (slowest, paid)",
            }
            
            for tier, count in sorted(summary["tier_breakdown"].items()):
                tier_table.add_row(
                    tier,
                    str(count),
                    tier_descriptions.get(tier, "")
                )
            
            console.print(tier_table)
        
        # Analyzer usage
        if summary["analyzer_usage"]:
            analyzer_table = Table(title="Analyzer Usage Details", show_header=True)
            analyzer_table.add_column("Analyzer", style="cyan")
            analyzer_table.add_column("Count", style="yellow")
            
            for analyzer, count in sorted(
                summary["analyzer_usage"].items(),
                key=lambda x: x[1],
                reverse=True
            ):
                analyzer_table.add_row(analyzer, str(count))
            
            console.print(analyzer_table)
        
        # Cost/performance insight
        specialized_pct = summary['specialized_count'] / summary['total_commands'] * 100 if summary['total_commands'] > 0 else 0
        
        if specialized_pct >= 80:
            console.print(f"\n✅ [green]Excellent![/green] {specialized_pct:.0f}% of commands used specialized analyzers")
        elif specialized_pct >= 50:
            console.print(f"\n✓ [yellow]Good![/yellow] {specialized_pct:.0f}% of commands used specialized analyzers")
        else:
            console.print(f"\n⚠️ [red]Low specialized usage[/red] ({specialized_pct:.0f}%). Consider adding more analyzers.")
        
        # Warn about missed opportunities
        if summary["missed_count"] > 0:
            console.print(f"\n⚠️ [red]Missed Opportunities:[/red] {summary['missed_count']} commands had available analyzers but weren't matched")
            
            missed_table = Table(title="Missed Analyzer Opportunities", show_header=True)
            missed_table.add_column("Command", style="cyan")
            missed_table.add_column("Available Analyzer", style="yellow")
            missed_table.add_column("Suggestion", style="dim")
            
            for missed in summary["missed_opportunities"][:10]:  # Show top 10
                cmd = missed["command"][:50] + "..." if len(missed["command"]) > 50 else missed["command"]
                missed_table.add_row(
                    cmd,
                    missed["available_analyzer"],
                    "Fix can_analyze() logic"
                )
            
            console.print(missed_table)
            console.print("[dim]Fix: Update analyzer's can_analyze() method to handle command variations[/dim]")
    
    def print_command_details(self):
        """Print detailed command-by-command breakdown."""
        if not self.stats:
            return
        
        table = Table(title="Command Analysis Details", show_header=True)
        table.add_column("#", style="dim", width=4)
        table.add_column("Command", style="cyan")
        table.add_column("Analyzer", style="green")
        table.add_column("Tier", style="yellow")
        table.add_column("Status", style="white")
        
        for i, stat in enumerate(self.stats, 1):
            status = "✓" if stat.success else "✗"
            analyzer = stat.analyzer_used or "generic"
            tier = stat.tier or "generic"
            
            # Truncate long commands
            cmd = stat.command[:40] + "..." if len(stat.command) > 40 else stat.command
            
            table.add_row(
                str(i),
                cmd,
                analyzer,
                tier,
                status
            )
        
        console.print(table)
    
    def enable(self):
        """Enable tracking."""
        self._enabled = True
    
    def disable(self):
        """Disable tracking."""
        self._enabled = False
    
    def reset(self):
        """Reset all statistics."""
        self.stats.clear()


# Global tracker instance
usage_tracker = AnalyzerUsageTracker()
