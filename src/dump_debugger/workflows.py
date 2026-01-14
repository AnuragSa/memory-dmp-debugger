"""Hypothesis-driven workflow for expert-level crash dump analysis."""

import signal
import sys
from pathlib import Path
from typing import Optional, TextIO

from langgraph.graph import END, StateGraph
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

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
from dump_debugger.security.redactor import load_custom_patterns
from dump_debugger.state import AnalysisState, Evidence, InvestigatorOutput, ReasonerOutput
from dump_debugger.token_tracker import get_tracker
from dump_debugger.analyzer_stats import usage_tracker

console = Console()


def _display_security_banner():
    """Display security and privacy status banner."""
    from pathlib import Path
    
    # Determine security mode
    if settings.local_only_mode:
        # Local-only mode - maximum security
        panel_content = (
            "[bold green]🔒 LOCAL-ONLY MODE ACTIVE[/bold green]\n\n"
            "[green]✓[/green] All processing stays on your machine\n"
            "[green]✓[/green] No data sent to cloud services\n"
            "[green]✓[/green] Using local LLM (Ollama)\n"
        )
        
        # Add custom patterns info
        custom_patterns = load_custom_patterns(settings.redaction_patterns_path)
        if custom_patterns:
            panel_content += f"[green]✓[/green] {len(custom_patterns)} custom redaction patterns loaded\n"
        
        # Add audit status
        if settings.enable_redaction_audit:
            panel_content += "[green]✓[/green] Redaction audit logging enabled\n"
        
        console.print(Panel(
            panel_content,
            border_style="green",
            title="🔒 Security Status",
            title_align="left"
        ))
    else:
        # Cloud mode - show warnings and redaction status
        provider_name = settings.llm_provider.upper()
        if settings.use_tiered_llm:
            provider_name = f"{settings.llm_provider.upper()} (tiered with Ollama)"
        
        panel_content = (
            f"[bold yellow]⚠️  CLOUD MODE - {provider_name}[/bold yellow]\n\n"
            "[yellow]![/yellow] Data will be sent to cloud LLM for analysis\n"
            "[green]✓[/green] Sensitive data is automatically redacted before transmission\n"
        )
        
        # Show redaction patterns
        custom_patterns = load_custom_patterns(settings.redaction_patterns_path)
        total_patterns = 40 + len(custom_patterns)  # ~40 built-in patterns
        panel_content += f"[green]✓[/green] {total_patterns} redaction patterns active "
        if custom_patterns:
            panel_content += f"({len(custom_patterns)} custom)\n"
        else:
            panel_content += "(built-in only)\n"
        
        # Add audit status
        if settings.enable_redaction_audit:
            panel_content += "[green]✓[/green] Redaction audit logging enabled\n"
        
        panel_content += "\n[dim]To prevent all cloud calls, use: --local-only flag[/dim]"
        
        console.print(Panel(
            panel_content,
            border_style="yellow",
            title="🔒 Security Status",
            title_align="left"
        ))
    
    console.print()  # Add spacing


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
        current_idx = state.get('current_task_index', 0)
        total_tasks = len(state.get('investigation_plan', []))
        is_from_critic = state.get('critique_triggered_investigation', False)
        
        # Show which task we're investigating
        if is_from_critic:
            console.print(f"\n[bold cyan]📊 Task {current_idx + 1}/{total_tasks}[/bold cyan]")
            # Extract just the main question part (before Context: or Suggested approach:)
            task_display = current_task.split(' Context:')[0].split(' Suggested approach:')[0]
            if len(task_display) > 100:
                console.print(f"[cyan]{task_display[:100]}...[/cyan]")
            else:
                console.print(f"[cyan]{task_display}[/cyan]")
        
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
        # Note: The ReasonerAgent.reason() method prints its own header,
        # so we don't need to print one here
        
        # Before reasoning, ensure hypothesis test evidence is in the inventory
        # This is critical when all hypotheses are rejected - otherwise evidence is lost
        evidence_inventory = state.get('evidence_inventory', {}).copy()
        
        for test in state.get('hypothesis_tests', []):
            hypothesis = test.get('hypothesis', 'Unknown hypothesis')
            test_evidence = test.get('evidence', [])
            
            if test_evidence:
                # Add hypothesis test evidence to inventory under the hypothesis name
                task_key = f"Hypothesis Test: {hypothesis}"
                if task_key not in evidence_inventory:
                    evidence_inventory[task_key] = []
                evidence_inventory[task_key].extend(test_evidence)
        
        # Update state with merged inventory
        updated_state = state.copy()
        updated_state['evidence_inventory'] = evidence_inventory
        
        result = reasoner.reason(updated_state)
        
        # Ensure the updated inventory persists
        if 'evidence_inventory' not in result:
            result['evidence_inventory'] = evidence_inventory
        
        # Clear critique investigation flag if it was set
        if state.get('critique_triggered_investigation', False):
            result['critique_triggered_investigation'] = False
        
        return result
    
    def critique_node(state: AnalysisState) -> dict:
        """Review analysis for quality issues."""
        return critic.critique(state)
    
    def respond_to_critique_node(state: AnalysisState) -> dict:
        """Respond to critique feedback - collect evidence if needed or re-analyze.
        
        The critic may identify:
        1. Evidence gaps requiring new commands → route to investigation
        2. Analysis quality issues (logic, contradictions) → re-run reasoner
        """
        critique_result = state.get('critique_result', {})
        issues = critique_result.get('critical_issues', [])
        suggested_actions = critique_result.get('suggested_actions', [])
        
        console.print(f"\n[bold cyan]📝 Responding to Round 1 Critique[/bold cyan]")
        
        # Check if critic is requesting new evidence collection
        # Look for action items that mention debugger commands
        evidence_requests = []
        command_keywords = ['!', 'execute', 'run', 'show actual', 'display', 'collect', 'gather']
        
        for action in suggested_actions:
            action_lower = action.lower()
            # Check if this is a request for new evidence (mentions commands)
            if any(keyword in action_lower for keyword in command_keywords):
                evidence_requests.append(action)
        
        if evidence_requests:
            # Critic identified evidence gaps - need to collect more data
            console.print(f"[yellow]⚠ Critic identified {len(evidence_requests)} evidence gap(s) requiring investigation[/yellow]")
            console.print(f"[dim]Collecting missing evidence before re-analysis...[/dim]\n")
            
            # Convert critic's suggestions into investigation requests
            investigation_requests = []
            for action in evidence_requests:
                investigation_requests.append({
                    'question': action,
                    'context': 'Critic identified evidence gap',
                    'approach': action
                })
            
            # Set flags to route to investigation
            current_round = state.get('critique_round', 0)
            return {
                'needs_evidence_collection': True,
                'investigation_requests': investigation_requests,
                'critique_triggered_investigation': True,
                'critique_round': current_round + 1  # Increment for next round
            }
        else:
            # No evidence gaps - just analysis quality issues
            # Re-run reasoner with critique feedback to address logical issues
            console.print(f"[dim]Addressing {len(issues)} concern(s) through re-analysis...[/dim]\n")
            
            result = reasoner.reason(state)
            
            # Increment critique round for tracking
            current_round = state.get('critique_round', 0)
            result['critique_round'] = current_round + 1
            result['needs_evidence_collection'] = False
            
            return result
    
    def prepare_deeper_investigation_node(state: AnalysisState) -> dict:
        """Prepare state for deeper investigation based on reasoner's gap requests."""
        investigation_requests = state.get('investigation_requests', [])
        is_from_critic = state.get('critique_triggered_investigation', False)
        
        if is_from_critic:
            console.print(f"\n[bold cyan]🔍 Setting Up Evidence Collection[/bold cyan]")
            console.print(f"[cyan]Preparing {len(investigation_requests)} investigation task(s) from critique feedback[/cyan]\n")
        else:
            console.print(f"\n[cyan]🔍 Preparing deeper investigation from {len(investigation_requests)} gap request(s)[/cyan]\n")
        
        # Convert investigation requests to investigation plan
        investigation_plan = []
        for i, req in enumerate(investigation_requests, 1):
            question = req.get('question', '')
            context = req.get('context', '')
            approach = req.get('approach', '')
            
            # Add detailed task to investigation plan
            task_description = f"{question}"
            if context and context != 'Critic identified evidence gap':
                task_description += f" Context: {context}"
            if approach and approach != question:  # Don't duplicate if approach same as question
                task_description += f" Suggested approach: {approach}"
            
            # Show task with number for clarity
            if len(question) > 80:
                console.print(f"[dim]  {i}. {question[:80]}...[/dim]")
            else:
                console.print(f"[dim]  {i}. {question}[/dim]")
            investigation_plan.append(task_description)
        
        # Return state updates
        return {
            'investigation_plan': investigation_plan,
            'current_task_index': 0,
            'current_task': investigation_plan[0] if investigation_plan else '',
            'investigation_results': []  # Clear previous results for new iteration
        }

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
    workflow.add_node("prepare_deeper_investigation", prepare_deeper_investigation_node)  # NEW: Bridge node for iterative reasoning
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
        
        # Note: Max hypothesis attempts check is now done in decide_next_step()
        # before generating new hypothesis to avoid wasting LLM calls
        
        if status == 'confirmed':
            # Hypothesis confirmed - start deep investigation
            return "investigate"
        elif status == 'testing':
            # New hypothesis formed - test it
            return "test"
        elif status == 'rejected':
            # Hypothesis rejected and hit max attempts (checked in decide_next_step)
            # Move to reasoning phase
            return "reason"
        else:
            # Shouldn't happen, but safety fallback
            console.print(f"[yellow]⚠ Unexpected hypothesis status: {status}, defaulting to test[/yellow]")
            return "test"
    
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
    
    # Routing after reasoning
    def route_after_reason(state: AnalysisState) -> str:
        """Route after reasoning: PRIORITY 1: Check gaps first, PRIORITY 2: Check confidence, PRIORITY 3: Critique."""
        
        confidence_level = state.get('confidence_level', 'medium')
        reasoning_iterations = state.get('reasoning_iterations', 0)
        
        # Check if this reasoning came from critique-triggered investigation
        # If so, go back to critique Round 2 (don't check for more gaps)
        if state.get('critique_triggered_investigation', False):
            console.print(f"[cyan]→ Evidence collection complete, proceeding to Critique Round 2[/cyan]\n")
            # Clear the flag and increment critique round
            return "critique"
        
        # PRIORITY 1: Check for evidence gaps FIRST (Iterative Reasoning)
        # This MUST happen before critique to ensure complete evidence
        needs_deeper = state.get('needs_deeper_investigation', False)
        investigation_requests = state.get('investigation_requests', [])
        max_iterations = 2  # Reduced from 3 - be more decisive
        
        # Always handle gaps before proceeding to critique
        if needs_deeper and investigation_requests and reasoning_iterations < max_iterations:
            console.print(f"[cyan]🔄 Iteration {reasoning_iterations + 1}: Reasoner identified {len(investigation_requests)} gap(s)[/cyan]")
            console.print(f"[cyan]   Current confidence: {confidence_level.upper()}[/cyan]")
            console.print(f"[cyan]   Collecting missing evidence to enable definitive conclusions[/cyan]")
            return "prepare_deeper_investigation"
        
        # Only show max iterations warning if NOT in critique-triggered investigation
        if reasoning_iterations >= max_iterations:
            if not state.get('critique_triggered_investigation', False):
                console.print(f"[yellow]⚠ Max reasoning iterations ({max_iterations}) reached[/yellow]")
                console.print(f"[yellow]   Proceeding to critique phase with current evidence[/yellow]")
        
        # PRIORITY 2: After evidence is complete, check confidence for informational message
        # Check for expert assessment consensus
        evidence_inventory = state.get('evidence_inventory', {})
        high_confidence_assessments = 0
        total_assessments = 0
        
        for task_evidence in evidence_inventory.values():
            for evidence in task_evidence:
                assessment = evidence.get('expert_assessment')
                if assessment:
                    total_assessments += 1
                    if assessment.get('confidence', 0) > 0.8:
                        high_confidence_assessments += 1
        
        # Calculate overall confidence
        expert_confidence_ratio = high_confidence_assessments / total_assessments if total_assessments > 0 else 0
        
        # Show confidence status (informational only - always proceed to critique)
        if confidence_level == 'high' and expert_confidence_ratio > 0.7 and not needs_deeper:
            console.print(f"[green]✓ HIGH confidence analysis with {expert_confidence_ratio:.0%} expert consensus[/green]")
            console.print(f"[green]  No evidence gaps detected - proceeding to quality review[/green]")
        
        # Normal flow: check hypothesis status
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
            "prepare_deeper_investigation": "prepare_deeper_investigation",  # Route to bridge node
            "critique": "critique",
            "report": "report"
        }
    )
    
    # Bridge node to set up deeper investigation
    workflow.add_edge("prepare_deeper_investigation", "investigate")
    
    workflow.add_conditional_edges(
        "critique",
        route_after_critique,
        {
            "respond": "respond",
            "report": "report"
        }
    )
    
    # Routing after respond - check if evidence collection needed
    def route_after_respond(state: AnalysisState) -> str:
        """Route after responding to critique.
        
        If critic identified evidence gaps → collect evidence → re-reason → critique Round 2
        If only analysis quality issues → already re-analyzed → critique Round 2
        """
        needs_collection = state.get('needs_evidence_collection', False)
        investigation_requests = state.get('investigation_requests', [])
        
        if needs_collection:
            console.print(f"[cyan]→ Routing to investigation to collect missing evidence[/cyan]\n")
            return "prepare_deeper_investigation"
        else:
            # Already re-analyzed, go straight to Round 2
            console.print(f"[cyan]→ No evidence collection needed, proceeding to Critique Round 2[/cyan]\n")
            return "critique"
    
    workflow.add_conditional_edges(
        "respond",
        route_after_respond,
        {
            "prepare_deeper_investigation": "prepare_deeper_investigation",
            "critique": "critique"
        }
    )
    
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
    
    # Set session ID for redaction audit logging
    settings.current_session_id = session_dir.name
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
        # Security banner removed - no longer needed
        
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
