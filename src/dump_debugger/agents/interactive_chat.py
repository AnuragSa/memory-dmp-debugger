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
from dump_debugger.utils.command_healer import CommandHealer

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
        self.healer = CommandHealer()
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
        attempted_commands = set()  # Track all commands we've tried to prevent duplicates
        
        for iteration in range(max_iterations):
            # Step 1: Build context from existing evidence
            context = self._build_context_for_question(state, user_question)
            
            # Add previously gathered evidence to context
            if all_new_evidence:
                context['relevant_evidence'].extend(all_new_evidence)
            
            # Add attempted commands to context so LLM knows what we've tried
            context['attempted_commands'] = list(attempted_commands)
            
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
                user_question, context, state, attempted_commands
            )
            
            all_commands_executed.extend(commands_executed)
            all_new_evidence.extend(new_evidence)
            
            # If no new evidence was gathered OR we're re-running same commands, stop
            if not new_evidence:
                console.print("[yellow]⚠ No new evidence gathered, stopping investigation[/yellow]")
                break
            
            # Check if we're stuck (same commands being suggested repeatedly)
            if iteration > 0 and len(set(commands_executed) & set(all_commands_executed[:-len(commands_executed)])) > 0:
                console.print("[yellow]⚠ Detected command repetition, stopping to avoid loop[/yellow]")
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
        
        # Add information about already attempted commands
        attempted_commands = context.get('attempted_commands', [])
        if attempted_commands:
            evidence_summary += "\n## Commands Already Executed\n"
            evidence_summary += "The following commands have already been run (do NOT suggest these again):\n"
            for cmd in attempted_commands:
                evidence_summary += f"- {cmd}\n"
            evidence_summary += "\n"
        
        prompt = f"""You are analyzing a Windows memory dump. A user has asked a follow-up question.

USER'S ORIGINAL ISSUE: {context['issue_description']}

USER'S QUESTION: {question}

{evidence_summary}

TASK: Determine if we have enough information to answer the user's question OBJECTIVELY based on evidence.

CRITICAL THINKING REQUIREMENTS:
1. Check if existing evidence CONTRADICTS the user's claim or question premise
2. If the user states something that conflicts with evidence (e.g., "CPU was 20%" but !runaway shows high CPU time), you MUST flag this as needing investigation
3. Do NOT assume the user's statement is correct - validate it against actual data
4. Look for objective measurements (CPU time, thread counts, memory sizes) that can prove or disprove claims
5. If evidence conflicts with the user's assumption, set has_sufficient_evidence=false and suggest commands to clarify

Analysis Steps:
1. What does the existing evidence objectively show?
2. Does the user's question contain an assumption or claim that needs validation?
3. Does existing evidence support, contradict, or remain silent on the user's claim?
4. If contradiction exists, we need MORE investigation to explain the discrepancy

Respond in JSON format:
{{
    "has_sufficient_evidence": true/false,
    "reasoning": "Brief explanation - mention any contradictions with user's assumptions",
    "suggested_commands": ["command1", "command2"] // Only if more investigation needed or contradiction found
}}

CRITICAL - If suggesting commands:
- Use ONLY pure WinDbg commands - NO PowerShell syntax
- FORBIDDEN: Pipes (|), foreach, findstr, grep, Where-Object, Select-Object, $_
- THREAD-SPECIFIC: Combine thread switch with command (e.g., '~8e !clrstack', NOT '~8s' then '!clrstack')
- VALID: '~8e !clrstack', '~*e !clrstack', '~10e !dso', '!dumpheap -stat', '!syncblk'"""

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
        self, question: str, context: dict[str, Any], state: AnalysisState, attempted_commands: set
    ) -> tuple[list[str], list[Evidence]]:
        """Execute debugger commands to gather information for the question.
        
        Args:
            question: User's question
            context: Built context
            state: Current analysis state
            attempted_commands: Set of commands already attempted (to avoid duplicates)
            
        Returns:
            Tuple of (commands_executed, new_evidence)
        """
        # Reset to default thread context for clean investigation
        # This ensures commands run in a neutral context unless the question is thread-specific
        if not any(keyword in question.lower() for keyword in ['thread', 'stack', 'specific thread']):
            console.print("[dim]Resetting to thread 0 for clean investigation...[/dim]")
            try:
                reset_result = self.debugger.execute_command("~0s", timeout=5)
                if reset_result.get('success'):
                    console.print("[dim green]✓ Reset to thread 0[/dim green]")
            except Exception as e:
                console.print(f"[dim yellow]⚠ Could not reset thread context: {e}[/dim yellow]")
        
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
            # Skip if we've already attempted this exact command
            if command in attempted_commands:
                console.print(f"  [dim yellow]⊘ Skipping already attempted:[/dim yellow] {command}")
                # Note: Evidence from previous execution is already in context['relevant_evidence']
                # and will be available for analysis
                continue
            
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
            
            # Execute with automatic healing
            result = self._execute_with_healing(
                command=command,
                question=question,
                context={
                    'previous_evidence': previous_evidence
                }
            )
            commands_executed.append(command)
            
            # Mark this command as attempted to prevent duplicates
            attempted_commands.add(command)
            
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
                    'summary': result.get('analysis', {}).get('summary') if result.get('analysis') else None,
                    'structured_data': result.get('analysis', {}).get('structured_data') if result.get('analysis') else {}
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
        """Generate debugger commands to answer the question with progressive object graph traversal.
        
        Args:
            question: User's question
            context: Built context
            state: Current analysis state
            
        Returns:
            List of debugger commands to execute
        """
        dump_type = state.get('dump_type', 'user')
        
        # Build evidence context showing what we've already collected
        evidence_context = ""
        attempted_commands = context.get('attempted_commands', [])
        if attempted_commands:
            evidence_context += "\n\nCOMMANDS ALREADY EXECUTED (do not repeat these):\n"
            for cmd in attempted_commands:
                evidence_context += f"- {cmd}\n"
        
        # Show evidence we've collected to help with progressive traversal
        relevant_evidence = context.get('relevant_evidence', [])
        if relevant_evidence:
            evidence_context += "\n\nEVIDENCE COLLECTED SO FAR:\n"
            for i, evidence in enumerate(relevant_evidence[-5:], 1):  # Last 5 pieces of evidence
                cmd = evidence.get('command', 'N/A')
                evidence_context += f"{i}. Command: {cmd}\n"
                
                # Show key information that might contain addresses or references to follow
                summary = evidence.get('summary', '')
                output = evidence.get('output', '')
                
                if summary:
                    evidence_context += f"   Summary: {summary[:500]}\n"
                elif output:
                    evidence_context += f"   Output preview: {output[:500]}\n"
                
                # Highlight any object addresses or method tables found
                import re
                addresses = re.findall(r'0x[0-9a-f]{8,16}', output[:2000], re.IGNORECASE)
                if addresses:
                    unique_addresses = list(dict.fromkeys(addresses))[:5]  # First 5 unique addresses
                    evidence_context += f"   → Contains addresses: {', '.join(unique_addresses)}\n"
        
        prompt = f"""You are a Windows debugger expert analyzing a memory dump. Generate WinDbg/CDB commands to answer this question using PROGRESSIVE OBJECT GRAPH TRAVERSAL.

DUMP TYPE: {dump_type}
ORIGINAL ISSUE: {context['issue_description']}
USER QUESTION: {question}
{evidence_context}

CRITICAL: PROGRESSIVE OBJECT GRAPH TRAVERSAL STRATEGY
When the question requires finding specific data (like database connection strings, configuration values, etc.):

1. START BROAD: First identify the relevant objects/threads
   Example: !dumpheap -type System.Data.SqlClient.SqlConnection

2. GET ADDRESSES: From the results, identify specific object addresses or method tables
   Example: If !dumpheap shows addresses like 0x000002541c3def00

3. EXAMINE OBJECTS: Use !do (dumpobj) to inspect the object and find field references
   Example: !do 0x000002541c3def00

4. FOLLOW REFERENCES: Look at the object fields and follow references to find nested data
   Example: If !do shows _connectionString field at 0x000002541c400000, then !do 0x000002541c400000

5. EXTRACT VALUES: Once you reach string/value objects, dump them to get the actual data
   Example: !do <string_object_address> shows the actual string value

EXAMPLES OF PROGRESSIVE TRAVERSAL:
- Question: "What database is the app connected to?"
  Commands: [
    "!dumpheap -type System.Data.SqlClient.SqlConnection",  // Find connection objects
    "!do <address_from_previous>",  // Examine first connection object
    "!do <connectionString_field_address>",  // Follow to connection string field
    "!do <server_field_address>"  // Follow to server name if needed
  ]

- Question: "What's in the configuration object?"
  Commands: [
    "!dumpheap -type ConfigurationManager",  // Find config object
    "!do <address>",  // Examine configuration object
    "!do <settings_field_address>"  // Follow to settings collection
  ]

AVAILABLE COMMANDS:
- For .NET/managed code: !threads, !clrstack, !dumpheap, !do, !gcroot, !finalizequeue, !syncblk, !threadpool
- For native code: k, ~*k, !analyze -v, dt, dv, !locks, !handle
- For general info: lm, !process, !peb, .lastevent

IMPORTANT: 
- If previous evidence shows object addresses, use !do <address> to examine those objects
- Build a SEQUENCE of commands where each step provides input for the next
- Use placeholder syntax ADDR_FROM_{pattern} when you need to reference addresses from previous output
  Example: "!do ADDR_FROM_SqlConnection" means "use the address from the SqlConnection output"

Generate 3-8 commands that progressively drill down to answer the question.

CRITICAL COMMAND SYNTAX RULES:
- Use ONLY pure WinDbg/CDB commands - NEVER PowerShell syntax
- FORBIDDEN: Pipes (|), foreach, findstr, grep, Where-Object, Select-Object, $_, any PowerShell operators
- THREAD-SPECIFIC COMMANDS: Always combine thread switch with command (e.g., '~8e !clrstack', NOT '~8s' then '!clrstack')
- INVALID EXAMPLES: '~*e !clrstack | findstr Thread', '!dumpheap | foreach', '~8s' followed by '!clrstack'
- VALID EXAMPLES: '~8e !clrstack', '~*e !clrstack', '~10e !dso', '!dumpheap -stat', '!syncblk', '!do 0x12345'
- For filtering: Use WinDbg native commands only (e.g., ~*e applies to all threads)
- For batch: Suggest single representative commands, not loops

Respond in JSON format:
{{
    "commands": ["command1", "command2", ...],
    "reasoning": "Explain the progressive traversal strategy - how each command builds on previous results",
    "traversal_plan": "Brief description of the object graph path you're following"
}}"""

        messages = [
            SystemMessage(content="You are an expert Windows crash dump analyst with deep knowledge of object graph traversal."),
            HumanMessage(content=prompt)
        ]
        
        response = self.llm.invoke(messages)
        result = self._extract_json(response.content)
        
        if result and 'commands' in result:
            console.print(f"[dim]Strategy: {result.get('reasoning', 'N/A')}[/dim]")
            if 'traversal_plan' in result:
                console.print(f"[dim cyan]Object Graph Path: {result['traversal_plan']}[/dim cyan]")
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
            
            # Detect if question requires detailed data (type breakdowns, statistics, lists)
            detail_keywords = ['which types', 'what types', 'breakdown', 'list of', 'top consumers', 
                              'specific', 'exactly', 'detail', 'all the', 'each', 'individual']
            needs_detailed_data = any(keyword in question.lower() for keyword in detail_keywords)
            
            for i, evidence in enumerate(new_evidence, 1):
                evidence_text += f"\n{i}. `{evidence['command']}`\n"
                
                # Check if this is external evidence with analysis
                if evidence.get('evidence_type') == 'external':
                    if needs_detailed_data and evidence.get('evidence_id'):
                        # Check if structured data is available (from analyzers like dumpheap)
                        structured_data = evidence.get('structured_data') or {}
                        
                        # If we have top_consumers_summary, use that instead of full output
                        if 'top_consumers_summary' in structured_data:
                            evidence_text += f"   Analysis: {evidence.get('summary', 'No summary available')}\n\n"
                            evidence_text += "   Top 20 Memory Consumers:\n"
                            for consumer in structured_data['top_consumers_summary']:
                                evidence_text += (
                                    f"   {consumer['rank']}. {consumer['class_name']} - "
                                    f"{consumer['size_formatted']} ({consumer['count']:,} objects, "
                                    f"MT: {consumer['method_table']})\n"
                                )
                            console.print(f"[dim cyan]  → Using structured top consumers data[/dim cyan]")
                        elif 'top_by_size' in structured_data:
                            # Fallback: old format without top_consumers_summary
                            evidence_text += f"   Analysis: {evidence.get('summary', 'No summary available')}\n\n"
                            evidence_text += "   Top Memory Consumers:\n"
                            for i, item in enumerate(structured_data['top_by_size'][:20], 1):
                                # Format size
                                size_bytes = item.get('total_size', 0)
                                if size_bytes < 1024 * 1024:
                                    size_str = f"{size_bytes / 1024:.1f} KB"
                                else:
                                    size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                                evidence_text += (
                                    f"   {i}. {item['class_name']} - "
                                    f"{size_str} ({item['count']:,} objects, "
                                    f"MT: {item['method_table']})\n"
                                )
                            console.print(f"[dim cyan]  → Using legacy structured data format[/dim cyan]")
                        else:
                            # No structured data - must retrieve full output (with safety limit)
                            full_output = self.evidence_retriever.evidence_store.retrieve_evidence(evidence['evidence_id'])
                            if full_output and len(full_output) <= 100000:
                                evidence_text += f"   Detailed Output:\n{full_output}\n"
                                console.print(f"[dim cyan]  → Retrieved full output for detailed question ({len(full_output)} chars)[/dim cyan]")
                            else:
                                # Too large - use summary only and warn
                                evidence_text += f"   Analysis: {evidence.get('summary', 'No summary available')}\n"
                                if full_output:
                                    console.print(f"[yellow]  ⚠ Output too large ({len(full_output)} chars), using summary only. Re-run command to get structured data.[/yellow]")
                                else:
                                    console.print(f"[yellow]  ⚠ Could not retrieve evidence[/yellow]")
                    else:
                        # Question doesn't need detailed data - use summary
                        evidence_text += f"   Analysis: {evidence.get('summary', 'No analysis available')}\n"
                else:
                    # Inline evidence - include with smart truncation
                    output = evidence['output']
                    if len(output) <= 15000:
                        # Small enough - include full output
                        evidence_text += f"   Output: {output}\n"
                    else:
                        # Large inline output - show head + tail with context
                        # This preserves beginning (command output) and end (important results)
                        evidence_text += f"   Output (showing 5KB head + 5KB tail of {len(output)} chars):\n{output[:5000]}\n[... {len(output) - 10000} chars omitted ...]\n{output[-5000:]}\n"
        
        prompt = f"""You are answering a user's question about a Windows memory dump analysis.

ORIGINAL ISSUE: {context['issue_description']}

USER'S QUESTION: {question}

{evidence_text}

TASK: Provide a clear, objective answer based ONLY on what the evidence shows.

CRITICAL GUIDELINES - OBJECTIVE ANALYSIS:
1. **Validate user assumptions against evidence** - If the user states something (e.g., "CPU was 20%") but evidence shows otherwise (e.g., !runaway shows hours of CPU time per thread), you MUST point out the contradiction
2. **Be evidence-driven, not agreement-driven** - Do NOT try to make the user's claim fit the data if they conflict
3. **Show the math** - When discussing metrics like CPU usage, thread counts, or memory sizes, calculate and show objective numbers from evidence
4. **Acknowledge conflicts** - If evidence contradicts the user's statement, say: "However, the evidence shows..." or "This conflicts with..."
5. **No speculation to fit user's narrative** - Base conclusions only on measurable data from commands

Standard Guidelines:
- Reference specific commands/evidence when making claims (e.g., "According to !runaway output...")
- DO NOT suggest manual debugger commands for the user to run
- Use technical terms appropriately but explain complex concepts
- Format your answer in markdown
- Keep it concise (3-5 paragraphs max unless more detail is warranted)

Provide your objective, evidence-based answer now:"""

        messages = [
            SystemMessage(content="You are an expert Windows crash dump analyst helping a user understand their dump."),
            HumanMessage(content=prompt)
        ]
        
        response = self.llm.invoke(messages)
        answer = response.content.strip()
        
        # Auto-retry if LLM mentions truncation or missing data
        truncation_indicators = [
            'truncated', 'cut off', 'incomplete', 'missing',
            'not visible', 'not shown', 'not available in the output',
            'would need', 'output ends', 'output was cut'
        ]
        
        if any(indicator in answer.lower() for indicator in truncation_indicators):
            console.print("[yellow]⚠ LLM detected missing/truncated data, retrieving full outputs...[/yellow]")
            
            # Track if we had to use summaries (initialize early to avoid UnboundLocalError)
            used_summaries = False
            
            # Rebuild evidence_text with full outputs (no truncation)
            evidence_text_full = "## Key Conclusions\n"
            if context.get('conclusions'):
                for conclusion in context['conclusions']:
                    evidence_text_full += f"- {conclusion}\n"
                evidence_text_full += "\n"
            
            if context.get('relevant_evidence'):
                evidence_text_full += "## Relevant Evidence from Prior Investigation\n"
                for i, evidence in enumerate(context['relevant_evidence'][:5], 1):
                    evidence_text_full += f"\n{i}. `{evidence.get('command', 'N/A')}`\n"
                    finding = evidence.get('finding', '')
                    if finding:
                        evidence_text_full += f"   {finding[:2000]}\n"
            
            if new_evidence:
                evidence_text_full += "\n## New Investigation Results (FULL OUTPUTS)\n"
                
                # Track total size to avoid token explosion
                total_evidence_chars = 0
                MAX_TOTAL_EVIDENCE = 400000  # 400KB total limit (~100K tokens)
                
                for i, evidence in enumerate(new_evidence, 1):
                    evidence_text_full += f"\n{i}. `{evidence['command']}`\n"
                    
                    if evidence.get('evidence_type') == 'external':
                        # Retrieve full output from external storage
                        if evidence.get('evidence_id'):
                            full_output = self.evidence_retriever.evidence_store.retrieve_evidence(evidence['evidence_id'])
                            if full_output:
                                # Smart sizing: limit per-evidence and check total
                                remaining_budget = MAX_TOTAL_EVIDENCE - total_evidence_chars
                                max_this_evidence = min(50000, remaining_budget)  # Max 50KB per evidence or remaining budget
                                
                                if max_this_evidence <= 0:
                                    console.print(f"[yellow]⚠ Evidence budget exhausted, using summaries for remaining items[/yellow]")
                                    evidence_text_full += f"   Summary: {evidence.get('summary', 'No summary available')}\n"
                                    used_summaries = True
                                    continue
                                
                                output_to_send = full_output[:max_this_evidence] if len(full_output) > max_this_evidence else full_output
                                evidence_text_full += f"   Full Output ({len(full_output)} chars, showing {len(output_to_send)}):\n{output_to_send}\n"
                                total_evidence_chars += len(output_to_send)
                                console.print(f"[dim cyan]  → Retrieved full external evidence ({len(full_output)} chars, used {len(output_to_send)})[/dim cyan]")
                            else:
                                evidence_text_full += f"   Analysis: {evidence.get('summary', 'No summary available')}\n"
                        else:
                            evidence_text_full += f"   Analysis: {evidence.get('summary', 'No summary available')}\n"
                    else:
                        # Inline evidence - include with budget check
                        output = evidence['output']
                        remaining_budget = MAX_TOTAL_EVIDENCE - total_evidence_chars
                        max_this_evidence = min(len(output), remaining_budget)
                        
                        if max_this_evidence <= 0:
                            console.print(f"[yellow]⚠ Evidence budget exhausted[/yellow]")
                            used_summaries = True
                            break
                        
                        output_to_send = output[:max_this_evidence]
                        evidence_text_full += f"   Full Output:\n{output_to_send}\n"
                        total_evidence_chars += len(output_to_send)
                
                console.print(f"[dim]Total evidence in retry: {total_evidence_chars} chars (~{total_evidence_chars // 4} tokens)[/dim]")
            
            # Prepend disclaimer if summaries were used
            disclaimer = ""
            if used_summaries:
                disclaimer = "\n> ⚠️ **Note**: Due to model context window constraints (200K tokens), some command outputs were summarized rather than provided in full. The analysis below is based on available summaries and may have limited detail. For complete accuracy, consider investigating specific areas with targeted follow-up questions.\n\n"
                console.print(f"[yellow]⚠ Adding disclaimer about summary-based analysis[/yellow]")
            
            # Retry with full outputs
            prompt_retry = f"""You are answering a user's question about a Windows memory dump analysis.

ORIGINAL ISSUE: {context['issue_description']}

USER'S QUESTION: {question}

{evidence_text_full}

IMPORTANT: You previously mentioned data was truncated or missing. The FULL outputs are now provided above.
Please re-examine the complete data and provide a thorough answer.

TASK: Provide a clear, concise answer to the user's question based on the COMPLETE evidence above.

GUIDELINES:
1. Be direct and specific - answer the question with the available evidence
2. Reference specific commands/evidence when making claims
3. DO NOT suggest manual debugger commands for the user to run
4. Use technical terms appropriately but explain complex concepts
5. Format your answer in markdown
6. Keep it concise (3-5 paragraphs max unless more detail is warranted)

Provide your answer now:"""
            
            # Safety check: estimate total prompt size
            estimated_tokens = len(prompt_retry) // 4  # Rough estimate: 4 chars per token
            if estimated_tokens > 180000:  # Leave 20K buffer from 200K limit
                console.print(f"[yellow]⚠ Retry prompt too large ({estimated_tokens} estimated tokens), falling back to summary-based answer[/yellow]")
                disclaimer = "\n> ⚠️ **Note**: Due to model context window constraints (200K tokens), this response is based on command summaries rather than full outputs. Results may lack detailed information. Consider asking more specific follow-up questions to get detailed analysis of particular areas.\n\n"
                return disclaimer + answer  # Return original answer with disclaimer
            
            console.print(f"[dim]Retry prompt size: ~{estimated_tokens} tokens[/dim]")
            
            messages_retry = [
                SystemMessage(content="You are an expert Windows crash dump analyst helping a user understand their dump."),
                HumanMessage(content=prompt_retry)
            ]
            
            response_retry = self.llm.invoke(messages_retry)
            answer = response_retry.content.strip()
            console.print("[green]✓ Retrieved full data and re-formulated answer[/green]")
            
            # Prepend disclaimer if it exists
            if disclaimer:
                answer = disclaimer + answer
        
        return answer
    
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
    
    def _execute_with_healing(self, command: str, question: str, context: dict) -> dict:
        """Execute command with automatic healing on failure.
        
        Args:
            command: Command to execute
            question: User's question
            context: Execution context with previous evidence
            
        Returns:
            Command execution result dict
        """
        max_heal_attempts = 2
        attempt = 0
        current_command = command
        
        while attempt <= max_heal_attempts:
            # Execute the command
            result = self.debugger.execute_command_with_analysis(
                command=current_command,
                intent=f"Investigating: {question}"
            )
            
            # Check if command failed
            if isinstance(result, dict):
                output = result.get('output', '')
                success = result.get('success', True)
                
                # Detect failure indicators in output
                failed = (
                    not success or
                    output.startswith('Error:') or
                    'Unable to bind' in output or
                    'Invalid object' in output or
                    'bad object' in output or
                    'not found' in output or
                    'Syntax error' in output
                )
                
                if failed and attempt < max_heal_attempts:
                    # Attempt to heal the command
                    healed_command = self.healer.heal_command(
                        current_command, 
                        output,
                        context
                    )
                    
                    if healed_command:
                        attempt += 1
                        current_command = healed_command
                        console.print(f"  [yellow]⚠ Retry {attempt}/{max_heal_attempts} with healed command[/yellow]")
                        continue  # Retry with healed command
                    else:
                        # Can't heal, return failure
                        return result
                else:
                    # Success or max attempts reached
                    return result
            else:
                # Non-dict result, return as-is
                return result
        
        # Max attempts reached, return last result
        return result
