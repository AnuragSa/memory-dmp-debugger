# Memory Dump Debugger

An AI-powered memory dump analyzer that uses LangGraph multi-agent system and WinDbg to automatically investigate crashes, hangs, and memory issues.

## Features

- 🤖 **Multi-Agent System**: Specialized agents for planning, debugging, analysis, and reporting
- 🧠 **LLM-Generated Commands**: Dynamically generates WinDbg/CDB commands based on analysis context
- 📊 **Data Model First**: Prefers structured `dx` commands for better reasoning
- 🔍 **Chain of Thought**: Real-time visibility into agent reasoning and actions
- 📈 **Rich CLI**: Beautiful terminal interface with progress tracking
- 🔄 **Iterative Analysis**: Agents learn from previous outputs to guide next steps

## Architecture

```
User Input (Dump Path + Issue Description)
    ↓
Planner Agent (Break down investigation tasks)
    ↓
Debugger Agent (Generate & execute WinDbg commands)
    ↓
Analyzer Agent (Interpret results, identify patterns)
    ↓
Report Writer Agent (Generate actionable findings)
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
uv run dump-debugger analyze path/to/dump.dmp --issue "Application crashed on startup"
```

With custom issue description:
```bash
uv run dump-debugger analyze myapp.dmp --issue "High CPU usage before crash"
```

Interactive mode:
```bash
uv run dump-debugger analyze crash.dmp --interactive
```

## Example Output

```
🔍 Memory Dump Debugger
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 Planning Phase
  └─ Breaking down investigation for: "Application crashed on startup"
  └─ Tasks identified: 
     • Analyze crash context
     • Examine exception record
     • Investigate call stack
     • Review loaded modules

🔧 Debugger Agent
  └─ Generating command: dx @$curprocess.Threads[0].Stack.Frames
  └─ Executing...
  └─ Found: Access violation in ntdll!RtlRaiseException

🧪 Analyzer Agent
  └─ Reasoning: Exception suggests null pointer dereference
  └─ Next action: Examine exception details

...
```

## Project Structure

```
src/dump_debugger/
├── agents/          # Agent implementations
├── core/            # Core functionality (debugger wrapper)
├── prompts/         # System prompts for agents
├── state/           # LangGraph state definitions
├── workflows/       # LangGraph workflow definitions
└── cli.py          # CLI entry point
```

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

## License

MIT License
