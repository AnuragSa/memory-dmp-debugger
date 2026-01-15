"""Thread list analyzer (Tier 1 - Pure code parsing)."""

import re
from typing import Any, Dict, List

from dump_debugger.analyzers.base import AnalysisResult, AnalyzerTier, BaseAnalyzer
from dump_debugger.utils.thread_registry import get_thread_registry


class ThreadsAnalyzer(BaseAnalyzer):
    """Analyzer for !threads command output.
    
    Tier 1: Pure code parsing - no LLM needed.
    Extracts thread list with IDs, managed IDs, apartment states, and lock counts.
    """
    
    name = "threads"
    description = "Analyzes !threads output to extract thread information"
    tier = AnalyzerTier.TIER_1
    supported_commands = ["!threads", "!t"]
    
    def can_analyze(self, command: str) -> bool:
        """Check if this is a !threads command."""
        cmd = command.strip().lower()
        return cmd.startswith("!threads") or cmd.startswith("!t ")
    
    def analyze(self, command: str, output: str) -> AnalysisResult:
        """Analyze !threads output.
        
        Example output:
        ```
        ThreadCount:      23
        UnstartedThread:  0
        BackgroundThread: 17
        PendingThread:    0
        DeadThread:       5
        Hosted Runtime:   no
                                                                                                            Lock  
         DBG   ID OSID ThreadOBJ           State GC Mode     GC Alloc Context                  Domain           Count Apt Exception
           0    1 4d8c 000001f2a3b4c5d6    2a020 Preemptive  0000000000000000:0000000000000000 000001f2a3b4d000 0     MTA 
           6    2 1234 000001f2a3b4c700    2b220 Preemptive  0000000000000000:0000000000000000 000001f2a3b4d000 0     MTA (Finalizer) 
          ...
        ```
        
        Returns:
            AnalysisResult with thread data
        """
        try:
            # Extract summary statistics
            stats = self._extract_stats(output)
            
            # Extract thread list
            threads = self._extract_threads(output)
            
            # Register threads in the global registry for cross-analyzer lookups
            self._register_threads(threads)
            
            # Count threads by state
            state_counts = self._count_by_state(threads)
            apartment_counts = self._count_by_apartment(threads)
            
            # Identify notable threads
            notable = self._find_notable_threads(threads)
            
            # Generate summary
            total_threads = stats.get("ThreadCount", len(threads))
            summary = self._generate_summary(total_threads, stats, state_counts, notable)
            
            # Generate findings
            findings = self._generate_findings(stats, threads, notable)
            
            return AnalysisResult(
                structured_data={
                    "stats": stats,
                    "threads": threads,
                    "state_counts": state_counts,
                    "apartment_counts": apartment_counts,
                    "notable_threads": notable,
                },
                summary=summary,
                findings=findings,
                metadata={
                    "analyzer": self.name,
                    "tier": self.tier.value,
                    "thread_count": total_threads,
                },
                success=True,
            )
        
        except Exception as e:
            return AnalysisResult(
                structured_data={},
                summary="",
                findings=[],
                metadata={"analyzer": self.name, "tier": self.tier.value},
                success=False,
                error=f"Failed to analyze threads: {str(e)}",
            )
    
    def _extract_stats(self, output: str) -> Dict[str, int]:
        """Extract thread statistics from header."""
        stats = {}
        patterns = {
            "ThreadCount": r"ThreadCount:\s+(\d+)",
            "UnstartedThread": r"UnstartedThread:\s+(\d+)",
            "BackgroundThread": r"BackgroundThread:\s+(\d+)",
            "PendingThread": r"PendingThread:\s+(\d+)",
            "DeadThread": r"DeadThread:\s+(\d+)",
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, output)
            if match:
                stats[key] = int(match.group(1))
        
        return stats
    
    def _extract_threads(self, output: str) -> List[Dict[str, Any]]:
        """Extract thread list from output."""
        threads = []
        
        # Handle different line ending styles (\n, \r\n, or \r)
        # Some debugger outputs use \r only (old Mac style)
        if '\r\n' in output:
            lines = output.split('\r\n')
        elif '\n' in output:
            lines = output.split('\n')
        else:
            lines = output.split('\r')
        
        # Pattern for thread line (flexible to handle variations)
        # Example live: "  0    1 4d8c 000001f2a3b4c5d6    2a020 Preemptive  ... 000001f2a3b4d000 0     MTA (Finalizer)"
        # Example dead: "XXXX  197    0 000002ef58a425b0  1039820 Preemptive  ... 000002eabfe9f650 0     Ukn (Threadpool Worker)"
        # The Exception column can contain:
        # - (Finalizer), (GC), (Threadpool Worker) - special thread types in parens
        # - System.NullReferenceException - exception type without parens
        # - (Finalizer) System.Exception - both special and exception
        #
        # NOTE: CDB/WinDbg may wrap long lines at ~120 characters. We need to join continuation lines.
        
        # First, join wrapped lines (lines that don't start with spaces followed by numbers/XXXX)
        joined_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # Check if this looks like a thread line start (starts with whitespace + number/XXXX)
            if re.match(r'^\s*(\d+|XXXX)\s+\d+\s+', line):
                # This is a thread line start, collect continuation lines
                full_line = line
                i += 1
                # Keep appending lines until we hit another thread line or end
                while i < len(lines):
                    next_line = lines[i]
                    # If next line starts a new thread entry, stop
                    if re.match(r'^\s*(\d+|XXXX)\s+\d+\s+', next_line):
                        break
                    # If it's an empty line or header, stop
                    if not next_line.strip() or \
                       next_line.strip().startswith('ThreadCount') or \
                       next_line.strip().startswith('ID OSID'):
                        break
                    # Otherwise, it's a continuation - append it
                    full_line += next_line.rstrip()
                    i += 1
                joined_lines.append(full_line)
            else:
                joined_lines.append(line)
                i += 1
        
        thread_pattern = re.compile(
            r'^\s*(\d+|XXXX)\s+(\d+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+(\w+)\s+'
            r'([0-9a-fA-F]+:[0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+(\d+)\s+(\w+)(?:\s+(.+))?$'
        )
        
        for line in joined_lines:
            # Strip trailing whitespace as CDB output often has trailing spaces
            line = line.rstrip()
            match = thread_pattern.match(line)
            if match:
                # Parse the exception/special column (group 11) which may contain:
                # "(Finalizer)", "System.Exception", "(GC) System.Exception", etc.
                exception_col = match.group(11).strip() if match.group(11) else None
                special = None
                exception = None
                
                if exception_col:
                    # Check for parenthesized special designation
                    special_match = re.match(r'\(([^)]+)\)', exception_col)
                    if special_match:
                        special = special_match.group(1)
                        # Remainder after special designation might be exception
                        remainder = exception_col[special_match.end():].strip()
                        if remainder:
                            exception = remainder
                    else:
                        # No parentheses - entire thing is exception type
                        exception = exception_col
                
                # Handle dead threads (XXXX marker)
                dbg_id_str = match.group(1)
                is_dead = (dbg_id_str == "XXXX")
                
                thread = {
                    "dbg_id": None if is_dead else int(dbg_id_str),
                    "managed_id": int(match.group(2)),
                    "osid": match.group(3),
                    "thread_obj": match.group(4),
                    "state": match.group(5),
                    "gc_mode": match.group(6),
                    "gc_alloc_context": match.group(7),
                    "domain": match.group(8),
                    "lock_count": int(match.group(9)),
                    "apartment": match.group(10),
                    "special": special,  # e.g., "Finalizer", "GC", "Threadpool Worker"
                    "exception": exception,  # e.g., "System.NullReferenceException"
                    "is_dead": is_dead,  # Mark dead threads
                }
                threads.append(thread)
        
        return threads
    
    def _register_threads(self, threads: List[Dict[str, Any]]):
        """Register all threads in the global thread registry.
        
        This allows other analyzers (like clrstack) to lookup user-friendly
        managed IDs from OSIDs. Only live threads are registered (dead threads
        have no valid DBG ID).
        """
        registry = get_thread_registry()
        # Clear existing registrations to ensure fresh data
        registry.clear()
        
        for thread in threads:
            # Skip dead threads (no valid DBG ID)
            if thread.get("is_dead", False):
                continue
                
            registry.register_thread(
                dbg_id=thread.get("dbg_id", 0),
                managed_id=thread.get("managed_id", 0),
                osid=thread.get("osid", ""),
                thread_obj=thread.get("thread_obj"),
                apartment=thread.get("apartment"),
                special=thread.get("special"),
            )
    
    def _count_by_state(self, threads: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count threads by GC mode."""
        counts = {}
        for thread in threads:
            mode = thread.get("gc_mode", "Unknown")
            counts[mode] = counts.get(mode, 0) + 1
        return counts
    
    def _count_by_apartment(self, threads: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count threads by apartment type."""
        counts = {}
        for thread in threads:
            apt = thread.get("apartment", "Unknown")
            counts[apt] = counts.get(apt, 0) + 1
        return counts
    
    def _find_notable_threads(self, threads: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Identify notable threads."""
        notable = {
            "high_lock_count": [],
            "finalizer": [],
            "gc": [],
        }
        
        for thread in threads:
            # High lock count (potential deadlock)
            if thread.get("lock_count", 0) > 0:
                notable["high_lock_count"].append(thread)
            
            # Special threads
            special = thread.get("special", "")
            if special and "finalizer" in special.lower():
                notable["finalizer"].append(thread)
            elif special and "gc" in special.lower():
                notable["gc"].append(thread)
        
        return notable
    
    def _generate_summary(
        self,
        total: int,
        stats: Dict[str, int],
        state_counts: Dict[str, int],
        notable: Dict[str, List[Dict[str, Any]]],
    ) -> str:
        """Generate human-readable summary."""
        parts = [f"Found {total} threads in the process."]
        
        if stats.get("BackgroundThread", 0) > 0:
            parts.append(f"{stats['BackgroundThread']} are background threads.")
        
        if stats.get("DeadThread", 0) > 0:
            parts.append(f"{stats['DeadThread']} are dead threads.")
        
        if notable["high_lock_count"]:
            parts.append(f"{len(notable['high_lock_count'])} threads hold locks.")
        
        return " ".join(parts)
    
    def _generate_findings(
        self,
        stats: Dict[str, int],
        threads: List[Dict[str, Any]],
        notable: Dict[str, List[Dict[str, Any]]],
    ) -> List[str]:
        """Generate key findings."""
        findings = []
        
        # Total thread count
        findings.append(f"Total threads: {stats.get('ThreadCount', len(threads))}")
        
        # Background vs foreground
        bg = stats.get("BackgroundThread", 0)
        total = stats.get("ThreadCount", len(threads))
        fg = total - bg
        findings.append(f"Foreground: {fg}, Background: {bg}")
        
        # Dead threads
        if stats.get("DeadThread", 0) > 0:
            findings.append(f"Dead threads: {stats['DeadThread']} (may indicate thread pool issues)")
        
        # Threads with locks
        if notable["high_lock_count"]:
            lock_count = len(notable["high_lock_count"])
            findings.append(f"{lock_count} threads holding locks (potential synchronization points)")
        
        # Special threads
        if notable["finalizer"]:
            findings.append("Finalizer thread detected")
        
        if notable["gc"]:
            findings.append(f"{len(notable['gc'])} GC threads detected")
        
        return findings
