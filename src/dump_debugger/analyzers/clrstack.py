"""CLR stack analyzer (Tier 3 - LLM-heavy for deep context analysis)."""

import re
from typing import Any, Dict, List

from dump_debugger.analyzers.base import AnalysisResult, AnalyzerTier, BaseAnalyzer, TaskComplexity


class CLRStackAnalyzer(BaseAnalyzer):
    """Analyzer for !CLRStack command output.
    
    Tier 3: LLM-heavy - requires deep understanding of stack context,
    exception chains, local variables, and execution flow.
    Uses cloud LLM for comprehensive analysis.
    """
    
    name = "clrstack"
    description = "Analyzes !CLRStack output for stack traces, exceptions, and execution context"
    tier = AnalyzerTier.TIER_3
    supported_commands = ["!clrstack", "!eestack", "~*e !clrstack"]
    
    def can_analyze(self, command: str) -> bool:
        """Check if this is a !clrstack command."""
        cmd = command.strip().lower()
        return "!clrstack" in cmd or "!eestack" in cmd
    
    def analyze(self, command: str, output: str) -> AnalysisResult:
        """Analyze !CLRStack output.
        
        Example output:
        ```
        OS Thread Id: 0x1234 (1)
        Child SP               IP Call Site
        000000abc1234567 00007ff8a1b2c3d0 System.Threading.Monitor.Wait(System.Object, Int32, Boolean)
        000000abc1234568 00007ff8a1b2c4e0 System.Threading.ManualResetEventSlim.Wait(Int32, System.Threading.CancellationToken)
        000000abc1234569 00007ff8a1b2c5f0 MyApp.Worker.ProcessQueue() [C:\\Source\\MyApp\\Worker.cs @ 45]
        
        Exception object: 000001f2a3b4c5d6
        Exception type:   System.InvalidOperationException
        Message:          Collection was modified; enumeration operation may not execute.
        ```
        
        Returns:
            AnalysisResult with stack analysis
        """
        try:
            # Check if this is multi-thread output
            is_multi_thread = "~*e" in command.lower()
            
            if is_multi_thread:
                return self._analyze_all_threads(output)
            else:
                return self._analyze_single_thread(output)
        
        except Exception as e:
            return AnalysisResult(
                structured_data={},
                summary="",
                findings=[],
                metadata={"analyzer": self.name, "tier": self.tier.value},
                success=False,
                error=f"Failed to analyze CLR stack: {str(e)}",
            )
    
    def _analyze_single_thread(self, output: str) -> AnalysisResult:
        """Analyze single thread stack."""
        # Parse stack frames (code parsing)
        frames = self._parse_stack_frames(output)
        exception = self._parse_exception_info(output)
        locals_vars = self._parse_local_variables(output)
        
        # Use cloud LLM for deep analysis (complex task)
        llm = self.get_llm(TaskComplexity.COMPLEX)
        analysis = self._deep_stack_analysis(llm, frames, exception, locals_vars, output)
        
        # Generate summary
        thread_id = self._extract_thread_id(output)
        summary = (
            f"Thread {thread_id} stack has {len(frames)} frames. "
            f"{analysis['summary']}"
        )
        
        # Generate findings
        findings = [
            f"Stack depth: {len(frames)} frames",
        ]
        
        if exception:
            findings.append(f"Exception: {exception['type']} - {exception['message']}")
        
        if analysis.get("root_cause"):
            findings.append(f"Root cause: {analysis['root_cause']}")
        
        findings.extend(analysis.get("insights", []))
        
        return AnalysisResult(
            structured_data={
                "thread_id": thread_id,
                "frames": frames,
                "exception": exception,
                "local_variables": locals_vars,
                "analysis": analysis,
            },
            summary=summary,
            findings=findings,
            metadata={
                "analyzer": self.name,
                "tier": self.tier.value,
                "frame_count": len(frames),
            },
            success=True,
        )
    
    def _analyze_all_threads(self, output: str) -> AnalysisResult:
        """Analyze all thread stacks (from ~*e !clrstack)."""
        # Split output by thread
        thread_outputs = self._split_by_thread(output)
        
        # Analyze each thread
        thread_analyses = []
        exceptions_found = []
        
        for thread_output in thread_outputs:
            thread_id = self._extract_thread_id(thread_output)
            frames = self._parse_stack_frames(thread_output)
            exception = self._parse_exception_info(thread_output)
            
            thread_analyses.append({
                "thread_id": thread_id,
                "frame_count": len(frames),
                "has_exception": exception is not None,
                "frames": frames[:5],  # Limit to top 5 frames per thread
            })
            
            if exception:
                exceptions_found.append({
                    "thread_id": thread_id,
                    "exception": exception,
                })
        
        # Use cloud LLM to find patterns across threads
        llm = self.get_llm(TaskComplexity.COMPLEX)
        cross_thread_analysis = self._analyze_thread_patterns(llm, thread_analyses, exceptions_found)
        
        # Generate summary
        summary = (
            f"Analyzed {len(thread_analyses)} threads. "
            f"{len(exceptions_found)} threads have exceptions. "
            f"{cross_thread_analysis['summary']}"
        )
        
        # Generate findings
        findings = [
            f"Total threads analyzed: {len(thread_analyses)}",
            f"Threads with exceptions: {len(exceptions_found)}",
        ]
        
        findings.extend(cross_thread_analysis.get("insights", []))
        
        return AnalysisResult(
            structured_data={
                "thread_count": len(thread_analyses),
                "threads": thread_analyses,
                "exceptions": exceptions_found,
                "cross_thread_analysis": cross_thread_analysis,
            },
            summary=summary,
            findings=findings,
            metadata={
                "analyzer": self.name,
                "tier": self.tier.value,
                "thread_count": len(thread_analyses),
            },
            success=True,
        )
    
    def _parse_stack_frames(self, output: str) -> List[Dict[str, Any]]:
        """Parse stack frames from output."""
        frames = []
        lines = output.split('\n')
        
        # Pattern: Child SP               IP Call Site
        # Example: 000000abc1234567 00007ff8a1b2c3d0 System.Threading.Monitor.Wait(...)
        frame_pattern = re.compile(
            r'^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+(.+?)(?:\s+\[(.+?)\s+@\s+(\d+)\])?$'
        )
        
        for line in lines:
            match = frame_pattern.match(line.strip())
            if match:
                frame = {
                    "child_sp": match.group(1),
                    "ip": match.group(2),
                    "call_site": match.group(3).strip(),
                }
                
                # Add source location if present
                if match.group(4):
                    frame["source_file"] = match.group(4)
                    frame["line_number"] = int(match.group(5))
                
                frames.append(frame)
        
        return frames
    
    def _parse_exception_info(self, output: str) -> Dict[str, str] | None:
        """Parse exception information if present."""
        exception = {}
        
        # Look for exception patterns
        obj_match = re.search(r'Exception object:\s+([0-9a-fA-F]+)', output)
        type_match = re.search(r'Exception type:\s+(.+)', output)
        msg_match = re.search(r'Message:\s+(.+)', output)
        
        if obj_match and type_match:
            exception["object"] = obj_match.group(1)
            exception["type"] = type_match.group(1).strip()
            exception["message"] = msg_match.group(1).strip() if msg_match else ""
            return exception
        
        return None
    
    def _parse_local_variables(self, output: str) -> Dict[str, str]:
        """Parse local variables if present (from -l flag)."""
        # Pattern: LOCALS: name = value
        locals_dict = {}
        
        in_locals = False
        for line in output.split('\n'):
            if "LOCALS:" in line or "PARAMETERS:" in line:
                in_locals = True
                continue
            
            if in_locals and "=" in line:
                parts = line.strip().split('=', 1)
                if len(parts) == 2:
                    locals_dict[parts[0].strip()] = parts[1].strip()
        
        return locals_dict
    
    def _extract_thread_id(self, output: str) -> str:
        """Extract thread ID from output."""
        match = re.search(r'OS Thread Id:\s+0x([0-9a-fA-F]+)', output)
        if match:
            return match.group(1)
        
        match = re.search(r'Thread\s+(\d+)', output)
        if match:
            return match.group(1)
        
        return "Unknown"
    
    def _split_by_thread(self, output: str) -> List[str]:
        """Split multi-thread output into individual thread outputs."""
        # Split on "OS Thread Id:" markers
        parts = re.split(r'(OS Thread Id:)', output)
        
        thread_outputs = []
        for i in range(1, len(parts), 2):
            if i + 1 < len(parts):
                thread_outputs.append(parts[i] + parts[i + 1])
        
        return thread_outputs
    
    def _deep_stack_analysis(
        self,
        llm: Any,
        frames: List[Dict[str, Any]],
        exception: Dict[str, str] | None,
        locals_vars: Dict[str, str],
        full_output: str,
    ) -> Dict[str, Any]:
        """Use cloud LLM for deep stack analysis.
        
        This is a complex task requiring:
        - Understanding exception context
        - Analyzing call chain
        - Identifying root cause
        - Suggesting fixes
        """
        # Build prompt with stack context
        stack_summary = "\n".join(
            f"{i+1}. {frame['call_site']}"
            for i, frame in enumerate(frames[:10])
        )
        
        exception_info = ""
        if exception:
            exception_info = f"\nException: {exception['type']}\nMessage: {exception['message']}"
        
        prompt = f"""Analyze this .NET stack trace and provide insights:

Stack Trace:
{stack_summary}
{exception_info}

Provide:
1. A 1-sentence summary of what this thread was doing
2. Root cause if there's an exception (1 sentence)
3. Key insights (2-3 bullet points)

Be concise and technical. Focus on actionable information."""
        
        try:
            response = llm.invoke(prompt)
            content = response.content.strip()
            
            # Parse LLM response
            lines = content.split('\n')
            summary_line = lines[0] if lines else "Stack analysis complete."
            
            return {
                "summary": summary_line,
                "root_cause": exception['message'] if exception else None,
                "insights": [line.strip('- ').strip() for line in lines[1:] if line.strip()],
                "full_analysis": content,
            }
        
        except Exception:
            # Fallback if LLM fails
            return {
                "summary": "Thread was executing application code.",
                "root_cause": exception['message'] if exception else None,
                "insights": ["Stack analysis completed"],
                "full_analysis": "",
            }
    
    def _analyze_thread_patterns(
        self,
        llm: Any,
        thread_analyses: List[Dict[str, Any]],
        exceptions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Analyze patterns across multiple threads."""
        # Build summary of threads
        thread_summary = "\n".join(
            f"Thread {t['thread_id']}: {t['frame_count']} frames" +
            (" [EXCEPTION]" if t['has_exception'] else "")
            for t in thread_analyses[:20]  # Limit to 20 threads
        )
        
        exception_summary = "\n".join(
            f"Thread {e['thread_id']}: {e['exception']['type']}"
            for e in exceptions[:10]
        )
        
        prompt = f"""Analyze these thread stacks for patterns:

Threads:
{thread_summary}

Exceptions:
{exception_summary if exceptions else "None"}

Identify:
1. Common patterns (deadlocks, thread pool starvation, etc.)
2. Concerning trends
3. Recommendations (1-2 sentences max)

Be concise."""
        
        try:
            response = llm.invoke(prompt)
            content = response.content.strip()
            
            lines = content.split('\n')
            summary_line = lines[0] if lines else "Multi-thread analysis complete."
            
            return {
                "summary": summary_line,
                "insights": [line.strip('- ').strip() for line in lines[1:] if line.strip()],
                "full_analysis": content,
            }
        
        except Exception:
            return {
                "summary": "Thread analysis completed.",
                "insights": [],
                "full_analysis": "",
            }
