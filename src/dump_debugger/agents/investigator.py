"""
Investigator agent that executes targeted debugger commands for specific investigation tasks.
"""
import json
import re
from rich.console import Console

from dump_debugger.core import DebuggerWrapper
from dump_debugger.llm import get_llm
from dump_debugger.state import AnalysisState, Evidence
from dump_debugger.utils.command_healer import CommandHealer
from dump_debugger.utils.smart_placeholder_resolver import SmartPlaceholderResolver, detect_placeholders

console = Console()


class InvestigatorAgent:
    """Investigates specific tasks by running targeted debugger commands."""
    
    def __init__(self, debugger: DebuggerWrapper):
        self.debugger = debugger
        self.llm = get_llm(temperature=0.1)
        self.healer = CommandHealer()
        # Use low temperature for precise placeholder validation and resolution
        self.smart_resolver = SmartPlaceholderResolver(get_llm(temperature=0.0))
    
    def investigate_task(self, state: AnalysisState) -> dict:
        """Execute investigation task and collect evidence using expert-level approach."""
        task = state['current_task']
        console.print(f"\n[cyan]🔍 Investigating:[/cyan] {task}")
        
        # Track heals in THIS investigation (not cumulative)
        heals_at_start = self.healer.heal_count
        
        from langchain_core.messages import HumanMessage, SystemMessage
        from dump_debugger.expert_knowledge import (
            get_efficient_commands_for_hypothesis,
        )
        
        hypothesis = state.get('current_hypothesis', '')
        prev_evidence = state.get('evidence_inventory', {}).get(task, [])
        supports_dx = state.get('supports_dx', False)
        
        # Get efficient command suggestions
        efficient_cmds = get_efficient_commands_for_hypothesis(task, supports_dx)
        cmd_suggestions = ""
        if efficient_cmds:
            cmd_suggestions = "\n\nSUGGESTED EFFICIENT COMMANDS:\n" + "\n".join(f"- {cmd}" for cmd in efficient_cmds[:3])
        
        # Check if task describes multiple commands (look for "then", "and then", "followed by", etc.)
        multi_step_indicators = [' then ', ' and then ', ' followed by ', ', then ', ',then']
        is_multi_step = any(indicator in task.lower() for indicator in multi_step_indicators)
        
        if is_multi_step:
            prompt = f"""You are an expert Windows debugger. The task describes MULTIPLE commands to execute in sequence.

CONFIRMED HYPOTHESIS: {hypothesis}
INVESTIGATION TASK: {task}
DUMP SUPPORTS DATA MODEL: {supports_dx}
Previous Evidence: {len(prev_evidence)} items

STRICT INSTRUCTIONS:
1. Extract ONLY the commands explicitly mentioned in the task description
2. Do NOT add extra commands or "helpful" suggestions
3. Do NOT substitute different commands even if they seem more efficient
4. If the task says "!dumpheap -mt XXXXX then !do on objects", return exactly those commands
5. Preserve the exact command syntax mentioned in the task
6. For ranges like "5-10 objects", use the middle value (e.g., 7 objects)

THREAD COMMAND RULES - CRITICAL:
When the task mentions examining specific threads (e.g., from !syncblk output):
1. NEVER use placeholder syntax like ~~[ThreadId] or ~~[thread] - this is INVALID
2. If you don't have the actual thread IDs, first include "!threads" to get them
3. Use concrete thread numbers OR use ~*e for all threads

VALID thread command syntax:
- ~0e !clrstack       (execute on debugger thread 0)
- ~24e !clrstack      (execute on debugger thread 24) 
- ~~[d78]e !clrstack  (execute on OSID d78 - MUST be actual hex OSID, NOT a placeholder)
- ~*e !clrstack       (execute on all threads)

INVALID (NEVER USE):
- ~~[ThreadId]s; !clrstack   (ThreadId is NOT a valid OSID)
- ~~[thread]e !clrstack      (thread is NOT a valid OSID)
- ~~[OWNER_THREAD]e !clrstack (OWNER_THREAD is NOT a valid OSID)

If task says "examine threads waiting on SyncBlock X":
1. Include "!threads" first to get actual thread IDs
2. Then use "~*e !clrstack" to get all thread stacks, OR
3. Use specific thread numbers if you know them from previous evidence

CRITICAL COMMAND SYNTAX RULES:
- ONLY use WinDbg/CDB/SOS commands - NO PowerShell syntax
- FORBIDDEN: pipes (|), foreach, findstr, grep, where-object, select-object, $_ variables
- Extract exact commands mentioned in the task (e.g., if task says "!threadpool", use "!threadpool")
- For "!do on N objects" type commands, use a placeholder address like "!do <addr>" (one command per object)
- For thread-specific commands, use "~<thread>e <command>" syntax with <thread> placeholder

Return ONLY valid JSON in this exact format:
{{
    "commands": ["command1", "command2", ...],
    "rationale": "extracted commands exactly as mentioned in task"
}}

EXAMPLES:
Task: "Run '!dumpheap -stat' then '!do' on 3 objects"
Response: {{"commands": ["!dumpheap -stat", "!do <addr>", "!do <addr>", "!do <addr>"], "rationale": "executing !dumpheap -stat followed by !do on 3 objects"}}

Task: "Examine all threads waiting on SyncBlock 470 with !clrstack"
Response: {{"commands": ["~*e !clrstack"], "rationale": "examining all thread stacks to find waiting threads"}}

Task: "Run !clrstack on thread 18 (DBG#) which holds the lock"
Response: {{"commands": ["~18e !clrstack"], "rationale": "examining specific thread 18 stack"}}

Task: "Execute '!clrstack' on several of the 21 threads waiting on the HostedCompiler lock"  
Response: {{"commands": ["~*e !clrstack"], "rationale": "examining all thread stacks to identify threads waiting on HostedCompiler lock"}}
"""
        else:
            prompt = f"""You are an expert Windows debugger. Generate ONE precise WinDbg/CDB command for this investigation.

CONFIRMED HYPOTHESIS: {hypothesis}
INVESTIGATION TASK: {task}
DUMP SUPPORTS DATA MODEL: {supports_dx}
Previous Evidence: {len(prev_evidence)} items
{cmd_suggestions}

CRITICAL - RECOGNIZE GAP-FILLING REQUESTS:
If the task includes "Suggested approach:" this is a GAP-FILLING request from iterative reasoning.
The reasoner has identified missing correlation data and is requesting SPECIFIC new commands.

WHEN YOU SEE "Suggested approach:" IN THE TASK:
1. Parse the suggested approach carefully - it tells you WHAT COMMANDS to use
2. Generate those EXACT commands, do NOT default to basic commands like !threads
3. Focus on NEW evidence, not repeating commands already executed
4. Examples of gap-filling commands:
   - !finalizequeue (to see finalization queue depth)
   - !dumpheap -type ClassName (to find specific object types)
   - !do <address> (to inspect object references)
   - !gcroot <address> (to find object roots)

Example Task: "What objects are queued for finalization? Suggested approach: Use !finalizequeue to see queue"
→ You MUST generate: !finalizequeue
→ Do NOT generate: !threads (already have that)

HANDLING DEEPER INVESTIGATION REQUESTS:
This task may come from the reasoner identifying gaps in object graph correlation. These are complex questions 
requiring multi-step investigation strategies. Common patterns:

1. CORRELATING SEPARATE OBJECT GRAPHS:
   Problem: "Found 50 TimeoutException objects and 100 SqlCommand objects, but cannot establish correlation"
   Strategy: 
   - Use !do on exception objects to extract references to related objects
   - Look for fields like "m_command", "_source", "m_innerException" that may hold references
   - Follow object addresses through !do chains to establish correlation
   
2. MAPPING OBJECTS TO THREADS:
   Problem: "Which threads are associated with these timeout objects?"
   Strategy:
   - Use !threads to see all managed threads
   - Use !clrstack on each thread to see stack frames
   - Match object addresses from stack references to timeout objects
   - Alternative: Use !gcroot <address> to find thread references
   
3. EXTRACTING NESTED DATA:
   Problem: "What SQL queries were executed by these SqlCommand objects?"
   Strategy:
   - !do <SqlCommand address> to inspect object
   - Look for string fields like "m_commandText" or "_commandText"
   - Use !do on nested string addresses to get actual SQL text
   
4. LINKING EXCEPTIONS TO SOURCES:
   Problem: "Which methods threw these exceptions?"
   Strategy:
   - !do on exception object
   - Examine "_stackTrace" or "_stackTraceString" fields
   - Use !do on StackTrace object if it's a reference
   - Cross-reference with !clrstack output on relevant threads

For investigation requests, break the problem into logical steps and return the FIRST command needed.
The workflow will call you iteratively to execute the full investigation chain.

Think like an expert debugger - you know WHAT the problem is (hypothesis confirmed), now find WHERE and WHY.
{"PREFER 'dx' commands with filters (.Select, .Where, .Take) for concise output." if supports_dx else "Use traditional WinDbg/SOS commands."}

CRITICAL THREAD ID CLARIFICATION:
There are THREE different thread identifiers in .NET debugging:
1. MANAGED THREAD ID: Shown in !threads "ID" column and !syncblk "Owning Thread" column (e.g., 12, 19, 42)
2. DEBUGGER THREAD NUMBER: Shown in !threads "DBG" column (e.g., 0, 1, 2, ...)
3. OS THREAD ID (OSID): Shown in !threads "OSID" column as hex (e.g., 0x3fc, 0x23c4)

Thread Command Syntax:
- Switch by debugger thread: ~<num>s (e.g., ~9s switches to debugger thread 9)
- Execute on debugger thread: ~<num>e <command> (e.g., ~9e !clrstack runs on thread 9 without switching)
- Switch by OSID: ~~[osid]s (e.g., ~~[3fc]s switches to OSID 0x3fc)
- Execute on OSID: ~~[osid]e <command> (e.g., ~~[3fc]e !clrstack runs on OSID 0x3fc)
- Execute on all threads: ~*e <command> (e.g., ~*e !clrstack)

CRITICAL SYNTAX RULES:
- OSID in brackets: DO NOT include "0x" prefix (use ~~[3fc]s NOT ~~[0x3fc]s)
- When referencing OSID in text: DO include "0x" prefix ("OSID 0x3fc" for clarity)
- Prefer 'e' (execute) over 's' (switch) when examining specific thread without changing context
- NEVER generate separate thread switch and command - ALWAYS combine them with 'e'
  - WRONG: ["~3s", "!clrstack"]  ← Two separate commands
  - RIGHT: ["~3e !clrstack"]     ← One atomic command
- Thread context commands MUST be atomic: ~3e !clrstack, NOT ~3s followed by !clrstack

IMPORTANT: When !syncblk shows "thread 12" as lock holder, this is the MANAGED THREAD ID.
To investigate this thread:
1. First get !threads output to see the DBG or OSID column for managed ID 12
2. Then use ~<DBG#>e or ~~[<OSID>]e to execute command on that thread
Example: If !threads shows "DBG=9, ID=12, OSID=3fc", managed thread 12 is at:
- Debugger thread 9: Use ~9e !clrstack (no 0x prefix needed)
- OSID 0x3fc: Use ~~[3fc]e !clrstack (bracket gets NO 0x prefix, but we refer to it as "OSID 0x3fc")

STRICT COMMAND SELECTION RULES:
1. If task explicitly mentions a command (e.g., "Execute '!do'", "Run !clrstack"), use that EXACT command
2. Do NOT add prerequisite steps unless the task explicitly says "then" or "followed by"
3. Task says "Execute '!do' on objects" → Generate: !do <addr> (with placeholder)
   DO NOT generate: !dumpheap first (that's a separate task)
4. Task says "Execute '!clrstack' on threads" → Generate: ~*e !clrstack or ~Xe !clrstack
   DO NOT generate: !threads first (we already have thread info)
5. If task mentions "actual objects", "specific objects", or "active objects":
   - Use placeholder syntax: !do <addr> or !gcroot <addr>
   - The system will auto-resolve <addr> from previous !dumpheap evidence
6. Use !dumpheap -stat ONLY when task asks for statistics/counts/summaries, never for object inspection
7. Follow task intent literally - don't be "helpful" by adding steps

CRITICAL COMMAND SYNTAX RULES:
1. ONLY use WinDbg/CDB/SOS commands - NO PowerShell syntax
2. FORBIDDEN: pipes (|), foreach, findstr, grep, where-object, select-object, $_ variables
3. Use WinDbg filtering: ~*e, .foreach, s -[d|a|u], !dumpheap -mt, etc.
4. VALID examples: "!clrstack", "~*e !clrstack", "!dumpheap -type Task", "dx @$curthread"
5. INVALID examples: "!clrstack | findstr", "~*e !clrstack | where", "!do $addr | foreach"
6. DUMPHEAP SYNTAX:
   - ✓ !dumpheap -type ClassName (finds objects by type name)
   - ✓ !dumpheap -type ClassName -short (abbreviated output)
   - ✓ !dumpheap -mt 0x00007fff12345678 (finds objects by method table ADDRESS)
   - ✓ !dumpheap -mt 0x00007fff12345678 -short (method table + abbreviated)
   - ✗ !dumpheap -mt ClassName (INVALID - -mt requires hex address, not name)
   - ✗ !dumpheap -mt -short ClassName (INVALID - -mt needs address before other flags)

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
        commands_to_execute = []
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
            
            # Extract commands (single or multiple)
            if 'commands' in result:
                # Multi-step task
                commands_to_execute = [cmd.strip() for cmd in result['commands']]
                rationale = result.get('rationale', '')
            else:
                # Single command task
                commands_to_execute = [result['command'].strip()]
                rationale = result.get('rationale', '')
            
            # Validate all commands against PowerShell syntax and filter setup commands
            powershell_patterns = ['| foreach', '| findstr', '| grep', '| where', '| select', '$_']
            setup_commands = ['.loadby sos', '.load sos', 'lmm sos', '.sympath', '.reload', '.cordll']
            
            cleaned_commands = []
            i = 0
            while i < len(commands_to_execute):
                cmd = commands_to_execute[i]
                cmd_lower = cmd.lower().strip()
                
                # Filter out setup/initialization commands
                if any(setup_cmd in cmd_lower for setup_cmd in setup_commands):
                    console.print(f"[yellow]⚠ Skipping setup command (already initialized): {cmd}[/yellow]")
                    i += 1
                    continue
                
                # Validate PowerShell syntax
                if any(pattern in cmd_lower for pattern in powershell_patterns):
                    console.print(f"[yellow]⚠ Invalid command (contains PowerShell syntax): {cmd}[/yellow]")
                    # Use fallback: extract the WinDbg part before the pipe
                    if '|' in cmd:
                        cmd = cmd.split('|')[0].strip()
                        console.print(f"[yellow]  Cleaned to: {cmd}[/yellow]")
                
                # Fix separated thread commands: combine ~Xs followed by !command into ~Xe !command
                if cmd.startswith('~') and cmd.endswith('s'):
                    # Check if next command is a SOS command without thread prefix
                    if i + 1 < len(commands_to_execute):
                        next_cmd = commands_to_execute[i + 1].strip()
                        if next_cmd.startswith('!') and not next_cmd.startswith('~'):
                            # Combine them with 'e' instead of 's'
                            thread_part = cmd[:-1]  # Remove 's' from ~3s
                            combined = f"{thread_part}e {next_cmd}"
                            console.print(f"[yellow]⚠ Combining separated thread commands:[/yellow]")
                            console.print(f"[yellow]  {cmd} + {next_cmd} → {combined}[/yellow]")
                            cleaned_commands.append(combined)
                            i += 2  # Skip next command since we combined it
                            continue
                
                cleaned_commands.append(cmd)
                i += 1
            
            commands_to_execute = cleaned_commands
            
            if len(commands_to_execute) > 1:
                console.print(f"  [dim]→ Executing {len(commands_to_execute)} commands in sequence[/dim]")
            
            if rationale and state.get('show_command_output'):
                console.print(f"  [dim italic]{rationale}[/dim italic]")
                
        except (json.JSONDecodeError, KeyError) as e:
            console.print(f"[yellow]⚠ JSON parsing failed: {e}[/yellow]")
            console.print(f"[yellow]Raw response: {response.content[:200]}[/yellow]")
            # Fallback: extract first line that looks like a command
            lines = response.content.strip().split('\n')
            commands_to_execute = [lines[0].strip()]
            console.print(f"  [dim]→ {commands_to_execute[0]} (fallback extraction)[/dim]")
        
        # Execute all commands and collect evidence
        inventory = dict(state.get('evidence_inventory', {}))
        if task not in inventory:
            inventory[task] = []
        
        all_commands = list(state.get('commands_executed', []))
        
        # Track outputs for placeholder resolution
        previous_outputs = []
        # Track which addresses have been used and which are invalid
        used_addresses = set()
        invalid_addresses = set()
        # Track thread IDs from !threads output for thread placeholder resolution
        available_thread_ids = []
        used_thread_ids = set()
        # Track consecutive failures for early stopping
        consecutive_failures = 0
        last_failure_message = None
        max_consecutive_failures = 3
        
        for i, command in enumerate(commands_to_execute):
            # Detect any placeholder pattern <...>
            from dump_debugger.utils import detect_placeholders, resolve_command_placeholders
            
            # Build evidence list for placeholder resolution
            evidence_for_resolution = []
            
            # First, add evidence from previous tasks in inventory (enables reuse across tasks)
            for task_key, task_evidence_list in inventory.items():
                for evidence_item in task_evidence_list:
                    evidence_for_resolution.append({
                        'command': evidence_item.get('command', ''),
                        'output': evidence_item.get('output', '') or evidence_item.get('summary', ''),
                        'evidence_type': evidence_item.get('evidence_type', 'inline'),
                        'evidence_id': evidence_item.get('evidence_id')
                    })
            
            # Then, add outputs from current task execution
            for j, output in enumerate(previous_outputs):
                evidence_for_resolution.append({
                    'command': commands_to_execute[j] if j < len(commands_to_execute) else 'unknown',
                    'output': output,
                    'evidence_type': 'inline'
                })
            
            # Special handling for <thread> placeholder
            if '<thread>' in command:
                if not available_thread_ids:
                    # Parse thread IDs from previous !threads output
                    for evidence in evidence_for_resolution:
                        if evidence.get('command', '').startswith('!threads'):
                            # Extract debugger thread numbers (DBG column)
                            thread_pattern = r'^\s*(\d+)\s+' # Matches debugger thread number at start of line
                            for line in evidence.get('output', '').split('\n'):
                                match = re.match(thread_pattern, line.strip())
                                if match:
                                    thread_id = match.group(1)
                                    if thread_id.isdigit():
                                        available_thread_ids.append(thread_id)
                    console.print(f"  [dim]Found {len(available_thread_ids)} threads to sample[/dim]")
                
                if available_thread_ids:
                    # Get next unused thread ID
                    unused_threads = [tid for tid in available_thread_ids if tid not in used_thread_ids]
                    if unused_threads:
                        selected_thread = unused_threads[0]
                        used_thread_ids.add(selected_thread)
                        command = command.replace('<thread>', selected_thread)
                        console.print(f"  [green]✓ Resolved <thread> to thread {selected_thread}[/green]")
                    else:
                        console.print(f"  [yellow]⚠ All threads exhausted, reusing threads[/yellow]")
                        # Reset and reuse
                        used_thread_ids.clear()
                        selected_thread = available_thread_ids[0]
                        used_thread_ids.add(selected_thread)
                        command = command.replace('<thread>', selected_thread)
                else:
                    console.print(f"  [red]✗ No thread IDs available - run !threads first[/red]")
                    console.print(f"  [yellow]⚠ Skipping command with unresolved <thread> placeholder[/yellow]")
                    continue
            
            # Check for other placeholders and use smart LLM-based resolution
            if detect_placeholders(command):
                console.print(f"  [yellow]⚠ Detected placeholders in:[/yellow] {command}")
                
                # Use unified smart resolver (validates AND resolves in one pass)
                resolved_command, success, message, details = self.smart_resolver.resolve_command(
                    command,
                    evidence_for_resolution,
                    used_addresses=used_addresses,
                    invalid_addresses=invalid_addresses
                )
                
                if not success:
                    # Could not resolve placeholders
                    console.print(f"  [red]✗ Resolution failed:[/red] {message}")
                    
                    # Show details from LLM analysis
                    if details.get('analysis', {}).get('placeholders'):
                        for ph in details['analysis']['placeholders']:
                            if not ph.get('resolvable', False):
                                console.print(f"    • {ph['text']}: {ph.get('reason', 'unknown')}")
                                if ph.get('prerequisite'):
                                    console.print(f"      [dim]Prerequisite: {ph['prerequisite']}[/dim]")
                    
                    console.print(f"  [yellow]⚠ Skipping command with unresolvable placeholders[/yellow]")
                    continue
                
                # Successfully resolved
                console.print(f"  [green]✓ Resolved to:[/green] {resolved_command}")
                
                # Track which addresses were used from the replacements
                if details.get('replacements'):
                    for placeholder, value in details['replacements'].items():
                        # Track addresses for deduplication
                        if re.match(r'0x[0-9a-f]+', value, re.IGNORECASE):
                            # Normalize to 16-digit format
                            addr = value if value.startswith('0x') else '0x' + value
                            if len(addr) < 18:  # 0x + 16 digits
                                addr = '0x' + addr[2:].zfill(16)
                            used_addresses.add(addr)
                
                command = resolved_command
            
            if len(commands_to_execute) > 1:
                console.print(f"  [dim]→ Step {i+1}/{len(commands_to_execute)}: {command}[/dim]")
            else:
                console.print(f"  [dim]→ {command}[/dim]")
            
            # Execute command with evidence analysis and auto-healing
            result = self._execute_with_healing(
                command=command,
                task=task,
                step_info=f"step {i+1}/{len(commands_to_execute)}",
                context={
                    'previous_evidence': evidence_for_resolution,
                    'used_addresses': used_addresses,
                    'invalid_addresses': invalid_addresses
                }
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
            
            # Post-process: Filter finalizequeue output if task mentions specific type
            if '!finalizequeue' in command.lower() and evidence_type == 'inline':
                # Check if task mentions a specific type to filter for
                type_match = re.search(r'(?:filter|filtered for|looking for|find|identify)\s+(\w+(?:\.\w+)*)', task.lower())
                if type_match:
                    filter_type = type_match.group(1)
                    # Filter output to only lines containing the type
                    filtered_lines = []
                    for line in output_str.split('\n'):
                        if filter_type.lower() in line.lower():
                            filtered_lines.append(line)
                    
                    if filtered_lines:
                        original_count = len(output_str.split('\n'))
                        filtered_output = '\n'.join(filtered_lines)
                        output_str = filtered_output
                        console.print(f"[dim]  → Filtered {original_count} lines to {len(filtered_lines)} lines containing '{filter_type}'[/dim]")
            
            # Display results with same visibility as hypothesis testing phase
            if state.get('show_command_output') and output_str:
                # Show summary if available (analyzer output)
                if analysis and analysis.get('summary'):
                    console.print(f"[dim cyan]  Analysis: {analysis['summary'][:300]}{'...' if len(analysis['summary']) > 300 else ''}[/dim cyan]")
                    # Show key findings if available
                    key_findings = analysis.get('key_findings', [])
                    if key_findings:
                        console.print(f"[dim cyan]  + {len(key_findings)} key findings[/dim cyan]")
                        for finding in key_findings[:3]:  # Show top 3
                            console.print(f"[dim cyan]    • {finding}[/dim cyan]")
                else:
                    # No analysis - show raw output preview
                    preview = output_str[:200] if len(output_str) > 200 else output_str
                    console.print(f"[dim cyan]  Result: {preview}[/dim cyan]")
            
            # Track invalid addresses (objects not found)
            if 'not found' in output_str.lower() or 'invalid' in output_str.lower() or 'not a valid' in output_str.lower():
                # Extract the address from the command (e.g., !do 0x123456)
                addr_match = re.search(r'(?:0x)?[0-9a-f]{8,16}', command, re.IGNORECASE)
                if addr_match:
                    invalid_addr = addr_match.group(0)
                    if not invalid_addr.startswith('0x'):
                        invalid_addr = '0x' + invalid_addr
                    # Normalize: pad to 16 hex digits for consistent tracking
                    if len(invalid_addr) < 18:  # 0x + 16 digits
                        invalid_addr = '0x' + invalid_addr[2:].zfill(16)
                    invalid_addresses.add(invalid_addr)
                    console.print(f"  [dim red]→ Marking {invalid_addr} as invalid[/dim red]")
            
            # Early stopping: detect repeated identical failures
            # BUT: Don't stop for address-related failures when we have placeholders
            is_failure = (
                'not found' in output_str.lower() or 
                'invalid' in output_str.lower() or
                'does not contain' in output_str.lower() or
                'error' in output_str.lower() or
                len(output_str) < 100  # Very small output often indicates failure
            )
            
            # Check if this is an address-related failure (invalid address, not command failure)
            is_address_failure = (
                'not a valid' in output_str.lower() or
                'invalid object' in output_str.lower() or
                'not found' in output_str.lower() or
                'object has an invalid class' in output_str.lower()
            )
            
            # Detect if command uses placeholders (will cycle to next address)
            from dump_debugger.utils import detect_placeholders
            has_placeholders = detect_placeholders(command)
            
            if is_failure:
                # For commands with placeholders and address failures, don't count toward stopping
                # The system will automatically cycle to the next address
                if has_placeholders and is_address_failure:
                    # This is expected - some addresses may be invalid/stale
                    # Just continue to next address, don't count as "consecutive failure"
                    pass
                else:
                    # Real failure (syntax error, command broken, etc.)
                    failure_sig = output_str[:100].lower().strip()
                    
                    if failure_sig == last_failure_message:
                        consecutive_failures += 1
                        console.print(f"  [yellow]⚠ Consecutive failure #{consecutive_failures}[/yellow]")
                        
                        if consecutive_failures >= max_consecutive_failures:
                            remaining = len(commands_to_execute) - i - 1
                            if remaining > 0:
                                console.print(f"  [red]✗ Stopping after {consecutive_failures} identical non-address failures[/red]")
                                console.print(f"  [dim]  Skipping {remaining} remaining commands[/dim]")
                                console.print(f"  [dim cyan]Failure: '{failure_sig[:50]}...'[/dim cyan]")
                                break  # Exit the command execution loop
                    else:
                        consecutive_failures = 1
                        last_failure_message = failure_sig
            else:
                # Success - reset counter
                consecutive_failures = 0
                last_failure_message = None
            
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
                'finding': f"Executed for task: {task} (step {i+1}/{len(commands_to_execute)})",
                'significance': "Investigating confirmed hypothesis",
                'confidence': 'medium',
                'evidence_type': evidence_type,
                'evidence_id': evidence_id,
                'summary': analysis.get('summary') if analysis else None
            }
            

            inventory[task].append(evidence)
            all_commands.append(command)
            
            # Store output for placeholder resolution in next commands
            if evidence_type == 'external' and evidence_id:
                # For external evidence, retrieve full output
                full_output = self.debugger.evidence_store.retrieve_evidence(evidence_id)
                previous_outputs.append(full_output if full_output else output_str)
            else:
                # For inline evidence, use the output directly
                previous_outputs.append(output_str)
            
            # Auto-generate follow-up inspection commands if task mentions them but we only found objects
            # Check for !do, !gcroot, !objsize, etc. - commands that need addresses from !dumpheap
            inspection_commands = {
                '!do': '!do',
                '!dumpobj': '!do',
                '!gcroot': '!gcroot',
                '!objsize': '!objsize',
                '!gchandles': '!gchandles'
            }
            
            # Check if task wants any inspection command and we just ran !dumpheap
            inspection_cmd = None
            for keyword, cmd in inspection_commands.items():
                if keyword in task.lower():
                    inspection_cmd = cmd
                    break
            
            if inspection_cmd and '!dumpheap' in command.lower() and i == len(commands_to_execute) - 1:
                # Task wants inspection but we only ran !dumpheap
                # Extract object addresses from output
                addr_pattern = r'^([0-9a-f]{12,16})\s+[0-9a-f]{12,16}\s+\d+'
                addr_matches = re.findall(addr_pattern, output_str.lower(), re.MULTILINE)
                
                if addr_matches:
                    # Determine number of objects based on task wording
                    max_objects = 7  # Default
                    if 'top 5' in task.lower() or '5-10' in task.lower():
                        max_objects = 5
                    elif 'top 10' in task.lower() or '10-15' in task.lower():
                        max_objects = 10
                    elif 'several' in task.lower() or 'few' in task.lower():
                        max_objects = 3
                    
                    num_to_inspect = min(len(addr_matches), max_objects)
                    console.print(f"[cyan]  → Task requested {inspection_cmd} inspection, auto-generating {num_to_inspect} commands[/cyan]")
                    
                    # Add inspection commands to execution queue
                    for addr in addr_matches[:num_to_inspect]:
                        commands_to_execute.append(f"{inspection_cmd} {addr}")
            
            # Limit commands_executed to prevent bloat
            if len(all_commands) > 30:
                all_commands = all_commands[-30:]
        
        # Log healing stats if any heals occurred IN THIS INVESTIGATION (not cumulative)
        heals_in_this_investigation = self.healer.heal_count - heals_at_start
        if heals_in_this_investigation > 0:
            console.print(f"[dim cyan]🔧 Healed {heals_in_this_investigation} failed command(s) during investigation[/dim cyan]")
        
        return {
            'evidence_inventory': inventory,
            'commands_executed': all_commands
        }
    
    def _execute_with_healing(self, command: str, task: str, step_info: str, context: dict) -> dict:
        """Execute command with automatic healing on failure.
        
        Args:
            command: Command to execute
            task: Investigation task description
            step_info: Step information for display
            context: Execution context with previous evidence, used addresses, etc.
            
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
                intent=f"Investigating: {task} ({step_info})"
            )
            
            # Check if command failed
            if isinstance(result, dict):
                output = result.get('output', '')
                success = result.get('success', True)
                
                # Precise failure detection - only trigger on actual command failures
                # Check for specific WinDbg error patterns, not analyzer commentary
                output_start = output[:300].strip() if output else ""
                
                # Check if we got substantial output (indicates success even if some warnings present)
                has_substantial_output = len(output) > 1000
                
                # Only flag as failed if output looks like an actual debugger error AND we don't have substantial output
                failed = (
                    not success or
                    (not has_substantial_output and (
                        output.startswith('Error:') or
                        output.startswith('0:000> Error') or
                        'Unable to ' in output_start or  # WinDbg errors start with "Unable to"
                        'Cannot ' in output_start or     # "Cannot load/find/access"
                        'Syntax error' in output_start or
                        'Unknown command' in output_start or
                        'No export' in output_start or
                        'Bad address' in output_start or
                        (len(output) < 50 and ('error' in output.lower() or 'invalid' in output.lower()))
                    ))
                )
                
                # Don't treat object inspection failures as command failures
                # These are expected when cycling through addresses
                if 'does not have a valid' in output or 'is not a valid object' in output:
                    failed = False  # Address is invalid, but command syntax was correct
                
                if failed and attempt < max_heal_attempts:
                    # Attempt to heal the command
                    healed_command = self.healer.heal_command(
                        current_command, 
                        output,
                        context
                    )
                    
                    if healed_command:
                        # Check if healer is fundamentally changing command type (bad sign)
                        orig_base_cmd = current_command.split()[0].lower().strip('!')
                        healed_base_cmd = healed_command.split()[0].lower().strip('!')
                        
                        # If command type changed dramatically (e.g., !do → !dumpmt), stop healing
                        incompatible_changes = [
                            ('do', 'dumpmt'), ('do', 'dumpclass'), ('do', 'dumpmodule'),
                            ('pe', 'dumpmt'), ('pe', 'dumpclass'), ('pe', 'dumpmodule'),
                            ('dumpobj', 'dumpmt'), ('dumpobj', 'dumpclass'),
                        ]
                        
                        command_changed_incompatibly = False
                        for orig, healed in incompatible_changes:
                            if orig in orig_base_cmd and healed in healed_base_cmd:
                                command_changed_incompatibly = True
                                console.print(f"  [yellow]⚠ Healer changed command type ({orig} → {healed}), likely address type mismatch[/yellow]")
                                break
                        
                        if command_changed_incompatibly:
                            # Address is wrong type, don't retry
                            console.print(f"  [dim yellow]→ Skipping command - address type mismatch detected[/dim yellow]")
                            return result
                        
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
