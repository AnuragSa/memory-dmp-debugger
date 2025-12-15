# Memory Dump Debugger

An AI-powered memory dump analyzer that uses hypothesis-driven investigation with LangGraph and WinDbg to automatically diagnose crashes, hangs, and memory issues.

## Features

- 🧠 **Hypothesis-Driven Analysis**: Forms and tests hypotheses like an expert debugger
- 🎯 **Adaptive Investigation**: Learns from evidence and pivots when hypotheses are rejected
- 🤖 **Expert Knowledge Base**: Built-in patterns for common crash types (access violations, deadlocks, etc.)
- 📊 **Structured Evidence**: Uses WinDbg data model (`dx`) commands for rich, parseable data
- 🔍 **Root Cause Focus**: Goes beyond symptoms to find the actual source of problems
- 📈 **Rich CLI**: Beautiful terminal interface with real-time analysis progress

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
6. **Report**: Generate actionable findings with evidence

## Architecture

See [EXPERT_ARCHITECTURE.md](EXPERT_ARCHITECTURE.md) for detailed architecture documentation.

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
- OpenAI API key or Anthropic API key

## Installation

1. Install uv (if not already installed):
```bash
pip install uv
```

2. Clone the repository and install dependencies:
```bash
cd c:\Anurag\projects\debugger\memory-dmp-debugger
uv sync
```

3. Configure environment:
```bash
copy .env.example .env
# Edit .env with your API keys and paths
```

## Usage

Basic usage:
```bash
uv run dump-debugger analyze "C:\Users\AnuragSaxena\Downloads\mem-dumps\dmp2.dmp" --issue "Investigate what issues do you see?" --show-commands
```

With output file:
```bash
uv run dump-debugger analyze crash.dmp --issue "High CPU usage" --output report.md
```

Show debugger commands as they execute:
```bash
uv run dump-debugger analyze crash.dmp --issue "Deadlock suspected" --show-commands
```

For more examples and workflow details, see [EXPERT_QUICK_REFERENCE.md](EXPERT_QUICK_REFERENCE.md).

## Example Output

```
🧠 Starting Expert Analysis (Hypothesis-Driven)

📋 Forming Initial Hypothesis
💡 Hypothesis: Access violation due to null pointer dereference
🎯 Confidence: HIGH
🔍 Will test with: !analyze -v, k, r

🧪 Testing Hypothesis
  → !analyze -v
  → k
  → r

❌ Result: REJECTED
Evidence shows stack overflow, not null pointer...

🔄 New Hypothesis: Stack overflow from infinite recursion
✓ Result: CONFIRMED

🔍 Investigating Root Cause
Task 1/3: Identify recursive function
Task 2/3: Examine loop condition
Task 3/3: Find termination bug

📊 Final Report
ROOT CAUSE: Infinite recursion in ProcessRequest...
```

## Project Structure

```
src/dump_debugger/
├── hypothesis_agent.py    # Hypothesis formation and testing
├── expert_knowledge.py    # Known crash patterns and focus areas
├── core/                  # Debugger wrapper (WinDbg/CDB integration)
├── state/                 # LangGraph state definitions
├── workflows.py           # Main analysis workflow
├── cli.py                 # CLI entry point
└── config.py             # Configuration management
```

## Development

## Development

Run tests:
```bash
uv run pytest
```

Format code:
```bash
uv run black src/
uv run ruff check src/
```

## Documentation

- [EXPERT_ARCHITECTURE.md](EXPERT_ARCHITECTURE.md) - Detailed architecture and design decisions
- [EXPERT_QUICK_REFERENCE.md](EXPERT_QUICK_REFERENCE.md) - Quick reference for using the tool
- [AZURE_AI_SETUP.md](AZURE_AI_SETUP.md) - Setup guide for Azure AI / Claude
- [UV_GUIDE.md](UV_GUIDE.md) - Guide to using uv package manager

## License

MIT License
