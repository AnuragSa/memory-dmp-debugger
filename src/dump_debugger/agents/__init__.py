"""Agent implementations for the dump debugger."""

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from rich.console import Console

from dump_debugger.config import settings
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
    
    def _neutralize_issue_description(self, issue_description: str) -> str:
        """Convert user's biased description into neutral investigation goal.
        
        Args:
            issue_description: User's description (may contain assumptions)
            
        Returns:
            Neutral investigation goal
        """
        issue_lower = issue_description.lower()
        
        # Strip assumption words and convert to neutral investigation
        if 'hang' in issue_lower or 'hung' in issue_lower or 'freeze' in issue_lower:
            return "Determine the actual state of the application and all threads"
        elif 'crash' in issue_lower:
            return "Determine what caused the application to terminate and verify if it was truly a crash"
        elif 'leak' in issue_lower:
            return "Analyze memory usage patterns and determine if there are any abnormalities"
        elif 'slow' in issue_lower or 'performance' in issue_lower:
            return "Analyze execution patterns and resource usage to determine actual performance characteristics"
        elif 'deadlock' in issue_lower:
            return "Analyze thread synchronization and locking to determine actual thread states"
        else:
            return "Investigate the application state objectively and determine root cause based on evidence"

    def plan(self, state: AnalysisState) -> dict[str, Any]:
        """Create an investigation plan based on the issue description.
        
        Args:
            state: Current analysis state
            
        Returns:
            Updated state with investigation plan
        """
        console.print("\n[bold cyan]>> Planner Agent[/bold cyan]")
        console.print("[dim]Creating investigation plan...[/dim]")

        # Reframe the issue as a neutral investigation goal
        neutral_goal = self._neutralize_issue_description(state['issue_description'])
        
        messages = [
            SystemMessage(content=PLANNER_PROMPT),
            HumanMessage(content=f"""Create an OBJECTIVE investigation plan for:

Dump Type: {state['dump_type']}
User's Report: {state['issue_description']}

⚠️ CRITICAL: The user's report above is just a HYPOTHESIS - it may be WRONG.
Your job is to investigate OBJECTIVELY and determine what ACTUALLY happened.

Investigation Goal: {neutral_goal}

Provide a structured plan with 4-6 specific investigation tasks that will reveal the TRUE state.
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


class CommandGeneratorAgent:
    """Agent responsible for generating hierarchical command sequences with incremental discovery."""

    def __init__(self) -> None:
        self.llm = get_structured_llm(temperature=0.0)

    def generate_next_command(self, state: AnalysisState) -> dict[str, Any]:
        """Generate the next command incrementally based on current knowledge.
        
        This is step 4 in the sequence: Command generator creates a syntactically correct
        command by hierarchically inspecting children and incrementally building the command.
        
        Args:
            state: Current analysis state
            
        Returns:
            Dictionary with command, purpose, reasoning
        """
        console.print("\n[bold cyan]>> Command Generator Agent[/bold cyan]")
        
        # Get the data request from analyzer (step 2)
        data_request = state.get('data_request', state['current_task'])
        console.print(f"[dim]Generating command to collect: {data_request}[/dim]")

        # Build context
        context = self._build_context(state)
        discovered = state.get("discovered_properties", {})
        discovered_str = json.dumps(discovered, indent=2) if discovered else "None yet"
        
        # Get analyzer feedback if available
        analyzer_feedback = state.get("analyzer_feedback", "")
        
        # Get syntax errors to avoid repeating mistakes
        syntax_errors = state.get("syntax_errors", [])
        syntax_errors_str = ""
        if syntax_errors:
            syntax_errors_str = "\n\n⚠️ SYNTAX ERRORS TO AVOID (DO NOT REPEAT THESE MISTAKES):\n"
            for err in syntax_errors[-5:]:  # Last 5 errors
                syntax_errors_str += f"❌ FAILED COMMAND: {err['command']}\n"
                syntax_errors_str += f"   ERROR: {err['error']}\n\n"

        messages = [
            SystemMessage(content=self._get_generator_prompt()),
            HumanMessage(content=f"""Generate the NEXT command for incremental discovery:

Task: {state['current_task']}
Data Requested by Analyzer: {data_request}
Dump Type: {state['dump_type']}
Data Model Available: {state.get('supports_dx', True)}

Discovered Properties (what we know exists):
{discovered_str}

Analyzer Feedback:
{analyzer_feedback if analyzer_feedback else "No feedback yet - this is the first command"}{syntax_errors_str}

{context}

CRITICAL: Use data model (dx) commands with FILTERS to limit output sent to LLM:
- Use .Count() instead of listing all items
- Use .Take(N) to limit results (e.g., .Take(10) for first 10 items)
- Use .Select() to get only specific fields (e.g., .Select(t => t.Id))
- Use .Where() to filter by conditions
- Use .First() or [0] to inspect single items

Generate ONE command that either:
1. INSPECTS a parent object if not yet discovered (e.g., dx @$curprocess, dx -r1 @$curprocess.Threads.First())
2. QUERIES data with filters if properties are verified (e.g., dx @$curprocess.Threads.Count(), dx @$curprocess.Threads.Take(10).Select(t => t.Id))

Return JSON:
{{
    "command": "single command to execute",
    "purpose": "inspect" or "query",
    "reasoning": "why this command and what it will discover",
    "builds_on": "what previous discovery enables this command"
}}""")
        ]

        try:
            response = self.llm.invoke(messages)
            result = json.loads(response.content)
            
            command = result.get("command", "!analyze -v")
            purpose = result.get("purpose", "query")
            reasoning = result.get("reasoning", "")
            
            # Note: Command is displayed in execute_next_command if show_commands is enabled
            # icon = "🔍" if purpose == "inspect" else "❓"
            # console.print(f"{icon} Command: {command}")
            # console.print(f"[dim]{reasoning}[/dim]")
            
            return {
                "command": command,
                "purpose": purpose,
                "reasoning": reasoning,
                "builds_on": result.get("builds_on", "")
            }

        except Exception as e:
            console.print(f"[red]✗ Command generation failed: {str(e)}[/red]")
            return {
                "command": "!analyze -v",
                "purpose": "query",
                "reasoning": f"Fallback due to error: {str(e)}",
                "builds_on": ""
            }

    def _get_generator_prompt(self) -> str:
        """Get the command generator system prompt."""
        return """You are an expert at generating WinDbg commands incrementally for safe discovery.

Your role is to generate ONE command at a time, building knowledge step-by-step through:
1. HIERARCHICAL INSPECTION: Inspect parents before children
2. INCREMENTAL BUILDING: Build commands based on verified properties
3. FILTERED QUERIES: Always use filters (.Count, .Take, .Select, .Where) to minimize output

The analyzer has requested specific data - your job is to generate a syntactically correct
command that will yield that data, using the data model (dx) as much as possible with filters.

CRITICAL RULES FOR DATA MODEL COMMANDS:

1. CHECK discovered_properties FIRST - NEVER query properties not in this dict:
   - If @$curprocess NOT in discovered_properties → generate: dx @$curprocess
   - If @$curprocess exists but Threads[0] not discovered → generate: dx -r1 @$curprocess.Threads.First()
   - If Threads[0] discovered with [Id, Index] → ONLY query Id or Index, nothing else

2. STRICT PROPERTY VERIFICATION:
   ❌ FORBIDDEN: dx @$curprocess.Threads.Select(t => t.Exception)
      Reason: Exception not in discovered_properties for Threads[0]
   ❌ FORBIDDEN: dx @$curprocess.Threads[0].Stack
      Reason: Stack not in discovered_properties for Threads[0]
   ✅ ALLOWED: dx @$curprocess.Threads.Select(t => t.Id)
      Reason: Id is in discovered_properties["Threads[0]"]

3. INCREMENTAL HIERARCHY:
   Never jump to nested properties without inspecting parents first:
   ❌ BAD: dx @$curprocess.Threads[0].Stack (haven't verified Threads[0] has Stack)
   ✅ GOOD: First inspect Threads[0], check if Stack appears, THEN query it

4. ALWAYS USE FILTERS TO MINIMIZE OUTPUT:
   The LLM analyzing the output has limited context, so use filters:
   
   ❌ CRITICAL - NEVER use 'new { }' syntax (WinDbg doesn't support it):
      dx @$curprocess.Threads.Select(t => new { t.Id, t.Index })  # FAILS with syntax error!
   
   ✅ CORRECT - Query ONE property at a time:
      dx @$curprocess.Threads.Select(t => t.Id)                   # Just IDs
      dx @$curprocess.Threads.Take(10)                             # Full objects, limited
   
   ❌ BAD: dx @$curprocess.Threads (dumps all threads, could be 100+ items)
   ✅ GOOD: dx @$curprocess.Threads.Count() (just the count)
   ✅ GOOD: dx @$curprocess.Threads.Take(5) (first 5 threads only)
   ✅ GOOD: dx @$curprocess.Threads.Select(t => t.Id) (just IDs, not full objects)
   ✅ GOOD: dx @$curprocess.Threads.Where(t => t.Id == 0x1234) (filter to specific thread)
   
   FILTERING METHODS:
   - .Count() - Get just the count
   - .Take(N) - Limit to first N items
   - .Select(t => t.Property) - Extract only specific property
   - .Where(condition) - Filter by condition
   - .First() or [0] - Get just first item
   - Combine: .Where().Take(10).Select(t => t.Id)

5. PURPOSE FIELD:
   - "inspect": Discover structure (dx, dx -r1) - use when property availability unknown
   - "query": Get actual data with FILTERS - ONLY use when properties are verified

6. USE ANALYZER FEEDBACK:
   If analyzer says "need thread details", check what's in discovered_properties["Threads[0]"]:
   - If has [Id, Index] → Generate: dx @$curprocess.Threads.Select(t => t.Id)
   - If only has [Id] → Only query Id, not Index
   
   If analyzer says "need stack trace", check if Stack in Threads[0]:
   - If Stack NOT in Threads[0] → Use traditional: ~* k
   - If Stack in Threads[0] → Query: dx @$curprocess.Threads[0].Stack.Frames

6. FALLBACK LOGIC:
   Common properties that DON'T EXIST in user-mode dumps:
   - Thread.State, Thread.WaitReason (use ~*e !threads instead)
   - Thread.Exception (use !threads -special or .lastevent)
   - Thread.Stack (use ~Xs k for thread X)
   - @$curprocess.Handles (use !handle 0 0)
   
   If you need these, use traditional commands immediately

EXAMPLES:

Scenario 1 - First command, nothing discovered:
{{
    "command": "dx @$curprocess",
    "purpose": "inspect",
    "reasoning": "First inspection to discover top-level properties like Threads, Modules, Id",
    "builds_on": "Starting from root"
}}

Scenario 2 - @$curprocess discovered with [Threads, Modules], but Threads[0] not inspected:
{{
    "command": "dx -r1 @$curprocess.Threads.First()",
    "purpose": "inspect",
    "reasoning": "Inspect first thread to discover available Thread properties",
    "builds_on": "@$curprocess.Threads exists"
}}

Scenario 3 - Threads[0] discovered with [Id, Environment], analyzer needs thread count:
{{
    "command": "dx @$curprocess.Threads.Count()",
    "purpose": "query",
    "reasoning": "Threads collection verified, can safely query count. Using Count() instead of listing all threads to minimize output.",
    "builds_on": "Threads property confirmed in @$curprocess"
}}

Scenario 4 - Analyzer needs list of thread IDs, Threads[0] has [Id] property:
{{
    "command": "dx @$curprocess.Threads.Select(t => t.Id)",
    "purpose": "query",
    "reasoning": "Id property verified, using Select() to extract only IDs, not full thread objects",
    "builds_on": "Threads[0] inspection confirmed Id property exists"
}}

Scenario 5 - Need first 10 thread IDs only (not all 100+ threads):
{{
    "command": "dx @$curprocess.Threads.Take(10).Select(t => t.Id)",
    "purpose": "query",
    "reasoning": "Using Take(10) to limit output to first 10 threads, then Select() for just IDs",
    "builds_on": "Filtering to minimize output for LLM analysis"
}}

Scenario 6 - Tried Stack property, failed (not in dump):
{{
    "command": "~* k",
    "purpose": "query",
    "reasoning": "Stack property unavailable in dump, using traditional stack trace command",
    "builds_on": "Fallback after dx Stack failed"
}}

REMEMBER: ALWAYS prefer filtered queries over dumping entire collections!

Return ONLY valid JSON matching the schema."""

    def _build_context(self, state: AnalysisState) -> str:
        """Build context from recent commands."""
        commands = state.get("commands_executed", [])
        if not commands:
            return "No previous commands executed."
        
        recent = commands[-3:]
        parts = ["Recent Commands:"]
        for cmd in recent:
            status = "✓" if cmd['success'] else "✗"
            parts.append(f"  {status} {cmd['command']}")
            if not cmd['success']:
                parts.append(f"    Error: {cmd.get('error', 'Unknown')}")
        
        return "\n".join(parts)


class DebuggerAgent:
    """Agent responsible for executing debugger command sequences."""

    def __init__(self, debugger: DebuggerWrapper, generator: CommandGeneratorAgent) -> None:
        self.debugger = debugger
        self.generator = generator

    def execute_next_command(self, state: AnalysisState) -> dict[str, Any]:
        """Generate and execute the next incremental command with retry logic for syntax errors.
        
        This implements steps 3, 4, and 5 in the sequence:
        3. Debugger asks command generator to generate a command for the requested data
        4. Command generator generates command (hierarchical inspection, incremental building)
        5. Debugger executes the command and returns results to analyzer
        
        If command fails with syntax error, asks generator to fix and retries.
        
        Args:
            state: Current analysis state
            
        Returns:
            Updated state with command result (only successful results go to analyzer)
        """
        console.print(f"\n[bold magenta]>> Debugger Agent[/bold magenta] [dim](Task: {state['current_task']})[/dim]")
        
        show_commands = state.get("show_commands", False)
        max_retries = settings.max_command_retries
        
        # Retry loop for command generation and execution
        for retry_attempt in range(max_retries + 1):
            # Step 3: Ask command generator to generate a command for the data request
            if show_commands:
                retry_msg = f" (Retry {retry_attempt}/{max_retries})" if retry_attempt > 0 else ""
                console.print(f"[dim]Requesting command from generator for: {state.get('data_request', 'task data')}{retry_msg}[/dim]")
            
            cmd_spec = self.generator.generate_next_command(state)
            
            command = cmd_spec["command"]
            purpose = cmd_spec.get("purpose", "query")
            reasoning = cmd_spec.get("reasoning", "")

            # Execute the command
            if show_commands:
                console.print(f"\nExecuting: {command}")
            cmd_result = self.debugger.execute_command(command)
            cmd_result["reasoning"] = reasoning
            cmd_result["purpose"] = purpose

            # Track results
            commands_executed = state.get("commands_executed", [])
            discovered_properties = state.get("discovered_properties", {})
            failed_count = state.get("failed_commands_current_task", 0)
            syntax_errors = state.get("syntax_errors", [])

            if cmd_result["success"]:
                # SUCCESS - return immediately, no retry needed
                if show_commands:
                    console.print("[green]✓[/green] Success")
                    # Display the command output
                    output = cmd_result.get("output", "")
                    if output:
                        console.print("[dim]─── Output ───[/dim]")
                        console.print(output[:5000])  # Limit to first 5000 chars for display
                        if len(output) > 5000:
                            console.print(f"[dim]... (truncated, {len(output)} total bytes)[/dim]")
                        console.print("[dim]─────────────[/dim]")
                # Reset failure counter on success
                failed_count = 0
                
                # Update discovered properties for inspection/dx commands
                if purpose == "inspect" or 'dx' in command.lower():
                    self._update_discovered_properties(cmd_result, discovered_properties)
                
                commands_executed.append(cmd_result)
                
                # Store updated state and return
                return {
                    "commands_executed": commands_executed,
                    "discovered_properties": discovered_properties,
                    "last_command_result": cmd_result,
                    "debugger_reasoning": reasoning,
                    "iteration": state.get("iteration", 0) + 1,
                    "failed_commands_current_task": failed_count,
                    "syntax_errors": syntax_errors,
                }
            else:
                # FAILURE - check if we should retry
                error_msg = cmd_result.get('error', '')
                is_syntax_error = any(keyword in error_msg.lower() for keyword in ['syntax', 'expected', 'invalid', 'parse'])
                
                if show_commands:
                    console.print(f"[red]✗[/red] Failed: {error_msg}")
                    # Display error output if available
                    error_output = cmd_result.get("output", "")
                    if error_output:
                        console.print("[dim]─── Error Output ───[/dim]")
                        console.print(error_output[:2000])  # Show less for errors
                        if len(error_output) > 2000:
                            console.print(f"[dim]... (truncated, {len(error_output)} total bytes)[/dim]")
                        console.print("[dim]──────────────────[/dim]")
                
                # Track syntax errors for feedback
                if is_syntax_error:
                    syntax_errors.append({
                        "command": command,
                        "error": error_msg
                    })
                    # Update state with error for next retry
                    state["syntax_errors"] = syntax_errors
                    
                    if retry_attempt < max_retries:
                        console.print(f"[yellow]⚠ Syntax error - asking generator to fix (attempt {retry_attempt + 1}/{max_retries})[/yellow]")
                        continue  # Retry with corrected command
                    else:
                        console.print(f"[red]✗ Max retries ({max_retries}) reached for syntax errors[/red]")
                else:
                    # Not a syntax error - could be missing property, permission issue, etc.
                    # Don't retry, let analyzer handle it
                    if show_commands:
                        if purpose == "inspect" and 'dx' in command.lower():
                            console.print("[yellow]⚠[/yellow] Property likely unavailable - will suggest fallback")
                
                # Increment failure counter
                failed_count += 1
                if show_commands:
                    console.print(f"[yellow]⚠ Failure {failed_count} for current task[/yellow]")
                
                commands_executed.append(cmd_result)
                
                # Return failed result (either non-syntax error or exhausted retries)
                return {
                    "commands_executed": commands_executed,
                    "discovered_properties": discovered_properties,
                    "last_command_result": cmd_result,
                    "debugger_reasoning": reasoning,
                    "iteration": state.get("iteration", 0) + 1,
                    "failed_commands_current_task": failed_count,
                    "syntax_errors": syntax_errors,
                }
        
        # Should never reach here, but return empty dict as fallback
        return {}

    def _update_discovered_properties(self, cmd_result: dict[str, Any], discovered_properties: dict[str, list[str]]) -> None:
        """Extract and store discovered properties from inspection commands.
        
        Args:
            cmd_result: Command result containing inspection output
            discovered_properties: Dictionary to update with discovered properties
        """
        import re
        
        command = cmd_result['command']
        output = str(cmd_result.get('parsed', cmd_result.get('output', '')))
        
        # Extract object path from command more robustly
        command_lower = command.strip().lower()
        object_path = None
        
        if command_lower == 'dx @$curprocess':
            object_path = "@$curprocess"
        elif 'dx -r1 @$curprocess.threads.first()' in command_lower or 'dx -r1 @$curprocess.threads[0]' in command_lower:
            object_path = "Threads[0]"
        elif 'dx -r1 @$curprocess.modules.first()' in command_lower or 'dx -r1 @$curprocess.modules[0]' in command_lower:
            object_path = "Modules[0]"
        elif 'dx -r1 @$curprocess.threads' in command_lower:
            object_path = "@$curprocess.Threads"
        elif 'dx -r1 @$curprocess.modules' in command_lower:
            object_path = "@$curprocess.Modules"
        elif 'dx @$curprocess.threads' in command and '[' in command:
            object_path = "Threads[0]"
        elif 'dx @$curprocess.modules' in command and '[' in command:
            object_path = "Modules[0]"
        else:
            return
        
        # Extract property names from output - support both : and = patterns
        properties = []
        for line in output.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue
            # Match patterns like "Id : 0x1234" or "Threads = [...]" or "Name : foo"
            match = re.match(r'([A-Za-z_]\w*)\s*[:=]', stripped)
            if match:
                prop_name = match.group(1)
                if prop_name not in ['quit', 'dx']:  # Filter out noise
                    properties.append(prop_name)
        
        if properties:
            # Merge with existing properties
            existing = set(discovered_properties.get(object_path, []))
            existing.update(properties)
            discovered_properties[object_path] = sorted(existing)
            
            preview = ', '.join(list(discovered_properties[object_path])[:5])
            suffix = '...' if len(discovered_properties[object_path]) > 5 else ''
            console.print(f"[dim]Discovered properties for {object_path}: {preview}{suffix}[/dim]")


class AnalyzerAgent:
    """Agent responsible for analyzing command outputs and extracting findings."""

    def __init__(self) -> None:
        self.llm = get_structured_llm(temperature=0.0)

    def request_data(self, state: AnalysisState) -> dict[str, Any]:
        """Request specific data needed to accomplish the current task.
        
        This is step 2 in the sequence: Analyzer looks at the current task
        and determines what specific data the debugger should gather.
        
        Args:
            state: Current analysis state
            
        Returns:
            Updated state with data_request specifying what the debugger should collect
        """
        console.print("\n[bold blue]>> Analyzer Agent - Data Request[/bold blue]")
        console.print(f"[dim]Analyzing task: {state['current_task']}[/dim]")

        # Check for repetitive requests - force different approach if stuck
        recent_requests = state.get("recent_data_requests", [])
        if len(recent_requests) >= 3:
            last_three = recent_requests[-3:]
            # Check if we're repeating similar requests
            if len(set(last_three)) <= 2:
                console.print(f"[yellow]WARNING: Detected repetitive requests. Forcing alternative approach...[/yellow]")
                task_lower = state['current_task'].lower()
                
                # Suggest traditional commands for common stuck scenarios
                if 'thread' in task_lower and 'state' in task_lower:
                    return {
                        "data_request": "Use traditional !threads command (requires SOS)",
                        "data_request_reasoning": "Thread states unavailable via dx. Switching to traditional WinDbg commands.",
                    }
                elif 'stack' in task_lower:
                    return {
                        "data_request": "Use ~*k or !clrstack for call stacks",
                        "data_request_reasoning": "Traditional stack commands more reliable than dx queries.",
                    }
                else:
                    # Move to next task to avoid infinite loop
                    console.print("[yellow]Moving to next task to avoid infinite loop[/yellow]")
                    return {
                        "data_request": "SKIP_TO_NEXT_TASK",
                        "data_request_reasoning": "Unable to gather required data after multiple attempts.",
                    }

        # Build context from previous findings
        findings_summary = "\n".join([f"  - {f}" for f in state.get('findings', [])]) if state.get('findings') else "None yet"
        
        # Get recent commands to understand what we've already tried
        commands = state.get("commands_executed", [])
        recent_commands = "\n".join([f"  - {cmd['command']}" for cmd in commands[-3:]]) if commands else "None yet"

        messages = [
            SystemMessage(content=self._get_data_request_prompt()),
            HumanMessage(content=f"""Determine what specific data is needed for this task:

Current Task: {state['current_task']}
Issue Description: {state['issue_description']}
Dump Type: {state['dump_type']}

Previous Findings:
{findings_summary}

Recent Commands:
{recent_commands}

Discovered Properties: {json.dumps(state.get('discovered_properties', {}), indent=2)}

IMPORTANT: If recent commands show repeated attempts without progress, suggest traditional WinDbg commands (!threads, ~*k, !clrstack) instead of dx commands.

What specific data should the debugger collect to accomplish this task?
Be specific about what information is needed (e.g., "thread count and IDs", "exception details", "stack trace of thread 0").

Return JSON:
{{
    "data_request": "specific data needed",
    "reasoning": "why this data is needed for the task",
    "priority": "high|medium|low"
}}""")
        ]

        try:
            console.print(f"[dim]Calling LLM for data request...[/dim]")
            response = self.llm.invoke(messages)
            console.print(f"[dim]LLM response received, parsing JSON...[/dim]")
            result = json.loads(response.content)
            
            data_request = result.get("data_request", "General information about the crash")
            reasoning = result.get("reasoning", "")
            
            console.print(f"[cyan]Data Request:[/cyan] {data_request}")
            console.print(f"[dim]{reasoning}[/dim]")
            
            return {
                "data_request": data_request,
                "data_request_reasoning": reasoning,
            }

        except json.JSONDecodeError as e:
            console.print(f"[yellow]⚠ JSON decode error: {str(e)}[/yellow]")
            # Use task as data request if JSON parsing fails
            task_based_request = f"Information needed for: {state['current_task']}"
            return {
                "data_request": task_based_request,
                "data_request_reasoning": f"Fallback - JSON parsing failed: {str(e)}",
            }
        except Exception as e:
            console.print(f"[red]✗ Data request failed: {str(e)}[/red]")
            console.print(f"[yellow]⚠ Using fallback: deriving request from task[/yellow]")
            # Derive a sensible request from the task
            task_lower = state['current_task'].lower()
            if 'thread' in task_lower and 'state' in task_lower:
                fallback_request = "Thread count, thread IDs, and thread states"
            elif 'stack' in task_lower:
                fallback_request = "Call stack information for relevant threads"
            elif 'exception' in task_lower or 'crash' in task_lower:
                fallback_request = "Exception details and crash information"
            elif 'file' in task_lower or 'io' in task_lower:
                fallback_request = "File I/O operations and file access information"
            elif 'lock' in task_lower or 'deadlock' in task_lower:
                fallback_request = "Lock and synchronization information"
            else:
                fallback_request = f"Information about: {state['current_task']}"
            
            return {
                "data_request": fallback_request,
                "data_request_reasoning": f"Fallback request due to error: {str(e)}",
            }

    def _get_data_request_prompt(self) -> str:
        """Get the system prompt for data request phase."""
        return """You are an expert analyzer determining what data is needed to investigate a crash.

Your role is to look at the current investigation task and specify EXACTLY what data 
the debugger should collect. Be specific and targeted.

EXAMPLES:

Task: "Identify the crashed thread and exception details"
Data Request: "Exception record, exception code, and faulting thread ID"

Task: "Analyze call stack of crashed thread"
Data Request: "Complete call stack with parameters for thread 0 (or identified crashed thread)"

Task: "Check for memory corruption"
Data Request: "Heap validation results and memory allocation summary"

Task: "List all threads and their states"
Data Request: "Thread count, thread IDs, and current wait states for all threads"

Be specific about:
- WHAT data (e.g., "thread IDs" not just "threads")
- HOW MUCH (e.g., "top 10 stack frames" not "all stack frames")
- WHICH items (e.g., "crashed thread" not "all threads" unless needed)

Output valid JSON with data_request, reasoning, and priority fields."""

    def analyze(self, state: AnalysisState) -> dict[str, Any]:
        """Analyze the results of recent commands.
        
        Args:
            state: Current analysis state
            
        Returns:
            Updated state with analysis results
        """
        console.print("\n[bold blue]>> Analyzer Agent[/bold blue]")

        # Get the last command result
        commands = state.get("commands_executed", [])
        if not commands:
            return {}

        last_cmd = commands[-1]
        
        messages = [
            SystemMessage(content=ANALYZER_AGENT_PROMPT),
            HumanMessage(content=f"""Analyze this debugger output OBJECTIVELY:

Current Task: {state['current_task']}
User's Claim: {state['issue_description']}

⚠️ CRITICAL: User's claim may be INCORRECT. Analyze ONLY the data below.

Command: {last_cmd['command']}
Success: {last_cmd['success']}
Output: {str(last_cmd.get('parsed', last_cmd.get('output', '')))}

Previous Findings: {state.get('findings', [])}

BEFORE stating your findings, ask yourself these verification questions:
1. Does the data actually support the user's claim?
2. What does the data ACTUALLY show, ignoring the claim?
3. Is there evidence that CONTRADICTS the user's claim?
4. What alternative explanations fit the data better?

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
            
            # Build feedback for command generator
            feedback_parts = []
            if analyzer_output["needs_more_investigation"]:
                feedback_parts.append(f"Analysis: {analyzer_output['reasoning']}")
                if analyzer_output["suggested_next_steps"]:
                    feedback_parts.append(f"Suggested next steps: {', '.join(analyzer_output['suggested_next_steps'])}")
            
            analyzer_feedback = "\n".join(feedback_parts) if feedback_parts else ""

            # Update state
            all_findings = state.get("findings", [])
            all_findings.extend(analyzer_output["findings"])
            
            # Determine if current task is complete
            # Task is complete when analyzer says no more investigation needed AND we have findings
            task_complete = not analyzer_output["needs_more_investigation"] and len(analyzer_output["findings"]) > 0

            # Log decision
            if task_complete:
                console.print(f"[green]✓ Task complete:[/green] {state['current_task']}")
            else:
                console.print(f"[yellow]⚠ More data needed for:[/yellow] {state['current_task']}")

            return {
                "findings": all_findings,
                "analyzer_reasoning": analyzer_output["reasoning"],
                "analyzer_feedback": analyzer_feedback,
                "needs_more_investigation": analyzer_output["needs_more_investigation"],
                "task_complete": task_complete,
            }

        except Exception as e:
            console.print(f"[red]✗ Analysis failed: {str(e)}[/red]")
            return {
                "needs_more_investigation": True,
                "analyzer_feedback": f"Analysis error: {str(e)}",
            }


class ReportWriterAgent:
    """Agent responsible for generating the final report."""

    def __init__(self) -> None:
        from dump_debugger.llm import get_llm
        self.llm = get_llm(temperature=0.2)

    def generate_report(self, state: AnalysisState) -> dict[str, Any]:
        """Generate the final analysis report.
        
        Args:
            state: Current analysis state
            
        Returns:
            Updated state with final report
        """
        console.print("\n[bold green]>> Report Writer Agent[/bold green]")
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
            f"User's Claim: {state['issue_description']}",
            f"Dump Type: {state['dump_type']}",
            "",
            "⚠️ CRITICAL INSTRUCTIONS FOR REPORT:",
            "1. The 'User's Claim' above may be INCORRECT - do NOT assume it's true",
            "2. Base your conclusions ONLY on the evidence from debugger output below",
            "3. If evidence CONTRADICTS the user's claim, state that clearly",
            "4. If evidence is INSUFFICIENT to support the claim, state that",
            "5. Challenge your own conclusions - what alternative explanations exist?",
            "",
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

        parts.append("\nKey Findings (from objective analysis):")
        for finding in state.get("findings", []):
            parts.append(f"  - {finding}")
        
        parts.append("\n")
        parts.append("VERIFICATION CHECKLIST before writing report:")
        parts.append("☐ Does the evidence actually support the user's claim?")
        parts.append("☐ Are there contradictions between claim and data?")
        parts.append("☐ What does the data show when ignoring the user's claim?")
        parts.append("☐ What alternative explanations fit the evidence?")

        return "\n".join(parts)


__all__ = [
    "PlannerAgent",
    "CommandGeneratorAgent",
    "DebuggerAgent",
    "AnalyzerAgent",
    "ReportWriterAgent",
]
