# Expert-Level Architecture - Hypothesis-Driven Investigation

## Overview

This is the **expert-level enhancement** to the memory dump debugger. It mimics how a seasoned debugger expert actually thinks:

1. **Form Hypothesis** from the user's question
2. **Test Hypothesis** with targeted commands
3. **Evaluate Results:**
   - ✅ **Confirmed** → Drill deep for root cause
   - ❌ **Rejected** → Pivot to new hypothesis
   - ❓ **Inconclusive** → Gather more evidence
4. **Investigate** systematically once hypothesis confirmed
5. **Reason** holistically over all evidence
6. **Report** with evidence chain

## How It Differs from V2

### V2 Architecture (Good)
```
User Question → Plan Tasks → Investigate Each → Reason → Report
```

**Characteristics:**
- Linear execution
- Pre-planned investigation
- Evidence-based
- No adaptation mid-stream

### Expert Architecture (Expert-Level)
```
User Question → Form Hypothesis → Test Hypothesis
    ↓
    Confirmed? → Deep Investigation → Reason → Report
    Rejected?  → New Hypothesis → Test Again
    Unclear?   → More Evidence → Retest
```

**Characteristics:**
- **Hypothesis-driven** (like real experts)
- **Adaptive** (pivots when wrong)
- **Pattern recognition** (uses known failure patterns)
- **Efficient** (tests hypothesis before deep dive)

## Expert Thinking Model

### Real Expert's Mental Process

```
User: "Are there active database connections?"

Expert's thought process:
1. HYPOTHESIS: "Likely has open SqlConnection objects"
2. QUICK TEST: Run !dumpheap -type SqlConnection
3. EVALUATE:
   - If found → "Yes, hypothesis confirmed. Now find out which threads use them"
   - If not found → "Hypothesis rejected. Maybe using different provider? Test for DbConnection"
   - If unclear → "Need more info. Check thread stacks for SQL activity"
4. DRILL DEEPER: Once confirmed, investigate root cause
5. REPORT: Evidence chain showing hypothesis → test → findings
```

### Our Implementation

```python
1. HypothesisDrivenAgent.form_initial_hypothesis()
   - Analyzes user question
   - Checks known patterns (deadlock, leak, starvation, etc.)
   - Forms testable hypothesis
   - Designs 2-3 commands to test it
   
2. HypothesisDrivenAgent.test_hypothesis()
   - Executes test commands
   - Collects evidence
   
3. HypothesisDrivenAgent.decide_next_step()
   - Evaluates: confirmed, rejected, or inconclusive
   - Routes to appropriate next action
   
4a. If CONFIRMED → _plan_deep_dive()
    - Create focused investigation plan
    - Use InvestigatorAgent for deep analysis
    
4b. If REJECTED → _form_alternative_hypothesis()
    - Learn from evidence
    - Form new hypothesis
    - Return to testing
    
4c. If INCONCLUSIVE → _gather_more_evidence()
    - Add 1-2 targeted commands
    - Retest
```

## Expert Knowledge Components

### 1. Pattern Library (`expert_knowledge.py`)

**9 Known Patterns:**
- Thread Pool Starvation
- SQL Connection Leak
- Deadlock
- Managed Memory Leak
- Unmanaged Memory Leak
- High CPU from GC
- Exception Storm
- Handle Leak
- Async-over-Sync Blocking

**Each pattern includes:**
```python
{
    "name": "SQL Connection Leak",
    "symptoms": [
        "Many SqlConnection objects on heap",
        "Connection timeout exceptions",
        "Heap growing over time"
    ],
    "confirmation_commands": [
        "!dumpheap -type SqlConnection -stat",
        "!finalizequeue"
    ],
    "typical_cause": "SqlConnection objects not being disposed",
    "investigation_focus": [
        "How many connection objects exist?",
        "Are they in finalizer queue (not disposed)?",
        "Which code paths are leaking?"
    ]
}
```

### 2. Expert Heuristics

**Domain Knowledge Shortcuts:**
```python
{
    "thread_count": {
        "normal_range": "10-50 for typical web app",
        "warning_threshold": ">100 threads",
        "critical_threshold": ">500 threads",
        "interpretation": "High thread count indicates thread pool starvation"
    },
    
    "sql_connection_pool": {
        "normal_range": "Default is 100 connections",
        "warning_threshold": ">80% of max",
        "interpretation": "Connection pool exhaustion causes timeouts"
    }
}
```

**Metrics tracked:**
- Thread count
- Heap fragmentation
- Gen2 heap size
- Finalizer queue length
- Connection pool capacity
- ThreadPool queue length
- Working set vs virtual size ratio
- GC time percentage

### 3. Command Shortcuts

**Expert's "Go-To" commands for specific scenarios:**

```python
COMMAND_SHORTCUTS = {
    "database_issues": [
        "~*e !clrstack | findstr -i sql",
        "!dumpheap -type SqlConnection -stat",
        "!dumpheap -type DbConnection -stat"
    ],
    
    "thread_issues": [
        "!threadpool",
        "~*e !clrstack",
        "!syncblk"
    ],
    
    "memory_issues": [
        "!address -summary",
        "!eeheap -gc",
        "!dumpheap -stat",
        "!finalizequeue"
    ]
}
```

## Workflow Example

### Scenario: "Are there active database connections?"

#### Phase 1: Hypothesis Formation

```
📋 Forming Initial Hypothesis

Matched Pattern: SQL Connection Leak (partial match)

💡 Hypothesis: "Application has open SqlConnection objects on the heap"
🎯 Confidence: HIGH
🔍 Will test with: !dumpheap -type SqlConnection -stat, ~*e !clrstack

Expected if confirmed: "Multiple SqlConnection instances found"
Expected if rejected: "No SqlConnection objects or very few"
```

#### Phase 2: Hypothesis Testing

```
🧪 Testing Hypothesis
  → !dumpheap -type SqlConnection -stat
  → ~*e !clrstack | findstr -i sql

✅ Result: CONFIRMED
   Found 3 SqlConnection objects on heap
   Thread 5 has SqlCommand.ExecuteReader in stack
   Matches expected pattern for active connections
```

#### Phase 3: Deep Investigation Plan

```
📋 Root Cause Investigation Plan:
  1. Examine state of the 3 SqlConnection objects
  2. Analyze thread 5's full call stack
  3. Check connection pool configuration
  4. Verify connections are being properly managed
```

#### Phase 4: Investigation (Each Task)

```
Task 1/4: Examine state of SqlConnection objects
  → !do <addr1>
  ✓ Connection is Open
  → !do <addr2>
  ✓ Connection is Open
  → !do <addr3>
  ✓ Connection is Open
→ Evidence stored

Task 2/4: Analyze thread 5's full call stack
  → !clrstack -a
  ✓ Thread executing stored procedure
→ Evidence stored

... Tasks 3 & 4 ...
```

#### Phase 5: Reasoning

```
→ Analyzing all collected evidence

Cross-reference findings:
- Hypothesis: SqlConnection objects exist ✓
- Thread evidence: Matches heap evidence (3 connections) ✓
- Pool state: 3/10 active ✓
- All connections healthy ✓

Conclusions:
1. YES - 3 active database connections confirmed
2. All connections in active use (not leaked)
3. One connection executing stored procedure
4. Connection pool healthy (70% capacity available)

Confidence: HIGH (multiple independent sources)
```

#### Phase 6: Report

```
## Database Connection Analysis

### Hypothesis Chain
**Initial Hypothesis:** Application has open SqlConnection objects
**Test Result:** CONFIRMED
**Evidence:** Found 3 SqlConnection instances on heap

### Detailed Findings
...
```

## When Hypothesis is Rejected

### Example: Wrong Initial Guess

```
User: "Why is the app slow?"

Initial Hypothesis: "Thread pool starvation"
Test: !threadpool shows 8/8 threads active
Result: REJECTED - ThreadPool is fine, only 8 threads total

🔄 New Hypothesis: "High GC pressure causing slowness"
Test: !gcheapstat
Result: CONFIRMED - Gen2 collections every 2 seconds, 80% time in GC

→ Now investigate WHY GC pressure is high
```

**Key Difference:** Expert system **adapts** rather than blindly executing a pre-made plan.

## Adaptive Pivoting Example

### Scenario: Misleading Question

```
User: "Check database connections"

Hypothesis: "DB connection issue"
Test: !dumpheap -type SqlConnection
Result: Only 2 connections, both properly disposed

Evidence shows: !address -summary reveals 4GB "Unknown" region

🔄 PIVOT: Evidence suggests memory issue, not DB issue

New Hypothesis: "Large unmanaged memory allocation (memory-mapped file or native leak)"
Test: !heap -s
Result: CONFIRMED - Large native heap allocation

→ Investigation shifts from DB to unmanaged memory
```

**This is expert behavior:** Recognizing when the user's assumption is wrong and investigating what the evidence actually shows.

## Comparison with Real Expert

| Behavior | Real Expert | V2 Architecture | Expert Architecture |
|----------|-------------|-----------------|---------------------|
| **Initial Approach** | Form hypothesis, test it | Plan all tasks upfront | ✅ Form hypothesis, test it |
| **Pattern Recognition** | Instant ("Oh, that's a deadlock") | Limited | ✅ Uses pattern library |
| **Adaptation** | Pivots when wrong | Completes plan regardless | ✅ Pivots to new hypothesis |
| **Efficiency** | Quick tests first | Executes full plan | ✅ Tests before deep dive |
| **Domain Knowledge** | Knows thresholds by heart | Learns each time | ✅ Uses expert heuristics |
| **Command Selection** | Goes straight to key commands | LLM decides each time | ✅ Uses command shortcuts |
| **Reasoning** | "This + That = Therefore" | Summarizes findings | ✅ Builds evidence chain |

## Benefits Over V2

1. **Faster:** Tests hypothesis before full investigation (2-3 commands vs 10-15)
2. **Smarter:** Uses known patterns and expert heuristics
3. **Adaptive:** Pivots when wrong instead of completing wrong plan
4. **More Accurate:** Pattern matching reduces guesswork
5. **More Realistic:** Mimics actual expert thought process

## When to Use Which

**Use V2 (Evidence-Based) when:**
- User has specific, narrow question
- Investigation path is clear
- Want systematic evidence collection

**Use Expert (Hypothesis-Driven) when:**
- User question is vague ("app is slow")
- Root cause is unknown
- Want most efficient analysis
- Need adaptive investigation

## Files

- **[expert_knowledge.py](src/dump_debugger/expert_knowledge.py)** - Pattern library, heuristics, command shortcuts
- **[hypothesis_agent.py](src/dump_debugger/hypothesis_agent.py)** - Hypothesis formation and testing logic
- **[workflows_expert.py](src/dump_debugger/workflows_expert.py)** - Expert workflow implementation
- **[state/__init__.py](src/dump_debugger/state/__init__.py)** - State with hypothesis tracking

## Usage

```bash
# Expert mode is now the default
dump-debugger analyze crash.dmp --issue "Why is the app slow?"

# See the hypothesis testing in action
dump-debugger analyze crash.dmp --issue "Are there deadlocks?" --show-commands
```

## Sample Output

```
🧠 Starting Expert Analysis (Hypothesis-Driven)

📋 Forming Initial Hypothesis
💡 Hypothesis: Deadlock between threads waiting on locks
🎯 Confidence: HIGH
🔍 Will test with: !syncblk, ~*e !clrstack

🧪 Testing Hypothesis
  → !syncblk
  → ~*e !clrstack

✅ Result: CONFIRMED
   Found circular wait: Thread 5 waiting for lock held by Thread 8
   Thread 8 waiting for lock held by Thread 5

📋 Root Cause Investigation Plan:
  1. Identify exact lock objects involved
  2. Find code locations that acquired locks
  3. Determine lock acquisition order

... Deep investigation ...

═══════════════════════════════════════
ANALYSIS COMPLETE
═══════════════════════════════════════

## Deadlock Analysis

### Hypothesis Confirmed
**Initial Hypothesis:** Circular lock dependency causing deadlock
**Evidence:** Thread 5 ↔ Thread 8 waiting on each other

### Root Cause
Deadlock occurs in OrderProcessor.cs:
- Thread 5 locks OrderLock, waits for InventoryLock
- Thread 8 locks InventoryLock, waits for OrderLock

### Recommendation
Fix: Always acquire locks in consistent order (Order → Inventory)
```

## Next Steps

This is **true expert-level debugging**:
- ✅ Hypothesis-driven investigation
- ✅ Pattern recognition
- ✅ Adaptive pivoting
- ✅ Domain knowledge
- ✅ Efficient command selection
- ✅ Evidence-based reasoning

The system now thinks like a seasoned debugger, not just executing a script.
