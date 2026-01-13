"""
Critic agent for reviewing analysis quality and identifying issues.
"""
import json
from typing import Any
from rich.console import Console
from langchain_core.messages import HumanMessage, SystemMessage

from dump_debugger.state import AnalysisState

console = Console()


class CriticAgent:
    """Reviews analysis output for quality and correctness issues."""
    
    def __init__(self, llm, max_rounds: int = 2):
        self.llm = llm
        self.max_rounds = max_rounds  # Configuration only, not mutable state
    
    def generate_follow_up_questions(self, critique_result: dict[str, Any], issue_description: str) -> list[str]:
        """Generate natural follow-up questions from critique issues.
        
        Args:
            critique_result: The critique findings
            issue_description: Original user question for context
            
        Returns:
            List of 3-5 natural follow-up questions
        """
        if not critique_result.get('issues_found', False):
            return []
        
        critical_issues = critique_result.get('critical_issues', [])
        if not critical_issues:
            return []
        
        # Format issues for LLM
        issues_text = "\n".join([
            f"- [{issue['type']}] {issue['description']}"
            for issue in critical_issues
        ])
        
        prompt = f"""Given these technical review findings from a crash dump analysis, generate 3-5 natural follow-up questions that a user could ask to clarify or resolve these issues.

ORIGINAL USER QUESTION:
{issue_description}

REVIEW FINDINGS:
{issues_text}

Generate questions that:
1. Are conversational and natural (as a user would ask)
2. Are specific and actionable
3. Focus on the most important gaps/contradictions
4. Can be answered with additional dump investigation
5. Help clarify or validate the analysis

Return ONLY a JSON array of question strings, nothing else:
["question 1", "question 2", "question 3"]"""
        
        try:
            response = self.llm.invoke([
                SystemMessage(content="You are an expert at converting technical critique into user-friendly questions. Return ONLY valid JSON."),
                HumanMessage(content=prompt)
            ])
            
            content = response.content.strip()
            if content.startswith('```'):
                parts = content.split('```')
                if len(parts) >= 2:
                    content = parts[1]
                    if content.startswith('json'):
                        content = content[4:]
            
            questions = json.loads(content.strip())
            return questions[:5]  # Max 5 questions
            
        except Exception as e:
            console.print(f"[dim]⚠ Failed to generate questions: {e}[/dim]")
            # Fallback: simple template-based questions
            return [
                f"Can you provide more evidence for the claims in the analysis?",
                f"What other factors could explain these findings?",
                f"Are there any contradictions in the evidence that need clarification?"
            ]
    
    def critique(self, state: AnalysisState) -> dict[str, Any]:
        """
        Review the analysis and identify critical issues.
        
        Args:
            state: Current analysis state
            
        Returns:
            Dictionary with critique results
        """
        current_round = state.get('critique_round', 0) + 1  # Pure: read from state
        
        # Only show header for first round (visible critique)
        # Second round is silent verification for follow-up questions only
        if current_round == 1:
            console.print(f"\n[bold magenta]🔍 Quality Review[/bold magenta]")
        
        # Get analysis components
        issue_description = state.get('issue_description', 'Unknown issue')
        hypothesis = state.get('current_hypothesis', 'Unknown')
        analysis = state.get('reasoner_analysis', '')
        conclusions = state.get('conclusions', [])
        confidence = state.get('confidence_level', 'medium')
        evidence = state.get('evidence_inventory', {})
        
        # Get Round 1 critique for Round 2 context
        previous_critique = state.get('critique_result', {})
        
        # Build evidence summary
        evidence_summary = []
        for cmd, results in evidence.items():
            if results and isinstance(results, list):
                evidence_summary.append(f"- {cmd}: {len(results)} result(s)")
        evidence_text = "\n".join(evidence_summary[:10])  # Limit to 10 items
        
        conclusions_text = "\n".join(f"- {c}" for c in conclusions)
        
        # Build Round 1 context for Round 2
        round1_context = ""
        if current_round == 2 and previous_critique.get('issues_found'):
            issues = previous_critique.get('critical_issues', [])
            round1_context = f"""
## ROUND 1 REVIEW (For your consideration)

The first reviewer identified {len(issues)} concern(s). Consider whether you agree:

"""
            for i, issue in enumerate(issues, 1):
                round1_context += f"{i}. [{issue.get('type', 'unknown')}] {issue.get('description', 'No description')}\n"
            
            round1_context += """
YOUR TASK: Provide an independent second opinion. You may:
- Agree with Round 1's concerns (confirm them)
- Disagree if you think the analysis is actually sound
- Find different issues Round 1 missed

"""
        
        prompt = f"""Review this crash dump analysis for CRITICAL issues only.

## CONTEXT

**Original User Question:** {issue_description}

The analysis must address THIS specific problem the user is trying to solve.
{round1_context}
## ANALYSIS TO REVIEW

**Hypothesis:** {hypothesis}
**Confidence:** {confidence.upper()}

**Conclusions:**
{conclusions_text}

**Analysis:**
{analysis}

**Evidence Collected:**
{evidence_text}

## YOUR TASK

Review for CRITICAL issues only. Flag issues that would MISLEAD the user:

### 1. ARCHITECTURAL ERRORS
- Does the analysis claim a technology does something it architecturally cannot do?
- Example: Claiming a monitoring library creates database connections when it uses HTTP
- Example: Claiming async code blocks threads when it uses continuation passing

### 2. EVIDENCE GAPS
- Are conclusions drawn WITHOUT supporting data shown in evidence?
- Example: Claiming "memory leak" but no heap growth timeline shown
- Example: Claiming "high GC pressure" but no GC stats collected

### 3. LOGICAL CONTRADICTIONS
- Do statements contradict each other?
- Does evidence contradict the conclusions?
- Example: "High memory usage" but heap shows 200MB

### 4. ALTERNATIVE EXPLANATIONS
- Is there an obvious alternative explanation not considered?
- Example: Static objects might be by design (caching), not leaks
- Example: Connection pooling behavior vs actual leak

## IMPORTANT
- Only flag CRITICAL issues that would mislead
- Don't nitpick minor wording
- Don't suggest "nice to have" additional investigation if conclusions are reasonable
- If analysis is sound and supported → return issues_found: false

## RESPONSE FORMAT

Return JSON only:
{{
    "issues_found": true/false,
    "critical_issues": [
        {{"type": "architectural|evidence_gap|contradiction|alternative", "description": "Specific issue"}},
        ...
    ],
    "suggested_actions": [
        "Specific command or revision needed",
        ...
    ],
    "severity": "high|medium|low"
}}

If no critical issues: {{"issues_found": false, "critical_issues": [], "suggested_actions": [], "severity": "low"}}
"""
        
        try:
            response = self.llm.invoke([
                SystemMessage(content="You are a SKEPTICAL technical reviewer. Your job is to find flaws, gaps, and unsupported claims. Return only JSON. Be thorough and critical - if ANY conclusion lacks evidence or has logical gaps, flag it."),
                HumanMessage(content=prompt)
            ])
            
            # Parse JSON response
            content = response.content.strip()
            if content.startswith('```'):
                parts = content.split('```')
                if len(parts) >= 2:
                    content = parts[1]
                    if content.startswith('json'):
                        content = content[4:]
            
            result = json.loads(content.strip())
            
            # Display results for both rounds
            if current_round == 1:
                if result.get('issues_found', False):
                    console.print(f"[yellow]⚠ Issues Found ({result.get('severity', 'medium')} severity)[/yellow]")
                    for issue in result.get('critical_issues', []):
                        issue_type = issue.get('type', 'unknown')
                        description = issue.get('description', '')
                        console.print(f"  • [{issue_type}] {description}")
                    
                    if result.get('suggested_actions'):
                        console.print("[dim]Suggested actions:[/dim]")
                        for action in result['suggested_actions']:
                            console.print(f"    - {action}")
                else:
                    console.print("[green]✓ No critical issues found[/green]")
            elif current_round == 2:
                # Round 2: Show second opinion
                if result.get('issues_found', False):
                    console.print(f"[yellow]⚠ Round 2: Confirmed concerns ({result.get('severity', 'medium')} severity)[/yellow]")
                    issue_count = len(result.get('critical_issues', []))
                    console.print(f"[dim]Second reviewer found {issue_count} issue(s)[/dim]")
                else:
                    console.print("[green]✓ Round 2: Second reviewer finds analysis acceptable[/green]")
            
            # Generate follow-up questions if this is the final round with issues
            suggested_questions = []
            if current_round >= self.max_rounds and result.get('issues_found', False):
                if current_round > 1:
                    # Round 2 with remaining issues - silent generation
                    console.print("\n[dim yellow]⚠ Some gaps remain - generating follow-up questions...[/dim yellow]")
                suggested_questions = self.generate_follow_up_questions(result, state.get('issue_description', 'Unknown issue'))
                result['suggested_questions'] = suggested_questions
            
            # Update state
            return {
                'critique_round': current_round,  # Pure: return state update
                'critique_result': result,
                'has_unresolved_issues': result.get('issues_found', False) and current_round >= self.max_rounds
            }
            
        except Exception as e:
            console.print(f"[yellow]⚠ Critique error: {e}[/yellow]")
            # On error, assume no issues and proceed
            current_round = state.get('critique_round', 0) + 1
            return {
                'critique_round': current_round,
                'critique_result': {'issues_found': False, 'critical_issues': [], 'suggested_actions': []},
                'has_unresolved_issues': False
            }
    
    def should_continue_critique(self, state: AnalysisState) -> bool:
        """Determine if another critique round is needed."""
        current_round = state.get('critique_round', 0)
        critique_result = state.get('critique_result', {})
        
        # Stop if max rounds reached
        if current_round >= self.max_rounds:
            return False
        
        # Stop if no issues found
        if not critique_result.get('issues_found', False):
            return False
        
        # Continue if issues found and under max rounds
        return True
