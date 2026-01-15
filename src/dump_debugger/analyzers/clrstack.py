"""CLR stack analyzer (Tier 3 - LLM-heavy for deep context analysis)."""

import re
from typing import Any, Dict, List

from dump_debugger.analyzers.base import AnalysisResult, AnalyzerTier, BaseAnalyzer, LLMInvocationError, TaskComplexity
from dump_debugger.utils.thread_registry import get_thread_registry


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
        analysis = self._deep_stack_analysis(frames, exception, locals_vars, output)
        
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
        cross_thread_analysis = self._analyze_thread_patterns(thread_analyses, exceptions_found)
        
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
        
        # Add concrete example stacks for threads with interesting patterns
        # This gives the LLM detailed diagnostic data instead of just summaries
        example_stacks = self._get_example_stacks(thread_analyses, exceptions_found)
        if example_stacks:
            findings.append("\nExample thread stacks:")
            findings.extend(example_stacks)
        
        # Add concrete example stacks for threads with interesting patterns
        # This gives the LLM detailed diagnostic data instead of just summaries
        example_stacks = self._get_example_stacks(thread_analyses, exceptions_found)
        if example_stacks:
            findings.append("\nExample thread stacks:")
            findings.extend(example_stacks)
        
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
        """Extract thread ID from output and return user-friendly display.
        
        Extracts the OSID from output and looks up the managed ID from 
        the thread registry (populated by !threads analyzer).
        
        Returns:
            User-friendly thread identifier (managed ID if available, OSID otherwise)
        """
        match = re.search(r'OS Thread Id:\s+0x([0-9a-fA-F]+)', output)
        if match:
            osid = match.group(1)
            # Look up managed ID from registry
            registry = get_thread_registry()
            info = registry.get_by_osid(osid)
            if info:
                return str(info.managed_id)
            # Fallback to OSID if not in registry
            return f"OSID 0x{osid}"
        
        match = re.search(r'Thread\s+(\d+)', output)
        if match:
            return match.group(1)
        
        return "Unknown"
    
    def _extract_raw_osid(self, output: str) -> str:
        """Extract raw OSID from output (for internal use).
        
        Returns:
            Raw OSID hex string, or "Unknown" if not found
        """
        match = re.search(r'OS Thread Id:\s+0x([0-9a-fA-F]+)', output)
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
            response = self.invoke_llm_with_fallback(prompt, TaskComplexity.COMPLEX)
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
        
        except LLMInvocationError:
            # Re-raise LLM errors - no silent fallback
            raise
    
    def _analyze_thread_patterns(
        self,
        thread_analyses: List[Dict[str, Any]],
        exceptions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Analyze patterns across multiple threads."""
        # Build summary of threads with top stack frames (critical for diagnosing blocking calls)
        thread_details = []
        for t in thread_analyses[:20]:  # Limit to 20 threads
            thread_line = f"Thread {t['thread_id']}: {t['frame_count']} frames"
            if t['has_exception']:
                thread_line += " [EXCEPTION]"
            
            # Include top 7 stack frames to show what the thread is doing (full call chain context)
            if t.get('frames'):
                top_frames = t['frames'][:7]
                frame_list = ", ".join([f['call_site'] for f in top_frames])
                thread_line += f" -> {frame_list}"
            
            thread_details.append(thread_line)
        
        thread_summary = "\n".join(thread_details)
        
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
            response = self.invoke_llm_with_fallback(prompt, TaskComplexity.COMPLEX)
            content = response.content.strip()
            
            lines = content.split('\n')
            summary_line = lines[0] if lines else "Multi-thread analysis complete."
            
            return {
                "summary": summary_line,
                "insights": [line.strip('- ').strip() for line in lines[1:] if line.strip()],
                "full_analysis": content,
            }
        
        except LLMInvocationError:
            # Re-raise LLM errors - no silent fallback
            raise
    
    def _get_example_stacks(self, thread_analyses: List[Dict[str, Any]], exceptions: List[Dict[str, Any]]) -> List[str]:
        """Get example COMPLETE stacks for threads with interesting patterns.
        
        Returns FULL detailed stacks (all frames, not truncated) for:
        1. Threads with exceptions
        2. Representative threads from EACH unique blocking pattern
        
        This ensures the LLM sees all different types of blocking, not just the first N threads.
        """
        examples = []
        blocking_keywords = ['wait', 'lock', 'result', 'getawaiter', 'monitor', 'semaphore', 'mutex']
        
        # First, add exception threads - FULL stacks
        for exc in exceptions[:2]:  # Max 2 exception examples
            thread_id = exc['thread_id']
            thread = next((t for t in thread_analyses if t['thread_id'] == thread_id), None)
            if thread and thread.get('frames'):
                # Include ALL frames for complete diagnostic data
                frames_text = "\n    ".join([f['call_site'] for f in thread['frames']])
                examples.append(f"  Thread {thread_id} [EXCEPTION: {exc['exception']['type']}]:\n    {frames_text}")
        
        # Group threads by their blocking pattern (top 3 frames define the pattern)
        blocking_patterns = {}
        for t in thread_analyses:
            if t.get('frames'):
                # Check if any frame contains blocking keywords
                stack_text = ' '.join([f['call_site'].lower() for f in t['frames']])
                if any(keyword in stack_text for keyword in blocking_keywords):
                    # Use top 3 frames as the pattern signature
                    pattern_key = tuple([f['call_site'] for f in t['frames'][:3]])
                    if pattern_key not in blocking_patterns:
                        blocking_patterns[pattern_key] = []
                    blocking_patterns[pattern_key].append(t)
        
        # Add 1-2 examples from each unique blocking pattern (up to 8 patterns total)
        max_patterns = 8 - len(examples)  # Reserve space for exceptions
        pattern_count = 0
        for pattern_threads in blocking_patterns.values():
            if pattern_count >= max_patterns:
                break
            
            # Show first thread from this pattern (representative)
            t = pattern_threads[0]
            frames_text = "\n    ".join([f['call_site'] for f in t['frames']])
            thread_count = len(pattern_threads)
            label = f"BLOCKING - {thread_count} thread(s) with this pattern" if thread_count > 1 else "BLOCKING"
            examples.append(f"  Thread {t['thread_id']} [{label}]:\n    {frames_text}")
            pattern_count += 1
        
        return examples
