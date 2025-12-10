"""LangGraph workflow definition for memory dump analysis."""

from pathlib import Path

from langgraph.graph import END, StateGraph
from rich.console import Console

from dump_debugger.agents import (
    AnalyzerAgent,
    DebuggerAgent,
    PlannerAgent,
    ReportWriterAgent,
)
from dump_debugger.config import settings
from dump_debugger.core import DebuggerWrapper
from dump_debugger.state import AnalysisState

console = Console()


def create_workflow(dump_path: Path) -> StateGraph:
    """Create the LangGraph workflow for dump analysis.
    
    Args:
        dump_path: Path to the memory dump file
        
    Returns:
        Configured StateGraph
    """
    # Initialize agents
    debugger = DebuggerWrapper(dump_path)
    planner = PlannerAgent()
    debugger_agent = DebuggerAgent(debugger)
    analyzer = AnalyzerAgent()
    report_writer = ReportWriterAgent()

    # Create the graph
    workflow = StateGraph(AnalysisState)

    # Define node functions
    def plan_node(state: AnalysisState) -> dict:
        """Planning node."""
        return planner.plan(state)

    def debug_node(state: AnalysisState) -> dict:
        """Debugger execution node."""
        return debugger_agent.execute_next_command(state)

    def analyze_node(state: AnalysisState) -> dict:
        """Analysis node."""
        return analyzer.analyze(state)

    def report_node(state: AnalysisState) -> dict:
        """Report generation node."""
        return report_writer.generate_report(state)

    def should_continue(state: AnalysisState) -> str:
        """Determine if we should continue investigating or move to reporting.
        
        Returns:
            "continue" to keep investigating, "report" to generate final report
        """
        # Check iteration limit
        if state.get("iteration", 0) >= state.get("max_iterations", settings.max_iterations):
            console.print("\n[yellow]⚠ Maximum iterations reached[/yellow]")
            return "report"

        # Check if analysis says we need more investigation
        if not state.get("needs_more_investigation", True):
            console.print("\n[green]✓ Investigation complete[/green]")
            return "report"

        # Check if we've completed all tasks
        current_idx = state.get("current_task_index", 0)
        plan = state.get("investigation_plan", [])
        
        if current_idx >= len(plan) - 1:
            console.print("\n[green]✓ All tasks completed[/green]")
            return "report"

        return "continue"

    def advance_task(state: AnalysisState) -> dict:
        """Move to the next investigation task."""
        current_idx = state.get("current_task_index", 0)
        plan = state.get("investigation_plan", [])
        
        next_idx = current_idx + 1
        if next_idx < len(plan):
            console.print(f"\n[cyan]→ Moving to next task: {plan[next_idx]}[/cyan]")
            return {
                "current_task_index": next_idx,
                "current_task": plan[next_idx],
            }
        
        return {}

    # Add nodes
    workflow.add_node("plan", plan_node)
    workflow.add_node("debug", debug_node)
    workflow.add_node("analyze", analyze_node)
    workflow.add_node("advance_task", advance_task)
    workflow.add_node("report", report_node)

    # Set entry point
    workflow.set_entry_point("plan")

    # Add edges
    workflow.add_edge("plan", "debug")
    workflow.add_edge("debug", "analyze")
    
    # Conditional edge after analysis
    workflow.add_conditional_edges(
        "analyze",
        should_continue,
        {
            "continue": "advance_task",
            "report": "report",
        }
    )
    
    workflow.add_edge("advance_task", "debug")
    workflow.add_edge("report", END)

    return workflow


def run_analysis(dump_path: Path, issue_description: str) -> AnalysisState:
    """Run the complete dump analysis workflow.
    
    Args:
        dump_path: Path to the memory dump
        issue_description: Description of the issue to investigate
        
    Returns:
        Final analysis state with report
    """
    console.print("[bold]🔍 Memory Dump Debugger[/bold]")
    console.print("━" * 60)
    
    # Validate dump
    debugger = DebuggerWrapper(dump_path)
    dump_info = debugger.validate_dump()
    
    if not dump_info["valid"]:
        console.print(f"[red]✗ Invalid dump file: {dump_info['error']}[/red]")
        raise ValueError(f"Invalid dump file: {dump_info['error']}")
    
    dump_type = debugger.get_dump_type()
    console.print(f"[green]✓[/green] Dump validated ([cyan]{dump_type}-mode[/cyan])")
    
    # Initialize state
    initial_state: AnalysisState = {
        "dump_path": str(dump_path),
        "issue_description": issue_description,
        "dump_type": dump_type,
        "investigation_plan": [],
        "current_task": "",
        "current_task_index": 0,
        "commands_executed": [],
        "findings": [],
        "planner_reasoning": "",
        "debugger_reasoning": "",
        "analyzer_reasoning": "",
        "iteration": 0,
        "max_iterations": settings.max_iterations,
        "should_continue": True,
        "needs_more_investigation": True,
        "final_report": None,
        "confidence_level": None,
        "messages": [],
    }
    
    # Create and compile workflow
    workflow = create_workflow(dump_path)
    app = workflow.compile()
    
    # Run the workflow
    console.print("\n[bold cyan]Starting Analysis...[/bold cyan]\n")
    
    try:
        final_state = app.invoke(initial_state)
        return final_state
    except Exception as e:
        console.print(f"\n[red]✗ Analysis failed: {str(e)}[/red]")
        raise
