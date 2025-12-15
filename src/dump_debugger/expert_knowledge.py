"""Expert knowledge base - patterns, heuristics, and domain knowledge for memory dump debugging."""

from typing import TypedDict


class Pattern(TypedDict):
    """A known failure pattern that experts recognize."""
    name: str
    symptoms: list[str]
    confirmation_commands: list[str]
    typical_cause: str
    investigation_focus: list[str]


class ExpertHeuristic(TypedDict):
    """Domain knowledge shortcut."""
    metric: str
    normal_range: str
    warning_threshold: str
    critical_threshold: str
    interpretation: str


# ============================================================================
# KNOWN FAILURE PATTERNS
# ============================================================================

KNOWN_PATTERNS: dict[str, Pattern] = {
    "thread_pool_starvation": {
        "name": "Thread Pool Starvation",
        "symptoms": [
            "High thread count (>50 for typical app)",
            "Most threads in WaitForSingleObject or similar wait states",
            "ThreadPool queue has pending work items",
            "Application appears hung or slow"
        ],
        "confirmation_commands": [
            "~*e !clrstack",  # All thread stacks
            "!threadpool",  # ThreadPool statistics
            "!syncblk"  # Check for blocking
        ],
        "typical_cause": "All ThreadPool threads are blocked waiting, preventing new work from being processed",
        "investigation_focus": [
            "What are threads waiting on?",
            "Are there deadlocks?",
            "Is there a long-running synchronous operation blocking threads?",
            "Check for database connection exhaustion"
        ]
    },
    
    "sql_connection_leak": {
        "name": "SQL Connection Leak",
        "symptoms": [
            "Many SqlConnection or DbConnection objects on heap",
            "Connection timeout exceptions",
            "Heap growing over time",
            "Connection pool exhausted errors"
        ],
        "confirmation_commands": [
            "!dumpheap -type SqlConnection -stat",
            "!dumpheap -type DbConnection -stat",
            "!finalizequeue"  # Check for undisposed connections
        ],
        "typical_cause": "SqlConnection objects not being properly disposed, exhausting connection pool",
        "investigation_focus": [
            "How many connection objects exist?",
            "Are they in finalizer queue (not disposed)?",
            "What's the connection pool limit?",
            "Which code paths are leaking connections?"
        ]
    },
    
    "deadlock": {
        "name": "Deadlock",
        "symptoms": [
            "Application completely hung",
            "Multiple threads waiting on locks",
            "Circular wait dependencies",
            "CPU usage near zero"
        ],
        "confirmation_commands": [
            "!syncblk",
            "~*e !clrstack",
            "!locks"  # For kernel-mode dumps
        ],
        "typical_cause": "Circular dependency where Thread A waits for lock held by Thread B, and Thread B waits for lock held by Thread A",
        "investigation_focus": [
            "Which threads are involved?",
            "What locks are they waiting on?",
            "What's the circular dependency chain?",
            "What code caused the deadlock?"
        ]
    },
    
    "memory_leak_managed": {
        "name": "Managed Memory Leak",
        "symptoms": [
            "Heap growing continuously",
            "Large Gen2 heap size",
            "High number of specific object types",
            "OutOfMemoryException"
        ],
        "confirmation_commands": [
            "!dumpheap -stat",
            "!gcheapstat",
            "!finalizerqueue"
        ],
        "typical_cause": "Objects being kept alive unintentionally (event handlers, static references, caches)",
        "investigation_focus": [
            "Which object types are accumulating?",
            "What's holding references to these objects?",
            "Are there event handler leaks?",
            "Is there an unbounded cache?"
        ]
    },
    
    "memory_leak_unmanaged": {
        "name": "Unmanaged Memory Leak",
        "symptoms": [
            "Process memory high but managed heap small",
            "Large 'Unknown' regions in !address -summary",
            "Virtual size >> working set",
            "Native memory allocations not freed"
        ],
        "confirmation_commands": [
            "!address -summary",
            "!heap -s",  # For user-mode dumps
            "!eeheap -gc"  # Compare managed vs total
        ],
        "typical_cause": "Unmanaged allocations (COM objects, handles, native DLLs) not being freed",
        "investigation_focus": [
            "What's consuming unmanaged memory?",
            "Check for handle leaks (!handle)",
            "Check for large memory-mapped files",
            "Are native DLLs leaking?"
        ]
    },
    
    "high_cpu_gc": {
        "name": "High CPU from GC Thrashing",
        "symptoms": [
            "High CPU usage",
            "Frequent Gen2 collections",
            "GC time percentage high (>10%)",
            "Application slow despite available memory"
        ],
        "confirmation_commands": [
            "!gcheapstat",
            "!finalizequeue",
            "!dumpheap -stat"
        ],
        "typical_cause": "GC spending too much time collecting because heap is near limit or too much garbage generated",
        "investigation_focus": [
            "How often is GC running?",
            "Are there many objects in finalizer queue?",
            "Is heap fragmented?",
            "Are large objects being allocated frequently?"
        ]
    },
    
    "exception_storm": {
        "name": "Exception Storm",
        "symptoms": [
            "Many exception objects on heap",
            "Multiple threads with exception in stack",
            "High CPU with lots of exception handling",
            "Application slow or unresponsive"
        ],
        "confirmation_commands": [
            "!dumpheap -type Exception -stat",
            "~*e !pe",  # Print exception on all threads
            "!analyze -v"  # Automatic analysis
        ],
        "typical_cause": "Code throwing and catching exceptions in tight loop, or unhandled exceptions causing retries",
        "investigation_focus": [
            "What exception types are being thrown?",
            "Which code is throwing them?",
            "Is this expected (flow control) or bug?",
            "Are exceptions being swallowed and retried?"
        ]
    },
    
    "handle_leak": {
        "name": "Handle Leak",
        "symptoms": [
            "High handle count in Task Manager",
            "Handle-related errors (too many files open, etc.)",
            "Many File/Mutex/Event objects on heap",
            "Process slow or failing operations"
        ],
        "confirmation_commands": [
            "!handle",  # User-mode only
            "!dumpheap -type FileStream -stat",
            "!dumpheap -type SafeHandle -stat"
        ],
        "typical_cause": "File streams, synchronization primitives, or COM objects not being disposed",
        "investigation_focus": [
            "What types of handles are leaking?",
            "Are FileStreams being disposed?",
            "Are mutex/event handles being closed?",
            "Check finalizer queue for undisposed objects"
        ]
    },
    
    "async_blocking": {
        "name": "Async over Sync Blocking",
        "symptoms": [
            "Thread pool starvation",
            "Many threads blocked on Task.Wait() or .Result",
            "Application hung despite async code",
            "Potential deadlock in async code"
        ],
        "confirmation_commands": [
            "~*e !clrstack",
            "!dumpheap -type Task -stat",
            "!syncblk"
        ],
        "typical_cause": "Blocking on async operations with .Wait() or .Result, causing thread pool starvation",
        "investigation_focus": [
            "Which threads are blocked on Task.Wait?",
            "Is there a sync-over-async pattern?",
            "Are there deadlocks from ConfigureAwait issues?",
            "Check for SynchronizationContext deadlocks"
        ]
    }
}


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
    
    Prefers data model commands for user-mode dumps (concise output).
    Falls back to traditional commands for kernel dumps or complex queries.
    
    Args:
        hypothesis: The hypothesis to test
        supports_dx: Whether data model commands are available
        pattern_name: Optional pattern name for specialized tests
        
    Returns:
        List of commands to execute
    """
    if not supports_dx:
        # Kernel dump - use traditional commands
        if pattern_name and pattern_name in KNOWN_PATTERNS:
            return KNOWN_PATTERNS[pattern_name]['confirmation_commands']
        return []
    
    # User-mode dump - prefer data model for quick tests
    commands = []
    
    # Check if pattern has data model quick test
    if pattern_name and pattern_name in DATA_MODEL_QUICK_TESTS:
        test_commands = DATA_MODEL_QUICK_TESTS[pattern_name]
        for key, cmd in test_commands.items():
            if key != 'interpretation' and key != 'fallback':
                commands.append(cmd)
        
        # Add fallback traditional command if specified
        if 'fallback' in test_commands:
            commands.append(test_commands['fallback'])
    
    # If no specific pattern, try to infer from hypothesis keywords
    elif supports_dx:
        hypothesis_lower = hypothesis.lower()
        
        if 'thread' in hypothesis_lower or 'starvation' in hypothesis_lower:
            commands.extend([
                DATA_MODEL_QUERIES['thread_count'],
                DATA_MODEL_QUERIES['blocked_thread_count']
            ])
        
        if 'database' in hypothesis_lower or 'sql' in hypothesis_lower or 'connection' in hypothesis_lower:
            commands.extend([
                DATA_MODEL_QUERIES['sql_connection_count'],
                DATA_MODEL_QUERIES['open_sql_connections']
            ])
        
        if 'deadlock' in hypothesis_lower:
            commands.append(DATA_MODEL_QUERIES['blocked_thread_count'])
            commands.append('!syncblk')  # Still need traditional for lock analysis
        
        if 'exception' in hypothesis_lower:
            commands.extend([
                DATA_MODEL_QUERIES['exception_count'],
                DATA_MODEL_QUERIES['exception_types']
            ])
        
        if 'task' in hypothesis_lower or 'async' in hypothesis_lower:
            commands.extend([
                DATA_MODEL_QUERIES['task_count'],
                DATA_MODEL_QUERIES['incomplete_tasks']
            ])
        
        if 'memory' in hypothesis_lower or 'leak' in hypothesis_lower:
            # Memory leaks still benefit from traditional commands for details
            commands.extend([
                '!eeheap -gc',
                '!dumpheap -stat'
            ])
    
    return commands if commands else []


# ============================================================================
# PATTERN MATCHING - Quick pattern recognition
# ============================================================================

def suggest_pattern_from_symptoms(symptoms: list[str]) -> list[str]:
    """Suggest patterns based on observed symptoms.
    
    Args:
        symptoms: List of symptoms observed
        
    Returns:
        List of pattern names that match the symptoms
    """
    matching_patterns = []
    
    for pattern_key, pattern in KNOWN_PATTERNS.items():
        # Simple keyword matching (could be enhanced with LLM)
        symptom_keywords = set(' '.join(pattern['symptoms']).lower().split())
        observed_keywords = set(' '.join(symptoms).lower().split())
        
        # If significant overlap, suggest this pattern
        overlap = symptom_keywords & observed_keywords
        if len(overlap) >= 3:  # At least 3 keyword matches
            matching_patterns.append(pattern_key)
    
    return matching_patterns


def get_confirmation_commands(pattern_name: str) -> list[str]:
    """Get commands to confirm a suspected pattern.
    
    Args:
        pattern_name: Name of the pattern to confirm
        
    Returns:
        List of debugger commands to run
    """
    pattern = KNOWN_PATTERNS.get(pattern_name)
    if pattern:
        return pattern['confirmation_commands']
    return []


def get_investigation_focus(pattern_name: str) -> list[str]:
    """Get investigation focus areas for a confirmed pattern.
    
    Args:
        pattern_name: Name of the confirmed pattern
        
    Returns:
        List of questions/areas to investigate
    """
    pattern = KNOWN_PATTERNS.get(pattern_name)
    if pattern:
        return pattern['investigation_focus']
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
