"""Evidence analyzer for chunking and LLM analysis of large outputs."""

import json
import time
from datetime import datetime
from typing import Any

from anthropic import RateLimitError
from langchain_core.messages import HumanMessage, SystemMessage
from rich.console import Console

from dump_debugger.config import settings
from dump_debugger.analyzers import get_analyzer, analyzer_registry
from dump_debugger.analyzer_stats import usage_tracker

console = Console()


class EvidenceAnalyzer:
    """Analyzes large debugger outputs in chunks using LLM."""
    
    def __init__(self, llm):
        """Initialize analyzer with LLM.
        
        Args:
            llm: LLM instance for analysis
        """
        self.llm = llm
    
    def analyze_evidence(
        self,
        command: str,
        output: str,
        intent: str,
        chunk_size: int = 8000
    ) -> dict:
        """Analyze output in chunks, tracking intent and findings.
        
        First tries specialized analyzer if available, then falls back to generic analysis.
        
        Args:
            command: Debugger command
            output: Command output
            intent: What we're looking for
            chunk_size: Maximum chunk size in characters
            
        Returns:
            Analysis dictionary with summary, findings, and trail
        """
        # Try specialized analyzer first
        specialized_analyzer = get_analyzer(command)
        start_time = time.time()
        
        if specialized_analyzer:
            console.print(f"[dim]Using specialized {specialized_analyzer.name} analyzer ({specialized_analyzer.tier.value})...[/dim]")
            try:
                result = specialized_analyzer.analyze(command, output)
                analysis_time_ms = (time.time() - start_time) * 1000
                
                # Record usage
                usage_tracker.record(
                    command=command,
                    analyzer_name=specialized_analyzer.name,
                    tier=specialized_analyzer.tier.value,
                    success=result.success,
                    analysis_time_ms=analysis_time_ms
                )
                
                if result.success:
                    return {
                        'summary': result.summary,
                        'key_findings': result.findings,
                        'blocking_operations': result.structured_data.get('blocking_operations', []),
                        'thread_states': result.structured_data.get('thread_states', []),
                        'analysis_trail': {
                            'intent': intent,
                            'command': command,
                            'output_size': len(output),
                            'analyzer': specialized_analyzer.name,
                            'tier': specialized_analyzer.tier.value,
                            'metadata': result.metadata,
                            'analysis_time_ms': analysis_time_ms,
                        },
                        'structured_data': result.structured_data,
                        'chunks': [(1, output, result.to_dict())]  # Single "chunk" for compatibility
                    }
                else:
                    console.print(f"[yellow]Specialized analyzer failed: {result.error}, falling back to generic analysis[/yellow]")
            except Exception as e:
                analysis_time_ms = (time.time() - start_time) * 1000
                usage_tracker.record(
                    command=command,
                    analyzer_name=specialized_analyzer.name,
                    tier=specialized_analyzer.tier.value,
                    success=False,
                    analysis_time_ms=analysis_time_ms
                )
                console.print(f"[yellow]Specialized analyzer error: {e}, falling back to generic analysis[/yellow]")
        
        # Record generic analysis - check if we missed an available analyzer
        analysis_time_ms = (time.time() - start_time) * 1000
        
        # Check if any analyzer could have handled this command (debugging)
        missed_analyzer = None
        for analyzer_info in analyzer_registry.list_analyzers():
            # Try to get the analyzer instance to test can_analyze
            from dump_debugger.analyzers import (
                ThreadsAnalyzer, SyncBlockAnalyzer, ThreadPoolAnalyzer,
                FinalizeQueueAnalyzer, EEHeapAnalyzer, DumpHeapAnalyzer,
                GCHandlesAnalyzer, CLRStackAnalyzer, GCRootAnalyzer, DOAnalyzer
            )
            analyzer_map = {
                "threads": ThreadsAnalyzer,
                "syncblk": SyncBlockAnalyzer,
                "threadpool": ThreadPoolAnalyzer,
                "finalizequeue": FinalizeQueueAnalyzer,
                "eeheap": EEHeapAnalyzer,
                "dumpheap": DumpHeapAnalyzer,
                "gchandles": GCHandlesAnalyzer,
                "clrstack": CLRStackAnalyzer,
                "gcroot": GCRootAnalyzer,
                "do": DOAnalyzer,
            }
            
            if analyzer_info["name"] in analyzer_map:
                try:
                    temp_analyzer = analyzer_map[analyzer_info["name"]]()
                    if temp_analyzer.can_analyze(command):
                        missed_analyzer = analyzer_info["name"]
                        console.print(f"[red]⚠️ WARNING: {analyzer_info['name']} analyzer exists but wasn't matched![/red]")
                        break
                except:
                    pass
        
        usage_tracker.record(
            command=command,
            analyzer_name=None,
            tier=None,
            success=True,  # Will be updated if fails
            analysis_time_ms=analysis_time_ms,
            missed_opportunity=missed_analyzer is not None,
            available_analyzer=missed_analyzer
        )
        
        # Fall back to generic chunk-based analysis
        analysis_trail = {
            'intent': intent,
            'command': command,
            'output_size': len(output),
            'chunk_analyses': [],
            'overall_findings': None
        }
        
        # Chunk the output
        chunks = self._smart_chunk(output, chunk_size)
        console.print(f"[dim]Analyzing {len(chunks)} chunk(s) of output...[/dim]")
        
        # Analyze each chunk
        chunk_findings = []
        for i, chunk in enumerate(chunks):
            if len(chunks) > 1:
                console.print(f"[dim]  Chunk {i+1}/{len(chunks)}...[/dim]")
            
            # Add delay between chunks to avoid rate limits (skip first chunk)
            if i > 0 and len(chunks) > 5:
                delay = settings.chunk_analysis_delay
                time.sleep(delay)  # Configurable delay for large multi-chunk analyses
            
            finding = self._analyze_chunk(
                command=command,
                chunk=chunk,
                chunk_num=i+1,
                total_chunks=len(chunks),
                intent=intent,
                previous_findings=chunk_findings[-2:]  # Last 2 for context
            )
            
            chunk_findings.append(finding)
            analysis_trail['chunk_analyses'].append({
                'chunk_num': i+1,
                'finding': finding,
                'timestamp': datetime.now().isoformat()
            })
        
        # Synthesize overall findings
        if len(chunks) > 1:
            console.print(f"[dim]  Synthesizing findings...[/dim]")
            overall = self._synthesize_findings(
                intent=intent,
                command=command,
                chunk_findings=chunk_findings
            )
        else:
            # Single chunk - use its findings directly
            overall = chunk_findings[0]
        
        analysis_trail['overall_findings'] = overall
        
        return {
            'summary': overall.get('summary', ''),
            'key_findings': overall.get('findings', []),
            'blocking_operations': overall.get('blocking_operations', []),
            'thread_states': overall.get('thread_states', []),
            'analysis_trail': analysis_trail,
            'chunks': [(i+1, chunk, finding) for i, (chunk, finding) in enumerate(zip(chunks, chunk_findings))]
        }
    
    def _smart_chunk(self, text: str, max_size: int) -> list[str]:
        """Chunk text intelligently at line boundaries.
        
        Args:
            text: Text to chunk
            max_size: Maximum chunk size
            
        Returns:
            List of chunks
        """
        if len(text) <= max_size:
            return [text]
        
        chunks = []
        lines = text.split('\n')
        current_chunk = []
        current_size = 0
        
        for line in lines:
            line_size = len(line) + 1  # +1 for newline
            
            if current_size + line_size > max_size and current_chunk:
                # Save current chunk
                chunks.append('\n'.join(current_chunk))
                current_chunk = []
                current_size = 0
            
            current_chunk.append(line)
            current_size += line_size
        
        # Add final chunk
        if current_chunk:
            chunks.append('\n'.join(current_chunk))
        
        return chunks
    
    def _analyze_chunk(
        self,
        command: str,
        chunk: str,
        chunk_num: int,
        total_chunks: int,
        intent: str,
        previous_findings: list[dict]
    ) -> dict:
        """Analyze a single chunk with context from previous chunks.
        
        Args:
            command: Debugger command
            chunk: Text chunk to analyze
            chunk_num: Current chunk number
            total_chunks: Total number of chunks
            intent: Analysis intent
            previous_findings: Findings from previous chunks
            
        Returns:
            Analysis dictionary
        """
        context = ""
        if previous_findings:
            context = "Previous chunks found:\n"
            for pf in previous_findings:
                summary = pf.get('summary', '')
                if summary:
                    context += f"- {summary}\n"
        
        prompt = f"""Analyze this debugger output chunk (part {chunk_num}/{total_chunks}).

INTENT: {intent}
COMMAND: {command}

{context}

CHUNK DATA:
{chunk}

Extract relevant information:
1. Any blocking operations (I/O, locks, waits, synchronization)
2. Thread IDs and their states
3. Exception messages or error conditions
4. Relevant call stack frames (methods, namespaces)
5. Memory addresses (locks, objects, handles)
6. Any patterns or anomalies

Return JSON:
{{
    "summary": "Brief summary of findings in this chunk",
    "findings": ["specific finding 1", "specific finding 2"],
    "blocking_operations": [{{"thread_id": "X", "operation": "Y"}}],
    "thread_states": [{{"thread_id": "X", "state": "Y"}}],
    "exceptions": ["exception messages if any"],
    "needs_more_context": true/false
}}

Be specific and precise. Extract actual values (thread IDs, addresses, method names)."""

        messages = [
            SystemMessage(content="You are an expert Windows debugger analyst. Extract precise technical details from debugger output."),
            HumanMessage(content=prompt)
        ]
        
        # Retry logic for rate limit errors
        max_retries = 3
        retry_delay = 5  # Start with 5 seconds
        
        for attempt in range(max_retries):
            try:
                response = self.llm.invoke(messages)
                return self._extract_json(response.content) or {
                    'summary': 'Analysis failed',
                    'findings': [],
                    'blocking_operations': [],
                    'thread_states': []
                }
            except RateLimitError as e:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                    console.print(f"[yellow]⚠ Rate limit hit, waiting {wait_time}s before retry {attempt + 1}/{max_retries}...[/yellow]")
                    time.sleep(wait_time)
                else:
                    console.print(f"[red]✗ Rate limit exceeded after {max_retries} retries[/red]")
                    raise
            except Exception as e:
                console.print(f"[red]✗ Error analyzing chunk: {e}[/red]")
                return {
                    'summary': f'Analysis error: {str(e)}',
                    'findings': [],
                    'blocking_operations': [],
                    'thread_states': []
                }
        
        # Should not reach here but just in case
        return {
            'summary': 'Analysis failed after retries',
            'findings': [],
            'blocking_operations': [],
            'thread_states': []
        }
    
    def _synthesize_findings(
        self,
        intent: str,
        command: str,
        chunk_findings: list[dict]
    ) -> dict:
        """Combine chunk findings into overall conclusion.
        
        Args:
            intent: Analysis intent
            command: Debugger command
            chunk_findings: List of findings from all chunks
            
        Returns:
            Synthesized findings dictionary
        """
        all_findings_text = "\n\n".join([
            f"Chunk {i+1}:\nSummary: {f.get('summary', 'N/A')}\nFindings: {', '.join(f.get('findings', []))}"
            for i, f in enumerate(chunk_findings)
        ])
        
        prompt = f"""Synthesize findings from {len(chunk_findings)} analyzed chunks into an overall conclusion.

INTENT: {intent}
COMMAND: {command}

CHUNK FINDINGS:
{all_findings_text}

Create overall conclusion:
1. What is the KEY finding across all chunks?
2. What specific operations/issues were identified?
3. Which threads/objects are involved?
4. What is the likely root cause or significant pattern?

Return JSON:
{{
    "summary": "Overall finding across all chunks",
    "findings": ["key finding 1", "key finding 2", "key finding 3"],
    "blocking_operations": [{{"thread_id": "X", "operation": "Y"}}],
    "thread_states": [{{"thread_id": "X", "state": "Y"}}],
    "root_cause": "Likely root cause if identifiable"
}}"""

        messages = [
            SystemMessage(content="You are an expert at synthesizing technical analysis results."),
            HumanMessage(content=prompt)
        ]
        
        # Retry logic for rate limit errors
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                response = self.llm.invoke(messages)
                return self._extract_json(response.content) or {
                    'summary': 'Synthesis failed',
                    'findings': [],
                    'blocking_operations': [],
                    'thread_states': []
                }
            except RateLimitError as e:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    console.print(f"[yellow]⚠ Rate limit hit during synthesis, waiting {wait_time}s...[/yellow]")
                    time.sleep(wait_time)
                else:
                    console.print(f"[red]✗ Rate limit exceeded during synthesis[/red]")
                    raise
            except Exception as e:
                console.print(f"[red]✗ Error synthesizing findings: {e}[/red]")
                return {
                    'summary': f'Synthesis error: {str(e)}',
                    'findings': [],
                    'blocking_operations': [],
                    'thread_states': []
                }
        
        return {
            'summary': 'Synthesis failed after retries',
            'findings': [],
            'blocking_operations': [],
            'thread_states': []
        }
    
    def _extract_json(self, text: str) -> dict | None:
        """Extract JSON from LLM response.
        
        Args:
            text: Response text
            
        Returns:
            Parsed JSON or None
        """
        # Try direct parse
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
                    try:
                        json_str = text[start_idx:i+1]
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        continue
        
        return None
