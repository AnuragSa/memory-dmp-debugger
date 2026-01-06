# Architecture Guide

This document dhows the project's architecture: the hypothesis-driven workflow, evidence management, specialized analyzers, quality review system, and interactive mode.

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
    → Critique Round 1 (review for gaps/errors)
      → Issues found? → Respond (collect missing evidence, re-analyze)
        → Critique Round 2 (final verification)
          → Still has issues? → Report with suggested follow-up questions
          → No issues? → Report
      → No issues? → Report
```

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
- **ReasonerAgent** (temp: 0.2) - Synthesizes all evidence into conclusions
- **CriticAgent** (temp: 0.5) - Reviews analysis for quality issues
- **ReportWriter** (temp: 0.2) - Generates formatted reports
- **InteractiveChatAgent** (temp: 0.2) - Handles follow-up questions

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

The agent:

1. Builds context from existing evidence
2. Decides if that evidence is sufficient
3. Runs additional debugger commands only when needed

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
- `src/dump_debugger/evidence/*`: evidence storage, retrieval, analysis orchestration
- `src/dump_debugger/analyzers/*`: specialized analyzers + registry
- `src/dump_debugger/workflows.py`: LangGraph orchestration (no agent business logic)

## Extending the System

### Add a new analyzer

1. Create a new analyzer in `src/dump_debugger/analyzers/`
2. Implement `can_analyze()` and `analyze()`
3. Register it in the analyzers package/registry

Keep analyzers narrowly scoped: match a command family, parse structured output, return a structured result + a concise summary.

### Add a new agent

1. Create a new agent in `src/dump_debugger/agents/`
2. Follow stateless pattern: receive `AnalysisState`, return `dict[str, Any]`
3. Set appropriate temperature in `__init__` based on agent's role
4. Add node to workflow in `workflows.py`
5. Connect with appropriate edges and routing logic
