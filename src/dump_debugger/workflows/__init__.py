"""LangGraph workflow definition for memory dump analysis."""

from pathlib import Path

from langgraph.graph import END, StateGraph
from rich.console import Console

from dump_debugger.agents import (
    AnalyzerAgent,
    CommandGeneratorAgent,
    DebuggerAgent,
    PlannerAgent,
    ReportWriterAgent,
)
from dump_debugger.config import settings
from dump_debugger.core import DebuggerWrapper
from dump_debugger.state import AnalysisState

console = Console()


def ask_user_to_continue() -> bool:
    """Ask user if they want to continue analysis after reaching iteration limit.
    
    Returns:
        True if user wants to continue, False otherwise
    """
    console.print("\n[yellow]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/yellow]")
    console.print("[yellow]Maximum iterations reached for this batch.[/yellow]")
    console.print("[yellow]Would you like to continue investigating?[/yellow]")
    console.print("[dim]  - Press 'y' or Enter to continue for another batch[/dim]")
    console.print("[dim]  - Press 'n' to stop and generate report now[/dim]")
    console.print("[yellow]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/yellow]")
    
    try:
        response = input("Continue? [Y/n]: ").strip().lower()
        if response in ['', 'y', 'yes']:
            console.print("[green]✓ Continuing analysis...[/green]\n")
            return True
        else:
            console.print("[yellow]⚠ Stopping analysis and generating report...[/yellow]\n")
            return False
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]⚠ User interrupted. Generating report...[/yellow]\n")
        return False


def create_workflow(dump_path: Path) -> StateGraph:
    """Create the LangGraph workflow for dump analysis.
    
    Args:
        dump_path: Path to the memory dump file
        
    Returns:
        Configured StateGraph
    """
    # Initialize agents
    debugger = DebuggerWrapper(dump_path)
    generator = CommandGeneratorAgent()
    planner = PlannerAgent()
    debugger_agent = DebuggerAgent(debugger, generator)
    analyzer = AnalyzerAgent()
    report_writer = ReportWriterAgent()

    # Create the graph
    workflow = StateGraph(AnalysisState)

    # Define node functions
    def plan_node(state: AnalysisState) -> dict:
        """Planning node."""
        return planner.plan(state)

    def analyzer_request_node(state: AnalysisState) -> dict:
        """Analyzer determines what data is needed for current task."""
        result = analyzer.request_data(state)
        
        # Check if analyzer wants to skip to next task
        data_request = result.get("data_request", "")
        if data_request == "SKIP_TO_NEXT_TASK":
            console.print("[yellow]Analyzer requests skipping to next task[/yellow]")
            result["task_complete"] = True
            result["needs_more_investigation"] = False
            return result
        
        # Track this request to detect infinite loops
        recent_requests = state.get("recent_data_requests", [])
        new_request = str(data_request)
        
        # Keep last 5 requests
        recent_requests.append(new_request)
        if len(recent_requests) > 5:
            recent_requests = recent_requests[-5:]
        
        result["recent_data_requests"] = recent_requests
        return result

    def debug_node(state: AnalysisState) -> dict:
        """Debugger execution node - asks generator for command, then executes."""
        result = {}
        
        # For .NET dumps, load SOS extension if not already loaded
        if not state.get("sos_loaded", False):
            issue = state.get("issue_description", "").lower()
            if "managed" in issue or ".net" in issue or "net" in issue:
                # Only load once per analysis session
                if not state.get("_sos_load_attempted", False):
                    console.print("[cyan]Loading SOS extension for .NET debugging...[/cyan]")
                    try:
                        sos_result = debugger.execute_command(".loadby sos clr")
                        result["_sos_load_attempted"] = True
                        if sos_result["success"]:
                            result["sos_loaded"] = True
                            console.print("[green]✓ SOS extension loaded[/green]")
                        else:
                            console.print(f"[yellow]Note: SOS load returned: {sos_result.get('output', 'No output')}[/yellow]")
                            result["sos_loaded"] = False
                    except Exception as e:
                        console.print(f"[yellow]Note: Could not load SOS: {str(e)}[/yellow]")
                        result["sos_loaded"] = False
                        result["_sos_load_attempted"] = True
        
        # Execute the command
        cmd_result = debugger_agent.execute_next_command(state)
        result.update(cmd_result)
        return result

    def analyze_node(state: AnalysisState) -> dict:
        """Analysis node - reviews results and determines if task is complete."""
        result = analyzer.analyze(state)
        # Increment iteration counter
        result["iteration"] = state.get("iteration", 0) + 1
        return result

    def report_node(state: AnalysisState) -> dict:
        """Report generation node."""
        return report_writer.generate_report(state)

    def reset_iteration_node(state: AnalysisState) -> dict:
        """Reset iteration counter when user chooses to continue."""
        console.print(f"[cyan]Continuing for another {settings.max_iterations} iterations...[/cyan]\n")
        return {
            "iteration": 0,
        }
    
    def should_continue(state: AnalysisState) -> str:
        """Determine if we should continue on current task or move to next/report.
        
        Returns:
            "reset_and_continue" - user wants to continue, reset iteration counter first
            "continue_task" - keep working on current task (loop back to debug)
            "next_task" - current task complete, advance to next task
            "report" - all tasks complete, generate report
        """
        # Check iteration limit
        current_iteration = state.get("iteration", 0)
        max_iterations = state.get("max_iterations", settings.max_iterations)
        
        if current_iteration >= max_iterations:
            # Ask user if they want to continue
            if ask_user_to_continue():
                # Route to reset node which will reset counter, then continue
                return "reset_and_continue"
            else:
                # User chose to stop - generate report
                console.print("\n[yellow]⚠ User stopped analysis at iteration limit[/yellow]")
                return "report"
        
        # Check if too many failures on current task - move to next task to prevent infinite loop
        failed_count = state.get("failed_commands_current_task", 0)
        if failed_count >= 5:
            console.print(f"\n[yellow]⚠ Too many failures ({failed_count}) on current task, moving to next task[/yellow]")
            return "next_task"
        
        # Check for repetitive data requests (infinite loop detection)
        recent_requests = state.get("recent_data_requests", [])
        if len(recent_requests) >= 4:
            # Check if last 3 requests are very similar
            last_three = recent_requests[-3:]
            if len(set(last_three)) <= 2:  # Only 1-2 unique requests in last 3
                console.print(f"\n[yellow]⚠ Detected repetitive data requests, forcing task completion[/yellow]")
                return "next_task"

        # Check if current task needs more investigation
        needs_more = state.get("needs_more_investigation", True)
        task_complete = state.get("task_complete", False)
        
        if needs_more and not task_complete:
            # Current task needs more work - loop back to debug
            return "continue_task"
        
        # Current task is complete - check if we have more tasks
        current_idx = state.get("current_task_index", 0)
        plan = state.get("investigation_plan", [])
        
        if current_idx >= len(plan) - 1:
            console.print("\n[green]✓ All tasks completed[/green]")
            return "report"
        
        # Move to next task
        return "next_task"

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
                "task_complete": False,  # Reset for new task
                "needs_more_investigation": True,  # New task needs investigation
                "failed_commands_current_task": 0,  # Reset failure counter
                "recent_data_requests": [],  # Reset request history
                "commands_executed_current_task": [],  # Reset command history
            }
        
        return {}

    # Add nodes
    workflow.add_node("plan", plan_node)
    workflow.add_node("analyzer_request", analyzer_request_node)
    workflow.add_node("debug", debug_node)
    workflow.add_node("analyze", analyze_node)
    workflow.add_node("reset_iteration", reset_iteration_node)
    workflow.add_node("advance_task", advance_task)
    workflow.add_node("report", report_node)

    # Set entry point
    workflow.set_entry_point("plan")

    # Add edges to enforce sequence:
    # plan -> analyzer_request (Analyzer looks at task, requests specific data)
    # analyzer_request -> debug (Debugger asks generator for command, executes)
    # debug -> analyze (Analyzer reviews results)
    # analyze -> (continue_task -> analyzer_request) | (reset_and_continue -> reset_iteration -> analyzer_request) | (next_task -> advance_task) | report
    workflow.add_edge("plan", "analyzer_request")
    workflow.add_edge("analyzer_request", "debug")
    workflow.add_edge("debug", "analyze")
    workflow.add_edge("reset_iteration", "analyzer_request")  # After reset, continue to analyzer_request
    
    # Conditional edge after analysis
    workflow.add_conditional_edges(
        "analyze",
        should_continue,
        {
            "continue_task": "analyzer_request",  # Loop back to analyzer_request for more data
            "reset_and_continue": "reset_iteration",  # Reset iteration counter, then continue
            "next_task": "advance_task",  # Move to next task
            "report": "report",  # Generate final report
        }
    )
    
    # After advancing to next task, go to analyzer_request (not debug directly)
    workflow.add_edge("advance_task", "analyzer_request")
    workflow.add_edge("report", END)

    return workflow


def run_analysis(dump_path: Path, issue_description: str, show_commands: bool = False) -> AnalysisState:
    """Run the complete dump analysis workflow.
    
    Args:
        dump_path: Path to the memory dump
        issue_description: Description of the issue to investigate
        show_commands: Whether to show command outputs (default: False)
        
    Returns:
        Final analysis state with report
    """
    console.print("[bold]Memory Dump Debugger[/bold]")
    console.print("━" * 60)
    
    # Validate dump
    debugger = DebuggerWrapper(dump_path, show_output=show_commands)
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
        "supports_dx": debugger.supports_dx,
        "investigation_plan": [],
        "current_task": "",
        "current_task_index": 0,
        "commands_executed": [],
        "findings": [],
        "discovered_properties": {},
        "planner_reasoning": "",
        "debugger_reasoning": "",
        "analyzer_reasoning": "",
        "data_request": "",
        "data_request_reasoning": "",
        "iteration": 0,
        "max_iterations": settings.max_iterations,
        "should_continue": True,
        "needs_more_investigation": True,
        "task_complete": False,
        "failed_commands_current_task": 0,
        "analyzer_feedback": "",
        "final_report": None,
        "confidence_level": None,
        "messages": [],
        "show_commands": show_commands,
        "syntax_errors": [],
    }
    
    # Create and compile workflow
    workflow = create_workflow(dump_path)
    app = workflow.compile()
    
    # Set recursion limit much higher to allow for multiple continuation batches
    # Each iteration = 3 nodes (analyzer_request -> debug -> analyze)
    # Allow for ~5-6 continuation batches with 15 iterations each = ~270 nodes
    # Plus overhead for plan, task advancement, resets = ~300 total
    config = {"recursion_limit": 300}
    
    # Run the workflow
    console.print("\n[bold cyan]Starting Analysis...[/bold cyan]\n")
    
    try:
        final_state = app.invoke(initial_state, config)
        return final_state
    except Exception as e:
        console.print(f"\n[red]✗ Analysis failed: {str(e)}[/red]")
        raise
    finally:
        # Clean up debugger session
        debugger.close()
