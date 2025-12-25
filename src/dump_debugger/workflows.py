"""Hypothesis-driven workflow for expert-level crash dump analysis."""

import sys
from pathlib import Path
from typing import Optional, TextIO

from langgraph.graph import END, StateGraph
from rich.console import Console

from dump_debugger.config import settings
from dump_debugger.core import DebuggerWrapper
from dump_debugger.hypothesis_agent import HypothesisDrivenAgent
from dump_debugger.interactive_agent import InteractiveChatAgent
from dump_debugger.llm import get_llm
from dump_debugger.state import AnalysisState, Evidence, InvestigatorOutput, ReasonerOutput
from dump_debugger.analyzer_stats import usage_tracker

console = Console()


# Simple agent classes (inline to avoid deleted agents_v2.py dependency)
class InvestigatorAgent:
    """Investigates specific tasks by running targeted debugger commands."""
    
    def __init__(self, debugger: DebuggerWrapper):
        self.debugger = debugger
        self.llm = get_llm(temperature=0.1)
    
    def investigate_task(self, state: AnalysisState) -> dict:
        """Execute investigation task and collect evidence using expert-level approach."""
        task = state['current_task']
        console.print(f"\n[cyan]🔍 Investigating:[/cyan] {task}")
        
        from langchain_core.messages import HumanMessage, SystemMessage
        from dump_debugger.expert_knowledge import (
            get_efficient_commands_for_hypothesis,
            KNOWN_PATTERNS,
            get_investigation_focus
        )
        import json
        
        hypothesis = state.get('current_hypothesis', '')
        prev_evidence = state.get('evidence_inventory', {}).get(task, [])
        supports_dx = state.get('supports_dx', False)
        
        # Get expert guidance for this type of investigation
        pattern_context = ""
        for pattern_name, pattern in KNOWN_PATTERNS.items():
            if any(keyword in hypothesis.lower() for keyword in pattern_name.split('_')):
                focus_areas = get_investigation_focus(pattern_name)
                pattern_context = f"\n\nEXPERT GUIDANCE for {pattern['name']}:\n"
                pattern_context += "\n".join(f"- {area}" for area in focus_areas)
                break
        
        # Get efficient command suggestions
        efficient_cmds = get_efficient_commands_for_hypothesis(task, supports_dx)
        cmd_suggestions = ""
        if efficient_cmds:
            cmd_suggestions = "\n\nSUGGESTED EFFICIENT COMMANDS:\n" + "\n".join(f"- {cmd}" for cmd in efficient_cmds[:3])
        
        prompt = f"""You are an expert Windows debugger. Generate ONE precise WinDbg/CDB command for this investigation.

CONFIRMED HYPOTHESIS: {hypothesis}
INVESTIGATION TASK: {task}
DUMP SUPPORTS DATA MODEL: {supports_dx}
Previous Evidence: {len(prev_evidence)} items
{pattern_context}
{cmd_suggestions}

Think like an expert debugger - you know WHAT the problem is (hypothesis confirmed), now find WHERE and WHY.
{"PREFER 'dx' commands with filters (.Select, .Where, .Take) for concise output." if supports_dx else "Use traditional WinDbg/SOS commands."}

Return ONLY valid JSON in this exact format:
{{
    "command": "the single best debugger command",
    "rationale": "brief one-line reason for choosing this command"
}}"""

        response = self.llm.invoke([
            SystemMessage(content="You are an expert Windows debugger. Always respond with valid JSON only."),
            HumanMessage(content=prompt)
        ])
        
        # Parse JSON response
        try:
            content = response.content.strip()
            # Remove markdown code blocks if present
            if content.startswith('```'):
                parts = content.split('```')
                if len(parts) >= 2:
                    content = parts[1]
                    if content.startswith('json'):
                        content = content[4:]
            
            result = json.loads(content.strip())
            command = result['command'].strip()
            rationale = result.get('rationale', '')
            
            console.print(f"  [dim]→ {command}[/dim]")
            if rationale and state.get('show_commands'):
                console.print(f"  [dim italic]{rationale}[/dim italic]")
                
        except (json.JSONDecodeError, KeyError) as e:
            console.print(f"[yellow]⚠ JSON parsing failed: {e}[/yellow]")
            console.print(f"[yellow]Raw response: {response.content[:200]}[/yellow]")
            # Fallback: extract first line that looks like a command
            lines = response.content.strip().split('\n')
            command = lines[0].strip()
            console.print(f"  [dim]→ {command} (fallback extraction)[/dim]")
        
        # Execute command with evidence analysis
        result = self.debugger.execute_command_with_analysis(
            command=command,
            intent=f"Investigating: {task}"
        )
        
        # Extract output properly (it's a dict!)
        if isinstance(result, dict):
            output_str = result.get('output', '')
            evidence_type = result.get('evidence_type', 'inline')
            evidence_id = result.get('evidence_id')
            analysis = result.get('analysis')
        else:
            output_str = str(result)
            evidence_type = 'inline'
            evidence_id = None
            analysis = None
        
        # Create evidence entry
        # For external evidence, output_str is already the summary (set by execute_command_with_analysis)
        # For inline evidence, truncate if needed to save memory
        if evidence_type == 'external':
            # Already a summary, use as-is
            output_for_state = output_str
        else:
            # Inline evidence - truncate to reasonable size for state
            output_for_state = output_str[:20000] if len(output_str) > 20000 else output_str
        
        evidence: Evidence = {
            'command': command,
            'output': output_for_state,
            'finding': f"Executed for task: {task}",
            'significance': "Investigating confirmed hypothesis",
            'confidence': 'medium',
            'evidence_type': evidence_type,
            'evidence_id': evidence_id,
            'summary': analysis.get('summary') if analysis else None
        }
        
        # Update evidence inventory
        inventory = dict(state.get('evidence_inventory', {}))
        if task not in inventory:
            inventory[task] = []
        inventory[task].append(evidence)
        
        # Limit commands_executed to prevent bloat
        all_commands = state.get('commands_executed', []) + [command]
        if len(all_commands) > 30:
            all_commands = all_commands[-30:]
        
        return {
            'evidence_inventory': inventory,
            'commands_executed': all_commands
        }


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


class ReasonerAgent:
    """Analyzes all evidence to draw conclusions."""
    
    def __init__(self):
        self.llm = get_llm(temperature=0.2)
    
    def reason(self, state: AnalysisState) -> dict:
        """Analyze all evidence and draw conclusions."""
        console.print(f"\n[bold magenta]🧠 Reasoning Over Evidence[/bold magenta]")
        
        from langchain_core.messages import HumanMessage, SystemMessage
        
        evidence_inventory = state.get('evidence_inventory', {})
        total_evidence = sum(len(ev) for ev in evidence_inventory.values())
        
        console.print(f"[dim]Analyzing {total_evidence} pieces of evidence...[/dim]")
        
        # Build evidence summary for reasoning
        evidence_summary = []
        total_chars = 0
        MAX_TOTAL = 800000  # ~200K tokens for Claude Sonnet 4.5
        
        for task, evidence_list in evidence_inventory.items():
            if total_chars >= MAX_TOTAL:
                evidence_summary.append(f"\n[Additional tasks truncated to stay within limits]")
                break
                
            evidence_summary.append(f"\n**Task: {task}**")
            for e in evidence_list:
                cmd = e.get('command', 'unknown')
                
                # Check if this is external evidence with analysis
                if e.get('evidence_type') == 'external' and e.get('summary'):
                    # Use the analyzed summary instead of truncated raw output
                    output_preview = f"[Large output analyzed and stored externally]\nSummary: {e.get('summary')}"
                    if e.get('evidence_id'):
                        output_preview += f"\nEvidence ID: {e.get('evidence_id')}"
                else:
                    # Inline evidence - include fully (Claude 4.5 handles large contexts)
                    output = e.get('output', '')
                    output_preview = output  # No truncation needed with large context window
                
                entry = f"- Command: {cmd}\n  Output: {output_preview}"
                if total_chars + len(entry) > MAX_TOTAL:
                    evidence_summary.append("  [Remaining evidence truncated]")
                    break
                    
                evidence_summary.append(entry)
                total_chars += len(entry)
        
        evidence_text = "\n".join(evidence_summary)
        console.print(f"[dim]Prepared reasoning evidence: {len(evidence_text)} chars (~{len(evidence_text)//4} tokens)[/dim]")
        
        # Get hypothesis test history
        tests_summary = []
        for test in state.get('hypothesis_tests', []):
            result = test.get('result')
            result_str = result.upper() if result else 'PENDING'
            tests_summary.append(f"- {test['hypothesis']}: {result_str}")
        tests_text = "\n".join(tests_summary)
        
        prompt = f"""Analyze all the evidence from this crash dump investigation and draw conclusions.

CONFIRMED HYPOTHESIS: {state.get('current_hypothesis', 'Unknown')}

HYPOTHESIS TESTING HISTORY:
{tests_text}

EVIDENCE COLLECTED:
{evidence_text}

Provide:
1. A holistic analysis of what the evidence reveals
2. Specific conclusions about the root cause
3. Your confidence level in these findings

Return JSON:
{{
    "analysis": "Comprehensive analysis of all evidence",
    "conclusions": ["Conclusion 1", "Conclusion 2", "Conclusion 3"],
    "confidence_level": "high|medium|low"
}}"""
        
        try:
            response = self.llm.invoke([
                SystemMessage(content="You are an expert at synthesizing crash dump evidence into actionable conclusions."),
                HumanMessage(content=prompt)
            ])
            
            # Extract JSON from response
            import json
            content = response.content.strip()
            if content.startswith('```'):
                parts = content.split('```')
                if len(parts) >= 2:
                    content = parts[1]
                    if content.startswith('json'):
                        content = content[4:]
            
            result = json.loads(content.strip())
            
            console.print(f"[green]✓ Analysis complete[/green]")
            console.print(f"[dim]Confidence: {result['confidence_level']}[/dim]")
            
            return {
                'reasoner_analysis': result['analysis'],
                'conclusions': result['conclusions'],
                'confidence_level': result['confidence_level']
            }
            
        except Exception as e:
            console.print(f"[yellow]⚠ Reasoning error: {e}, using fallback[/yellow]")
            # Fallback
            return {
                'reasoner_analysis': f"Analyzed evidence from {len(evidence_inventory)} investigation tasks.",
                'conclusions': [
                    f"Hypothesis '{state['current_hypothesis']}' was confirmed",
                    "Investigation completed across all planned tasks"
                ],
                'confidence_level': 'medium'
            }


class ReportWriterAgentV2:
    """Generates final analysis report."""
    
    def __init__(self):
        self.llm = get_llm(temperature=0.2)
    
    def show_analysis_summary(self, state: AnalysisState) -> dict:
        """Show comprehensive analysis in terminal without generating LLM report.
        
        Used in interactive mode to display all findings before Q&A session.
        Full LLM-generated report is only created when user explicitly requests it via /report.
        """
        console.print(f"\n[bold green]═══════════════════════════════════════════════════[/bold green]")
        console.print(f"[bold green]ANALYSIS COMPLETE[/bold green]")
        console.print(f"[bold green]═══════════════════════════════════════════════════[/bold green]\n")
        
        # Display comprehensive findings
        issue = state.get('issue_description', 'Unknown')
        hypothesis = state.get('current_hypothesis', 'Unknown')
        confidence = state.get('confidence_level', 'medium')
        conclusions = state.get('conclusions', [])
        analysis = state.get('reasoner_analysis', '')
        hypothesis_tests = state.get('hypothesis_tests', [])
        
        # Issue
        console.print(f"[bold cyan]Original Issue:[/bold cyan] {issue}\n")
        
        # Final Hypothesis
        console.print(f"[bold cyan]Final Hypothesis:[/bold cyan]")
        console.print(f"{hypothesis}")
        console.print(f"[bold cyan]Confidence:[/bold cyan] {confidence.upper()}\n")
        
        # Hypothesis Testing History
        if hypothesis_tests:
            console.print(f"[bold cyan]Hypothesis Testing Process:[/bold cyan]")
            for i, test in enumerate(hypothesis_tests, 1):
                result = test.get('result')
                result_str = result.upper() if result else 'PENDING'
                hyp = test.get('hypothesis', 'Unknown')
                
                if result == 'confirmed':
                    console.print(f"  {i}. [green]{hyp} → {result_str}[/green]")
                elif result == 'rejected':
                    console.print(f"  {i}. [red]{hyp} → {result_str}[/red]")
                else:
                    console.print(f"  {i}. [yellow]{hyp} → {result_str}[/yellow]")
                
                reasoning = test.get('evaluation_reasoning', '')
                if reasoning:
                    console.print(f"     [dim]{reasoning[:300]}[/dim]")
            console.print()
        
        # Key Conclusions
        if conclusions:
            console.print("[bold cyan]Key Conclusions:[/bold cyan]")
            for i, conclusion in enumerate(conclusions, 1):
                console.print(f"  {i}. {conclusion}")
            console.print()
        
        # Detailed Analysis
        if analysis:
            console.print("[bold cyan]Detailed Analysis:[/bold cyan]")
            console.print(analysis)
            console.print()
        
        console.print("[dim]Type /report to generate a formatted report, or ask follow-up questions below.[/dim]\n")
        
        # Store a placeholder that report can be generated on demand
        return {
            'final_report': None,  # Will be generated on /report command
            'should_continue': False
        }
    
    def generate_report(self, state: AnalysisState) -> dict:
        """Generate comprehensive analysis report."""
        console.print(f"\n[bold green]📊 Generating Final Report[/bold green]")
        
        from langchain_core.messages import HumanMessage, SystemMessage
        
        # Build detailed report context
        hypothesis = state.get('current_hypothesis', 'Unknown')
        hypothesis_tests = state.get('hypothesis_tests', [])
        evidence = state.get('evidence_inventory', {})
        conclusions = state.get('conclusions', [])
        analysis = state.get('reasoner_analysis', '')
        confidence = state.get('confidence_level', 'medium')
        
        # Build hypothesis testing history
        test_history = []
        for i, test in enumerate(hypothesis_tests, 1):
            result = test.get('result')
            result_str = result.upper() if result else 'PENDING'
            test_history.append(f"{i}. {test['hypothesis']} → **{result_str}**")
            if test.get('evaluation_reasoning'):
                test_history.append(f"   {test['evaluation_reasoning'][:200]}")
        
        test_history_text = "\n".join(test_history)
        
        # Build evidence summary for comprehensive reporting
        evidence_summary = []
        total_chars = 0
        MAX_TOTAL = 800000  # ~200K tokens for Claude Sonnet 4.5
        
        for task, evidence_list in evidence.items():
            if total_chars >= MAX_TOTAL:
                evidence_summary.append(f"\n[Additional tasks omitted to stay within limits]")
                break
                
            evidence_summary.append(f"\n**{task}:**")
            for e in evidence_list:
                cmd = e.get('command', 'unknown')
                finding = e.get('finding', '')
                
                # Check if this is external evidence with analysis
                if e.get('evidence_type') == 'external' and e.get('summary'):
                    # Use analyzed summary for external evidence
                    output_preview = f"[Analyzed externally]\n{e.get('summary')}"
                else:
                    # Include command and smart output preview for inline evidence
                    output = e.get('output', '')
                    if len(output) <= 3000:
                        output_preview = output
                    else:
                        # Show head + tail for context
                        output_preview = f"{output[:1500]}\n[... {len(output) - 3000} chars ...]\n{output[-1500:]}"
                
                entry = f"- Command: {cmd}\n  Output: {output_preview}"
                if finding:
                    entry += f"\n  Finding: {finding}"
                    
                if total_chars + len(entry) > MAX_TOTAL:
                    evidence_summary.append("  [Remaining evidence omitted]")
                    break
                    
                evidence_summary.append(entry)
                total_chars += len(entry)
        
        evidence_text = "\n".join(evidence_summary)
        console.print(f"[dim]Prepared report evidence: {len(evidence_text)} chars (~{len(evidence_text)//4} tokens)[/dim]")
        conclusions_text = "\n".join(f"- {c}" for c in conclusions)
        
        context = f"""Generate a comprehensive crash dump analysis report.

## INVESTIGATION SUMMARY
**User Question:** {state['issue_description']}
**Dump Type:** {state.get('dump_type', 'unknown')}
**Final Hypothesis:** {hypothesis}
**Confidence:** {confidence.upper()}

## HYPOTHESIS TESTING PROCESS
{test_history_text}

## KEY EVIDENCE
{evidence_text}

## ANALYSIS
{analysis}

## CONCLUSIONS
{conclusions_text}

Create a professional report with:
1. **Executive Summary** - Brief overview for management
2. **Root Cause Analysis** - Detailed technical explanation of what caused the issue
3. **Evidence** - Key findings from the investigation
4. **Recommendations** - Specific actions to fix/prevent this issue
5. **Technical Details** - Important debugger outputs and observations

Write in clear, professional technical language.
"""

        try:
            # Use 5 minute timeout for report generation to handle large contexts
            from langchain_core.runnables import RunnableConfig
            config = RunnableConfig(timeout=300)  # 5 minute timeout
            
            response = self.llm.invoke([
                SystemMessage(content="You are an expert at writing technical crash analysis reports for Windows applications."),
                HumanMessage(content=context)
            ], config=config)
            
            report = response.content
            
            # Append chat history if interactive session occurred
            chat_history = state.get('chat_history', [])
            if chat_history:
                report += self._append_chat_section(chat_history)
            
            console.print("[green]✓ Report generated[/green]")
            
            return {
                'final_report': report,
                'should_continue': False
            }
        except Exception as e:
            console.print(f"\n[yellow]⚠ Report generation error: {e}[/yellow]")
            console.print(f"[yellow]Using fallback report format...[/yellow]\n")
            
            # Build fallback report with all available information
            fallback_report = f"""# Crash Dump Analysis Report

## Issue Description
{state['issue_description']}

## Final Hypothesis
{hypothesis}

## Confidence Level
{confidence.upper()}

## Key Conclusions
{conclusions_text if conclusions_text else 'No conclusions available'}

## Detailed Analysis
{analysis if analysis else 'No detailed analysis available'}

## Hypothesis Testing History
{test_history_text if test_history_text else 'No hypothesis tests recorded'}

---
*Note: This is a fallback report due to LLM timeout. Full report generation failed.*
"""
            
            # Append chat history if available
            chat_history = state.get('chat_history', [])
            if chat_history:
                fallback_report += self._append_chat_section(chat_history)
            
            console.print("[green]✓ Fallback report generated[/green]")
            
            return {
                'final_report': fallback_report,
                'should_continue': False
            }
    
    def _append_chat_section(self, chat_history: list) -> str:
        """Append interactive Q&A section to report.
        
        Args:
            chat_history: List of ChatMessage entries
            
        Returns:
            Formatted chat section as markdown
        """
        section = "\n\n---\n\n# Follow-up Questions & Answers\n\n"
        section += "The following questions were asked during the interactive analysis session:\n\n"
        
        # Group messages by Q&A pairs
        for i in range(0, len(chat_history), 2):
            if i + 1 < len(chat_history):
                user_msg = chat_history[i]
                assistant_msg = chat_history[i + 1]
                
                section += f"## Question {i//2 + 1}\n\n"
                section += f"**User:** {user_msg['content']}\n\n"
                section += f"**Answer:** {assistant_msg['content']}\n\n"
                
                # Add commands executed if any
                commands = assistant_msg.get('commands_executed', [])
                if commands:
                    section += "*Investigative commands executed:*\n"
                    for cmd in commands:
                        section += f"- `{cmd}`\n"
                    section += "\n"
        
        return section


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
            # Skip further hypothesis testing and investigation - go straight to reasoning
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
    
    # Routing in chat loop
    def route_after_chat(state: AnalysisState) -> str:
        """Route after chat: continue chat or END."""
        if state.get('chat_active', False):
            return "chat"
        return "end"
    
    # Final steps
    workflow.add_edge("reason", "report")
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
    show_commands: bool = False,
    log_to_file: bool = True,
    log_output_path: Path | None = None,
    interactive: bool = False,
) -> str:
    """Run expert-level hypothesis-driven memory dump analysis.
    
    Args:
        dump_path: Path to the dump file
        issue_description: User's description of the issue
        show_commands: Whether to show debugger command outputs
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
            
            # Output
            'final_report': None,
            
            # Flags
            'sos_loaded': False,
            'show_commands': show_commands,
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
