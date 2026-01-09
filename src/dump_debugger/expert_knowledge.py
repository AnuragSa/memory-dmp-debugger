"""Expert knowledge base - heuristics, command shortcuts, and domain knowledge for memory dump debugging.

NOTE: Known failure patterns have been moved to src/dump_debugger/knowledge/known_patterns.json
Use PatternChecker from dump_debugger.knowledge to access patterns.
"""

from typing import TypedDict


class ExpertHeuristic(TypedDict):
    """Domain knowledge shortcut."""
    metric: str
    normal_range: str
    warning_threshold: str
    critical_threshold: str
    interpretation: str


# ============================================================================
# EXPERT HEURISTICS & DOMAIN KNOWLEDGE
# ============================================================================

EXPERT_HEURISTICS: dict[str, ExpertHeuristic] = {
    "thread_count": {
        "metric": "Total Thread Count",
        "normal_range": "10-50 for typical web app",
        "warning_threshold": ">100 threads",
        "critical_threshold": ">500 threads",
        "interpretation": "High thread count often indicates thread pool starvation or async-over-sync blocking"
    },
    
    "heap_fragmentation": {
        "metric": "Heap Fragmentation Percentage",
        "normal_range": "15-35%",
        "warning_threshold": ">50%",
        "critical_threshold": ">70%",
        "interpretation": "High fragmentation can cause OOM even with available memory. Check for LOH fragmentation."
    },
    
    "gen2_size": {
        "metric": "Generation 2 Heap Size",
        "normal_range": "<200 MB for typical app",
        "warning_threshold": ">500 MB",
        "critical_threshold": ">1 GB",
        "interpretation": "Large Gen2 indicates long-lived objects accumulating. Check for memory leaks or caches."
    },
    
    "finalizer_queue": {
        "metric": "Objects in Finalizer Queue",
        "normal_range": "<100",
        "warning_threshold": ">1000",
        "critical_threshold": ">10000",
        "interpretation": "Many objects in finalizer queue indicates undisposed IDisposable objects or GC pressure"
    },
    
    "sql_connection_pool": {
        "metric": "SQL Connection Pool Max Size",
        "normal_range": "Default is 100 connections",
        "warning_threshold": ">80% of max",
        "critical_threshold": "At max capacity",
        "interpretation": "Connection pool exhaustion causes timeouts. Check for connection leaks or increase pool size."
    },
    
    "threadpool_queue": {
        "metric": "ThreadPool Work Item Queue Length",
        "normal_range": "0-10",
        "warning_threshold": ">50",
        "critical_threshold": ">500",
        "interpretation": "Long queue indicates thread pool can't keep up. Check for blocked threads or increase pool size."
    },
    
    "working_set_vs_virtual": {
        "metric": "Working Set vs Virtual Size Ratio",
        "normal_range": "70-90%",
        "warning_threshold": "<50%",
        "critical_threshold": "<30%",
        "interpretation": "Low ratio (virtual >> working set) indicates reserved memory (arrays, memory-mapped files) not actual leaks"
    },
    
    "gc_time_percentage": {
        "metric": "% Time in GC",
        "normal_range": "<5%",
        "warning_threshold": ">10%",
        "critical_threshold": ">20%",
        "interpretation": "High GC time indicates GC thrashing. Check for excessive allocations or near-OOM conditions."
    }
}


# ============================================================================
# DATA MODEL COMMANDS - Efficient, targeted queries (user-mode dumps only)
# ============================================================================

DATA_MODEL_QUERIES: dict[str, str] = {
    # Thread analysis
    "thread_count": "dx @$curprocess.Threads.Count()",
    "blocked_thread_count": "dx @$curprocess.Threads.Where(t => t.State.Contains(\"Wait\")).Count()",
    "running_thread_count": "dx @$curprocess.Threads.Where(t => t.State.Contains(\"Running\")).Count()",
    
    # Database connections (SqlConnection)
    "sql_connection_count": "dx @$cursession.Objects.@\"System.Data.SqlClient.SqlConnection\".Count()",
    "open_sql_connections": "dx @$cursession.Objects.@\"System.Data.SqlClient.SqlConnection\".Where(c => c.State.ToString().Contains(\"Open\")).Count()",
    
    # Database connections (Generic DbConnection)
    "db_connection_count": "dx @$cursession.Objects.@\"System.Data.Common.DbConnection\".Count()",
    
    # Exception analysis
    "exception_count": "dx @$cursession.Objects.@\"System.Exception\".Count()",
    "exception_types": "dx @$cursession.Objects.@\"System.Exception\".GroupBy(e => e.GetType().Name).Select(g => new { Type = g.Key, Count = g.Count() })",
    
    # Memory analysis
    "string_count": "dx @$cursession.Objects.@\"System.String\".Count()",
    "byte_array_count": "dx @$cursession.Objects.@\"System.Byte[]\".Count()",
    
    # Task/async analysis
    "task_count": "dx @$cursession.Objects.@\"System.Threading.Tasks.Task\".Count()",
    "incomplete_tasks": "dx @$cursession.Objects.@\"System.Threading.Tasks.Task\".Where(t => !t.IsCompleted).Count()",
    
    # Handle analysis
    "file_stream_count": "dx @$cursession.Objects.@\"System.IO.FileStream\".Count()",
    "safe_handle_count": "dx @$cursession.Objects.@\"System.Runtime.InteropServices.SafeHandle\".Count()",
}


# Quick tests for hypothesis validation (returns concise data)
DATA_MODEL_QUICK_TESTS: dict[str, dict[str, str]] = {
    "thread_pool_starvation": {
        "thread_count": "dx @$curprocess.Threads.Count()",
        "blocked_threads": "dx @$curprocess.Threads.Where(t => t.State.Contains(\"Wait\")).Count()",
        "interpretation": "If blocked_threads / thread_count > 0.8, likely thread pool starvation"
    },
    
    "sql_connection_leak": {
        "total_connections": "dx @$cursession.Objects.@\"System.Data.SqlClient.SqlConnection\".Count()",
        "open_connections": "dx @$cursession.Objects.@\"System.Data.SqlClient.SqlConnection\".Where(c => c.State.ToString().Contains(\"Open\")).Count()",
        "interpretation": "If total_connections > 50 or open_connections > 80% of pool max, likely leak"
    },
    
    "deadlock": {
        "blocked_threads": "dx @$curprocess.Threads.Where(t => t.State.Contains(\"Wait\")).Count()",
        "fallback": "!syncblk",
        "interpretation": "If many blocked threads, check !syncblk for circular dependencies"
    },
    
    "exception_storm": {
        "exception_count": "dx @$cursession.Objects.@\"System.Exception\".Count()",
        "interpretation": "If exception_count > 1000, likely exception storm"
    },
    
    "async_blocking": {
        "incomplete_tasks": "dx @$cursession.Objects.@\"System.Threading.Tasks.Task\".Where(t => !t.IsCompleted).Count()",
        "blocked_threads": "dx @$curprocess.Threads.Where(t => t.State.Contains(\"Wait\")).Count()",
        "interpretation": "If many incomplete tasks + blocked threads, check for .Wait() or .Result deadlocks"
    }
}


# ============================================================================
# COMMAND SHORTCUTS - Expert's "go-to" commands for specific scenarios
# ============================================================================

COMMAND_SHORTCUTS: dict[str, list[str]] = {
    "quick_overview": [
        "!analyze -v",  # Automatic analysis
        "!eeversion",  # .NET version
        "!threads",  # Thread overview
        "!dumpheap -stat"  # Heap overview
    ],
    
    "database_issues": [
        "~*e !clrstack | findstr -i sql",  # All threads doing SQL
        "!dumpheap -type SqlConnection -stat",
        "!dumpheap -type DbConnection -stat",
        "!do [connection_address]"  # Inspect connection state
    ],
    
    "thread_issues": [
        "!threadpool",  # ThreadPool stats
        "~*e !clrstack",  # All thread stacks
        "!syncblk",  # Blocking/deadlocks
        "!locks"  # Kernel-mode locks
    ],
    
    "memory_issues": [
        "!address -summary",  # Memory regions
        "!eeheap -gc",  # Managed heap stats
        "!dumpheap -stat",  # Object types
        "!gcheapstat",  # GC statistics
        "!finalizequeue"  # Undisposed objects
    ],
    
    "exception_analysis": [
        "!dumpheap -type Exception -stat",
        "~*e !pe",  # Print exception on all threads
        "!analyze -v",  # Automatic exception analysis
        "!clrstack -a"  # Stack with arguments (shows exception details)
    ],
    
    "performance_issues": [
        "!runaway",  # CPU time per thread
        "!gcheapstat",  # GC pressure
        "!threadpool",  # Thread pool utilization
        "~*e !clrstack | findstr -i wait"  # Find waiting threads
    ]
}


# ============================================================================
# DATA MODEL HELPER FUNCTIONS
# ============================================================================

def get_data_model_test_for_pattern(pattern_name: str) -> dict[str, str] | None:
    """Get data model quick test for a known pattern.
    
    Args:
        pattern_name: Name of the pattern
        
    Returns:
        Dictionary of data model commands to test the pattern, or None if no quick test
    """
    return DATA_MODEL_QUICK_TESTS.get(pattern_name)


def get_efficient_commands_for_hypothesis(
    hypothesis: str, 
    supports_dx: bool,
    pattern_name: str | None = None
) -> list[str]:
    """Get most efficient commands to test a hypothesis.
    
    Uses traditional SOS/WinDbg commands for reliability.
    Avoids data model (dx) commands due to high failure rates and complex syntax.
    
    Args:
        hypothesis: The hypothesis to test
        supports_dx: Whether data model commands are available (ignored - always use traditional)
        pattern_name: Optional pattern name (deprecated - kept for backward compatibility)
        
    Returns:
        List of commands to execute
    """
    # Infer commands from hypothesis keywords
    commands = []
    hypothesis_lower = hypothesis.lower()
    
    if 'thread' in hypothesis_lower or 'starvation' in hypothesis_lower:
        commands.extend([
            '!threads',
            '!threadpool'
        ])
    
    if 'database' in hypothesis_lower or 'sql' in hypothesis_lower or 'connection' in hypothesis_lower:
        commands.extend([
            '!dumpheap -stat -type System.Data.SqlClient.SqlConnection',
            '!dumpheap -stat -type SqlConnection'
        ])
    
    if 'deadlock' in hypothesis_lower or 'lock' in hypothesis_lower:
        commands.extend([
            '!syncblk',
            '~*e !clrstack'
        ])
    
    if 'exception' in hypothesis_lower:
        commands.extend([
            '!dumpheap -stat -type System.Exception',
            '!pe'  # Print exception if one exists
        ])
    
    if 'task' in hypothesis_lower or 'async' in hypothesis_lower:
        commands.extend([
            '!dumpheap -stat -type System.Threading.Tasks.Task',
            '~*e !clrstack'
        ])
    
    if 'memory' in hypothesis_lower or 'leak' in hypothesis_lower:
        commands.extend([
            '!eeheap -gc',
            '!dumpheap -stat'
        ])
    
    if 'http' in hypothesis_lower or 'request' in hypothesis_lower or 'web' in hypothesis_lower:
        commands.extend([
            '!dumpheap -stat -type HttpContext',
            '!threads'
        ])
    
    return commands if commands else []


# ============================================================================
# PATTERN MATCHING - Deprecated (use PatternChecker from knowledge module)
# ============================================================================

def suggest_pattern_from_symptoms(symptoms: list[str]) -> list[str]:
    """Suggest patterns based on observed symptoms.
    
    DEPRECATED: Use PatternChecker from dump_debugger.knowledge instead.
    This function is kept for backward compatibility only.
    
    Args:
        symptoms: List of symptoms observed
        
    Returns:
        Empty list (patterns moved to JSON-based system)
    """
    return []


def get_confirmation_commands(pattern_name: str) -> list[str]:
    """Get commands to confirm a suspected pattern.
    
    DEPRECATED: Patterns moved to knowledge/known_patterns.json.
    Use PatternChecker from dump_debugger.knowledge instead.
    
    Args:
        pattern_name: Name of the pattern to confirm
        
    Returns:
        Empty list (use PatternChecker instead)
    """
    return []


def get_investigation_focus(pattern_name: str) -> list[str]:
    """Get investigation focus areas for a confirmed pattern.
    
    DEPRECATED: Patterns moved to knowledge/known_patterns.json.
    Use PatternChecker from dump_debugger.knowledge instead.
    
    Args:
        pattern_name: Name of the confirmed pattern
        
    Returns:
        Empty list (use PatternChecker instead)
    """
    return []


def evaluate_metric(metric_name: str, value: float) -> str:
    """Evaluate a metric value against expert heuristics.
    
    Args:
        metric_name: Name of the metric
        value: Observed value
        
    Returns:
        Assessment: "normal", "warning", or "critical"
    """
    heuristic = EXPERT_HEURISTICS.get(metric_name)
    if not heuristic:
        return "unknown"
    
    # This is simplified - in practice, parse the threshold strings
    # For now, just return the heuristic for LLM to evaluate
    return heuristic['interpretation']
