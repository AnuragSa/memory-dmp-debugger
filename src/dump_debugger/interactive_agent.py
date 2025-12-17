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
        console.print(f"\n[cyan]❓ Question:[/cyan] {user_question}")
        
        # Step 1: Build context from existing evidence
        context = self._build_context_for_question(state, user_question)
        
        # Step 2: Check if existing evidence is sufficient
        needs_investigation, reasoning = self._check_existing_evidence(
            user_question, context, state
        )
        
        # Step 3: Execute investigative commands if needed
        commands_executed = []
        new_evidence = []
        
        if needs_investigation:
            console.print(f"[yellow]🔍 Need more data: {reasoning}[/yellow]")
            commands_executed, new_evidence = self._execute_investigative_commands(
                user_question, context, state
            )
        else:
            console.print(f"[green]✓ Sufficient evidence: {reasoning}[/green]")
        
        # Step 4: Formulate the answer
        answer = self._formulate_answer(
            user_question, context, new_evidence, state
        )
        
        # Create chat message
        timestamp = datetime.now().isoformat()
        evidence_refs = [e['command'] for e in context['relevant_evidence']]
        if new_evidence:
            evidence_refs.extend([e.command for e in new_evidence])
        
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
        4. Evidence inventory
        
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
        
        # Extract most relevant evidence using semantic matching
        # For now, use simple keyword matching - can be enhanced with embeddings
        question_lower = question.lower()
        
        # Collect all evidence from hypothesis tests
        all_evidence = []
        for test in context['hypothesis_tests']:
            all_evidence.extend(test.get('evidence', []))
        
        # Add evidence from inventory
        for task, evidence_list in context['evidence_inventory'].items():
            all_evidence.extend(evidence_list)
        
        # Score evidence by relevance (simple keyword matching)
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
            evidence_summary += context['final_report'][:2000] + "\n\n"
        
        if context['conclusions']:
            evidence_summary += "## Key Conclusions\n"
            for conclusion in context['conclusions']:
                evidence_summary += f"- {conclusion}\n"
            evidence_summary += "\n"
        
        if context['relevant_evidence']:
            evidence_summary += "## Relevant Evidence from Investigation\n"
            for i, evidence in enumerate(context['relevant_evidence'][:5], 1):
                evidence_summary += f"\n{i}. Command: {evidence.get('command', 'N/A')}\n"
                finding = evidence.get('finding', '')
                if finding:
                    evidence_summary += f"   Finding: {finding[:300]}\n"
        
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
}}"""

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
        
        console.print(f"[cyan]Executing {len(suggested_commands)} investigative command(s)...[/cyan]")
        
        for command in suggested_commands[:5]:  # Limit to 5 commands
            console.print(f"  [dim]Running:[/dim] {command}")
            
            success, output, error = self.debugger.execute_command(command)
            commands_executed.append(command)
            
            if success and output:
                # Create evidence entry
                evidence: Evidence = {
                    'command': command,
                    'output': output,
                    'finding': f"Data for: {question}",
                    'significance': 'medium',
                    'confidence': 'medium'
                }
                new_evidence.append(evidence)
                
                # Show truncated output
                output_preview = output[:200] + "..." if len(output) > 200 else output
                console.print(f"  [green]✓[/green] {output_preview}")
            else:
                console.print(f"  [red]✗ Error:[/red] {error}")
        
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
            evidence_text += context['final_report'][:1500] + "\n\n"
        
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
                    evidence_text += f"   {finding[:400]}\n"
        
        if new_evidence:
            evidence_text += "\n## New Investigation Results\n"
            for i, evidence in enumerate(new_evidence, 1):
                evidence_text += f"\n{i}. `{evidence['command']}`\n"
                output_preview = evidence['output'][:500]
                evidence_text += f"   Output: {output_preview}\n"
        
        prompt = f"""You are answering a user's question about a Windows memory dump analysis.

ORIGINAL ISSUE: {context['issue_description']}

USER'S QUESTION: {question}

{evidence_text}

TASK: Provide a clear, concise answer to the user's question based on the evidence above.

GUIDELINES:
1. Be direct and specific
2. Reference specific commands/evidence when making claims (e.g., "According to !threads output...")
3. If the evidence doesn't fully answer the question, be honest about limitations
4. Use technical terms appropriately but explain complex concepts
5. Format your answer in markdown
6. Keep it concise (3-5 paragraphs max unless more detail is warranted)

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
