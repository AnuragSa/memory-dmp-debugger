"""Interactive chat agent for follow-up questions after analysis."""

import json
from datetime import datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from rich.console import Console

from dump_debugger.config import settings
from dump_debugger.core import DebuggerWrapper
from dump_debugger.llm import get_llm
from dump_debugger.state import AnalysisState, ChatMessage, Evidence
from dump_debugger.utils import detect_placeholders, resolve_command_placeholders

console = Console()


class InteractiveChatAgent:
    """Agent that answers user questions about the dump interactively.
    
    This agent:
    1. Receives user questions about the analyzed dump
    2. Checks if existing evidence can answer the question
    3. Executes new debugger commands if needed
    4. Formulates clear, citation-backed answers
    """
    
    def __init__(self, debugger: DebuggerWrapper):
        self.debugger = debugger
        self.llm = get_llm(temperature=0.2)
        
        # Initialize evidence retriever if session available
        self.evidence_retriever = None
        if debugger.evidence_store:
            from dump_debugger.evidence import EvidenceRetriever
            
            # Use embeddings client from debugger (already configured for Azure or OpenAI)
            embeddings_client = debugger.embeddings_client
            
            self.evidence_retriever = EvidenceRetriever(
                evidence_store=debugger.evidence_store,
                llm=self.llm,
                embeddings_client=embeddings_client
            )
    
    def answer_question(self, state: AnalysisState, user_question: str) -> dict[str, Any]:
        """Answer a user question using existing evidence or new investigation.
        
        This is the main 3-step process:
        1. Build context from existing evidence
        2. Check if we have enough information
        3. Execute new commands if needed, then answer
        
        Args:
            state: Current analysis state
            user_question: The user's question
            
        Returns:
            Updated state with new chat message
        """
        # Validate input
        if not user_question or not user_question.strip():
            console.print("[yellow]⚠ Empty question provided[/yellow]")
            return {'chat_history': state.get('chat_history', [])}  # Return current state, no changes
        
        console.print(f"\n[cyan]❓ Question:[/cyan] {user_question}")
        
        # Iterative investigation loop - keep investigating until we can answer
        max_iterations = 3
        all_commands_executed = []
        all_new_evidence = []
        
        for iteration in range(max_iterations):
            # Step 1: Build context from existing evidence
            context = self._build_context_for_question(state, user_question)
            
            # Add previously gathered evidence to context
            if all_new_evidence:
                context['relevant_evidence'].extend(all_new_evidence)
            
            # Step 2: Check if current evidence is sufficient
            needs_investigation, reasoning = self._check_existing_evidence(
                user_question, context, state
            )
            
            if not needs_investigation:
                console.print(f"[green]✓ Sufficient evidence after {iteration} iteration(s): {reasoning}[/green]")
                break
            
            # Step 3: Execute investigative commands
            console.print(f"[yellow]🔍 Investigation round {iteration + 1}/{max_iterations}: {reasoning}[/yellow]")
            commands_executed, new_evidence = self._execute_investigative_commands(
                user_question, context, state
            )
            
            all_commands_executed.extend(commands_executed)
            all_new_evidence.extend(new_evidence)
            
            # If no new evidence was gathered, stop iterating
            if not new_evidence:
                console.print("[yellow]⚠ No new evidence gathered, stopping investigation[/yellow]")
                break
        
        # Step 4: Formulate the answer with all gathered evidence
        answer = self._formulate_answer(
            user_question, context, all_new_evidence, state
        )
        
        commands_executed = all_commands_executed
        new_evidence = all_new_evidence
        
        # Create chat message
        timestamp = datetime.now().isoformat()
        evidence_refs = [e['command'] for e in context['relevant_evidence']]
        if new_evidence:
            evidence_refs.extend([e['command'] for e in new_evidence])
        
        user_msg: ChatMessage = {
            'role': 'user',
            'content': user_question,
            'timestamp': timestamp,
            'commands_executed': [],
            'evidence_used': []
        }
        
        assistant_msg: ChatMessage = {
            'role': 'assistant',
            'content': answer,
            'timestamp': timestamp,
            'commands_executed': commands_executed,
            'evidence_used': evidence_refs
        }
        
        # Update chat history
        chat_history = state.get('chat_history', [])
        chat_history.append(user_msg)
        chat_history.append(assistant_msg)
        
        # Trim if exceeds max
        if len(chat_history) > settings.max_chat_messages:
            chat_history = chat_history[-settings.max_chat_messages:]
        
        console.print(f"\n[bold green]💬 Answer:[/bold green]")
        console.print(answer)
        
        return {
            'chat_history': chat_history
        }
    
    def _build_context_for_question(
        self, state: AnalysisState, question: str
    ) -> dict[str, Any]:
        """Build tiered context from existing evidence.
        
        Loads evidence in priority order:
        1. Final report (if available)
        2. Conclusions and reasoning
        3. Recent hypothesis tests
        4. Evidence inventory (with semantic search if available)
        
        Args:
            state: Current analysis state
            question: User's question
            
        Returns:
            Context dictionary with relevant information
        """
        context = {
            'question': question,
            'issue_description': state.get('issue_description', ''),
            'dump_type': state.get('dump_type', 'user'),
            'final_report': state.get('final_report'),
            'conclusions': state.get('conclusions', []),
            'reasoner_analysis': state.get('reasoner_analysis', ''),
            'hypothesis_tests': state.get('hypothesis_tests', []),
            'evidence_inventory': state.get('evidence_inventory', {}),
            'relevant_evidence': []
        }
        
        # Collect all evidence from hypothesis tests
        all_evidence = []
        for test in context['hypothesis_tests']:
            all_evidence.extend(test.get('evidence', []))
        
        # Add evidence from inventory
        for task, evidence_list in context['evidence_inventory'].items():
            all_evidence.extend(evidence_list)
        
        # Use semantic search if available, otherwise keyword matching
        if self.evidence_retriever:
            console.print("[dim]Using semantic search for evidence...[/dim]")
            use_embeddings = settings.use_embeddings and self.evidence_retriever.embeddings_client is not None
            relevant = self.evidence_retriever.find_relevant_evidence(
                question=question,
                evidence_inventory=context['evidence_inventory'],
                top_k=10,
                use_embeddings=use_embeddings
            )
            context['relevant_evidence'] = relevant
        else:
            # Fallback to simple keyword matching
            question_lower = question.lower()
            scored_evidence = []
            for evidence in all_evidence:
                score = 0
                evidence_text = f"{evidence.get('command', '')} {evidence.get('finding', '')}".lower()
                
                # Count keyword matches
                keywords = question_lower.split()
                for keyword in keywords:
                    if len(keyword) > 3:  # Skip short words
                        score += evidence_text.count(keyword)
                
                if score > 0:
                    scored_evidence.append((score, evidence))
            
            # Sort by score and take top 10
            scored_evidence.sort(reverse=True, key=lambda x: x[0])
            context['relevant_evidence'] = [e for _, e in scored_evidence[:10]]
        
        return context
    
    def _check_existing_evidence(
        self, question: str, context: dict[str, Any], state: AnalysisState
    ) -> tuple[bool, str]:
        """Use LLM to determine if existing evidence can answer the question.
        
        Args:
            question: User's question
            context: Built context with existing evidence
            state: Current analysis state
            
        Returns:
            Tuple of (needs_investigation, reasoning)
        """
        # Build evidence summary
        evidence_summary = "# Existing Evidence\n\n"
        
        if context['final_report']:
            evidence_summary += "## Final Report\n"
            evidence_summary += context['final_report'][:20000] + "\n\n"
        
        if context['conclusions']:
            evidence_summary += "## Key Conclusions\n"
            for conclusion in context['conclusions']:
                evidence_summary += f"- {conclusion}\n"
            evidence_summary += "\n"
        
        if context['relevant_evidence']:
            evidence_summary += "## Relevant Evidence from Investigation\n"
            for i, evidence in enumerate(context['relevant_evidence'][:10], 1):  # Increased from 5 to 10
                evidence_summary += f"\n{i}. Command: {evidence.get('command', 'N/A')}\n"
                
                # Prefer analyzer summary if available (regardless of evidence type)
                if evidence.get('summary'):
                    evidence_summary += f"   Summary: {evidence['summary'][:2000]}\n"
                elif evidence.get('output'):
                    # Fallback to raw output if no summary available
                    output_preview = evidence['output'][:2000]
                    evidence_summary += f"   Output: {output_preview}\n"
                
                # Also show finding if it's not generic
                finding = evidence.get('finding', '')
                if finding and not finding.startswith('Data for:'):
                    evidence_summary += f"   Finding: {finding[:1000]}\n"
        
        prompt = f"""You are analyzing a Windows memory dump. A user has asked a follow-up question.

USER'S ORIGINAL ISSUE: {context['issue_description']}

USER'S QUESTION: {question}

{evidence_summary}

TASK: Determine if we have enough information to answer the user's question.

Consider:
1. Does the existing evidence directly address the question?
2. Can we infer the answer from what we know?
3. Or do we need to run new debugger commands to get more data?

Respond in JSON format:
{{
    "has_sufficient_evidence": true/false,
    "reasoning": "Brief explanation of why we do or don't have enough information",
    "suggested_commands": ["command1", "command2"] // Only if more investigation needed
}}

CRITICAL - If suggesting commands:
- Use ONLY pure WinDbg commands - NO PowerShell syntax
- FORBIDDEN: Pipes (|), foreach, findstr, grep, Where-Object, Select-Object, $_
- VALID: '!threads', '~*e !clrstack', '!dumpheap -stat', '!syncblk'"""

        messages = [
            SystemMessage(content="You are an expert Windows crash dump analyst."),
            HumanMessage(content=prompt)
        ]
        
        response = self.llm.invoke(messages)
        result = self._extract_json(response.content)
        
        if result:
            needs_investigation = not result.get('has_sufficient_evidence', False)
            reasoning = result.get('reasoning', 'Need more data')
            
            # Store suggested commands for later use
            self._suggested_commands = result.get('suggested_commands', [])
            
            return needs_investigation, reasoning
        
        # Fallback: assume we need to investigate
        return True, "Unable to determine if evidence is sufficient"
    
    def _execute_investigative_commands(
        self, question: str, context: dict[str, Any], state: AnalysisState
    ) -> tuple[list[str], list[Evidence]]:
        """Execute debugger commands to gather information for the question.
        
        Args:
            question: User's question
            context: Built context
            state: Current analysis state
            
        Returns:
            Tuple of (commands_executed, new_evidence)
        """
        # Get suggested commands from previous step
        suggested_commands = getattr(self, '_suggested_commands', [])
        
        if not suggested_commands:
            # Fallback: ask LLM for commands
            console.print("[yellow]Determining what commands to run...[/yellow]")
            suggested_commands = self._generate_investigative_commands(question, context, state)
        
        commands_executed = []
        new_evidence = []
        
        # Dynamic limit based on context window capacity (Claude 4.5 can handle ~800KB)
        max_commands_per_iteration = 15  # Increased from 5
        max_total_evidence_size = 600000  # 600KB total evidence limit
        total_evidence_size = 0
        
        console.print(f"[cyan]Executing up to {min(len(suggested_commands), max_commands_per_iteration)} investigative command(s)...[/cyan]")
        
        # Build previous evidence list for placeholder resolution
        previous_evidence = []
        
        # Add evidence from context
        if context.get('relevant_evidence'):
            previous_evidence.extend(context['relevant_evidence'])
        
        # Add newly gathered evidence from current iteration
        previous_evidence.extend(new_evidence)
        
        for command in suggested_commands[:max_commands_per_iteration]:
            # Validate command syntax - reject PowerShell constructs
            invalid_syntax = ['| foreach', '| findstr', '| grep', '| where', '| select', '$_']
            if any(invalid in command.lower() for invalid in invalid_syntax):
                console.print(f"  [red]✗ Invalid command syntax - contains PowerShell operators[/red]")
                console.print(f"  [yellow]Skipping: {command}[/yellow]")
                console.print(f"  [dim]Use pure WinDbg commands only (no pipes, foreach, findstr, etc.)[/dim]")
                continue
            
            # Check for placeholders and try to resolve them
            if detect_placeholders(command):
                console.print(f"  [yellow]⚠ Detected placeholders in:[/yellow] {command}")
                resolved_command, success, message = resolve_command_placeholders(command, previous_evidence)
                
                if success:
                    console.print(f"  [green]✓ Resolved to:[/green] {resolved_command}")
                    command = resolved_command
                else:
                    console.print(f"  [red]✗ {message}[/red]")
                    console.print(f"  [yellow]⚠ Skipping command with unresolved placeholders[/yellow]")
                    continue
            
            console.print(f"  [dim]Running:[/dim] {command}")
            
            # Use execute_command_with_analysis to get summaries for large outputs
            result = self.debugger.execute_command_with_analysis(
                command=command,
                intent=f"Investigating: {question}"
            )
            commands_executed.append(command)
            
            if result['success'] and result['output']:
                # For evidence size tracking, use the output size (might be summary for large outputs)
                evidence_type = result.get('evidence_type', 'inline')
                output_for_evidence = result['output']  # Already summary for external evidence
                
                # Track evidence size based on what we're actually storing
                total_evidence_size += len(output_for_evidence)
                
                # Create evidence entry - includes metadata for external evidence
                evidence: Evidence = {
                    'command': command,
                    'output': output_for_evidence,
                    'finding': f"Data for: {question}",
                    'significance': 'medium',
                    'confidence': 'medium',
                    'evidence_type': evidence_type,
                    'evidence_id': result.get('evidence_id'),
                    'summary': result.get('analysis', {}).get('summary') if result.get('analysis') else None
                }
                new_evidence.append(evidence)
                
                # Add to previous_evidence for next placeholder resolution
                previous_evidence.append(evidence)
                
                # Show truncated output
                output_preview = result['output'][:200] + "..." if len(result['output']) > 200 else result['output']
                
                # Show cache status
                if result.get('cached'):
                    console.print(f"  [green]✓ (cached)[/green] {output_preview}")
                else:
                    console.print(f"  [green]✓[/green] {output_preview}")
                
                # Stop if we've gathered enough evidence
                if total_evidence_size > max_total_evidence_size:
                    remaining = len(suggested_commands) - len(commands_executed)
                    if remaining > 0:
                        console.print(f"[yellow]⚠ Evidence limit reached ({total_evidence_size} bytes), skipping {remaining} remaining commands[/yellow]")
                    break
            else:
                # Command failed - show error message
                if result.get('cached'):
                    console.print(f"  [yellow]⚠ Cached result was empty or failed[/yellow]")
                else:
                    error_msg = result.get('error', 'Unknown error')
                    console.print(f"  [red]✗ Error:[/red] {error_msg}")
        
        return commands_executed, new_evidence
    
    def _generate_investigative_commands(
        self, question: str, context: dict[str, Any], state: AnalysisState
    ) -> list[str]:
        """Generate debugger commands to answer the question.
        
        Args:
            question: User's question
            context: Built context
            state: Current analysis state
            
        Returns:
            List of debugger commands to execute
        """
        dump_type = state.get('dump_type', 'user')
        
        prompt = f"""You are a Windows debugger expert. Generate WinDbg/CDB commands to answer this question.

DUMP TYPE: {dump_type}
ORIGINAL ISSUE: {context['issue_description']}
USER QUESTION: {question}

AVAILABLE COMMANDS:
- For .NET/managed code: !threads, !clrstack, !dumpheap, !gcroot, !finalizequeue, !syncblk, !threadpool
- For native code: k, ~*k, !analyze -v, dt, dv, !locks, !handle
- For general info: lm, !process, !peb, .lastevent

Generate 1-5 specific commands that will help answer the question.

CRITICAL COMMAND SYNTAX RULES:
- Use ONLY pure WinDbg/CDB commands - NEVER PowerShell syntax
- FORBIDDEN: Pipes (|), foreach, findstr, grep, Where-Object, Select-Object, $_, any PowerShell operators
- INVALID EXAMPLES: '~*e !clrstack | findstr Thread', '!dumpheap | foreach', '!threads | grep'
- VALID EXAMPLES: '!threads', '~*e !clrstack', '!dumpheap -stat', '!syncblk', '!do <address>'
- For filtering: Use WinDbg native commands only (e.g., ~*e applies to all threads)
- For batch: Suggest single representative commands, not loops

Respond in JSON format:
{{
    "commands": ["command1", "command2", ...],
    "reasoning": "Why these commands will help"
}}"""

        messages = [
            SystemMessage(content="You are an expert Windows crash dump analyst."),
            HumanMessage(content=prompt)
        ]
        
        response = self.llm.invoke(messages)
        result = self._extract_json(response.content)
        
        if result and 'commands' in result:
            console.print(f"[dim]Strategy: {result.get('reasoning', 'N/A')}[/dim]")
            return result['commands']
        
        # Fallback to basic commands
        return ['!analyze -v']
    
    def _formulate_answer(
        self, 
        question: str, 
        context: dict[str, Any], 
        new_evidence: list[Evidence],
        state: AnalysisState
    ) -> str:
        """Generate a clear, citation-backed answer to the user's question.
        
        Args:
            question: User's question
            context: Built context
            new_evidence: Newly gathered evidence
            state: Current analysis state
            
        Returns:
            Formatted answer with citations
        """
        # Build comprehensive evidence section
        evidence_text = "# Available Evidence\n\n"
        
        if context['final_report']:
            evidence_text += "## Analysis Report Summary\n"
            evidence_text += context['final_report'][:20000] + "\n\n"
        
        if context['conclusions']:
            evidence_text += "## Key Findings\n"
            for conclusion in context['conclusions']:
                evidence_text += f"- {conclusion}\n"
            evidence_text += "\n"
        
        if context['relevant_evidence']:
            evidence_text += "## Relevant Evidence from Prior Investigation\n"
            for i, evidence in enumerate(context['relevant_evidence'][:5], 1):
                evidence_text += f"\n{i}. `{evidence.get('command', 'N/A')}`\n"
                finding = evidence.get('finding', '')
                if finding:
                    evidence_text += f"   {finding[:2000]}\n"
        
        if new_evidence:
            evidence_text += "\n## New Investigation Results\n"
            for i, evidence in enumerate(new_evidence, 1):
                evidence_text += f"\n{i}. `{evidence['command']}`\n"
                
                # Check if this is external evidence with analysis or inline evidence
                if evidence.get('evidence_type') == 'external' and evidence.get('summary'):
                    # Use analyzed summary for large outputs (already captures key findings)
                    evidence_text += f"   Analysis: {evidence['summary']}\n"
                else:
                    # Use truncated output for inline evidence
                    output_preview = evidence['output'][:5000]
                    evidence_text += f"   Output: {output_preview}\n"
        
        prompt = f"""You are answering a user's question about a Windows memory dump analysis.

ORIGINAL ISSUE: {context['issue_description']}

USER'S QUESTION: {question}

{evidence_text}

TASK: Provide a clear, concise answer to the user's question based on the evidence above.

GUIDELINES:
1. Be direct and specific - answer the question with the available evidence
2. Reference specific commands/evidence when making claims (e.g., "According to !threads output...")
3. DO NOT suggest manual debugger commands for the user to run - if evidence is insufficient, state what's missing
4. DO NOT provide "Recommended Investigation Steps" - that's the system's job, not yours
5. Use technical terms appropriately but explain complex concepts
6. Format your answer in markdown
7. Keep it concise (3-5 paragraphs max unless more detail is warranted)
8. Focus on answering the question, not on what additional investigation could be done

Provide your answer now:"""

        messages = [
            SystemMessage(content="You are an expert Windows crash dump analyst helping a user understand their dump."),
            HumanMessage(content=prompt)
        ]
        
        response = self.llm.invoke(messages)
        return response.content.strip()
    
    def _extract_json(self, text: str) -> dict[str, Any] | None:
        """Extract JSON from LLM response that may have text before/after.
        
        Uses balanced brace counting to find valid JSON blocks.
        
        Args:
            text: Text that may contain JSON
            
        Returns:
            Parsed JSON dict or None if parsing fails
        """
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # Find JSON block using balanced brace counting
        brace_count = 0
        start_idx = -1
        
        for i, char in enumerate(text):
            if char == '{':
                if brace_count == 0:
                    start_idx = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start_idx != -1:
                    # Found complete JSON block
                    try:
                        json_str = text[start_idx:i+1]
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        continue
        
        return None
