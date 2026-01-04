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
        for test in state.get('hypothesis_tests', []):
            result = test.get('result')
            result_str = result.upper() if result else 'PENDING'
            tests_summary.append(f"- {test['hypothesis']}: {result_str}")
        tests_text = "\n".join(tests_summary)
        
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
        
        prompt = f"""Analyze all the evidence from this crash dump investigation and draw conclusions.

{critique_section}
CONFIRMED HYPOTHESIS: {state.get('current_hypothesis', 'Unknown')}

HYPOTHESIS TESTING HISTORY:
{tests_text}

EVIDENCE COLLECTED:
{evidence_text}

Provide:
1. A holistic analysis of what the evidence reveals
2. Specific conclusions about the root cause
3. Your confidence level in these findings

FORMATTING REQUIREMENTS FOR ANALYSIS FIELD:
- Structure your analysis with numbered points (1., 2., 3., etc.)
- Each point should be a separate paragraph or finding
- Start each new point on a new line with the number
- Keep points focused and readable

Example format:
"analysis": "1. LOCK CONTENTION PATTERN: The evidence shows...\n\n2. THREAD POOL IMPACT: Multiple threads are blocked...\n\n3. ROOT CAUSE: The architectural design..."

CRITICAL: Return ONLY valid JSON. Do NOT use markdown, explanatory text, or formatting.
Do NOT start your response with # or any other text. Start directly with {{

Return JSON:
{{
    "analysis": "1. First finding with details...\n\n2. Second finding with details...\n\n3. Third finding...",
    "conclusions": ["Conclusion 1", "Conclusion 2", "Conclusion 3"],
    "confidence_level": "high|medium|low"
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
            
            return {
                'reasoner_analysis': result['analysis'],
                'conclusions': result['conclusions'],
                'confidence_level': result['confidence_level']
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
                'confidence_level': 'medium'
            }
