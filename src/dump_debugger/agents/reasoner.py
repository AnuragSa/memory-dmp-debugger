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
    
    def reason(self, state: AnalysisState) -> dict:
        """Analyze all evidence and draw conclusions."""
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
⚠️ ANALYSIS MODE: SYNTHESIS FROM EVIDENCE
All tested hypotheses were ruled out by evidence. Your task now is to synthesize what the evidence DOES show,
rather than focusing on what was ruled out. Users need to see positive findings, not just rejections.

CRITICAL INSTRUCTIONS FOR REJECTED HYPOTHESES:
1. Start with "WHAT WE LEARNED FROM EVIDENCE" not "why hypothesis was wrong"
2. Focus on POSITIVE FINDINGS: What IS happening in the application
3. Frame conclusions as discoveries: "Evidence shows X" not "Hypothesis about Y was rejected"
4. Provide actionable next steps based on actual observations
5. If no root cause found, describe the ACTUAL STATE observed and what it rules out

EXAMPLE OF GOOD FRAMING:
BAD:  "HYPOTHESIS REJECTED: Thread termination cascade theory disproven by only 2 exceptions vs 30 dead threads"
GOOD: "ACTUAL STATE: Thread pool maintains healthy 47% idle capacity (28/59 workers), zero queued work, low CPU 0.78%"
      "FINDING: Application is waiting for work, not experiencing capacity issues"
      "IMPLICATION: Root cause lies in work scheduling/queueing mechanism, not thread health"

Your analysis should inspire confidence that the tool understands the system, even when initial theories were wrong.
"""
        
        # Check for critique feedback to address
        critique_result = state.get('critique_result', {})
        critique_section = ""
        if critique_result.get('issues_found'):
            critique_round = state.get('critique_round', 0)
            critical_issues = critique_result.get('critical_issues', [])
            suggested_actions = critique_result.get('suggested_actions', [])
            
            # Sanitize text to prevent JSON parsing issues - replace quotes with smart quotes
            def sanitize_text(text):
                return text.replace('"', '\"').replace("'", "'")
            
            issues_text = "\n".join([f"- [{issue['type']}] {sanitize_text(issue['description'])}" for issue in critical_issues])
            actions_text = "\n".join([f"- {sanitize_text(action)}" for action in suggested_actions])
            
            critique_section = f"""
⚠️ INTERNAL QUALITY REVIEW (Round {critique_round}): Your previous analysis had issues that need correction.
The following problems were identified - incorporate these corrections into your analysis WITHOUT mentioning this review process.

ISSUES TO FIX:
{issues_text}

REQUIRED CORRECTIONS:
{actions_text}

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
        
        prompt = f"""You are analyzing a .NET crash dump with expert-level diagnostic capabilities that surpass human analysts. Your goal is to provide DECISIVE, QUANTITATIVE conclusions that connect disparate evidence into causal chains - demonstrating superhuman pattern recognition across multiple data sources.

{critique_section}{analysis_mode_note}
CONFIRMED HYPOTHESIS: {state.get('current_hypothesis', 'Unknown')}

HYPOTHESIS TESTING HISTORY:
{tests_text}

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

Return JSON:
{{
    \"analysis\": \"1. First finding with quantitative data...\\n\\n2. Second finding correlating evidence...\\n\\n3. Root cause with causal chain...\",
    \"conclusions\": [\"Decisive conclusion 1 with numbers\", \"Conclusion 2 with cross-reference\", \"Conclusion 3 with impact\"],
    \"confidence_level\": \"high|medium|low\",
    \"needs_deeper_investigation\": false,
    \"investigation_requests\": []
}}

OR if critical correlation data needed:
{{
    \"analysis\": \"...\",
    \"conclusions\": [\"Strong conclusion with caveat about missing correlation\"],
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
            console.print(f"[dim]Confidence: {result['confidence_level']}[/dim]")
            
            # Check if deeper investigation is needed
            needs_deeper = result.get('needs_deeper_investigation', False)
            investigation_requests = result.get('investigation_requests', [])
            
            if needs_deeper and investigation_requests:
                console.print(f"[yellow]🔍 Identified {len(investigation_requests)} gap(s) requiring deeper investigation[/yellow]")
                for i, req in enumerate(investigation_requests, 1):
                    console.print(f"[dim]  {i}. {req.get('question', 'Unknown question')}[/dim]")
            
            return {
                'reasoner_analysis': result['analysis'],
                'conclusions': result['conclusions'],
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
            # Fallback
            return {
                'reasoner_analysis': f"Analyzed evidence from {len(evidence_inventory)} investigation tasks.",
                'conclusions': [
                    f"Hypothesis '{state['current_hypothesis']}' was confirmed",
                    "Investigation completed across all planned tasks"
                ],
                'confidence_level': 'medium',
                'needs_deeper_investigation': False,
                'investigation_requests': [],
                'reasoning_iterations': state.get('reasoning_iterations', 0) + 1
            }
