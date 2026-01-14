"""
Report writer agent that generates final analysis reports.
"""
from rich.console import Console
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from dump_debugger.llm import get_llm
from dump_debugger.state import AnalysisState

console = Console()


class ReportWriterAgentV2:
    """Generates final analysis report."""
    
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
            "\n## THREAD REFERENCE",
            "Format: Thread DBG#: Managed ID X, OSID 0xY [special]",
            "DBG# is the number used in ~Xe commands (e.g., ~18e !clrstack)",
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
    
    def _format_analysis_text(self, text: str) -> str:
        """Format analysis text with proper bullet points for readability."""
        import re
        
        # Try pattern: "1. TEXT", "2. TEXT", etc. (most common from reasoner)
        # Look for number followed by period at start of line or after newline
        lines = text.split('\n')
        formatted_lines = []
        in_numbered_section = False
        
        for line in lines:
            stripped = line.strip()
            # Check if line starts with "N. " where N is a digit or digits
            match = re.match(r'^(\d+)\.\s+(.+)$', stripped)
            if match:
                number = match.group(1)
                content = match.group(2)
                formatted_lines.append(f"\n  • {content}")
                in_numbered_section = True
            elif stripped and in_numbered_section:
                # Continuation of previous point
                formatted_lines.append(f"    {stripped}")
            elif stripped:
                # Regular text
                if in_numbered_section:
                    formatted_lines.append(f"\n{stripped}")
                else:
                    formatted_lines.append(stripped)
                in_numbered_section = False
            else:
                # Blank line
                if formatted_lines and formatted_lines[-1] != '':
                    formatted_lines.append('')
        
        # If no "N." pattern found, try "(N)" pattern
        result = '\n'.join(formatted_lines)
        if not in_numbered_section:
            segments = re.split(r'\((\d+)\)', text)
            if len(segments) > 2:
                formatted_parts = []
                if segments[0].strip():
                    formatted_parts.append(segments[0].strip())
                i = 1
                while i < len(segments) - 1:
                    number = segments[i]
                    content = segments[i + 1].strip().strip(', ')
                    formatted_parts.append(f"\n  • {content}")
                    i += 2
                result = ''.join(formatted_parts)
        
        return result
    
    def show_analysis_summary(self, state: AnalysisState) -> dict:
        """Show comprehensive analysis in terminal without generating LLM report.
        
        Used in interactive mode to display all findings before Q&A session.
        Full LLM-generated report is only created when user explicitly requests it via /report.
        """
        console.print(f"\n[bold green]═══════════════════════════════════════════════════[/bold green]")
        console.print(f"[bold green]ANALYSIS COMPLETE[/bold green]")
        console.print(f"[bold green]═══════════════════════════════════════════════════[/bold green]\n")
        
        # Display comprehensive findings
        issue = state.get('issue_description', 'Unknown')
        hypothesis = state.get('current_hypothesis', 'Unknown')
        confidence = state.get('confidence_level', 'medium')
        conclusions = state.get('conclusions', [])
        analysis = state.get('reasoner_analysis', '')
        hypothesis_tests = state.get('hypothesis_tests', [])
        
        # Issue
        console.print(f"[bold cyan]Original Issue:[/bold cyan] {issue}\n")
        
        # Final Hypothesis
        console.print(f"[bold cyan]Final Hypothesis:[/bold cyan]")
        console.print(f"{hypothesis}")
        console.print(f"[bold cyan]Confidence:[/bold cyan] {confidence.upper()}\n")
        
        # Hypothesis Testing History
        if hypothesis_tests:
            console.print(f"[bold cyan]Hypothesis Testing Process:[/bold cyan]")
            for i, test in enumerate(hypothesis_tests, 1):
                result = test.get('result')
                result_str = result.upper() if result else 'PENDING'
                hyp = test.get('hypothesis', 'Unknown')
                
                if result == 'confirmed':
                    console.print(f"  {i}. [green]{hyp} → {result_str}[/green]")
                elif result == 'rejected':
                    console.print(f"  {i}. [red]{hyp} → {result_str}[/red]")
                else:
                    console.print(f"  {i}. [yellow]{hyp} → {result_str}[/yellow]")
                
                reasoning = test.get('evaluation_reasoning', '')
                if reasoning:
                    console.print(f"     [dim]{reasoning[:300]}[/dim]")
            console.print()
        
        # Key Conclusions
        if conclusions:
            console.print("[bold cyan]Key Conclusions:[/bold cyan]")
            for i, conclusion in enumerate(conclusions, 1):
                console.print(f"  {i}. {conclusion}")
            console.print()
        
        # Detailed Analysis
        if analysis:
            console.print("[bold cyan]Detailed Analysis:[/bold cyan]")
            # Format analysis with bullet points for readability
            formatted_analysis = self._format_analysis_text(analysis)
            console.print(formatted_analysis)
            console.print()
        
        # Show follow-up questions if critic found unresolved issues
        if state.get('has_unresolved_issues', False):
            critique_result = state.get('critique_result', {})
            questions = critique_result.get('suggested_questions', [])
            if questions:
                console.print("\n[bold yellow]🔍 Suggested Follow-Up Questions[/bold yellow]")
                console.print("[dim]Want to dig deeper? Here are specific questions you can ask:[/dim]\n")
                for i, question in enumerate(questions, 1):
                    console.print(f"  {i}. {question}")
                console.print()
        
        console.print("[dim]Type /report to generate a formatted report, or ask follow-up questions below.[/dim]\n")
        
        # Store a placeholder that report can be generated on demand
        return {
            'final_report': None,  # Will be generated on /report command
            'should_continue': False
        }
    
    def _generate_failure_report(self, state: AnalysisState) -> dict:
        """Generate report when all hypotheses were rejected - but show what we learned."""
        issue = state.get('issue_description', 'Unknown issue')
        hypothesis_tests = state.get('hypothesis_tests', [])
        analysis = state.get('reasoner_analysis', '')
        conclusions = state.get('conclusions', [])
        confidence = state.get('confidence_level', 'medium')
        
        # Build tested hypotheses list
        tested_hypotheses = []
        for i, test in enumerate(hypothesis_tests, 1):
            hyp = test['hypothesis']
            tested_hypotheses.append(f"{i}. {hyp}")
        
        tested_text = "\n".join(tested_hypotheses)
        
        # Build conclusions with confidence indicators
        conclusions_text = "\n".join([f"• {c}" for c in conclusions]) if conclusions else "• Evidence collected but root cause remains unclear"
        
        # Check if reasoner provided actionable findings despite rejections
        has_positive_findings = analysis and len(analysis) > 200
        
        if has_positive_findings:
            # We have substantial analysis - present as "what we learned"
            report = f"""
ANALYSIS COMPLETE - Root Cause Investigation
=============================================

Original Issue: {issue}

Investigation Path:
------------------
The analysis tested {len(hypothesis_tests)} hypotheses through systematic evidence collection:

{tested_text}

While these specific theories were ruled out by evidence, the investigation revealed important findings about the actual system state.

═══════════════════════════════════════════════════════════════════
FINDINGS FROM EVIDENCE
═══════════════════════════════════════════════════════════════════

{analysis}

Key Takeaways:
--------------
{conclusions_text}

Analysis Confidence: {confidence.upper()}

What This Means:
----------------
The systematic investigation ruled out several common failure patterns and collected concrete evidence about the system's actual state.
{self._interpret_confidence_level(confidence, has_ruling_out=True)}

Next Steps:
-----------
1. Review the "FINDINGS FROM EVIDENCE" section above - it describes what IS happening in the system
2. Compare findings against expected behavior for your application
3. Use interactive mode to drill deeper into specific observations
4. Consider if the issue might be in areas not yet explored (external dependencies, timing-sensitive conditions, etc.)

For deeper analysis, use the interactive mode to ask specific questions about the evidence collected.
"""
        else:
            # Minimal analysis - traditional failure report
            rejection_summary = []
            for i, test in enumerate(hypothesis_tests, 1):
                result = test.get('result', 'UNKNOWN')
                hyp = test['hypothesis']
                reasoning = test.get('evaluation_reasoning', 'No reasoning provided')[:300]
                rejection_summary.append(f"\n{i}. **{hyp}**\n   Result: {result.upper()}\n   Reason: {reasoning}...")
            
            rejection_text = "\n".join(rejection_summary)
            
            report = f"""
INVESTIGATION INCOMPLETE - Insufficient Evidence
================================================

Original Issue: {issue}

Investigation Summary:
---------------------
Tested {len(hypothesis_tests)} different hypotheses but none could be confirmed with the available evidence.

Hypotheses Tested:
{rejection_text}

Conclusion:
-----------
The investigation was unable to identify a confirmed root cause. This may indicate:

1. **Insufficient Evidence**: The dump may not contain the information needed to diagnose this issue
2. **Complex/Unknown Issue**: The problem may be outside the scope of tested hypotheses
3. **Multiple Contributing Factors**: The issue may involve interactions not captured by single hypotheses
4. **Dump Timing**: The dump may have been captured at a time that doesn't show the root cause

Recommendations:
----------------
1. Capture a new dump at the moment the issue occurs
2. Enable additional logging or diagnostics before reproducing
3. Review the rejection reasons above - they may provide clues about what's NOT the issue
4. Consider manual analysis with more specialized tools
5. Consult with domain experts familiar with the specific application/framework

For interactive analysis, you can ask specific questions about the dump data that was collected.
"""
        
        return {
            'final_report': report.strip(),
            'should_continue': False
        }
    
    def _interpret_confidence_level(self, confidence: str, has_ruling_out: bool = False) -> str:
        """Provide context for confidence level."""
        if has_ruling_out:
            # When we ruled things out
            interpretations = {
                'high': 'The evidence provides strong clarity about what is NOT causing the issue and clear observations about the actual system state.',
                'medium': 'The evidence rules out several possibilities and provides useful observations, though some aspects may need further investigation.',
                'low': 'The evidence provides some ruling-out value but may need additional data points for complete clarity.'
            }
        else:
            # When we confirmed something
            interpretations = {
                'high': 'The evidence provides strong support for the root cause identification with clear causal chains.',
                'medium': 'The evidence supports the findings but some aspects could benefit from additional validation.',
                'low': 'The findings are preliminary and should be validated with additional evidence.'
            }
        return interpretations.get(confidence, 'Confidence level indicates uncertainty in the analysis.')
    
    def generate_report(self, state: AnalysisState) -> dict:
        """Generate comprehensive analysis report."""
        console.print(f"\n[bold green]📊 Generating Final Report[/bold green]")
        
        # Check if we failed to confirm any hypothesis
        hypothesis_status = state.get('hypothesis_status', 'testing')
        hypothesis_tests = state.get('hypothesis_tests', [])
        
        if hypothesis_status != 'confirmed' and len(hypothesis_tests) > 0:
            # All hypotheses were rejected - generate failure report
            return self._generate_failure_report(state)
        
        # Build detailed report context
        hypothesis = state.get('current_hypothesis', 'Unknown')
        evidence = state.get('evidence_inventory', {})
        conclusions = state.get('conclusions', [])
        analysis = state.get('reasoner_analysis', '')
        confidence = state.get('confidence_level', 'medium')
        
        # Build hypothesis testing history
        test_history = []
        for i, test in enumerate(hypothesis_tests, 1):
            result = test.get('result')
            result_str = result.upper() if result else 'PENDING'
            test_history.append(f"{i}. {test['hypothesis']} → **{result_str}**")
            if test.get('evaluation_reasoning'):
                test_history.append(f"   {test['evaluation_reasoning'][:200]}")
        
        test_history_text = "\n".join(test_history)
        
        # Build evidence summary for comprehensive reporting
        evidence_summary = []
        total_chars = 0
        MAX_TOTAL = 800000  # ~200K tokens for Claude Sonnet 4.5
        
        for task, evidence_list in evidence.items():
            if total_chars >= MAX_TOTAL:
                evidence_summary.append(f"\n[Additional tasks omitted to stay within limits]")
                break
                
            evidence_summary.append(f"\n**{task}:**")
            for e in evidence_list:
                cmd = e.get('command', 'unknown')
                finding = e.get('finding', '')
                
                # Check if this is external evidence with analysis
                if e.get('evidence_type') == 'external' and e.get('summary'):
                    # Use analyzed summary for external evidence
                    output_preview = f"[Analyzed externally]\n{e.get('summary')}"
                else:
                    # Include full output for inline evidence
                    # Inline evidence is already kept at reasonable size (20KB max from storage)
                    output_preview = e.get('output', '')
                
                entry = f"- Command: {cmd}\n  Output: {output_preview}"
                if finding:
                    entry += f"\n  Finding: {finding}"
                    
                if total_chars + len(entry) > MAX_TOTAL:
                    evidence_summary.append("  [Remaining evidence omitted]")
                    break
                    
                evidence_summary.append(entry)
                total_chars += len(entry)
        
        evidence_text = "\n".join(evidence_summary)
        console.print(f"[dim]Prepared report evidence: {len(evidence_text)} chars (~{len(evidence_text)//4} tokens)[/dim]")
        conclusions_text = "\n".join(f"- {c}" for c in conclusions)
        
        # Build thread reference section for user-friendly thread identification
        thread_reference = self._build_thread_reference(state)
        
        context = f"""Generate a comprehensive crash dump analysis report.

## INVESTIGATION SUMMARY
**User Question:** {state['issue_description']}
**Dump Type:** {state.get('dump_type', 'unknown')}
**Final Hypothesis:** {hypothesis}
**Confidence:** {confidence.upper()}

## HYPOTHESIS TESTING PROCESS
{test_history_text}
{thread_reference}
## KEY EVIDENCE
{evidence_text}

## ANALYSIS
{analysis}

## CONCLUSIONS
{conclusions_text}

Create a professional report with:
1. **Executive Summary** - Brief overview for management
2. **Root Cause Analysis** - Detailed technical explanation of what caused the issue
3. **Evidence** - Key findings from the investigation
4. **Recommendations** - Specific actions to fix/prevent this issue
5. **Technical Details** - Important debugger outputs and observations

Write in clear, professional technical language.
"""

        try:
            # Use 5 minute timeout for report generation to handle large contexts
            config = RunnableConfig(timeout=300)  # 5 minute timeout
            
            response = self.llm.invoke([
                SystemMessage(content="You are an expert at writing technical crash analysis reports for Windows applications."),
                HumanMessage(content=context)
            ], config=config)
            
            report = response.content
            
            # Add follow-up questions if needed
            if state.get('has_unresolved_issues', False):
                critique_result = state.get('critique_result', {})
                interactive_mode = state.get('interactive_mode', False)
                report += self._append_critique_disclaimer(critique_result, interactive_mode)
            
            # Append chat history if interactive session occurred
            chat_history = state.get('chat_history', [])
            if chat_history:
                report += self._append_chat_section(chat_history)
            
            console.print("[green]✓ Report generated[/green]")
            
            return {
                'final_report': report,
                'should_continue': False
            }
        except Exception as e:
            console.print(f"\n[yellow]⚠ Report generation error: {e}[/yellow]")
            console.print(f"[yellow]Using fallback report format...[/yellow]\n")
            
            # Build fallback report with all available information
            fallback_report = f"""# Crash Dump Analysis Report

## Issue Description
{state['issue_description']}

## Final Hypothesis
{hypothesis}

## Confidence Level
{confidence.upper()}

## Key Conclusions
{conclusions_text if conclusions_text else 'No conclusions available'}

## Detailed Analysis
{analysis if analysis else 'No detailed analysis available'}

## Hypothesis Testing History
{test_history_text if test_history_text else 'No hypothesis tests recorded'}

---
*Note: This is a fallback report due to LLM timeout. Full report generation failed.*
"""
            
            # Append chat history if available
            chat_history = state.get('chat_history', [])
            if chat_history:
                fallback_report += self._append_chat_section(chat_history)
            
            # Add follow-up questions if needed
            if state.get('has_unresolved_issues', False):
                critique_result = state.get('critique_result', {})
                interactive_mode = state.get('interactive_mode', False)
                fallback_report += self._append_critique_disclaimer(critique_result, interactive_mode)
            
            console.print("[green]✓ Fallback report generated[/green]")
            
            return {
                'final_report': fallback_report,
                'should_continue': False
            }
    
    def _append_chat_section(self, chat_history: list) -> str:
        """Append interactive Q&A section to report.
        
        Args:
            chat_history: List of ChatMessage entries
            
        Returns:
            Formatted chat section as markdown
        """
        section = "\n\n---\n\n# Follow-up Questions & Answers\n\n"
        section += "The following questions were asked during the interactive analysis session:\n\n"
        
        # Group messages by Q&A pairs
        for i in range(0, len(chat_history), 2):
            if i + 1 < len(chat_history):
                user_msg = chat_history[i]
                assistant_msg = chat_history[i + 1]
                
                section += f"## Question {i//2 + 1}\n\n"
                section += f"**User:** {user_msg['content']}\n\n"
                section += f"**Answer:** {assistant_msg['content']}\n\n"
                
                # Add commands executed if any
                commands = assistant_msg.get('commands_executed', [])
                if commands:
                    section += "*Investigative commands executed:*\n"
                    for cmd in commands:
                        section += f"- `{cmd}`\n"
                    section += "\n"
        
        return section
    
    def _append_critique_disclaimer(self, critique_result: dict, interactive_mode: bool = False) -> str:
        """Generate follow-up questions section from critique.
        
        Args:
            critique_result: Result from critic agent with suggested_questions
            interactive_mode: Whether running in interactive mode
            
        Returns:
            Formatted questions section as markdown
        """
        questions = critique_result.get('suggested_questions', [])
        if not questions:
            return ""
        
        section = "\n\n---\n\n# 🔍 Suggested Follow-Up Questions\n\n"
        section += "Want to dig deeper? Here are specific questions you can ask to explore further:\n\n"
        
        for i, question in enumerate(questions, 1):
            section += f"{i}. {question}\n"
        
        section += "\n💡 **Tip:** Copy and paste these questions in the chat to investigate further"
        if not interactive_mode:
            section += ", or run with `-i` flag for interactive mode"
        section += ".\n"
        
        return section
