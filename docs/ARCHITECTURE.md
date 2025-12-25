# Architecture Guide

This document consolidates the project’s architecture notes: the hypothesis-driven workflow, evidence management, specialized analyzers, and interactive mode.

## High-Level Flow

The tool runs a persistent WinDbg/CDB session against a dump and iteratively collects evidence to answer the user’s issue.

1. **Form hypothesis** from the issue/question
2. **Test hypothesis** with 2–3 targeted commands
3. **Evaluate** results: confirmed / rejected / inconclusive
4. **Investigate** deeper only after confirmation
5. **Reason + report** with an evidence chain

## Expert / Hypothesis-Driven Workflow

The “expert” behavior mimics how a seasoned debugger operates:

- Prefer **fast tests** before expensive exploration
- **Pivot** when evidence contradicts the current hypothesis
- Use known **patterns** (deadlock, leak, starvation, etc.) and **heuristics** (what ranges are normal)

Conceptually:

```
User Issue
  → Hypothesis
    → Test (2–3 commands)
      → Confirmed?  → Deep investigation
      → Rejected?   → New hypothesis
      → Unclear?    → Gather more evidence → Re-test
```

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

Large command outputs are handled via an evidence system so analysis doesn’t lose critical data due to token limits.

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

The agent:

1. Builds context from existing evidence
2. Decides if that evidence is sufficient
3. Runs additional debugger commands only when needed

## Key Modules (Orientation)

- `src/dump_debugger/core/debugger.py`: persistent debugger session + command execution
- `src/dump_debugger/evidence/*`: evidence storage, retrieval, analysis orchestration
- `src/dump_debugger/analyzers/*`: specialized analyzers + registry
- `src/dump_debugger/workflows.py`: end-to-end workflow orchestration

## Extending the System

### Add a new analyzer

1. Create a new analyzer in `src/dump_debugger/analyzers/`
2. Implement `can_analyze()` and `analyze()`
3. Register it in the analyzers package/registry

Keep analyzers narrowly scoped: match a command family, parse structured output, return a structured result + a concise summary.
