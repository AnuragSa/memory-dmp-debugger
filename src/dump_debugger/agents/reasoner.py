"""
Reasoner agent that analyzes all evidence to draw conclusions.
"""
import json
from rich.console import Console
from langchain_core.messages import HumanMessage, SystemMessage

from dump_debugger.llm import get_llm
from dump_debugger.state import AnalysisState

console = Console()


class ReasonerAgent:
    """Analyzes all evidence to draw conclusions."""
    
    def __init__(self):
        self.llm = get_llm(temperature=0.2)
    
    def _build_thread_reference(self, state: AnalysisState) -> str:
        """Build thread reference section for LLM prompt.
        
        Creates a mapping organized by DBG# (debugger thread index) for easy lookup.
        When users say 'thread 18', they mean DBG# 18 (used in ~18e commands).
        """
        thread_info = state.get('thread_info')
        if not thread_info:
            return ""
        
        threads = thread_info.get('threads', [])
        if not threads:
            return ""
        
        # Build compact reference table indexed by DBG#
        lines = [
            "\nTHREAD REFERENCE (indexed by DBG# - the number used in ~Xe commands):",
            "When user says 'thread X', X refers to DBG# (e.g., 'thread 18' means ~18e).",
            "Format: Thread DBG#: Managed ID X, OSID 0xY [special]",
        ]
        
        for t in threads[:50]:  # Limit to 50 threads for prompt size
            dbg_id = t.get('dbg_id', '')
            managed_id = t.get('managed_id', '')
            osid = t.get('osid', '')
            special = t.get('special', '')
            
            if special:
                lines.append(f"  Thread {dbg_id}: Managed ID {managed_id}, OSID 0x{osid} ({special})")
            else:
                lines.append(f"  Thread {dbg_id}: Managed ID {managed_id}, OSID 0x{osid}")
        
        if len(threads) > 50:
            lines.append(f"  ... and {len(threads) - 50} more threads")
        
        lines.append("")
        return "\n".join(lines)
    
    def reason(self, state: AnalysisState) -> dict:
        """Analyze all evidence and draw conclusions."""
        # Check if this is re-analysis after critique-triggered investigation
        if state.get('critique_triggered_investigation', False):
            console.print(f"\n[bold magenta]🧠 Re-analyzing with Newly Collected Evidence[/bold magenta]")
            console.print(f"[dim]Incorporating evidence from critic's investigation requests...[/dim]")
        else:
            # Determine if we're in synthesis mode (all hypotheses rejected)
            hypothesis_status = state.get('hypothesis_status', 'testing')
            all_rejected = hypothesis_status != 'confirmed' and len(state.get('hypothesis_tests', [])) > 0
            
            if all_rejected:
                console.print(f"\n[bold magenta]🔍 Synthesizing Findings from Evidence[/bold magenta]")
                console.print(f"[dim]All tested hypotheses ruled out - analyzing what the evidence actually shows...[/dim]")
            else:
                console.print(f"\n[bold magenta]🧠 Reasoning Over Evidence[/bold magenta]")
        
        evidence_inventory = state.get('evidence_inventory', {})
        total_evidence = sum(len(ev) for ev in evidence_inventory.values())
        
        console.print(f"[dim]Analyzing {total_evidence} pieces of evidence...[/dim]")
        
        # Deduplicate evidence by command (same command run multiple times across hypothesis tests)
        seen_commands = {}
        for task, evidence_list in evidence_inventory.items():
            for e in evidence_list:
                cmd = e.get('command', 'unknown')
                # Keep only the most recent instance of each command
                if cmd not in seen_commands:
                    seen_commands[cmd] = (task, e)
        
        console.print(f"[dim]Deduplicated to {len(seen_commands)} unique commands (from {total_evidence} total)[/dim]")
        
        # Build evidence summary for reasoning
        evidence_summary = []
        total_chars = 0
        MAX_TOTAL = 600000  # ~150K tokens for Claude Sonnet 4.5 (leave 50K for system prompt)
        
        # Group deduplicated evidence by task for readability
        task_groups = {}
        for cmd, (task, e) in seen_commands.items():
            if task not in task_groups:
                task_groups[task] = []
            task_groups[task].append((cmd, e))
        
        for task, cmd_evidence_list in task_groups.items():
            if total_chars >= MAX_TOTAL:
                evidence_summary.append(f"\n[Additional tasks truncated to stay within limits]")
                break
                
            evidence_summary.append(f"\n**Task: {task}**")
            for cmd, e in cmd_evidence_list:
                # Check if this is external evidence with analysis
                if e.get('evidence_type') == 'external' and e.get('summary'):
                    # Use analyzed summary for cost efficiency (already contains key findings)
                    output_preview = f"[Large output analyzed and stored externally]\nAnalysis: {e.get('summary')}"
                    if e.get('evidence_id'):
                        output_preview += f"\n[Full details available in: {e.get('evidence_id')}]"
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
        hypothesis_status = state.get('hypothesis_status', 'testing')
        for test in state.get('hypothesis_tests', []):
            result = test.get('result')
            result_str = result.upper() if result else 'PENDING'
            tests_summary.append(f"- {test['hypothesis']}: {result_str}")
        tests_text = "\n".join(tests_summary)
        
        # Determine analysis mode based on hypothesis status
        all_rejected = hypothesis_status != 'confirmed' and len(state.get('hypothesis_tests', [])) > 0
        analysis_mode_note = ""
        if all_rejected:
            analysis_mode_note = """
⚠️ ANALYSIS MODE: NO HYPOTHESIS CONFIRMED
All tested hypotheses were rejected by the evidence. This is a VALID OUTCOME - not every issue has evidence in the dump.

CRITICAL INSTRUCTIONS FOR REJECTED HYPOTHESES:
1. ANALYZE EVIDENCE OBJECTIVELY: Review all metrics (thread pool, memory, CPU, locks, etc.) without bias
2. DO NOT manufacture problems: Just because you have data doesn't mean there's a problem
3. Report observations neutrally using "HEALTHY" / "NORMAL" / "within expected range" when appropriate
4. If observations ARE concerning, explain WHY with expert assessment backing (severity, expected impact)
5. Let conclusion emerge from evidence - do NOT start with verdict and work backwards

FOLLOW BOTTOM-UP WORKFLOW:
Step 1: DETAILED_ANALYSIS - Analyze all evidence objectively (thread pool, memory, CPU, locks, resources)
Step 2: KEY_FINDINGS - Extract facts: "X idle workers - HEALTHY", "Y% Gen2 free - NORMAL", etc.
Step 3: SUMMARY - Conclude from findings: If all healthy, say "NO EVIDENCE FOUND"

EXAMPLE OF CORRECT BOTTOM-UP ANALYSIS:
User claimed: "Application has performance issues"

DETAILED_ANALYSIS:
"1. THREAD POOL STATE: !threadpool shows 28 idle workers out of 28 total, 0 work items queued, 6% CPU utilization. This indicates 100% available worker capacity with no queuing or saturation - HEALTHY state.

2. MEMORY STATE: !eeheap shows 1.5GB total heap with Gen2 at 1.2GB. !gcheapstat shows 15% free space in Gen2 across all heaps. This is within normal operational range for .NET applications under steady load - NORMAL.

3. CPU AND ACTIVITY: 6% CPU utilization with 28 idle workers indicates application is waiting for work, not processing work. No signs of computational bottleneck.

4. LOCK CONTENTION: !syncblk shows 0 contested locks, no threads blocked on Monitor.Enter. No synchronization bottlenecks detected.

5. RESOURCE HEALTH: !finalizequeue shows 37K objects pending finalization - within normal range for long-running applications. Finalizer thread is active and processing normally.

All tested hypotheses (thread exhaustion, GC pressure, lock contention) are contradicted by above evidence."

KEY_FINDINGS (extracted from analysis):
- "Thread pool: 28 idle workers, 0 queue depth - HEALTHY (from point 1)"
- "Memory: 1.5GB heap, 15% Gen2 free space - NORMAL (from point 2)"
- "CPU: 6% utilization - not under load (from point 3)"
- "No lock contention or blocking threads detected (from point 4)"

SUMMARY (conclusion from findings):
"NO EVIDENCE of performance issues found in this dump. All tested hypotheses were rejected by the evidence. Application metrics indicate healthy operation at time of dump capture."

❌ WRONG (top-down approach):
Starting with "NO EVIDENCE FOUND" and then cherry-picking metrics to support that verdict.
Manufacturing problems from observations: "Entity Framework memory leak with 1GB of objects causing GC pressure..."
"""
        
        # Check for critique feedback to address
        critique_result = state.get('critique_result', {})
        critique_section = ""
        if critique_result.get('issues_found'):
            critique_round = state.get('critique_round', 0)
            critical_issues = critique_result.get('critical_issues', [])
            evidence_gaps = critique_result.get('evidence_gaps', [])
            
            # Sanitize text to prevent JSON parsing issues - replace quotes with smart quotes
            def sanitize_text(text):
                return text.replace('"', '\“').replace("'", "\u2019")
            
            issues_text = "\n".join([f"- [{issue['type']}] {sanitize_text(issue['description'])}" for issue in critical_issues])
            
            # Format evidence gaps if present
            gaps_text = ""
            if evidence_gaps:
                gaps_text = "\n\nEVIDENCE GAPS ADDRESSED:\n"
                for gap_info in evidence_gaps:
                    gap_desc = gap_info.get('gap', 'Unknown gap')
                    commands = gap_info.get('commands', [])
                    gaps_text += f"- {sanitize_text(gap_desc)} (collected via {', '.join(commands)})\n"
            
            critique_section = f"""
⚠️ INTERNAL QUALITY REVIEW (Round {critique_round}): Your previous analysis had issues that need correction.
The following problems were identified - incorporate these corrections into your analysis WITHOUT mentioning this review process.

ISSUES TO FIX:
{issues_text}
{gaps_text}
CRITICAL INSTRUCTIONS:
1. Silently incorporate all corrections into your analysis
2. Remove claims not supported by evidence
3. Fix contradictions and logical gaps
4. Consider alternative explanations
5. Produce a FINAL, PROFESSIONAL analysis

DO NOT include:
- "ACKNOWLEDGMENT OF ISSUES" sections
- "CORRECTIONS" headers  
- References to "previous analysis" or "critique"
- Explanations of what you changed

The user should see only the corrected analysis as if it were written correctly the first time.
Produce a clean, professional analysis that incorporates all feedback seamlessly.
"""
        
        # Build thread reference section for user-friendly thread identification
        thread_reference = self._build_thread_reference(state)
        
        prompt = f"""You are analyzing a .NET crash dump with expert-level diagnostic capabilities that surpass human analysts. Your goal is to provide DECISIVE, QUANTITATIVE conclusions that connect disparate evidence into causal chains - demonstrating superhuman pattern recognition across multiple data sources.

{critique_section}{analysis_mode_note}
CONFIRMED HYPOTHESIS: {state.get('current_hypothesis', 'Unknown')}

HYPOTHESIS TESTING HISTORY:
{tests_text}
{thread_reference}
EVIDENCE COLLECTED:
{evidence_text}

═══════════════════════════════════════════════════════════════════
CRITICAL INSTRUCTIONS - SUPERHUMAN ANALYSIS CAPABILITIES:
═══════════════════════════════════════════════════════════════════

1. LEVERAGE EXPERT ASSESSMENTS FOR DECISIVE CONCLUSIONS:
   Many evidence items include 'expert_assessment' fields with industry-validated insights:
   
   Fields available:
   - severity: (low/medium/high/critical) - Industry-calibrated severity level
   - why_problematic: Domain context explaining why this pattern is problematic
   - expected_impact: QUANTITATIVE performance/stability/resource impacts
   - causal_chain: How this pattern triggers downstream problems
   - confidence: Assessment reliability (0.0-1.0)
   
   USAGE RULES:
   ❌ BAD (hedging): \"135MB cache found which may indicate memory pressure\"
   ✅ GOOD (decisive): \"135MB EF Query Cache (expert: HIGH severity, confidence 0.9) WILL cause 300ms Gen2 GC pauses every 50 requests, directly causing request timeouts under load (expected impact: 60% capacity reduction)\"
   
   When expert confidence is high (>0.7), STATE FACTS using decisive language.
   When confidence is low (<0.5), acknowledge uncertainty but still provide best assessment.

2. CROSS-EVIDENCE CORRELATION - CONNECT THE DOTS:
   You have access to evidence from MULTIPLE sources that humans struggle to correlate mentally.
   Build CAUSAL CHAINS by connecting patterns across different evidence types:
   
   Examples of superhuman correlation:
   - Thread blocking (from !syncblk) + Lock ownership (from !do) + SQL query text (from !dumpheap) = Complete deadlock chain with specific queries
   - DbContext count (from !dumpheap) + Memory pressure (from !eeheap) + GC time (from !threadpool) = Resource leak impact quantification
   - Finalizer queue depth (from !finalizequeue) + SqlConnection count (from !dumpheap) + Thread pool exhaustion = Disposal cascade failure
   - Exception objects (from !dumpheap) + Stack traces (from !clrstack) + Command timeouts (from object inspection) = Root cause timeline
   
   BUILD COMPLETE CAUSAL CHAINS:
   ✅ \"9000 undisposed DbContext instances (from !dumpheap -type DbContext) accumulate 180MB memory (45MB per 2.25K contexts based on expert assessment) → triggers Gen2 GC every 30 seconds (from !eeheap) → blocks all threads for 500ms (expert: high severity) → causes ASP.NET request timeouts (seen in 50 TimeoutException objects from !dumpheap -type TimeoutException) → cascade failure with 60% capacity loss\"

3. QUANTITATIVE IMPACT ANALYSIS - ALWAYS INCLUDE NUMBERS:
   Use expert assessments' \"expected_impact\" field for quantification, and correlate with actual observations:
   
   Pattern → Quantitative Impact:
   - \"X threads blocked\" → \"X threads * 1MB stack = YMB wasted + Z% CPU idle\"
   - \"N DbContext open\" → \"N * 20KB overhead = XMB memory + Y Gen2 collections/minute\"
   - \"Cache size X\" → \"GC pause Y ms at frequency Z\" (from expert assessment)
   - \"Q connection pool exhausted\" → \"P requests blocked, R% capacity reduction\"
   
   Cross-reference quantitative predictions with observed evidence:
   - Expert predicts \"300ms GC pause\" → Evidence shows \"!threadpool with 500ms work item delays\" → CONFIRMS prediction
   - Expert predicts \"180MB memory impact\" → Evidence shows \"!eeheap total 250MB, 180MB in Gen2\" → VALIDATES assessment

4. DECISIVE LANGUAGE BASED ON CONFIDENCE:
   Your language should reflect the strength of evidence and expert assessments:
   
   High Confidence (expert >0.8, multiple corroborating evidence):
   ✅ \"WILL cause\", \"directly causes\", \"leads to\", \"results in\", \"demonstrates\", \"proves\"
   ✅ \"The root cause IS...\", \"This pattern EXPLAINS...\", \"The evidence SHOWS...\"
   
   Medium Confidence (expert 0.5-0.8, some supporting evidence):
   ✅ \"likely causes\", \"strongly suggests\", \"indicates\", \"points to\"
   ✅ \"The most probable cause is...\", \"The evidence strongly indicates...\"
   
   Low Confidence (expert <0.5, limited corroboration):
   ✅ \"may contribute\", \"could indicate\", \"suggests possibility\"
   ✅ BUT STILL PROVIDE: \"Based on available evidence, the best assessment is...\"
   
   FORBIDDEN PHRASES (unless truly missing critical data):
   ❌ \"cannot verify\", \"unable to determine\", \"insufficient information\"
   ❌ \"might possibly\", \"could perhaps\", \"it's unclear whether\"

5. IDENTIFY INVESTIGATION GAPS:
   
   YOU MUST REQUEST INVESTIGATION if:
   ✅ Making claims about threads/handles/locks but !threads, !handle, or !syncblk are MISSING from evidence
   ✅ Discussing slowness/performance but !threadpool or CPU usage data is MISSING
   ✅ Claiming memory pressure but !eeheap, !dumpheap, or GC stats are MISSING
   ✅ Describing object behavior but concrete object inspection (!do, !dumpobj) is MISSING
   ✅ Mentioning exceptions but exception dump/stack traces are MISSING
   ✅ Any hypothesis about system state that lacks direct evidence from debugger commands
   
   AUTONOMOUS INVESTIGATION PRINCIPLE:
   If you identify a gap in evidence (e.g., "native handle enumeration is REQUIRED" or "thread analysis needed"),
   you MUST request that investigation using specific commands. NEVER state that something is "required" or "needed"
   without also requesting the investigation to collect it. The tool should autonomously collect missing evidence,
   not give up and blame incomplete data.
   
   You MAY SKIP investigation ONLY if:
   ✅ Expert assessments provide sufficient quantitative context
   ✅ Causal chains are already proven by existing evidence
   ✅ All baseline diagnostic commands for the hypothesis have been executed
   
   When requesting investigation, provide SPECIFIC commands:
   ✅ \"Use !threads to enumerate all threads and identify native handle usage patterns\"
   ✅ \"Use !handle to count total handles and identify handle leak patterns\"
   ✅ \"Use !finalizequeue to see finalization queue depth and object types\"
   ✅ \"Use !dumpheap -type SqlConnection then !do on 5 addresses to inspect connection state fields\"
   ✅ \"Use !do <timeout_exception_addr> to extract SqlCommand reference from _innerException field\"
   
   ❌ \"Inspect the finalization queue\" (missing command)
   ❌ \"Look at the connection objects\" (too vague)
   ❌ \"Thread analysis needed\" (no command specified)

FORMATTING REQUIREMENTS FOR ANALYSIS FIELD:
- Structure your analysis with numbered points (1., 2., 3., etc.)
- Each point should be a separate paragraph or finding
- Start each new point on a new line with the number
- Keep points focused and readable
- Include quantitative data in every point where applicable

Example format:
\"analysis\": \"1. RESOURCE LEAK PATTERN: 9000 undisposed DbContext instances (from !dumpheap) accumulate 180MB memory (expert: HIGH severity, confidence 0.95, expected impact: 20KB per instance). This exceeds normal operational range (50-100 instances) by 90x.\\n\\n2. CASCADING IMPACT: The memory pressure triggers Gen2 GC collections every 30 seconds (from !eeheap showing 180MB in Gen2 of 250MB total). Expert assessment predicts 500ms pause time for collections this size, CONFIRMED by !threadpool showing 500-600ms work item delays.\\n\\n3. ROOT CAUSE: Architectural design flaw where DbContext instances are captured in closures and never disposed (seen in !gcroot showing closure references). This DIRECTLY CAUSES the request timeouts observed in 50 TimeoutException objects.\"

CRITICAL: Return ONLY valid JSON. Do NOT use markdown, explanatory text, or formatting.
Do NOT start your response with # or any other text. Start directly with {{

ANALYSIS WORKFLOW (bottom-up):
1. ANALYZE EVIDENCE FIRST: Review all evidence objectively, look for patterns, correlations, metrics
2. EXTRACT KEY FINDINGS: Identify 3-5 most important facts/patterns from your analysis
3. SYNTHESIZE SUMMARY: Based on findings, write direct answer to user's question

DO NOT write summary first and cherry-pick evidence to support it.
DO NOT start with conclusion and work backwards.
START with evidence, END with summary.

REQUIRED OUTPUT STRUCTURE:
Return three sections in this JSON order (analysis workflow order):

1. DETAILED_ANALYSIS: Numbered analysis of ALL relevant evidence (this is your work)
2. KEY_FINDINGS: 3-5 bullet points extracted FROM your analysis (this is what you found)
3. SUMMARY: Direct answer derived FROM your findings (this is your conclusion)

ALIGNMENT RULES:
- Summary must be logical conclusion from key findings
- Key findings must be extracted from detailed analysis
- If analysis shows healthy metrics, findings must say "HEALTHY" and summary must say "NO PROBLEM"
- If analysis shows root cause, findings must prove it and summary must state it
- NEVER contradict between any sections
- Everything must trace back to specific evidence

Return JSON:

IF PROBLEM CONFIRMED:
{{
    \"detailed_analysis\": \"1. PRIMARY EVIDENCE: [Analyze the main evidence with command outputs and metrics]\\n\\n2. SUPPORTING EVIDENCE: [Analyze corroborating data]\\n\\n3. MECHANISM: [How the problem causes symptoms based on evidence]\\n\\n4. IMPACT: [Quantified effects from evidence]\\n\\n5. ALTERNATIVES RULED OUT: [What evidence contradicts other explanations]\",
    \"key_findings\": [
        \"Primary evidence proving root cause (extracted from point 1 above)\",
        \"Supporting evidence showing mechanism (extracted from point 2-3)\",
        \"Impact quantification (extracted from point 4)\",
        \"Alternative causes ruled out (extracted from point 5)\"
    ],
    \"summary\": \"ROOT CAUSE IDENTIFIED: [Problem name from findings]. [What's happening from findings]. [Impact from findings].\",
    \"confidence_level\": \"high|medium|low\",
    \"needs_deeper_investigation\": false,
    \"investigation_requests\": []
}}

IF ALL HYPOTHESES REJECTED (no problem found):
{{
    \"detailed_analysis\": \"1. THREAD POOL STATE: [Full analysis from !threadpool evidence]\\n\\n2. MEMORY STATE: [Full analysis from !eeheap evidence]\\n\\n3. CPU AND ACTIVITY: [Analysis of utilization evidence]\\n\\n4. LOCK CONTENTION: [Analysis showing no blocking]\\n\\n5. RESOURCE HEALTH: [Analysis of other health metrics]\\n\\nAll tested hypotheses were rejected by above evidence. Application shows healthy operational state at dump capture time.\",
    \"key_findings\": [
        \"Thread pool: X idle workers, 0 queue depth - HEALTHY (from point 1)\",
        \"Memory: X GB heap, Y% Gen2 free - NORMAL (from point 2)\",
        \"CPU: X% utilization - not under load (from point 3)\",
        \"No lock contention or blocking threads detected (from point 4)\"
    ],
    \"summary\": \"NO EVIDENCE of [user's reported issue] found in this dump. All tested hypotheses (list them) were rejected by the evidence. Application metrics indicate healthy operation at time of dump capture.\",
    \"confidence_level\": \"high\",
    \"needs_deeper_investigation\": false,
    \"investigation_requests\": []
}}

IF PROBLEM CONFIRMED BUT INCOMPLETE EVIDENCE:
{{
    \"detailed_analysis\": \"1. STRONG EVIDENCE: [Analyze what we found]\\n\\n2. SUPPORTING PATTERNS: [Analyze corroborating data]\\n\\n3. MISSING CORRELATION: [Analyze what specific data we need]\\n\\n4. ALTERNATIVE EXPLANATIONS: [Analyze what else could explain this]\\n\\n5. CONFIDENCE LIMITATION: [Why we can't be certain without missing data]\",
    \"key_findings\": [
        \"Strong evidence for root cause (from point 1): [specific metrics]\",
        \"Supporting pattern observed (from point 2): [data]\",
        \"Missing correlation (from point 3): [what we need to confirm]\",
        \"Confidence limited by (from point 5): [specific gap]\"
    ],
    \"summary\": \"LIKELY ROOT CAUSE: [Problem name from findings] based on available evidence, but additional correlation needed to confirm [specific missing link from findings].\",
    \"confidence_level\": \"medium\",
    \"needs_deeper_investigation\": true,
    \"investigation_requests\": [
        {{
            \"question\": \"Which SqlCommand objects correspond to the TimeoutException objects?\",
            \"context\": \"Found 50 TimeoutException and 100 SqlCommand objects but need to establish which commands caused which timeouts for complete causal chain\",
            \"approach\": \"Use !do on sample TimeoutException addresses to inspect _innerException and _stackTrace fields, extract SqlCommand references, then !do on those addresses to get command details\"
        }}
    ]
}}"""
        
        try:
            response = self.llm.invoke([
                SystemMessage(content="You are an expert at synthesizing crash dump evidence into actionable conclusions. You MUST respond ONLY with valid JSON, nothing else. No markdown, no explanations outside the JSON. Use \\n for newlines in string values, not literal newlines."),
                HumanMessage(content=prompt)
            ])
            
            # Extract JSON from response
            content = response.content.strip()
            if content.startswith('```'):
                parts = content.split('```')
                if len(parts) >= 2:
                    content = parts[1]
                    if content.startswith('json'):
                        content = content[4:]
            
            content = content.strip()
            
            # Try to parse JSON, handling control character issues
            try:
                result = json.loads(content)
            except json.JSONDecodeError as e:
                console.print(f"[yellow]⚠ JSON parse error: {e}[/yellow]")
                console.print(f"[yellow]Attempting to fix malformed JSON...[/yellow]")
                
                # The LLM likely output literal newlines in string values
                # Use a more lenient parser or fix the content
                # Strategy: parse with a library that handles this, or manually fix
                
                # Try using ast.literal_eval as fallback? No, that won't work for JSON
                # Instead, let's try to intelligently escape control chars in strings
                
                # Find the "analysis": "..." portion and fix it
                import re
                
                def escape_in_json_string(text):
                    """Escape control characters between JSON string quotes."""
                    result = []
                    in_string = False
                    escape_next = False
                    i = 0
                    
                    while i < len(text):
                        char = text[i]
                        
                        if escape_next:
                            result.append(char)
                            escape_next = False
                        elif char == '\\':
                            result.append(char)
                            escape_next = True
                        elif char == '"' and not escape_next:
                            in_string = not in_string
                            result.append(char)
                        elif in_string:
                            # We're inside a string, escape control characters
                            if char == '\n':
                                result.append('\\n')
                            elif char == '\r':
                                result.append('\\r')
                            elif char == '\t':
                                result.append('\\t')
                            elif char == '\b':
                                result.append('\\b')
                            elif char == '\f':
                                result.append('\\f')
                            else:
                                result.append(char)
                        else:
                            result.append(char)
                        
                        i += 1
                    
                    return ''.join(result)
                
                fixed_content = escape_in_json_string(content)
                result = json.loads(fixed_content)
                console.print(f"[green]✓ Fixed and parsed JSON successfully[/green]")
            
            console.print(f"[green]✓ Analysis complete[/green]")
            # Only show these messages if NOT in critique-triggered investigation mode
            if not state.get('critique_triggered_investigation', False):
                console.print(f"[dim]Confidence: {result['confidence_level']}[/dim]")
            
            # Check if deeper investigation is needed
            needs_deeper = result.get('needs_deeper_investigation', False)
            investigation_requests = result.get('investigation_requests', [])
            
            # Only show gaps if NOT in critique-triggered investigation mode
            if needs_deeper and investigation_requests:
                if not state.get('critique_triggered_investigation', False):
                    console.print(f"[yellow]🔍 Identified {len(investigation_requests)} gap(s) requiring deeper investigation[/yellow]")
                    for i, req in enumerate(investigation_requests, 1):
                        console.print(f"[dim]  {i}. {req.get('question', 'Unknown question')}[/dim]")
            
            # Extract new structured fields (with fallback to old format for backward compatibility)
            summary = result.get('summary', '')
            key_findings = result.get('key_findings', result.get('conclusions', []))
            detailed_analysis = result.get('detailed_analysis', result.get('analysis', ''))
            
            return {
                'analysis_summary': summary,
                'key_findings': key_findings,
                'reasoner_analysis': detailed_analysis,
                'conclusions': key_findings,  # For backward compatibility
                'confidence_level': result['confidence_level'],
                'needs_deeper_investigation': needs_deeper,
                'investigation_requests': investigation_requests,
                'reasoning_iterations': state.get('reasoning_iterations', 0) + 1
            }
            
        except Exception as e:
            console.print(f"[yellow]⚠ Reasoning error: {e}[/yellow]")
            # Show what the LLM actually returned for debugging
            try:
                if 'response' in locals():
                    console.print(f"[dim]LLM Response (first 500 chars): {response.content[:500]}...[/dim]")
            except:
                pass
            console.print(f"[yellow]Using fallback analysis[/yellow]")
            # Fallback - check actual hypothesis status
            hypothesis_status = state.get('hypothesis_status', 'testing')
            current_hyp = state.get('current_hypothesis', 'Unknown')
            
            if hypothesis_status == 'confirmed':
                conclusions = [
                    f"Hypothesis '{current_hyp}' was confirmed",
                    "Investigation completed across all planned tasks"
                ]
            elif hypothesis_status == 'rejected':
                conclusions = [
                    "All tested hypotheses were rejected by evidence",
                    f"Most recent hypothesis: {current_hyp}",
                    "Evidence analysis incomplete due to token limit - manual investigation may be needed"
                ]
            else:
                conclusions = [
                    f"Hypothesis testing in progress: {current_hyp}",
                    "Investigation ongoing"
                ]
            
            # Fallback
            return {
                'reasoner_analysis': f"Analyzed evidence from {len(evidence_inventory)} investigation tasks. Analysis truncated due to token limits.",
                'conclusions': conclusions,
                'confidence_level': 'low',  # Low confidence due to incomplete analysis
                'needs_deeper_investigation': hypothesis_status != 'confirmed',
                'investigation_requests': [],
                'reasoning_iterations': state.get('reasoning_iterations', 0) + 1
            }
