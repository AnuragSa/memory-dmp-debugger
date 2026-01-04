"""
Planner agent that creates investigation plans after hypothesis confirmation.
"""
from rich.console import Console

from dump_debugger.llm import get_llm
from dump_debugger.state import AnalysisState

console = Console()


class PlannerAgentV2:
    """Creates investigation plans after hypothesis is confirmed."""
    
    def __init__(self):
        self.llm = get_llm(temperature=0.1)
    
    def plan(self, state: AnalysisState) -> dict:
        """Create focused investigation plan."""
        hypothesis = state['current_hypothesis']
        console.print(f"\n[bold cyan]📋 Planning Investigation[/bold cyan]")
        console.print(f"[dim]For hypothesis: {hypothesis}[/dim]")
        
        # Simple default plan
        plan = [
            "Examine crash context and exception details",
            "Analyze call stack and thread states",
            "Investigate memory and heap state"
        ]
        
        return {
            'investigation_plan': plan,
            'current_task': plan[0] if plan else "",
            'current_task_index': 0,
            'planner_reasoning': f"Investigating: {hypothesis}"
        }
