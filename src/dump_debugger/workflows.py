"""Hypothesis-driven workflow for expert-level crash dump analysis."""

import signal
import sys
from pathlib import Path
from typing import Optional, TextIO

from langgraph.graph import END, StateGraph
from rich.console import Console

from dump_debugger.config import settings
from dump_debugger.core import DebuggerWrapper
from dump_debugger.agents import (
    CriticAgent,
    HypothesisDrivenAgent,
    InteractiveChatAgent,
    InvestigatorAgent,
    PlannerAgentV2,
    ReasonerAgent,
    ReportWriterAgentV2,
)
from dump_debugger.llm import get_llm
from dump_debugger.state import AnalysisState, Evidence, InvestigatorOutput, ReasonerOutput
from dump_debugger.token_tracker import get_tracker
from dump_debugger.analyzer_stats import usage_tracker

console = Console()


# Signal handler for clean exit
def _signal_handler(sig, frame):
    """Handle Ctrl+C gracefully and show token summary."""
    console.print("\n\n[yellow]⚠ Analysis interrupted by user[/yellow]")
    tracker = get_tracker()
    tracker.print_summary()
    sys.exit(0)


# Register signal handler
signal.signal(signal.SIGINT, _signal_handler)


# Utility classes for output management
class TeeOutput:
    """File-like object that writes to both stdout and a file."""
    
    def __init__(self, original_stdout: TextIO, file_handle: TextIO):
        self.original_stdout = original_stdout
        self.file = file_handle
    
    def write(self, text: str) -> int:
        self.original_stdout.write(text)
        self.original_stdout.flush()
        self.file.write(text)
        self.file.flush()
        return len(text)
    
    def flush(self):
        self.original_stdout.flush()
        self.file.flush()
    
    def isatty(self):
        return self.original_stdout.isatty()


_log_file_handle = None
_original_stdout = None


def handle_special_command(command: str, state: AnalysisState) -> dict:
    """Handle special commands in interactive mode.
    
    Args:
        command: The special command (e.g., /exit, /help)
        state: Current analysis state
        
    Returns:
        State updates
    """
    cmd = command.lower().strip()
    
    if cmd == '/exit' or cmd == '/quit':
        console.print("\n[cyan]👋 Exiting interactive mode. Goodbye![/cyan]")
        return {'chat_active': False}
    
    elif cmd == '/help':
        console.print("\n[bold cyan]Available Commands:[/bold cyan]")
        console.print("  [green]/exit, /quit[/green]     - Exit interactive mode")
        console.print("  [green]/report[/green]          - Regenerate full analysis report")
        console.print("  [green]/history[/green]         - Show chat history")
        console.print("  [green]/evidence[/green]        - List available evidence")
        console.print("  [green]/help[/green]            - Show this help message")
        console.print("\n[dim]Or just ask a question about the dump![/dim]\n")
        return {}
    
    elif cmd == '/report':
        console.print("\n[cyan]📄 Generating full analysis report...[/cyan]\n")
        
        # Check if report already exists
        report = state.get('final_report')
        
        if report is None:
            # Generate report on-demand
            from dump_debugger.workflows import ReportWriterAgentV2
            report_writer = ReportWriterAgentV2()
            result = report_writer.generate_report(state)
            report = result.get('final_report', 'Report generation failed')
            
            # Display it
            console.print(report)
            console.print()
            
            # Return updated state with report
            return {
                'final_report': report,
                'user_requested_report': True
            }
        else:
            # Report already exists, just display it
            console.print(report)
            console.print()
            return {'user_requested_report': True}
    
    elif cmd == '/history':
        chat_history = state.get('chat_history', [])
        if not chat_history:
            console.print("\n[dim]No chat history yet.[/dim]\n")
        else:
            console.print("\n[bold cyan]Chat History:[/bold cyan]\n")
            for i, msg in enumerate(chat_history, 1):
                role = msg['role']
                content = msg['content']
                timestamp = msg.get('timestamp', 'N/A')
                
                if role == 'user':
                    console.print(f"[bold cyan]{i}. You:[/bold cyan] {content}")
                else:
                    # Truncate long assistant responses
                    preview = content[:200] + "..." if len(content) > 200 else content
                    console.print(f"[green]{i}. Assistant:[/green] {preview}")
            console.print()
        return {}
    
    elif cmd == '/evidence':
        console.print("\n[bold cyan]Available Evidence:[/bold cyan]\n")
        
        # Show conclusions
        conclusions = state.get('conclusions', [])
        if conclusions:
            console.print("[bold]Key Conclusions:[/bold]")
            for i, conclusion in enumerate(conclusions, 1):
                console.print(f"  {i}. {conclusion}")
            console.print()
        
        # Show hypothesis tests
        hypothesis_tests = state.get('hypothesis_tests', [])
        if hypothesis_tests:
            console.print(f"[bold]Hypothesis Tests:[/bold] {len(hypothesis_tests)} tests conducted")
            for i, test in enumerate(hypothesis_tests[:3], 1):
                hypothesis = test.get('hypothesis', 'N/A')
                result = test.get('result', 'N/A')
                console.print(f"  {i}. {hypothesis} → {result}")
            if len(hypothesis_tests) > 3:
                console.print(f"  ... and {len(hypothesis_tests) - 3} more")
            console.print()
        
        # Show evidence inventory
        evidence_inventory = state.get('evidence_inventory', {})
        total_evidence = sum(len(ev_list) for ev_list in evidence_inventory.values())
        if total_evidence > 0:
            console.print(f"[bold]Evidence Collected:[/bold] {total_evidence} pieces")
            for task, evidence_list in list(evidence_inventory.items())[:3]:
                console.print(f"  • {task}: {len(evidence_list)} items")
            console.print()
        
        console.print("[dim]Ask a question to explore this evidence![/dim]\n")
        return {}
    
    else:
        console.print(f"[yellow]Unknown command: {command}[/yellow]")
        console.print("[dim]Type /help for available commands[/dim]\n")
        return {}


def create_expert_workflow(dump_path: Path, session_dir: Path) -> StateGraph:
    """Create expert-level hypothesis-driven workflow.
    
    Flow: Hypothesis → Test → [Confirmed: Investigate | Rejected: New Hypothesis] → Reason → Report
    
    Args:
        dump_path: Path to the memory dump file
        session_dir: Session directory for evidence storage
        
    Returns:
        Configured StateGraph
    """
    # Initialize agents with session directory
    debugger = DebuggerWrapper(dump_path, session_dir=session_dir)
    hypothesis_agent = HypothesisDrivenAgent(debugger)
    planner = PlannerAgentV2()
    investigator = InvestigatorAgent(debugger)
    reasoner = ReasonerAgent()
    critic = CriticAgent(llm=get_llm(temperature=0.5))  # Higher temp for skeptical review
    report_writer = ReportWriterAgentV2()
    interactive_chat = InteractiveChatAgent(debugger)

    # Create the graph
    workflow = StateGraph(AnalysisState)

    # Node functions
    def form_hypothesis_node(state: AnalysisState) -> dict:
        """Form initial hypothesis from user question."""
        return hypothesis_agent.form_initial_hypothesis(state)
    
    def test_hypothesis_node(state: AnalysisState) -> dict:
        """Test the current hypothesis."""
        result = hypothesis_agent.test_hypothesis(state)
        state['iteration'] += 1
        result['iteration'] = state['iteration']
        return result
    
    def decide_next_node(state: AnalysisState) -> dict:
        """Decide what to do based on test results."""
        return hypothesis_agent.decide_next_step(state)
    
    def investigate_node(state: AnalysisState) -> dict:
        """Deep investigation of current task (after hypothesis confirmed)."""
        current_task = state.get('current_task', '')
        
        # Perform investigation
        result = investigator.investigate_task(state)
        state['iteration'] += 1
        result['iteration'] = state['iteration']
        
        # Mark current task as completed
        completed = list(state.get('completed_tasks', []))
        if current_task and current_task not in completed:
            completed.append(current_task)
            result['completed_tasks'] = completed
        
        # Always advance the index (even if no next task exists)
        # This is critical so routing can detect completion
        current_idx = state.get('current_task_index', 0)
        investigation_plan = state.get('investigation_plan', [])
        next_idx = current_idx + 1
        
        # Always update the index
        result['current_task_index'] = next_idx
        
        # Only set next task if it exists
        if next_idx < len(investigation_plan):
            result['current_task'] = investigation_plan[next_idx]
        else:
            # Clear current_task when done
            result['current_task'] = ''
        
        return result

    def reason_node(state: AnalysisState) -> dict:
        """Analyze all evidence and draw conclusions."""
        return reasoner.reason(state)
    
    def critique_node(state: AnalysisState) -> dict:
        """Review analysis for quality issues."""
        return critic.critique(state)
    
    def respond_to_critique_node(state: AnalysisState) -> dict:
        """Respond to critic's feedback by collecting missing evidence and re-analyzing."""
        critique_result = state.get('critique_result', {})
        
        if not critique_result.get('issues_found', False):
            # No issues - proceed to report
            return {}
        
        console.print(f"\n[bold yellow]📝 Responding to Critique[/bold yellow]")
        
        # Extract only WinDbg commands from suggested actions (e.g., !threadpool, !syncblk)
        suggested_actions = critique_result.get('suggested_actions', [])
        commands_to_run = []
        
        import re
        for action in suggested_actions:
            # Match WinDbg commands: !command or ~thread !command
            # Pattern: optional ~thread prefix, then !word, optionally with -flags
            matches = re.findall(r'(~[\w*]+\s+)?(![\w\-]+(?:\s+\-[\w]+)*)', action)
            for match in matches:
                prefix = match[0].strip() if match[0] else ""
                cmd = match[1].strip()
                full_cmd = f"{prefix} {cmd}".strip() if prefix else cmd
                
                # Only add simple commands (not descriptions)
                if len(full_cmd.split()) <= 4 and full_cmd not in commands_to_run:
                    commands_to_run.append(full_cmd)
        
        # Check if these commands were already run
        evidence_inventory = state.get('evidence_inventory', {})
        commands_executed = state.get('commands_executed', [])
        
        new_commands = []
        for cmd in commands_to_run:
            # Check if command already exists in evidence
            already_have_evidence = False
            for task_evidence in evidence_inventory.values():
                if any(cmd in e.get('command', '') for e in task_evidence):
                    already_have_evidence = True
                    break
            
            if not already_have_evidence and cmd not in commands_executed:
                new_commands.append(cmd)
        
        # Collect missing evidence if needed
        state_updates = {}
        if new_commands:
            console.print(f"[dim]Collecting {len(new_commands)} missing pieces of evidence:[/dim]")
            
            evidence_inventory = evidence_inventory.copy()
            critique_task = "Critique-requested evidence"
            
            if critique_task not in evidence_inventory:
                evidence_inventory[critique_task] = []
            
            for cmd in new_commands:
                try:
                    console.print(f"  [dim]Running: {cmd}[/dim]")
                    result = debugger.execute_command(cmd)
                    
                    # execute_command returns a dict with 'output' key
                    if isinstance(result, dict):
                        output = result.get('output', '')
                    else:
                        output = result
                    
                    if output and not str(output).startswith("Error:"):
                        evidence = {
                            'command': cmd,
                            'output': output,
                            'success': True
                        }
                        evidence_inventory[critique_task].append(evidence)
                        console.print(f"  [green]✓[/green] Collected")
                    else:
                        console.print(f"  [yellow]⚠ No output[/yellow]")
                        
                except Exception as e:
                    console.print(f"  [yellow]⚠ Failed: {e}[/yellow]")
            
            state_updates['evidence_inventory'] = evidence_inventory
        else:
            console.print(f"[dim]All requested evidence already collected. Re-analyzing with critique feedback...[/dim]")
        
        # Re-run reasoner with critique awareness and any new evidence
        merged_state = {**state, **state_updates}
        
        try:
            reasoner_updates = reasoner.reason(merged_state)
            
            # Show updated analysis summary for visibility
            console.print(f"\n[bold cyan]Updated Analysis:[/bold cyan]")
            console.print(f"[dim]Confidence: {reasoner_updates.get('confidence_level', 'unknown')}[/dim]")
            
            # Show first 500 chars of updated analysis
            analysis = reasoner_updates.get('reasoner_analysis', '')
            preview = analysis[:500] + "..." if len(analysis) > 500 else analysis
            console.print(f"[dim]{preview}[/dim]\n")
            
            # Merge all updates
            return {**state_updates, **reasoner_updates}
            
        except Exception as e:
            console.print(f"[yellow]⚠ Reasoner error during response: {e}[/yellow]")
            # Return just the new evidence without analysis changes
            return state_updates if state_updates else {}

    def report_node(state: AnalysisState) -> dict:
        """Generate final report or show analysis summary in interactive mode."""
        # In interactive mode, skip report generation and show summary instead
        if state.get('interactive_mode', False):
            return report_writer.show_analysis_summary(state)
        else:
            return report_writer.generate_report(state)
    
    def chat_loop_node(state: AnalysisState) -> dict:
        """Interactive chat loop for user questions."""
        from datetime import datetime, timedelta
        
        # If this is the first time entering chat, activate it
        if not state.get('chat_active'):
            console.print("\n[bold green]═══════════════════════════════════════════════════[/bold green]")
            console.print("[bold green]INTERACTIVE CHAT MODE[/bold green]")
            console.print("[bold green]═══════════════════════════════════════════════════[/bold green]")
            console.print("\n[cyan]You can now ask follow-up questions about the dump.[/cyan]")
            console.print("[dim]Special commands: /exit (quit), /report (regenerate), /help (show help)[/dim]")
            console.print(f"[dim]Session timeout: {settings.chat_session_timeout_minutes} minutes[/dim]\n")
            
            # Store session start time
            return {
                'chat_active': True,
                '_chat_start_time': datetime.now().isoformat()
            }
        
        # Check session timeout
        start_time_str = state.get('_chat_start_time')
        if start_time_str:
            start_time = datetime.fromisoformat(start_time_str)
            elapsed = datetime.now() - start_time
            timeout_duration = timedelta(minutes=settings.chat_session_timeout_minutes)
            
            if elapsed > timeout_duration:
                console.print("\n[yellow]⏰ Chat session timeout reached. Exiting interactive mode...[/yellow]")
                return {'chat_active': False}
        
        # Get user input
        try:
            user_input = console.input("[bold cyan]Your question:[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[cyan]👋 Exiting interactive mode...[/cyan]")
            return {'chat_active': False}
        except Exception as e:
            console.print(f"\n[red]Input error: {e}. Exiting interactive mode...[/red]")
            return {'chat_active': False}
        if not user_input:
            console.print("[dim]Please enter a question or /exit to quit[/dim]")
            # Return chat_active to keep the loop going
            return {'chat_active': True}
        
        # Handle special commands
        if user_input.startswith('/'):
            return handle_special_command(user_input, state)
        
        # Answer the question using InteractiveChatAgent
        try:
            result = interactive_chat.answer_question(state, user_input)
            return result
        except KeyboardInterrupt:
            console.print("\n[yellow]Operation cancelled. Type /exit to quit or ask another question.[/yellow]")
            return {'chat_active': True}  # Keep chat active
        except Exception as e:
            console.print(f"\n[red]Error processing question: {e}[/red]")
            console.print("[yellow]Exiting interactive mode due to error. Please restart if needed.[/yellow]")
            import traceback
            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            # Exit chat mode on error to prevent infinite loops
            return {'chat_active': False}

    # Add nodes
    workflow.add_node("form_hypothesis", form_hypothesis_node)
    workflow.add_node("test_hypothesis", test_hypothesis_node)
    workflow.add_node("decide", decide_next_node)
    workflow.add_node("investigate", investigate_node)
    workflow.add_node("reason", reason_node)
    workflow.add_node("critique", critique_node)
    workflow.add_node("respond", respond_to_critique_node)
    workflow.add_node("report", report_node)
    workflow.add_node("chat", chat_loop_node)

    # Define routing logic
    def route_after_test(state: AnalysisState) -> str:
        """Route after testing hypothesis."""
        current_test = state['hypothesis_tests'][-1]
        result = current_test.get('result')
        
        if result is None:
            # Need to test (or retest after gathering more evidence)
            return "test"
        else:
            # Evaluate result in decide node
            return "decide"
    
    def route_after_decide(state: AnalysisState) -> str:
        """Route based on hypothesis status."""
        status = state.get('hypothesis_status', 'testing')
        
        # Check iteration limit
        if state['iteration'] >= state['max_iterations']:
            console.print("[yellow]⚠ Max iterations reached[/yellow]")
            return "reason"
        
        # Check maximum hypothesis attempts
        num_hypotheses = len(state.get('hypothesis_tests', []))
        if num_hypotheses >= settings.max_hypothesis_attempts:
            console.print(f"[yellow]⚠ Max hypothesis attempts ({settings.max_hypothesis_attempts}) reached[/yellow]")
            console.print("[yellow]Moving to analysis with evidence collected so far...[/yellow]")
            # Go to reasoning regardless - user might learn something from collected evidence
            return "reason"
        
        if status == 'confirmed':
            # Hypothesis confirmed - start deep investigation
            return "investigate"
        elif status == 'testing':
            # New hypothesis formed - test it
            return "test"
        else:
            # Shouldn't happen, but safety fallback
            return "reason"
    
    def route_after_investigate(state: AnalysisState) -> str:
        """Route after investigation: next task or reasoning phase."""
        current_idx = state.get('current_task_index', 0)
        total_tasks = len(state.get('investigation_plan', []))
        current_task = state.get('current_task', '')
        completed = state.get('completed_tasks', [])
        
        # Check iteration limit
        if state.get('iteration', 0) >= state.get('max_iterations', 100):
            console.print("[yellow]⚠ Max iterations reached, moving to reasoning[/yellow]")
            return "reason"
        
        # Check if current task was already in completed list (shouldn't happen now)
        # This is just a safety check since investigate_node handles completion
        
        # Check if there are more tasks
        if current_idx < total_tasks:
            next_task = state.get('investigation_plan', [])[current_idx]
            
            # Skip if already completed (loop detection)
            if next_task in completed:
                console.print(f"[yellow]⚠ Task '{next_task}' already completed, moving to reasoning[/yellow]")
                return "reason"
            
            console.print(f"[cyan]→ Moving to task {current_idx + 1}/{total_tasks}[/cyan]\n")
            return "investigate"
        else:
            console.print("[cyan]→ All tasks complete, moving to reasoning phase[/cyan]\n")
            return "reason"

    # Set up the flow
    workflow.set_entry_point("form_hypothesis")
    
    # Hypothesis testing loop
    workflow.add_edge("form_hypothesis", "test_hypothesis")
    workflow.add_conditional_edges(
        "test_hypothesis",
        route_after_test,
        {
            "test": "test_hypothesis",  # Retest with more evidence
            "decide": "decide"
        }
    )
    
    # Decision routing
    workflow.add_conditional_edges(
        "decide",
        route_after_decide,
        {
            "test": "test_hypothesis",  # New hypothesis to test
            "investigate": "investigate",  # Confirmed - start deep investigation
            "reason": "reason"  # Give up and reason with what we have
        }
    )
    
    # Investigation loop
    workflow.add_conditional_edges(
        "investigate",
        route_after_investigate,
        {
            "investigate": "investigate",  # Next task
            "reason": "reason"  # All tasks done
        }
    )
    
    # Routing after report
    def route_after_report(state: AnalysisState) -> str:
        """Route after report: to chat if interactive mode, otherwise END."""
        if state.get('interactive_mode', False):
            return "chat"
        return "end"
    
    # Routing after critique
    def route_after_critique(state: AnalysisState) -> str:
        """Route after critique: respond if issues found and under max rounds, else report."""
        critique_result = state.get('critique_result', {})
        current_round = state.get('critique_round', 0)
        max_rounds = 2
        
        # If no issues or max rounds reached, go to report
        if not critique_result.get('issues_found', False):
            return "report"
        
        if current_round >= max_rounds:
            console.print(f"[yellow]⚠ Max critique rounds ({max_rounds}) reached. Proceeding to report with disclaimer.[/yellow]")
            return "report"
        
        # Issues found and under max rounds - respond
        return "respond"
    
    # Routing after respond
    def route_after_respond(state: AnalysisState) -> str:
        """After responding to critique, do another critique round."""
        return "critique"
    
    # Routing after reasoning
    def route_after_reason(state: AnalysisState) -> str:
        """Route after reasoning: critique if hypothesis confirmed, else skip to report."""
        hypothesis_status = state.get('hypothesis_status', 'testing')
        
        # Only critique if we have a confirmed hypothesis
        if hypothesis_status == 'confirmed':
            return "critique"
        else:
            # All hypotheses rejected - skip critique, let user ask questions if needed
            console.print("[yellow]⚠ No confirmed hypothesis - skipping critique review[/yellow]")
            return "report"
    
    # Routing in chat loop
    def route_after_chat(state: AnalysisState) -> str:
        """Route after chat: continue chat or END."""
        if state.get('chat_active', False):
            return "chat"
        return "end"
    
    # Final steps - add critique loop
    workflow.add_conditional_edges(
        "reason",
        route_after_reason,
        {
            "critique": "critique",
            "report": "report"
        }
    )
    workflow.add_conditional_edges(
        "critique",
        route_after_critique,
        {
            "respond": "respond",
            "report": "report"
        }
    )
    workflow.add_edge("respond", "critique")
    workflow.add_conditional_edges(
        "report",
        route_after_report,
        {
            "chat": "chat",
            "end": END
        }
    )
    workflow.add_conditional_edges(
        "chat",
        route_after_chat,
        {
            "chat": "chat",
            "end": END
        }
    )

    return workflow


def run_analysis(
    dump_path: Path,
    issue_description: str,
    show_command_output: bool = False,
    log_to_file: bool = True,
    log_output_path: Path | None = None,
    interactive: bool = False,
) -> str:
    """Run expert-level hypothesis-driven memory dump analysis.
    
    Args:
        dump_path: Path to the dump file
        issue_description: User's description of the issue
        show_command_output: Whether to show debugger command outputs
        log_to_file: Whether to log output to session.log
        log_output_path: Custom log file path (relative to session dir or absolute)
        interactive: Whether to enable interactive chat mode after analysis
        
    Returns:
        Final analysis report
    """
    global _log_file_handle, _original_stdout
    
    # Create session directory for this analysis
    from dump_debugger.session import SessionManager
    
    session_manager = SessionManager(base_dir=Path(settings.sessions_base_dir))
    session_dir = session_manager.create_session(dump_path)
    
    console.print(f"[dim]Session: {session_dir.name}[/dim]")
    
    # Set up logging to session directory
    if log_to_file:
        # Resolve log path: if relative, place inside session_dir; if absolute, use as-is
        if log_output_path is not None:
            resolved_log_path = log_output_path if log_output_path.is_absolute() else (session_dir / log_output_path)
        else:
            resolved_log_path = session_dir / "session.log"
        
        console.print(f"[dim]Logging to: {resolved_log_path}[/dim]")
        _log_file_handle = open(resolved_log_path, 'w', encoding='utf-8')
        _original_stdout = sys.stdout
        sys.stdout = TeeOutput(_original_stdout, _log_file_handle)
    
    try:
        # Validate dump file (debugger will be created inside workflow)
        # Just do a quick validation here
        if not dump_path.exists():
            raise FileNotFoundError(f"Dump file not found: {dump_path}")
        
        # Determine dump type from file (simple check without starting debugger)
        dump_type = 'user'  # Default assumption, workflow will create debugger
        
        # Initialize state
        initial_state: AnalysisState = {
            'dump_path': str(dump_path),
            'issue_description': issue_description,
            'dump_type': dump_type,
            'supports_dx': dump_type == 'user',
            
            # Session management
            'session_dir': str(session_dir),
            
            # Hypothesis tracking
            'current_hypothesis': '',
            'hypothesis_confidence': '',
            'hypothesis_reasoning': '',
            'hypothesis_tests': [],
            'alternative_hypotheses': [],
            'hypothesis_status': 'testing',
            
            # Investigation
            'investigation_plan': [],
            'planner_reasoning': '',
            'current_task': '',
            'current_task_index': 0,
            'evidence_inventory': {},
            'completed_tasks': [],  # Track completed tasks to prevent loops
            
            # Execution
            'commands_executed': [],
            'iteration': 0,
            'max_iterations': settings.max_iterations,
            
            # Reasoning
            'reasoner_analysis': '',
            'conclusions': [],
            'confidence_level': None,
            
            # Critique (quality review)
            'critique_round': 0,
            'critique_result': {},
            'has_unresolved_issues': False,
            
            # Output
            'final_report': None,
            
            # Flags
            'sos_loaded': False,
            'show_command_output': show_command_output,
            'should_continue': True,
            
            # Interactive mode
            'interactive_mode': interactive,
            'chat_history': [],
            'chat_active': False,
            'user_requested_report': False,
        }
        
        # Create and run workflow
        workflow = create_expert_workflow(dump_path, session_dir)
        app = workflow.compile()
        
        console.print("\n[bold cyan]🧠 Starting Expert Analysis (Hypothesis-Driven)[/bold cyan]\n")
        
        # Run the workflow with increased recursion limit for interactive chat sessions
        # Each user question in chat mode counts as a graph iteration
        final_state = app.invoke(
            initial_state,
            config={"recursion_limit": settings.graph_recursion_limit}
        )
        
        # Display report
        console.print("\n[bold green]═══════════════════════════════════════════════════[/bold green]")
        console.print("[bold green]ANALYSIS COMPLETE[/bold green]")
        console.print("[bold green]═══════════════════════════════════════════════════[/bold green]\n")
        
        report = final_state.get('final_report', 'No report generated')
        console.print(report)
        
        # Display token usage summary
        token_tracker = get_tracker()
        token_tracker.print_summary()
        
        # Display analyzer usage statistics
        console.print("\n")
        usage_tracker.print_summary()
        
        # Update session access time
        session_manager.update_access_time(session_dir)
        
        console.print(f"\n[dim]Session data saved to: {session_dir}[/dim]")
        
        return report
        
    finally:
        # Restore stdout and close log file
        if _log_file_handle:
            sys.stdout = _original_stdout
            _log_file_handle.close()
            _log_file_handle = None


def enable_logging(log_path: Path) -> None:
    """Enable console output logging to file."""
    global _log_file_handle, _original_stdout
    
    console.print(f"[dim]Logging console output to: {log_path.name}[/dim]")
    _log_file_handle = open(log_path, 'w', encoding='utf-8')
    _original_stdout = sys.stdout
    sys.stdout = TeeOutput(_original_stdout, _log_file_handle)


def disable_logging() -> None:
    """Disable console output logging."""
    global _log_file_handle, _original_stdout
    
    if _log_file_handle:
        sys.stdout = _original_stdout
        _log_file_handle.close()
        _log_file_handle = None
