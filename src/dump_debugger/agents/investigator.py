"""
Investigator agent that executes targeted debugger commands for specific investigation tasks.
"""
import json
import re
from rich.console import Console

from dump_debugger.core import DebuggerWrapper
from dump_debugger.llm import get_llm
from dump_debugger.state import AnalysisState, Evidence

console = Console()


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

CRITICAL COMMAND SYNTAX RULES:
- ONLY use WinDbg/CDB/SOS commands - NO PowerShell syntax
- FORBIDDEN: pipes (|), foreach, findstr, grep, where-object, select-object, $_ variables
- Extract exact commands mentioned in the task (e.g., if task says "!threadpool", use "!threadpool")
- For "!do on N objects" type commands, use a placeholder address like "!do <addr>" (one command per object)

Return ONLY valid JSON in this exact format:
{{
    "commands": ["command1", "command2", ...],
    "rationale": "extracted commands exactly as mentioned in task"
}}

EXAMPLES:
Task: "Run '!dumpheap -stat' then '!do' on 3 objects"
Response: {{"commands": ["!dumpheap -stat", "!do <addr>", "!do <addr>", "!do <addr>"], "rationale": "executing !dumpheap -stat followed by !do on 3 objects"}}

Task: "Run '!dumpheap -mt 00007ff8' then '!do' on 5-10 Thread objects"
Response: {{"commands": ["!dumpheap -mt 00007ff8", "!do <addr>", "!do <addr>", "!do <addr>", "!do <addr>", "!do <addr>", "!do <addr>", "!do <addr>"], "rationale": "executing !dumpheap followed by !do on 7 Thread objects (middle of 5-10 range)"}}
"""
        else:
            prompt = f"""You are an expert Windows debugger. Generate ONE precise WinDbg/CDB command for this investigation.

CONFIRMED HYPOTHESIS: {hypothesis}
INVESTIGATION TASK: {task}
DUMP SUPPORTS DATA MODEL: {supports_dx}
Previous Evidence: {len(prev_evidence)} items
{pattern_context}
{cmd_suggestions}

Think like an expert debugger - you know WHAT the problem is (hypothesis confirmed), now find WHERE and WHY.
{"PREFER 'dx' commands with filters (.Select, .Where, .Take) for concise output." if supports_dx else "Use traditional WinDbg/SOS commands."}

STRICT COMMAND SELECTION RULES:
1. If task explicitly mentions a command (e.g., "Use !do", "Run !clrstack"), use that EXACT command
2. Do NOT substitute with different commands even if they seem more efficient
3. If task mentions "!do on objects" or "inspect/examine objects with !do":
   - Use !dumpheap -type TypeName (WITHOUT -stat) to get actual object addresses
   - DO NOT use -stat flag when addresses are needed for !do inspection
   - We'll auto-generate !do commands for the addresses found
4. Use !dumpheap -stat ONLY when task asks for statistics/counts/summaries, never for object inspection
5. Follow task intent: finding objects for statistics ≠ finding objects for inspection

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
            
            # Validate all commands against PowerShell syntax
            powershell_patterns = ['| foreach', '| findstr', '| grep', '| where', '| select', '$_']
            cleaned_commands = []
            for cmd in commands_to_execute:
                if any(pattern in cmd.lower() for pattern in powershell_patterns):
                    console.print(f"[yellow]⚠ Invalid command (contains PowerShell syntax): {cmd}[/yellow]")
                    # Use fallback: extract the WinDbg part before the pipe
                    if '|' in cmd:
                        cmd = cmd.split('|')[0].strip()
                        console.print(f"[yellow]  Cleaned to: {cmd}[/yellow]")
                cleaned_commands.append(cmd)
            
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
        
        for i, command in enumerate(commands_to_execute):
            # Detect any placeholder pattern <...>
            from dump_debugger.utils import detect_placeholders, resolve_command_placeholders
            
            # Build evidence list for placeholder resolution
            evidence_for_resolution = []
            for j, output in enumerate(previous_outputs):
                evidence_for_resolution.append({
                    'command': commands_to_execute[j] if j < len(commands_to_execute) else 'unknown',
                    'output': output,
                    'evidence_type': 'inline'
                })
            
            # Check for placeholders and try to resolve them
            if detect_placeholders(command):
                console.print(f"  [yellow]⚠ Detected placeholders in:[/yellow] {command}")
                
                # Try to resolve, cycling through available addresses and skipping used/invalid ones
                resolved_command, success, message = resolve_command_placeholders(
                    command, 
                    evidence_for_resolution,
                    used_addresses=used_addresses,
                    invalid_addresses=invalid_addresses
                )
                
                if success:
                    console.print(f"  [green]✓ Resolved to:[/green] {resolved_command}")
                    # Track which address was used
                    addr_match = re.search(r'(?:0x)?[0-9a-f]{8,16}', resolved_command, re.IGNORECASE)
                    if addr_match:
                        used_addr = addr_match.group(0)
                        if not used_addr.startswith('0x'):
                            used_addr = '0x' + used_addr
                        used_addresses.add(used_addr)
                    command = resolved_command
                else:
                    console.print(f"  [red]✗ {message}[/red]")
                    console.print(f"  [yellow]⚠ Skipping command with unresolved placeholders[/yellow]")
                    # Skip this command entirely
                    continue
            
            if len(commands_to_execute) > 1:
                console.print(f"  [dim]→ Step {i+1}/{len(commands_to_execute)}: {command}[/dim]")
            else:
                console.print(f"  [dim]→ {command}[/dim]")
            
            # Execute command with evidence analysis
            result = self.debugger.execute_command_with_analysis(
                command=command,
                intent=f"Investigating: {task} (step {i+1}/{len(commands_to_execute)})"
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
            if 'not found' in output_str.lower() or 'invalid' in output_str.lower():
                # Extract the address from the command (e.g., !do 0x123456)
                addr_match = re.search(r'(?:0x)?[0-9a-f]{8,16}', command, re.IGNORECASE)
                if addr_match:
                    invalid_addr = addr_match.group(0)
                    if not invalid_addr.startswith('0x'):
                        invalid_addr = '0x' + invalid_addr
                    invalid_addresses.add(invalid_addr)
                    console.print(f"  [dim red]→ Marking {invalid_addr} as invalid[/dim red]")
            
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
        
        return {
            'evidence_inventory': inventory,
            'commands_executed': all_commands
        }
