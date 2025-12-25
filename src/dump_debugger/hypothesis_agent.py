"""Hypothesis-driven investigation agent - thinks like an expert debugger."""

import json
from typing import Any

from rich.console import Console

from dump_debugger.config import settings
from dump_debugger.core import DebuggerWrapper
from dump_debugger.expert_knowledge import (
    COMMAND_SHORTCUTS,
    DATA_MODEL_QUERIES,
    KNOWN_PATTERNS,
    get_confirmation_commands,
    get_efficient_commands_for_hypothesis,
    get_investigation_focus,
    suggest_pattern_from_symptoms,
)
from dump_debugger.llm import get_llm
from dump_debugger.state import AnalysisState, Evidence, HypothesisTest

console = Console()


class HypothesisDrivenAgent:
    """Agent that forms and tests hypotheses like an expert debugger.
    
    This agent:
    1. Forms initial hypothesis from user question
    2. Designs targeted commands to test hypothesis
    3. Evaluates results: confirmed, rejected, or inconclusive
    4. Pivots to new hypothesis if rejected
    5. Drills deeper if confirmed
    """
    
    def __init__(self, debugger: DebuggerWrapper):
        self.debugger = debugger
        self.llm = get_llm()
    
    def form_initial_hypothesis(self, state: AnalysisState) -> dict[str, Any]:
        """Form initial hypothesis from user question and known patterns.
        
        Args:
            state: Current analysis state
            
        Returns:
            Updated state with hypothesis
        """
        console.print("\n[bold cyan]📋 Forming Initial Hypothesis[/bold cyan]")
        
        issue = state['issue_description']
        dump_type = state.get('dump_type', 'unknown')
        supports_dx = state.get('supports_dx', False)
        
        # Check if question matches known patterns
        symptoms_from_question = [issue]
        matching_patterns = suggest_pattern_from_symptoms(symptoms_from_question)
        
        pattern_context = ""
        suggested_pattern = None
        if matching_patterns:
            suggested_pattern = matching_patterns[0]  # Use top match
            pattern_context = "\n\nKNOWN PATTERNS that might match:\n"
            for pattern_name in matching_patterns[:3]:  # Top 3
                pattern = KNOWN_PATTERNS[pattern_name]
                pattern_context += f"\n**{pattern['name']}**\n"
                pattern_context += f"Typical cause: {pattern['typical_cause']}\n"
                pattern_context += f"Confirmation needed: {', '.join(pattern['confirmation_commands'][:2])}\n"
        
        # Get efficient test commands suggestion
        efficient_commands = get_efficient_commands_for_hypothesis(
            issue, 
            supports_dx, 
            suggested_pattern
        )
        
        command_suggestion = ""
        if efficient_commands:
            if supports_dx:
                command_suggestion = f"\n\nRECOMMENDED EFFICIENT COMMANDS (use data model for concise output):\n"
                command_suggestion += "\n".join(f"- {cmd}" for cmd in efficient_commands[:3])
            else:
                command_suggestion = f"\n\nRECOMMENDED COMMANDS:\n"
                command_suggestion += "\n".join(f"- {cmd}" for cmd in efficient_commands[:3])
        
        prompt = f"""You are an expert debugger analyzing a memory dump. Form an initial hypothesis about the issue.

USER QUESTION: {issue}
DUMP TYPE: {dump_type}
DATA MODEL AVAILABLE: {"Yes, but use sparingly" if supports_dx else "No"}
{pattern_context}
{command_suggestion}

Based on the user's question and your expertise, form an initial hypothesis.

Think like an expert:
- What's the most likely root cause?
- What pattern does this match (deadlock, leak, starvation, etc.)?
- What would you check first to confirm or reject this hypothesis?

Return a JSON object with:
{{
    "hypothesis": "Your hypothesis about the root cause",
    "confidence": "high|medium|low",
    "reasoning": "Why you think this is the cause",
    "test_commands": ["command1", "command2"],
    "expected_if_confirmed": "What output would confirm this hypothesis",
    "expected_if_rejected": "What output would reject this hypothesis",
    "alternative_hypotheses": ["Alternative explanation 1", "Alternative explanation 2"]
}}

COMMAND GUIDELINES:
- ALWAYS prefer traditional SOS/WinDbg commands: !threads, !threadpool, !dumpheap, !clrstack, !syncblk, !eeheap, !finalizequeue
- AVOID dx commands - they have complex syntax and high failure rates
- Only use dx if traditional commands cannot achieve the goal
- Use commands appropriate for {dump_type}-mode dumps
- Be specific with commands - use actual command syntax"""
        
        response = self.llm.invoke(prompt)
        hypothesis_data = self._extract_json(response.content)
        
        # Store in state
        console.print(f"[cyan]💡 Hypothesis:[/cyan] {hypothesis_data['hypothesis']}")
        console.print(f"[cyan]🎯 Confidence:[/cyan] {hypothesis_data['confidence'].upper()}")
        console.print(f"[cyan]🔍 Will test with:[/cyan] {', '.join(hypothesis_data['test_commands'][:2])}")
        
        return {
            'current_hypothesis': hypothesis_data['hypothesis'],
            'hypothesis_confidence': hypothesis_data['confidence'],
            'hypothesis_reasoning': hypothesis_data['reasoning'],
            'hypothesis_tests': [{
                'hypothesis': hypothesis_data['hypothesis'],
                'test_commands': hypothesis_data['test_commands'],
                'expected_confirmed': hypothesis_data['expected_if_confirmed'],
                'expected_rejected': hypothesis_data['expected_if_rejected'],
                'result': None,
                'evidence': [],
                'evaluation_reasoning': '',
                'inconclusive_count': 0,  # Track how many times test is inconclusive
            }],
            'alternative_hypotheses': hypothesis_data.get('alternative_hypotheses', [])
        }
    
    def test_hypothesis(self, state: AnalysisState) -> dict[str, Any]:
        """Execute commands to test current hypothesis.
        
        Args:
            state: Current analysis state
            
        Returns:
            Updated state with test results
        """
        current_test = state['hypothesis_tests'][-1]  # Most recent test
        
        if current_test['result'] is not None:
            # Already tested
            return {}
        
        console.print(f"\n[bold cyan]🧪 Testing Hypothesis[/bold cyan]")
        console.print(f"[dim]{current_test['hypothesis']}[/dim]")
        
        # CRITICAL: Start with fresh evidence list for this test run
        # Do NOT accumulate evidence from previous test attempts
        evidence_collected: list[Evidence] = []
        
        # Clear any old evidence from previous test runs to prevent accumulation
        if 'evidence' in current_test:
            old_count = len(current_test.get('evidence', []))
            console.print(f"[dim]DEBUG: Clearing {old_count} old evidence items from previous test run[/dim]")
            current_test['evidence'] = []
        
        # Execute test commands with immediate retry on each failure
        commands_to_execute = current_test['test_commands'][:3].copy()  # Max 3 commands per test
        max_retries_per_command = 1
        
        for cmd_index in range(len(commands_to_execute)):
            cmd = commands_to_execute[cmd_index]
            
            for attempt in range(max_retries_per_command + 1):
                # Only print command on first attempt (avoid duplicate printing after "Retrying with:")
                if attempt == 0:
                    console.print(f"  [cyan]→[/cyan] {cmd}")
                
                # Use evidence analysis for large outputs
                output = self.debugger.execute_command_with_analysis(
                    cmd,
                    intent=f"Testing hypothesis: {current_test['hypothesis']}"
                )
                
                # Extract the actual output from the dict returned by debugger
                if isinstance(output, dict):
                    output_str = output.get('output', '')
                    evidence_type = output.get('evidence_type', 'inline')
                    evidence_id = output.get('evidence_id')
                    analysis = output.get('analysis')
                else:
                    output_str = str(output)
                    evidence_type = 'inline'
                    evidence_id = None
                    analysis = None
                
                # Always show a preview of the output - especially important for retry attempts
                output_preview = output_str[:500] if len(output_str) > 500 else output_str
                # Show output on retries (attempt > 0) OR if show_commands is enabled
                if attempt > 0 or state.get('show_commands'):
                    console.print(f"[dim]{output_preview}{'...' if len(output_str) > 500 else ''}[/dim]")
                
                # Detect command failures
                failed = False
                if "Error: Unable to bind name" in output_str or "Couldn't resolve" in output_str or "Syntax error" in output_str:
                    failed = True
                    error_msg = output_str.strip()[:200]
                    console.print(f"[red]⚠ Command failed: {error_msg}[/red]")
                    
                    # If failed and we can retry, ask LLM for alternative immediately
                    if attempt < max_retries_per_command:
                        console.print(f"[yellow]🔄 Asking LLM for alternative command...[/yellow]")
                        
                        retry_prompt = f"""The following command failed. Generate ONE alternative command that will work.

HYPOTHESIS: {current_test['hypothesis']}
EXPECTED IF CONFIRMED: {current_test.get('expected_confirmed', 'Evidence showing the hypothesis is true')}

FAILED COMMAND:
{cmd}

ERROR:
{error_msg}

REASON: {"Data model (dx) commands not working - use traditional SOS commands" if "Unable to bind" in error_msg else "Command syntax or execution error"}

Generate ONE alternative command using SOS/WinDbg commands that tests the same thing.
EXAMPLES: !dumpheap -stat -type <TypeName>, !threadpool, ~*e !clrstack, !syncblk, !do <address>

Return JSON:
{{
    "alternative_command": "single command to try instead",
    "reasoning": "why this will work"
}}"""
                        
                        try:
                            response = self.llm.invoke(retry_prompt)
                            retry_data = self._extract_json(response.content)
                            
                            # Use the alternative command for next iteration
                            cmd = retry_data['alternative_command']
                            console.print(f"[cyan]  Retrying with: {cmd}[/cyan]")
                            continue  # Retry with new command
                            
                        except Exception as e:
                            console.print(f"[red]Failed to generate alternative: {e}[/red]")
                            # Fall through to store failed evidence
                    else:
                        console.print(f"[yellow]  Max retries reached, storing failure[/yellow]")
                else:
                    # Command succeeded
                    if attempt > 0:
                        console.print(f"[green]✓ Alternative command succeeded[/green]")
                
                # Command succeeded or we've exhausted retries - store evidence and break
                evidence_collected.append({
                    'command': cmd,
                    'output': output_str,  # For external evidence, this is already the summary
                    'finding': '',
                    'significance': '',
                    'confidence': 'medium',
                    'failed': failed,
                    'evidence_type': evidence_type,
                    'evidence_id': evidence_id,
                    'summary': analysis.get('summary') if analysis else None
                })
                
                state['commands_executed'].append(cmd)
                break  # Move to next command
        
        # Evaluate results
        evaluation = self._evaluate_test_results(
            current_test,
            evidence_collected
        )
        
        # Update test with results
        # For external evidence, output is already a summary
        # For inline evidence, keep up to 200KB for Claude 4.5
        for e in evidence_collected:
            if e.get('evidence_type') != 'external':
                # Only truncate inline evidence if exceeds 200KB
                if len(e.get('output', '')) > 200000:
                    e['output'] = e['output'][:200000] + '\n[... output truncated at 200K chars ...]'
        
        current_test['result'] = evaluation['result']  # 'confirmed', 'rejected', 'inconclusive'
        current_test['evidence'] = evidence_collected
        current_test['evaluation_reasoning'] = evaluation['reasoning']
        
        console.print(f"\n[bold]{'✅' if evaluation['result'] == 'confirmed' else '❌' if evaluation['result'] == 'rejected' else '❓'} Result:[/bold] {evaluation['result'].upper()}")
        console.print(f"[dim]{evaluation['reasoning']}[/dim]")
        
        # Limit commands_executed to last 20 to prevent state bloat
        all_commands = state.get('commands_executed', [])
        if len(all_commands) > 20:
            all_commands = all_commands[-20:]
        
        return {
            'hypothesis_tests': state['hypothesis_tests'],
            'commands_executed': all_commands
        }
    
    def decide_next_step(self, state: AnalysisState) -> dict[str, Any]:
        """Decide what to do based on hypothesis test results.
        
        Args:
            state: Current analysis state
            
        Returns:
            Updated state with next action
        """
        current_test = state['hypothesis_tests'][-1]
        result = current_test['result']
        
        if result == 'confirmed':
            # Drill deeper to find root cause
            console.print("\n[bold green]✅ Hypothesis CONFIRMED - Drilling deeper for root cause[/bold green]")
            return self._plan_deep_dive(state, current_test)
        
        elif result == 'rejected':
            # Form new hypothesis
            console.print("\n[bold yellow]❌ Hypothesis REJECTED - Forming new hypothesis[/bold yellow]")
            return self._form_alternative_hypothesis(state, current_test)
        
        else:  # inconclusive
            # Gather more evidence
            console.print("\n[bold yellow]❓ Inconclusive - Gathering more evidence[/bold yellow]")
            return self._gather_more_evidence(state, current_test)
    
    def _summarize_large_output(self, output: str, max_chars: int = 50000) -> str:
        """Use LLM to intelligently summarize large command outputs.
        
        Args:
            output: Large command output to summarize
            max_chars: Maximum characters for summary
            
        Returns:
            Summarized output preserving diagnostic details
        """
        console.print(f"[yellow]⚙ Summarizing large output ({len(output)} chars) using LLM...[/yellow]")
        
        # Give LLM head and tail to work with
        sample = output[:15000] + "\n\n[... middle section truncated ...]\n\n" + output[-15000:]
        
        prompt = f"""Summarize this debugger output, preserving ALL diagnostic details:
- Thread states, IDs, and wait reasons
- Lock contention details (which threads waiting, which holding)
- Stack traces showing blocking operations
- Error messages and exceptions
- Memory addresses and object references
- Counts, statistics, and numerical values

Output sample (head + tail of {len(output)} total chars):
{sample}

Provide a complete technical summary maintaining all diagnostic value for crash analysis.
Keep critical details like thread IDs, addresses, lock holders, and wait patterns."""
        
        try:
            response = get_llm(temperature=0).invoke(prompt)
            summary = response.content[:max_chars]
            console.print(f"[green]✓ Summarized to {len(summary)} chars[/green]")
            return summary
        except Exception as e:
            console.print(f"[red]✗ Summarization failed: {e}[/red]")
            # Fallback to simple truncation
            return output[:max_chars]
    
    def _prepare_evidence_for_evaluation(self, evidence: list[Evidence]) -> str:
        """Prepare evidence for evaluation with smart truncation/summarization.
        
        Args:
            evidence: List of evidence to prepare
            
        Returns:
            Prepared evidence text that fits within token limits
        """
        evidence_parts = []
        total_size = 0
        MAX_TOTAL = 800000  # chars (~200K tokens for Claude Sonnet 4.5)
        MAX_SINGLE = 200000  # chars per evidence item (~50K tokens)
        
        for i, e in enumerate(evidence):
            cmd = e.get('command', 'unknown')
            
            # Check if this is external evidence with analysis
            if e.get('evidence_type') == 'external' and e.get('summary'):
                # Use the analyzed summary instead of truncating raw output
                processed = f"[Large output analyzed externally]\nSummary: {e.get('summary')}"
                console.print(f"[dim]  Evidence {i+1}: Using analyzed summary from evidence store[/dim]")
            else:
                # Inline evidence - include up to MAX_SINGLE, truncate if larger
                output = e.get('output', '')
                
                if len(output) <= MAX_SINGLE:
                    # Include as-is - Claude 4.5 handles large contexts well
                    processed = output
                else:
                    # Truncate if exceeds limit (rare with 200KB threshold)
                    processed = output[:MAX_SINGLE] + f"\n\n[... truncated {len(output) - MAX_SINGLE} chars ...]"
                    console.print(f"[dim]  Evidence {i+1}: Truncated to {MAX_SINGLE} chars[/dim]")
            
            entry = f"Command: {cmd}\nOutput:\n{processed}"
            
            # Check if we'd exceed total budget
            if total_size + len(entry) > MAX_TOTAL:
                remaining = len(evidence) - len(evidence_parts)
                evidence_parts.append(f"\n[{remaining} more evidence items omitted to stay within token limits]")
                console.print(f"[yellow]⚠ Truncated {remaining} evidence items to stay under token limit[/yellow]")
                break
            
            evidence_parts.append(entry)
            total_size += len(entry)
        
        result = "\n\n".join(evidence_parts)
        console.print(f"[dim]Prepared evidence: {total_size} chars (~{total_size//4} tokens)[/dim]")
        return result
    
    def _evaluate_test_results(
        self,
        test: HypothesisTest,
        evidence: list[Evidence]
    ) -> dict[str, Any]:
        """Evaluate whether test results confirm, reject, or are inconclusive.
        
        Args:
            test: The hypothesis test
            evidence: Evidence collected
            
        Returns:
            Evaluation result
        """
        # Prepare evidence with intelligent truncation/summarization
        evidence_text = self._prepare_evidence_for_evaluation(evidence)
        
        # Truncate hypothesis strings to prevent bloat
        hypothesis = str(test.get('hypothesis', ''))[:1000]
        expected_confirmed = str(test.get('expected_confirmed', ''))[:500]
        expected_rejected = str(test.get('expected_rejected', ''))[:500]
        
        prompt = f"""Evaluate whether this evidence confirms or rejects the hypothesis.

HYPOTHESIS: {hypothesis}

EXPECTED IF CONFIRMED: {expected_confirmed}
EXPECTED IF REJECTED: {expected_rejected}

ACTUAL EVIDENCE:
{evidence_text}

Based on the actual output, determine:
1. Does the evidence CONFIRM the hypothesis? (matches expected_confirmed)
2. Does the evidence REJECT the hypothesis? (matches expected_rejected)
3. Is the evidence INCONCLUSIVE? (unclear or need more data)

Return JSON:
{{
    "result": "confirmed|rejected|inconclusive",
    "reasoning": "Detailed explanation of why you reached this conclusion",
    "key_findings": ["Finding 1", "Finding 2"]
}}

Be decisive - if evidence clearly points one way, don't say inconclusive."""
        
        # Use message format with explicit system/user split
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content="You are an expert at analyzing crash dump evidence. Return only JSON."),
            HumanMessage(content=prompt)
        ]
        
        response = get_llm(temperature=0.1).invoke(messages)
        return self._extract_json(response.content)
    
    def _plan_deep_dive(self, state: AnalysisState, confirmed_test: HypothesisTest) -> dict[str, Any]:
        """Plan deep investigation now that hypothesis is confirmed.
        
        Args:
            state: Current state
            confirmed_test: The confirmed hypothesis test
            
        Returns:
            Investigation plan
        """
        hypothesis = confirmed_test['hypothesis']
        # Build evidence text with limits to prevent token overflow
        MAX_EVIDENCE_ITEMS = 10
        evidence_list = confirmed_test.get('evidence', [])
        recent_evidence = evidence_list[-MAX_EVIDENCE_ITEMS:] if len(evidence_list) > MAX_EVIDENCE_ITEMS else evidence_list
        
        evidence_parts = []
        for e in recent_evidence:
            cmd = e.get('command', '')
            output = e.get('output', '')
            truncated = output[:200] if len(output) > 200 else output
            evidence_parts.append(f"{cmd}: {truncated}")
        
        if len(evidence_list) > MAX_EVIDENCE_ITEMS:
            evidence_parts.insert(0, f"[Last {MAX_EVIDENCE_ITEMS} of {len(evidence_list)} items]")
        evidence_text = "\n".join(evidence_parts)
        
        # Check if this matches a known pattern
        pattern_guidance = ""
        for pattern_name, pattern in KNOWN_PATTERNS.items():
            if any(keyword in hypothesis.lower() for keyword in pattern_name.split('_')):
                focus_areas = get_investigation_focus(pattern_name)
                pattern_guidance = f"\n\nEXPERT FOCUS AREAS for {pattern['name']}:\n"
                pattern_guidance += "\n".join(f"- {area}" for area in focus_areas)
                break
        
        prompt = f"""Hypothesis CONFIRMED: {hypothesis}

Evidence collected:
{evidence_text}
{pattern_guidance}

Now create a focused investigation plan to find the ROOT CAUSE.

Think like an expert - you know WHAT the problem is, now find exactly WHERE and WHY.

Return JSON:
{{
    "investigation_plan": [
        "Specific task 1 to find root cause",
        "Specific task 2 to identify source",
        "Specific task 3 to confirm fix approach"
    ],
    "reasoning": "Why these specific tasks will find the root cause"
}}

Keep it focused - 3-5 tasks maximum. Be surgical, not exploratory."""
        
        response = self.llm.invoke(prompt)
        plan_data = self._extract_json(response.content)
        
        console.print(f"\n[cyan]📋 Root Cause Investigation Plan:[/cyan]")
        for i, task in enumerate(plan_data['investigation_plan'], 1):
            console.print(f"  {i}. {task}")
        
        return {
            'investigation_plan': plan_data['investigation_plan'],
            'planner_reasoning': plan_data['reasoning'],
            'current_task_index': 0,
            'current_task': plan_data['investigation_plan'][0] if plan_data['investigation_plan'] else '',
            'hypothesis_status': 'confirmed'
        }
    
    def _form_alternative_hypothesis(self, state: AnalysisState, rejected_test: HypothesisTest) -> dict[str, Any]:
        """Form new hypothesis after previous one was rejected.
        
        Args:
            state: Current state
            rejected_test: The rejected hypothesis test
            
        Returns:
            New hypothesis
        """
        old_hypothesis = rejected_test['hypothesis']
        # Build evidence text with limits to prevent token overflow
        MAX_EVIDENCE_ITEMS = 10
        evidence_list = rejected_test.get('evidence', [])
        recent_evidence = evidence_list[-MAX_EVIDENCE_ITEMS:] if len(evidence_list) > MAX_EVIDENCE_ITEMS else evidence_list
        
        evidence_parts = []
        for e in recent_evidence:
            cmd = e.get('command', '')
            output = e.get('output', '')
            truncated = output[:200] if len(output) > 200 else output
            evidence_parts.append(f"{cmd}: {truncated}")
        
        if len(evidence_list) > MAX_EVIDENCE_ITEMS:
            evidence_parts.insert(0, f"[Last {MAX_EVIDENCE_ITEMS} of {len(evidence_list)} items]")
        evidence_text = "\n".join(evidence_parts)
        alternatives = state.get('alternative_hypotheses', [])
        
        prompt = f"""Previous hypothesis REJECTED: {old_hypothesis}

Evidence that rejected it:
{evidence_text}

Alternative hypotheses to consider:
{chr(10).join(f"- {alt}" for alt in alternatives)}

Based on the evidence, form a NEW hypothesis about the actual root cause.

Return JSON (same format as initial hypothesis):
{{
    "hypothesis": "New hypothesis based on evidence",
    "confidence": "high|medium|low",
    "reasoning": "Why this new hypothesis fits the evidence better",
    "test_commands": ["command1", "command2"],
    "expected_if_confirmed": "What output would confirm",
    "expected_if_rejected": "What output would reject",
    "alternative_hypotheses": ["Backup explanation 1", "Backup explanation 2"]
}}

COMMAND GUIDELINES:
- ALWAYS prefer traditional SOS/WinDbg commands: !threads, !threadpool, !dumpheap, !clrstack, !syncblk
- AVOID dx commands - they frequently fail and have complex syntax
- Only use dx if traditional commands cannot achieve the goal

Learn from the rejected hypothesis - what did the evidence actually show?"""
        
        response = self.llm.invoke(prompt)
        new_hypothesis = self._extract_json(response.content)
        
        console.print(f"\n[yellow]🔄 New Hypothesis:[/yellow] {new_hypothesis['hypothesis']}")
        
        # Add new test to the list
        new_test: HypothesisTest = {
            'hypothesis': new_hypothesis['hypothesis'],
            'test_commands': new_hypothesis['test_commands'],
            'expected_confirmed': new_hypothesis['expected_if_confirmed'],
            'expected_rejected': new_hypothesis['expected_if_rejected'],
            'result': None,
            'evidence': []
        }
        
        state['hypothesis_tests'].append(new_test)
        
        return {
            'current_hypothesis': new_hypothesis['hypothesis'],
            'hypothesis_confidence': new_hypothesis['confidence'],
            'hypothesis_reasoning': new_hypothesis['reasoning'],
            'hypothesis_tests': state['hypothesis_tests'],
            'alternative_hypotheses': new_hypothesis.get('alternative_hypotheses', []),
            'hypothesis_status': 'testing'
        }
    
    def _gather_more_evidence(self, state: AnalysisState, inconclusive_test: HypothesisTest) -> dict[str, Any]:
        """Gather additional evidence when results are inconclusive.
        
        Args:
            state: Current state
            inconclusive_test: The inconclusive test
            
        Returns:
            Additional commands to run
        """
        # Track how many times this test has been inconclusive
        inconclusive_count = inconclusive_test.get('inconclusive_count', 0) + 1
        inconclusive_test['inconclusive_count'] = inconclusive_count
        
        # After 2 inconclusive attempts, give up and try alternative hypothesis
        if inconclusive_count >= 2:
            console.print("[yellow]⚠ Too many inconclusive results, treating as REJECTED[/yellow]")
            inconclusive_test['result'] = 'rejected'
            inconclusive_test['evaluation_reasoning'] = f"After {inconclusive_count} attempts, evidence remains inconclusive. Moving to alternative hypothesis."
            return {
                'hypothesis_status': 'rejected',
                'hypothesis_tests': state['hypothesis_tests']
            }
        
        hypothesis = inconclusive_test['hypothesis']
        # Build evidence text with limits to prevent token overflow
        MAX_EVIDENCE_ITEMS = 10
        evidence_list = inconclusive_test.get('evidence', [])
        recent_evidence = evidence_list[-MAX_EVIDENCE_ITEMS:] if len(evidence_list) > MAX_EVIDENCE_ITEMS else evidence_list
        
        # Identify failed commands
        failed_commands = []
        evidence_parts = []
        for e in recent_evidence:
            cmd = e.get('command', '')
            output = e.get('output', '')
            truncated = output[:200] if len(output) > 200 else output
            evidence_parts.append(f"{cmd}: {truncated}")
            
            # Track failures
            if e.get('failed') or 'Error:' in output or 'Unable to bind' in output:
                failed_commands.append(cmd)
        
        if len(evidence_list) > MAX_EVIDENCE_ITEMS:
            evidence_parts.insert(0, f"[Last {MAX_EVIDENCE_ITEMS} of {len(evidence_list)} items]")
        evidence_text = "\n".join(evidence_parts)
        
        # Build context about failures
        failure_context = ""
        if failed_commands:
            failure_context = f"\n\nFAILED COMMANDS (DO NOT REPEAT THESE):\n"
            for cmd in failed_commands:
                failure_context += f"❌ {cmd}\n"
            failure_context += "\nREASON: Data model (dx) commands are failing. Use traditional SOS commands instead.\n"
            failure_context += "ALTERNATIVES: !dumpheap -stat, !do <address>, !gcroot, !threadpool, ~*e !clrstack\n"
        
        supports_dx = state.get('supports_dx', False)
        
        prompt = f"""Hypothesis: {hypothesis}

Evidence collected so far is INCONCLUSIVE:
{evidence_text}
{failure_context}

What alternative commands should we run to clarify?

IMPORTANT:
- DO NOT repeat any failed commands
- If 'dx' commands failed, use traditional SOS commands like !dumpheap, !do, !gcroot
- Focus on different diagnostic approaches
- Attempt #{inconclusive_count}/2 - make it count!

Return JSON:
{{
    "additional_commands": ["command1", "command2"],
    "reasoning": "Why these commands will clarify the situation"
}}

Maximum 2 additional commands. Be targeted and use commands that will definitely work."""
        
        response = self.llm.invoke(prompt)
        data = self._extract_json(response.content)
        
        # REPLACE the test_commands instead of extending (so we don't re-run failed ones)
        inconclusive_test['test_commands'] = data['additional_commands']
        inconclusive_test['result'] = None  # Reset to test again
        
        console.print(f"[cyan]🔍 Gathering more evidence (attempt {inconclusive_count}/2):[/cyan] {', '.join(data['additional_commands'])}")
        
        return {
            'hypothesis_tests': state['hypothesis_tests']
        }
    
    def _extract_json(self, content: str) -> dict[str, Any]:
        """Extract JSON from LLM response with robust parsing."""
        content = content.strip()
        
        # Method 1: Remove markdown code blocks
        if content.startswith('```'):
            parts = content.split('```')
            if len(parts) >= 2:
                content = parts[1]
                if content.startswith('json'):
                    content = content[4:]
                content = content.strip()
        
        # Method 2: Try direct parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        
        # Method 3: Find JSON object with balanced braces
        import re
        
        # Find all potential JSON starts
        brace_positions = [i for i, c in enumerate(content) if c == '{']
        
        for start_pos in brace_positions:
            # Count braces to find matching closing brace
            depth = 0
            for i in range(start_pos, len(content)):
                if content[i] == '{':
                    depth += 1
                elif content[i] == '}':
                    depth -= 1
                    if depth == 0:
                        # Found complete JSON object
                        json_str = content[start_pos:i+1]
                        try:
                            return json.loads(json_str)
                        except json.JSONDecodeError:
                            continue  # Try next position
        
        # Method 4: Last resort - try to extract from first { to last }
        first_brace = content.find('{')
        last_brace = content.rfind('}')
        if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
            json_str = content[first_brace:last_brace+1]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass
        
        # Failed all methods
        console.print(f"[red]Failed to extract JSON from response[/red]")
        console.print(f"[dim]Content preview: {content[:500]}...[/dim]")
        raise ValueError(f"Could not parse JSON from LLM response. Response started with: {content[:100]}")
