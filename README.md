# Memory Dump Analyzer

An AI-powered memory dump analyzer that uses hypothesis-driven investigation with LangGraph and WinDbg to automatically diagnose crashes, hangs, and memory issues.

## Documentation

- Setup and configuration: `docs/SETUP.md`
- Architecture overview: `docs/ARCHITECTURE.md`

## Features

- **Hypothesis-Driven Analysis**: Forms and tests hypotheses like an expert debugger
- **Adaptive Investigation**: Learns from evidence and pivots when hypotheses are rejected
- **Interactive Chat Mode**: Ask follow-up questions after automated analysis completes
- **Pattern Recognition**: Automatically recognizes common failure patterns (deadlocks, leaks, starvation, etc.)
- **Expert Knowledge Base**: Built-in heuristics and domain knowledge for quick diagnosis
- **Efficient Testing**: Tests hypotheses with 2-3 commands before deep investigation
- **Rich CLI**: Beautiful terminal interface with real-time analysis progress
- **Self-Correcting**: Automatically pivots to new hypotheses when evidence contradicts initial assumptions

## How It Works

The debugger works like an expert engineer would:

1. **Initial Hypothesis**: Forms an initial theory based on crash symptoms
2. **Test Hypothesis**: Runs targeted WinDbg commands to gather evidence
3. **Evaluate**: Determines if evidence confirms, rejects, or is inconclusive
4. **Adapt**: 
   - If CONFIRMED → Deep dive to find root cause
   - If REJECTED → Form alternative hypothesis
   - If INCONCLUSIVE → Gather more targeted evidence (max 2 attempts)
5. **Investigate**: Execute focused tasks to pinpoint the exact issue
6. **Reason**: Synthesize all evidence into coherent conclusions
7. **Review**: Critic agent reviews analysis for gaps, errors, contradictions (2 rounds)
8. **Refine**: If issues found, collect missing evidence and produce corrected analysis
9. **Report**: Generate actionable findings with suggested follow-up questions if needed

## Quality Assurance

Before presenting findings, a **CriticAgent** reviews the analysis for:

- **Architectural errors** (claims that violate how technologies actually work)
- **Evidence gaps** (conclusions without supporting data)
- **Logical contradictions** (conflicting statements)
- **Alternative explanations** (obvious alternatives not considered)

If issues are found:
1. **Round 1**: System collects missing evidence and re-analyzes with critique feedback
2. **Round 2**: Final verification - if issues remain, generates **follow-up questions** for user

This self-review catches errors before presenting to you, improving output quality.

## Why Hypothesis-Driven?

Traditional debuggers execute a fixed plan. This debugger **thinks**:

- **Forms hypotheses** based on symptoms and known patterns
- **Tests quickly** with 2-3 commands before committing to deep investigation
- **Pivots when wrong** instead of continuing down the wrong path
- **Applies expert knowledge** like thread count thresholds and common failure patterns
- **Self-reviews** through critic agent to catch errors before output
- **Builds evidence chains** showing how it reached conclusions

This mirrors how expert debuggers actually work—they don't blindly run commands; they form theories, test them, adapt, and validate their conclusions.

## Interactive Mode

After automated analysis completes, you can ask follow-up questions about the dump. The agent uses existing evidence when possible and executes new debugger commands only when needed.

**Suggested Questions**: If the quality review finds unresolved issues, the system generates specific follow-up questions you can ask to explore further:

```
🔍 Suggested Follow-Up Questions

1. Can you execute !threadpool to confirm thread pool statistics?
2. What evidence links the SQL timeouts to the compiler lock contention?
3. Could this be happening at runtime rather than initialization?
```

### Quick Start

```bash
# Basic analysis (interactive mode + command output enabled by default)
dump-debugger analyze crash.dmp --issue "App hanging"
```

### How It Works

The interactive agent follows a 3-step process for each question:

1. **Build Context** - Gathers relevant evidence from the automated analysis
2. **Assess Sufficiency** - Determines if existing evidence can answer the question
3. **Investigate** - Runs additional debugger commands only if more data is needed

### Special Commands

| Command | Description |
|---------|-------------|
| `/exit` or `/quit` | Exit interactive mode |
| `/help` | Show available commands |
| `/report` | Regenerate and display the full analysis report |
| `/history` | Show conversation history with message count |
| `/evidence` | List available evidence (conclusions, hypothesis tests, collected data) |

### Session Management

- **Timeout**: Sessions automatically timeout after 30 minutes
- **Message Limit**: Chat history limited to 50 messages
- **Graceful Exit**: Press Ctrl+C or Ctrl+D to exit anytime

### Example Session

```
═══════════════════════════════════════════════════
INTERACTIVE CHAT MODE
═══════════════════════════════════════════════════

You can ask follow-up questions about the dump.
Special commands: /exit (quit), /report (regenerate), /help (show help)
Session timeout: 30 minutes

Your question: What threads are blocked?

❓ Question: What threads are blocked?
✓ Sufficient evidence: Information available from !threads output

💬 Answer:
Based on the !threads output from the investigation, 18 out of 54 threads 
are blocked. They are all waiting on lock 0x000001a2b3c4d5e6 which is held 
by thread 42. The blocked threads have call stacks showing they're waiting 
in the VB expression compiler.

Your question: Show me thread 42's call stack

❓ Question: Show me thread 42's call stack
🔍 Need more data: Need to get specific thread call stack
Executing 1 investigative command(s)...
  Running: ~42s
  ✓ 00 00007ff8`1234abcd ntdll!NtWaitForSingleObject...

💬 Answer:
Thread 42 is the lock holder. Its call stack shows...

Your question: /exit

👋 Exiting interactive mode. Goodbye!
```

### Example Questions

**Root Cause Investigation:**
- "What was the last exception thrown?"
- "Which thread caused the crash?"
- "What is the root cause of the deadlock?"

**Thread Analysis:**
- "Show me all blocked threads"
- "What is thread 12 waiting for?"
- "Are there any threads in infinite loops?"

**Memory Analysis:**
- "Are there any memory leaks?"
- "What objects are consuming the most memory?"
- "Show me the largest objects on the heap"

**Lock Analysis:**
- "What locks are held?"
- "Which threads are waiting on locks?"
- "Is there a deadlock?"

**Exception Analysis:**
- "What exceptions were thrown?"
- "Show me the exception call stack"
- "What is the exception message?"

### Report Integration

All questions and answers from the interactive session are automatically appended to the final report under a "Follow-up Questions & Answers" section with:
- Each Q&A pair
- Commands executed for each answer
- Timestamps and evidence citations

This ensures your entire investigation is documented for future reference.

## Known Patterns

The debugger automatically recognizes these common issues:

- **Thread Pool Starvation** - All threads blocked, preventing work processing
- **SQL Connection Leak** - Unclosed database connections exhausting pool
- **Deadlock** - Circular lock dependencies between threads
- **Managed Memory Leak** - Objects retained in heap, preventing GC
- **Unmanaged Memory Leak** - Native heap growth from P/Invoke or COM
- **High GC Pressure** - Excessive garbage collection causing performance issues
- **Exception Storm** - Rapid-fire exceptions indicating deeper problems
- **Handle Leak** - File/registry handles not released
- **Async-over-Sync** - Blocking on async operations causing thread starvation

## Architecture

See `docs/ARCHITECTURE.md` for architecture documentation.

```
User Input → Form Hypothesis → Test → Evaluate
                    ↑              ↓
                    └── Rejected ──┘
                         ↓ Confirmed
                    Investigate Root Cause → Report
```

## Prerequisites

- Python 3.11+
- Windows Debugging Tools (CDB required; WinDbg optional)
  - CDB (`cdb.exe`) runs all commands, including data model (`dx`)
  - WinDbg (`windbg.exe`) can be used if you prefer, but is not required
- LLM Provider (one of the following):
  - Azure OpenAI or Claude via Azure AI Foundry
  - Standard OpenAI/Anthropic API key
  - Optional (recommended for local + tiered routing): Ollama + a code-capable model (e.g., qwen2.5-coder:7b, llama3.1:14b)

## Installation

1. Install uv (fast Python package manager):
```powershell
pip install uv
```

2. Clone the repository and install dependencies:
```powershell
cd c:\your_work_folder\projects\debugger\memory-dmp-debugger
uv sync
```

3. Configure environment:
```powershell
copy .env.example .env
# Edit .env with your API keys and paths
```

### Configuration Options

The tool supports multiple LLM providers. Configure in `.env`:

**Claude via Azure AI Foundry (Recommended):**
```env
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://your-project.services.ai.azure.com/models/anthropic/
AZURE_OPENAI_DEPLOYMENT=claude-sonnet-4-5
AZURE_OPENAI_API_VERSION=2024-10-01-preview
AZURE_OPENAI_API_KEY=your-key
```

**Azure OpenAI:**
```env
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://your-instance.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4
AZURE_OPENAI_API_KEY=your-key
```

**OpenAI:**
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-4-turbo-preview
```

**Anthropic:**
```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
```

See `docs/SETUP.md` for provider setup instructions.

## Usage

Basic usage (interactive mode + command output enabled by default):
```powershell
uv run dump-debugger analyze crash.dmp --issue "Application crashed on startup"
```

With output file:
```powershell
uv run dump-debugger analyze crash.dmp --issue "High CPU usage" --output report.md
```

Disable interactive mode if you just want automated analysis:
```powershell
uv run dump-debugger analyze crash.dmp --issue "Deadlock suspected" --no-interactive
```

Hide debugger command outputs (if you prefer cleaner output):
```powershell
uv run dump-debugger analyze crash.dmp --issue "App hanging" --no-show-command-output
```

Save detailed session log:
```powershell
uv run dump-debugger analyze crash.dmp --issue "Memory leak" --log-output session.log
```

### Session Management

Each analysis creates an isolated session with its own directory containing:
- Evidence database (SQLite) for large debugger outputs
- Session metadata and logs
- Analyzed chunks and findings

List all sessions:
```powershell
uv run dump-debugger sessions
```

Clean up old sessions:
```powershell
# Delete sessions older than 7 days, keep 5 most recent
uv run dump-debugger cleanup --days 7 --keep 5
```

**Session Isolation Benefits:**
- Each dump analysis is completely isolated
- Large outputs (>250KB) are automatically stored externally and analyzed in chunks
- Evidence from past analyses doesn't contaminate current analysis
- Session data persists for future reference
- Sessions are automatically cleaned up based on age

Sessions are stored in `.sessions/` directory by default. Each session is named with timestamp and dump file name:
```
.sessions/
  └── session_20251217_143052_crash_dmp/
      ├── evidence.db          # SQLite database with analyzed evidence
      ├── evidence/            # Large debugger outputs
      │   └── ev_threads_001.txt
      ├── metadata.json        # Session info
      └── session.log          # Full session log
```

For more workflow details, see `docs/ARCHITECTURE.md`.

## Evidence Management

The tool automatically handles large debugger outputs to ensure accurate analysis:

### Automatic Evidence Storage

When a debugger command produces large output (>250KB by default):
1. **Chunked Analysis**: Output is split into manageable chunks (~250KB each)
2. **LLM Analysis**: Each chunk is analyzed separately to extract key findings
3. **External Storage**: Full output stored in session directory
4. **Database Tracking**: Metadata and findings stored in SQLite
5. **Smart Retrieval**: Semantic search finds relevant evidence for questions

### Benefits

- **No Token Limits**: Large call stacks, thread dumps analyzed completely
- **Accurate Results**: No critical information lost to truncation
- **Fast Search**: Semantic embeddings find relevant evidence quickly
- **Session Isolation**: Evidence never crosses between different dump analyses

### Configuration

Adjust thresholds in `.env`:

**For Azure OpenAI Embeddings (Recommended):**
```env
# Enable semantic search with embeddings
USE_EMBEDDINGS=true
EMBEDDINGS_PROVIDER=azure

# Azure OpenAI embeddings deployment
AZURE_EMBEDDINGS_DEPLOYMENT=text-embedding-3-small

# Storage thresholds
EVIDENCE_STORAGE_THRESHOLD=250000  # Store outputs larger than 250KB
EVIDENCE_CHUNK_SIZE=250000         # Chunk size for LLM analysis (~250KB optimized for Claude)

# Optional: Use separate endpoint/key for embeddings
# If not specified, uses AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY
#AZURE_EMBEDDINGS_ENDPOINT=https://your-instance.openai.azure.com/
#AZURE_EMBEDDINGS_API_KEY=your-embeddings-key
```

**For Standard OpenAI Embeddings:**
```env
# Enable semantic search with embeddings
USE_EMBEDDINGS=true
EMBEDDINGS_PROVIDER=openai
EMBEDDINGS_MODEL=text-embedding-3-small

# Requires OpenAI API key
OPENAI_API_KEY=sk-...
```

**Disable Embeddings (Use Keyword Search):**
```env
USE_EMBEDDINGS=false
```

## Example Output

### Console Output
```
🧠 Starting Expert Analysis (Hypothesis-Driven)

📋 Forming Initial Hypothesis
💡 Hypothesis: Thread pool starvation due to blocking operations
🎯 Confidence: HIGH
🔍 Will test with: !threads, !syncblk, ~*e!clrstack

🧪 Testing Hypothesis
  → !threads
  → !syncblk
  → ~*e!clrstack

✅ Result: CONFIRMED
18 out of 54 threads blocked on compiler locks...

🔍 Investigating Root Cause
Task 1/4: Analyze lock holders and waiters
Task 2/4: Examine blocking call stacks
Task 3/4: Identify resource contention pattern
Task 4/4: Validate corruption in synchronization objects

📊 Final Report
ROOT CAUSE: Visual Basic expression compiler lock contention
IMPACT: 35% of threads blocked, workflow initialization hung
RECOMMENDATION: Pre-compile VB expressions at startup, implement throttling
```

### Generated Report (example)
```markdown
## Executive Summary

YES, the application is in a hang state. Analysis confirms that 35% of all 
threads (18 out of 54) are blocked waiting for Visual Basic expression 
compiler locks. The application is experiencing severe lock contention in 
the Windows Workflow Foundation's Visual Basic compiler component.

**Severity:** Critical
**Impact:** Multiple workflow instances cannot start
**Root Cause:** Architectural bottleneck in VB expression compilation

## Key Findings

### 1. Lock Contention Bottleneck
- 4 threads hold Monitor locks on HostedCompiler objects
- 18 threads blocked waiting for these locks
- Thread 19: 9 threads waiting
- Thread 18: 7 threads waiting

### 2. Memory Corruption Detected
- Lock object at 0x0000027df1812988 is corrupted/invalid
- Makes deadlock unrecoverable without restart

## Recommendations

1. **Restart immediately** - Corrupted lock makes recovery impossible
2. **Implement throttling** - Limit concurrent workflow initialization
3. **Pre-compile expressions** - Move compilation to startup phase
4. **Monitor lock contention** - Alert when >10 threads blocked
```

Tip: you can write reports to a file via `--output <path>`.

## Performance

| Metric | Time | Commands | Accuracy |
|--------|------|----------|----------|
| Simple issues (direct pattern match) | 2-3 min | 8-11 | ~95% |
| Complex issues (multiple hypotheses) | 3-4 min | 12-15 | ~90% |
| Issues requiring pivoting | 4-5 min | 15-18 | ~85% |

**Key Benefits:**
- **40% fewer commands** than exhaustive investigation approaches
- **50-60% faster** than manual analysis
- **Adaptive** - pivots when initial hypothesis is wrong
- **Expert-level** - applies domain knowledge and pattern recognition

## Project Structure

```
src/dump_debugger/
├── agents/                # AI agents for different analysis tasks
│   ├── critic.py         # Reviews analysis for errors/gaps
│   ├── hypothesis.py     # Forms and tests hypotheses
│   ├── investigator.py   # Executes investigation plans
│   ├── reasoner.py       # Synthesizes evidence into conclusions
│   ├── report_writer.py  # Generates final reports
│   └── interactive_chat.py  # Handles follow-up questions
├── analyzers/            # Specialized debugger output parsers
│   ├── clrstack.py       # Call stack analysis
│   ├── threads.py        # Thread state analysis
│   ├── syncblk.py        # Lock contention analysis
│   └── ...               # Other specialized analyzers
├── core/                 # Core debugger integration
│   └── debugger.py       # WinDbg/CDB wrapper
├── evidence/             # Evidence management system
│   ├── analyzer.py       # Analyzes large outputs in chunks
│   ├── retrieval.py      # Semantic/keyword search
│   └── storage.py        # SQLite storage for evidence
├── state/                # LangGraph state definitions
│   └── __init__.py       # AnalysisState and related models
├── prompts/              # LLM prompts for agents
│   └── __init__.py       # Prompt templates
├── session/              # Session management
│   └── __init__.py       # Session creation and cleanup
├── workflows.py          # LangGraph workflow orchestration
├── cli.py                # CLI entry point
├── config.py             # Configuration management
├── llm.py                # LLM provider abstraction
├── llm_router.py         # Cloud/local LLM routing
├── token_tracker.py      # Token usage tracking
├── expert_knowledge.py   # Pattern recognition and heuristics
└── analyzer_stats.py     # Usage statistics tracking
```

## Development

Run tests:
```powershell
uv run pytest
```

Format code:
```powershell
uv run black src/
uv run ruff check src/
```

## Documentation

- `docs/SETUP.md` - Setup and configuration
- `docs/ARCHITECTURE.md` - Architecture overview

## License

MIT License
