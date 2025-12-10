"""Agent implementations for the dump debugger."""

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from rich.console import Console

from dump_debugger.core import DebuggerWrapper
from dump_debugger.llm import get_structured_llm
from dump_debugger.prompts import (
    ANALYZER_AGENT_PROMPT,
    DEBUGGER_AGENT_PROMPT,
    PLANNER_PROMPT,
    REPORT_WRITER_PROMPT,
)
from dump_debugger.state import (
    AnalysisState,
    AnalyzerOutput,
    DebuggerOutput,
    PlannerOutput,
)

console = Console()


class PlannerAgent:
    """Agent responsible for creating investigation plans."""

    def __init__(self) -> None:
        self.llm = get_structured_llm(temperature=0.1)

    def plan(self, state: AnalysisState) -> dict[str, Any]:
        """Create an investigation plan based on the issue description.
        
        Args:
            state: Current analysis state
            
        Returns:
            Updated state with investigation plan
        """
        console.print("\n[bold cyan]📋 Planner Agent[/bold cyan]")
        console.print("[dim]Creating investigation plan...[/dim]")

        messages = [
            SystemMessage(content=PLANNER_PROMPT),
            HumanMessage(content=f"""Create an investigation plan for:

Dump Type: {state['dump_type']}
Issue Description: {state['issue_description']}

Provide a structured plan with 4-6 specific investigation tasks.
Return your response as valid JSON matching the schema.""")
        ]

        try:
            response = self.llm.invoke(messages)
            result = json.loads(response.content)
            
            plan_output: PlannerOutput = {
                "investigation_plan": result.get("investigation_plan", []),
                "reasoning": result.get("reasoning", ""),
                "estimated_complexity": result.get("estimated_complexity", "moderate")
            }

            console.print(f"[green]✓[/green] Plan created with {len(plan_output['investigation_plan'])} tasks")
            console.print(f"[dim]Complexity: {plan_output['estimated_complexity']}[/dim]")
            
            for i, task in enumerate(plan_output['investigation_plan'], 1):
                console.print(f"  [cyan]{i}.[/cyan] {task}")

            return {
                "investigation_plan": plan_output["investigation_plan"],
                "planner_reasoning": plan_output["reasoning"],
                "current_task_index": 0,
                "current_task": plan_output["investigation_plan"][0] if plan_output["investigation_plan"] else "",
            }

        except Exception as e:
            console.print(f"[red]✗ Planning failed: {str(e)}[/red]")
            # Fallback plan
            return {
                "investigation_plan": ["Analyze crash context", "Examine exception details"],
                "planner_reasoning": f"Using fallback plan due to error: {str(e)}",
                "current_task_index": 0,
                "current_task": "Analyze crash context",
            }


class DebuggerAgent:
    """Agent responsible for generating and executing debugger commands."""

    def __init__(self, debugger: DebuggerWrapper) -> None:
        self.llm = get_structured_llm(temperature=0.0)
        self.debugger = debugger

    def execute_next_command(self, state: AnalysisState) -> dict[str, Any]:
        """Generate and execute the next debugger command.
        
        Args:
            state: Current analysis state
            
        Returns:
            Updated state with command result
        """
        console.print(f"\n[bold magenta]🔧 Debugger Agent[/bold magenta] [dim](Task: {state['current_task']})[/dim]")

        # Build context from previous commands
        context = self._build_context(state)

        messages = [
            SystemMessage(content=DEBUGGER_AGENT_PROMPT),
            HumanMessage(content=f"""Generate the next debugger command for:

Current Task: {state['current_task']}
Dump Type: {state['dump_type']}

{context}

Return your response as valid JSON with: command, reasoning, expected_insights""")
        ]

        try:
            response = self.llm.invoke(messages)
            result = json.loads(response.content)
            
            debugger_output: DebuggerOutput = {
                "command": result.get("command", "!analyze -v"),
                "reasoning": result.get("reasoning", ""),
                "expected_insights": result.get("expected_insights", "")
            }

            console.print(f"[dim]Reasoning: {debugger_output['reasoning']}[/dim]")
            console.print(f"[yellow]Command:[/yellow] {debugger_output['command']}")

            # Execute the command
            cmd_result = self.debugger.execute_command(debugger_output['command'])
            
            cmd_result["reasoning"] = debugger_output["reasoning"]

            if cmd_result["success"]:
                console.print("[green]✓[/green] Command executed successfully")
            else:
                console.print(f"[red]✗[/red] Command failed: {cmd_result.get('error')}")

            # Update state
            commands_executed = state.get("commands_executed", [])
            commands_executed.append(cmd_result)

            return {
                "commands_executed": commands_executed,
                "debugger_reasoning": debugger_output["reasoning"],
                "iteration": state.get("iteration", 0) + 1,
            }

        except Exception as e:
            console.print(f"[red]✗ Command generation failed: {str(e)}[/red]")
            return {
                "iteration": state.get("iteration", 0) + 1,
            }

    def _build_context(self, state: AnalysisState) -> str:
        """Build context string from previous commands.
        
        Args:
            state: Current analysis state
            
        Returns:
            Context string for the LLM
        """
        commands = state.get("commands_executed", [])
        
        if not commands:
            return "No previous commands executed yet."

        # Include last 3 commands to avoid token overflow
        recent_commands = commands[-3:]
        
        context_parts = ["Previous Commands and Outputs:"]
        for i, cmd in enumerate(recent_commands, 1):
            context_parts.append(f"\n{i}. Command: {cmd['command']}")
            context_parts.append(f"   Success: {cmd['success']}")
            if cmd['success']:
                # Truncate long outputs
                output = str(cmd.get('parsed', cmd.get('output', '')))
                if len(output) > 1000:
                    output = output[:1000] + "\n... (truncated)"
                context_parts.append(f"   Output: {output}")
            else:
                context_parts.append(f"   Error: {cmd.get('error')}")

        findings = state.get("findings", [])
        if findings:
            context_parts.append("\nKey Findings So Far:")
            for finding in findings:
                context_parts.append(f"  - {finding}")

        return "\n".join(context_parts)


class AnalyzerAgent:
    """Agent responsible for analyzing command outputs and extracting findings."""

    def __init__(self) -> None:
        self.llm = get_structured_llm(temperature=0.0)

    def analyze(self, state: AnalysisState) -> dict[str, Any]:
        """Analyze the results of recent commands.
        
        Args:
            state: Current analysis state
            
        Returns:
            Updated state with analysis results
        """
        console.print("\n[bold blue]🧪 Analyzer Agent[/bold blue]")

        # Get the last command result
        commands = state.get("commands_executed", [])
        if not commands:
            return {}

        last_cmd = commands[-1]
        
        messages = [
            SystemMessage(content=ANALYZER_AGENT_PROMPT),
            HumanMessage(content=f"""Analyze this debugger output:

Current Task: {state['current_task']}
Issue Description: {state['issue_description']}

Command: {last_cmd['command']}
Success: {last_cmd['success']}
Output: {str(last_cmd.get('parsed', last_cmd.get('output', '')))}

Previous Findings: {state.get('findings', [])}

Return your response as valid JSON with: findings, reasoning, needs_more_investigation, suggested_next_steps""")
        ]

        try:
            response = self.llm.invoke(messages)
            result = json.loads(response.content)
            
            analyzer_output: AnalyzerOutput = {
                "findings": result.get("findings", []),
                "reasoning": result.get("reasoning", ""),
                "needs_more_investigation": result.get("needs_more_investigation", True),
                "suggested_next_steps": result.get("suggested_next_steps")
            }

            console.print(f"[dim]Analysis: {analyzer_output['reasoning']}[/dim]")
            
            if analyzer_output["findings"]:
                console.print("[green]New Findings:[/green]")
                for finding in analyzer_output["findings"]:
                    console.print(f"  • {finding}")

            # Update state
            all_findings = state.get("findings", [])
            all_findings.extend(analyzer_output["findings"])

            return {
                "findings": all_findings,
                "analyzer_reasoning": analyzer_output["reasoning"],
                "needs_more_investigation": analyzer_output["needs_more_investigation"],
            }

        except Exception as e:
            console.print(f"[red]✗ Analysis failed: {str(e)}[/red]")
            return {
                "needs_more_investigation": True,
            }


class ReportWriterAgent:
    """Agent responsible for generating the final report."""

    def __init__(self) -> None:
        self.llm = get_structured_llm(temperature=0.2)

    def generate_report(self, state: AnalysisState) -> dict[str, Any]:
        """Generate the final analysis report.
        
        Args:
            state: Current analysis state
            
        Returns:
            Updated state with final report
        """
        console.print("\n[bold green]📝 Report Writer Agent[/bold green]")
        console.print("[dim]Generating final report...[/dim]")

        # Build comprehensive context
        context = self._build_report_context(state)

        messages = [
            SystemMessage(content=REPORT_WRITER_PROMPT),
            HumanMessage(content=context)
        ]

        try:
            response = self.llm.invoke(messages)
            report = response.content

            console.print("[green]✓[/green] Report generated")

            return {
                "final_report": report,
                "should_continue": False,
            }

        except Exception as e:
            console.print(f"[red]✗ Report generation failed: {str(e)}[/red]")
            return {
                "final_report": f"Error generating report: {str(e)}",
                "should_continue": False,
            }

    def _build_report_context(self, state: AnalysisState) -> str:
        """Build context for report generation.
        
        Args:
            state: Current analysis state
            
        Returns:
            Context string for report generation
        """
        parts = [
            f"Issue Description: {state['issue_description']}",
            f"Dump Type: {state['dump_type']}",
            f"\nInvestigation Plan:",
        ]

        for i, task in enumerate(state.get("investigation_plan", []), 1):
            parts.append(f"{i}. {task}")

        parts.append("\nCommands Executed:")
        for cmd in state.get("commands_executed", []):
            parts.append(f"\nCommand: {cmd['command']}")
            parts.append(f"Reasoning: {cmd.get('reasoning', 'N/A')}")
            if cmd['success']:
                output = str(cmd.get('parsed', ''))
                if len(output) > 500:
                    output = output[:500] + "... (truncated)"
                parts.append(f"Output: {output}")

        parts.append("\nKey Findings:")
        for finding in state.get("findings", []):
            parts.append(f"  - {finding}")

        return "\n".join(parts)
