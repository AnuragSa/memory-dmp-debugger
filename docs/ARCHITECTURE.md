# Architecture Guide

This document describes the project's architecture: the hypothesis-driven workflow, pattern knowledge base, evidence management, specialized analyzers, quality review system, iterative reasoning, and interactive mode.

## Table of Contents

1. [High-Level Flow](#high-level-flow)
2. [Expert / Hypothesis-Driven Workflow](#expert--hypothesis-driven-workflow)
3. [Iterative Reasoning Feedback Loop](#iterative-reasoning-feedback-loop)
   - [The Problem](#the-problem)
   - [The Solution](#the-solution)
   - [Implementation](#implementation)
   - [Workflow Example](#workflow-example)
   - [Console Output](#console-output)
4. [Quality Review System](#quality-review-system)
   - [Critic Agent](#critic-agent-temperature-05)
   - [Critique Loop](#critique-loop-2-rounds-maximum)
   - [Follow-Up Questions](#follow-up-questions)
5. [Agent Architecture](#agent-architecture)
   - [Core Agents](#core-agents)
   - [Pattern Knowledge System](#pattern-knowledge-system)
   - [Temperature Strategy](#temperature-strategy)
   - [Stateless Pattern](#stateless-pattern)
6. [Specialized Analyzers](#specialized-analyzers)
   - [Tiers](#tiers)
   - [Routing](#routing)
7. [Evidence Management](#evidence-management)
   - [Key Behaviors](#key-behaviors)
   - [Session Structure](#session-structure)
8. [Interactive Mode](#interactive-mode)
   - [Flow](#flow)
   - [Command Deduplication](#command-deduplication)
   - [Atomic Thread Commands](#atomic-thread-commands)
   - [Iteration Safeguards](#iteration-safeguards)
   - [Critical Thinking in Chat](#critical-thinking-in-chat)
9. [Token Tracking](#token-tracking)
10. [Key Modules (Orientation)](#key-modules-orientation)
11. [Data Redaction](#data-redaction)
12. [Extending the System](#extending-the-system)
    - [Add a New Analyzer](#add-a-new-analyzer)
    - [Add a New Agent](#add-a-new-agent)

---

## High-Level Flow

The tool runs a persistent WinDbg/CDB session against a dump and iteratively collects evidence to answer the user's issue.

1. **Form hypothesis** from the issue/question
2. **Test hypothesis** with 2–3 targeted commands
3. **Evaluate** results: confirmed / rejected / inconclusive
4. **Investigate** deeper only after confirmation
5. **Reason** over all evidence to draw conclusions
6. **Critique** analysis for quality (2 rounds maximum)
7. **Refine** analysis based on critique feedback
8. **Report** final findings with follow-up questions if needed
9. **Chat** for interactive follow-up questions

## Expert / Hypothesis-Driven Workflow

The "expert" behavior mimics how a seasoned debugger operates:

- Prefer **fast tests** before expensive exploration
- **Pivot** when evidence contradicts the current hypothesis
- Use known **patterns** (deadlock, leak, starvation, etc.) and **heuristics** (what ranges are normal)
- **Self-review** through a critic agent to catch errors before presenting to user

Conceptually:

```
User Issue
  → Hypothesis
    → Test (2–3 commands)
      → Confirmed?  → Deep investigation → Reason
      → Rejected?   → New hypothesis
      → Unclear?    → Gather more evidence → Re-test
        
After confirmation:
  → Reason (synthesize evidence)
    → Check for investigation gaps (NEW: Iterative Reasoning)
      → Gaps found? → Loop back to investigate with deeper questions
      → Max iterations reached or no gaps? → Continue to critique
    → Critique Round 1 (review for gaps/errors)
      → Issues found? → Respond (collect missing evidence, re-analyze)
        → Critique Round 2 (final verification)
          → Still has issues? → Report with suggested follow-up questions
          → No issues? → Report
      → No issues? → Report
```

## Iterative Reasoning Feedback Loop

The tool implements an **iterative reasoning feedback loop** to solve complex object graph correlation problems that cannot be resolved with simple analysis.

### The Problem

Traditional static analysis fails when root cause requires correlating data across separate object graphs in memory. For example:
- Evidence: "50 SqlConnectionTimeoutErrorInternal objects at addresses X, Y, Z"
- Evidence: "100 SqlCommand objects in memory"
- Gap: **Cannot determine which timeout corresponds to which SQL query**

Hardcoded "specialized analyzers" for every possible correlation pattern don't scale.

### The Solution

Use **iterative reasoning** where:
1. Cloud LLM (reasoner) identifies gaps in correlation
2. Returns specific investigation requests with questions
3. Workflow loops back to investigate phase
4. Local LLM (investigator) generates commands dynamically to answer questions
5. Loop back to reasoner with new evidence
6. Max 3 iterations to prevent infinite loops

### Implementation



**Investigation Request Structure**:
```python
{
    'question': 'Which SqlCommand objects correspond to timeout exceptions?',
    'context': 'Found 50 timeout objects and 100 SqlCommand objects but cannot correlate',
    'approach': 'Use !do on timeout objects to extract SqlCommand references'
}
```

**ReasonerAgent Enhancement**: Detects correlation gaps and generates investigation requests
**Workflow Routing**: `route_after_reason()` loops back to investigate phase when gaps found (max 3 iterations)
**InvestigatorAgent Strategies**: Includes prompts for common patterns:
- Correlating separate object graphs (using `!do` chains)
- Mapping objects to threads (using `!gcroot` or `!clrstack`)
- Extracting nested data from object fields
- Linking exceptions to sources via stack traces

### Workflow Example

**Iteration 0 (Initial):**
```
Observer: Finds 50 timeout exceptions
Hypotheses: "Application experiencing SQL timeouts"
Investigate: Runs !dumpheap -type SqlTimeout
Reasoner: "Found timeout objects but cannot determine which SQL queries caused them"
         Sets needs_deeper_investigation = true
         Returns: [{"question": "Which SqlCommand objects correspond to timeouts?", ...}]
```

**Iteration 1 (Deeper Investigation):**
```
Workflow: Routes back to "investigate" with new plan
Investigate: Generates !do commands on timeout objects
            Extracts SqlCommand references from exception fields
            Runs !do on SqlCommand addresses
            Extracts SQL text from m_commandText fields
Reasoner: "Timeout occurred in query: SELECT * FROM LargeTable WHERE..."
         Sets needs_deeper_investigation = false
```

**Final Phase:**
```
Workflow: Routes to "critique" (no more gaps)
Critique: Reviews analysis quality
Report: Generates final report with root cause
```

### Console Output

When gap detected: `🔍 Identified 2 gap(s) requiring deeper investigation`  
When looping back: `🔄 Iteration 1: Reasoner identified 2 gap(s)`  
When max reached: `⚠ Max reasoning iterations (3) reached`

## Quality Review System

After the reasoner synthesizes all evidence, a **CriticAgent** reviews the analysis for quality issues before presenting to the user.

### Critic Agent (Temperature: 0.5)

The critic is a skeptical reviewer that checks for:

1. **Architectural Errors** - Claims that a technology does something it architecturally cannot do
2. **Evidence Gaps** - Conclusions drawn without supporting data shown
3. **Logical Contradictions** - Statements that contradict each other or the evidence
4. **Alternative Explanations** - Obvious alternatives not considered

### Critique Loop (2 Rounds Maximum)

- **Round 1**: Critic reviews initial analysis, identifies issues
  - If issues found → **Respond node** collects missing evidence and reasoner re-analyzes with critique feedback
  - If no issues → Proceed to report
  
- **Round 2**: Critic verifies the updated analysis
  - If still has issues → Generate **follow-up questions** for user instead of blocking output
  - If no issues → Proceed to report

### Follow-Up Questions

When Round 2 critique finds unresolved issues, instead of showing technical error messages, the system:

1. Uses an LLM to convert technical critique findings into **natural user questions**
2. Displays 3-5 specific questions the user can ask to explore further
3. Shows these questions in both terminal output and generated reports

Example output:
```
🔍 Suggested Follow-Up Questions

Want to dig deeper? Here are specific questions you can ask:

1. Can you execute !threadpool to confirm thread pool statistics?
2. What evidence links the SQL timeouts to the compiler lock contention?
3. Could the compilation be happening at runtime rather than initialization?
```

## Agent Architecture

All agents follow LangGraph's stateless pattern and are organized in the `src/dump_debugger/agents/` module:

### Core Agents

- **HypothesisDrivenAgent** (temp: 0.0) - Forms and tests hypotheses, evaluates results
- **InvestigatorAgent** (temp: 0.1) - Executes focused investigation tasks  
- **PlannerAgentV2** (temp: 0.1) - Plans investigation strategies and task sequences
- **ReasonerAgent** (temp: 0.2) - Synthesizes all evidence into conclusions
- **CriticAgent** (temp: 0.5) - Reviews analysis for quality issues
- **ReportWriter** (temp: 0.2) - Generates formatted reports
- **InteractiveChatAgent** (temp: 0.2) - Handles follow-up questions

### Pattern Knowledge System

The **PatternChecker** (`src/dump_debugger/knowledge/`) provides intelligent pattern matching during hypothesis formation:

**Pattern Database**: 19 known debugging patterns in `known_patterns.json`:
- Application Framework Issues (10): NLog buffers, EF DbContext leaks, SqlConnection deadlocks, SignalR leaks, fire-and-forget tasks, HttpClient anti-pattern, Timer leaks, LOH fragmentation, Finalizer queue, Event handlers
- General .NET Issues (9): Thread pool starvation, SQL connection leak, Deadlock, Memory leaks (managed/unmanaged), GC thrashing, Exception storm, Handle leak, Async-over-sync blocking

**Matching Modes**:
1. **Semantic Search** (default): Uses embeddings for similarity matching (OpenAI/Azure/Ollama)
2. **Keyword Fallback**: Automatic fallback if embeddings unavailable (Azure without deployment, errors)

**Integration**: Pattern hints are automatically included in hypothesis formation prompts, boosting confidence when known patterns detected.

### Temperature Strategy

Different agents use different temperatures based on their role:

- **Low (0.0-0.1)**: Precision tasks - hypothesis formation, command generation, data parsing
- **Medium (0.2)**: Synthesis tasks - reasoning, report writing, conversation
- **Higher (0.5)**: Critical thinking - finding issues, considering alternatives

The critic specifically needs higher temperature to be creative in identifying problems the reasoner might miss.

### Stateless Pattern

All agents follow LangGraph's stateless pattern:

- Agents receive state as input
- Agents return state updates as dict
- No mutable instance variables tracking progress
- All state stored in `AnalysisState` TypedDict

This ensures clean state management and easier LangGraph upgrades.

## Specialized Analyzers

To optimize cost/speed/quality, command outputs are routed to specialized analyzers.

### Tiers

- **Tier 1 (Pure code parsing)**: deterministic extraction (fast, free)
- **Tier 2 (Code + local LLM)**: light interpretation on structured data (fast, usually free)
- **Tier 3 (Cloud LLM)**: deep reasoning for complex contexts (slower, costs tokens)

### Routing

The analyzer registry selects a specialized analyzer when possible; otherwise it falls back to generic analysis.

Typical classification:

- Simple: `!threads`, `!syncblk`, `!threadpool`
- Moderate: `!dumpheap -stat`, object summaries
- Complex: multi-thread stack analysis, deep correlation, multi-stage reasoning

## Evidence Management

Large command outputs are handled via an evidence system so analysis doesn't lose critical data due to token limits.

### Key behaviors

- Outputs over a configured threshold are stored externally in a session directory
- Large outputs can be analyzed in chunks when needed
- Evidence is tracked per session (isolation + reproducibility)

### Session structure

Sessions are written under a base sessions directory (default `.sessions/`) and include:

- A session metadata file
- A SQLite database for evidence metadata
- Full raw outputs in files

## Interactive Mode

After the automated run completes, interactive mode lets you ask follow-up questions.

### Flow

The **InteractiveChatAgent** follows a 3-step iterative process (max 3 iterations):

1. **Build Context**: Retrieves relevant evidence using semantic search or keyword matching
2. **Check Sufficiency**: LLM determines if existing evidence can answer the question
3. **Investigate**: If insufficient, executes new commands and loops back to step 1

### Command Deduplication

- Tracks all attempted commands across iterations in `attempted_commands` set
- Skips duplicate commands but reuses their cached evidence
- LLM receives list of already-executed commands to suggest alternatives
- Prevents infinite loops where same commands are repeatedly suggested

### Atomic Thread Commands

- LLM generates combined commands: `~8e !clrstack` (not separate `~8s` + `!clrstack`)
- Uses proper WinDbg syntax: `~Ne <command>` runs command on specific thread
- Eliminates thread context confusion and simplifies deduplication
- Each command is self-contained with explicit thread context

### Iteration Safeguards

- Maximum 3 investigation rounds per question
- Stops if no new evidence gathered
- Detects command repetition and breaks early

### Critical Thinking in Chat

The interactive agent is designed to **challenge user assumptions**:

- Validates user claims against actual evidence
- Points out contradictions (e.g., user says "CPU was 20%" but evidence shows high CPU)
- Shows objective measurements and calculations
- Does NOT try to make user's narrative fit the data if they conflict

## Token Tracking

The system tracks token usage separately for local vs cloud LLMs:

- **TokenTrackingLLM wrapper** intercepts all LLM calls
- Tracks input tokens and output tokens separately
- Separates local model usage from cloud model usage
- Displays summary on Ctrl+C or at end of analysis

## Key Modules (Orientation)

- `src/dump_debugger/core/debugger.py`: persistent debugger session + command execution
- `src/dump_debugger/agents/`: individual agent implementations (stateless LangGraph pattern)
  - `hypothesis.py` - Hypothesis formation and testing
  - `investigator.py` - Focused investigation execution
  - `reasoner.py` - Evidence synthesis and reasoning
  - `critic.py` - Quality review and critique
  - `report_writer.py` - Report generation
  - `interactive_chat.py` - Follow-up Q&A
- `src/dump_debugger/evidence/`: evidence storage, retrieval, and analysis orchestration
  - `storage.py` - Evidence persistence
  - `retrieval.py` - Evidence querying
  - `analyzer.py` - Analysis coordination
- `src/dump_debugger/analyzers/`: specialized command output analyzers + registry
  - `base.py` - Base analyzer class
  - `registry.py` - Analyzer registration and lookup
  - Individual analyzers: `threads.py`, `threadpool.py`, `clrstack.py`, `dumpheap.py`, `syncblk.py`, etc.
- `src/dump_debugger/security/redactor.py`: intelligent pattern-based redaction for cloud LLM calls
- `src/dump_debugger/workflows.py`: LangGraph orchestration (no agent business logic)

## Data Redaction

When using cloud LLM providers, the `DataRedactor` component attempts to protect sensitive information:

**Architecture:**
- **Pattern-based detection**: Credit cards (Luhn validation), SSNs (SSA rules), emails, API keys, tokens
- **Context-aware filtering**: Memory addresses and hash codes are NOT redacted when in technical contexts
- **Stable placeholders**: Same value always gets same placeholder (e.g., `CC_1`) for consistent LLM reasoning
- **Audit trail**: Optional logging via `--audit-redaction` flag to track what was redacted

**Integration Points:**
- Wraps all debugger command outputs before sending to cloud LLMs
- Applied at evidence collection time in `debugger.py`
- Disabled entirely in `LOCAL_ONLY_MODE` (both CLI `--local-only` and env var)

**Extensibility:**
Add custom redaction patterns without modifying source code:

1. **Custom Patterns File** (Recommended):
   - Create `.redaction/custom_patterns.py` based on `.redaction/example_patterns.py`
   - Define patterns as a list of `RedactionPattern` objects:
     ```python
     CUSTOM_PATTERNS = [
         RedactionPattern(
             name="INTERNAL_ID",
             pattern=r"\bID-\d{8}-[A-Z]{3}\b",
             replacement="[INTERNAL_ID]",
             description="Company-specific ID format"
         )
     ]
     ```
   - Patterns are automatically loaded at startup
   - File is ignored by git to keep your patterns private

2. **Source Code Extension** (Advanced):
   - Edit `src/dump_debugger/security/redactor.py`
   - Add pattern to built-in patterns list
   - Implement custom validation in `_validate_match()` if needed

## Extending the System

### Add a new analyzer

1. Create a new analyzer in `src/dump_debugger/analyzers/`
2. Inherit from `BaseAnalyzer` in `base.py`
3. Implement `can_analyze()` and `analyze()` methods
4. Register it in `registry.py`

Keep analyzers narrowly scoped: match a command family, parse structured output, return a structured result + a concise summary.

### Add a new agent

1. Create a new agent in `src/dump_debugger/agents/`
2. Follow stateless pattern: receive `AnalysisState`, return `dict[str, Any]`
3. Set appropriate temperature in `__init__` based on agent's role
4. Add node to workflow in `workflows.py`
5. Connect with appropriate edges and routing logic