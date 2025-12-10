# Quick Start Guide

## Installation

1. **Install uv** (if not already installed):
```powershell
pip install uv
```

2. **Install Dependencies**:
```powershell
cd c:\Anurag\projects\debugger\memory-dmp-debugger
uv sync
```

3. **Setup Configuration**:
```powershell
uv run dump-debugger setup
```

Then edit `.env` file with your settings:
- Add your OpenAI API key (or Anthropic/Azure)
- Update paths to WinDbg/CDB if different
- Configure symbol paths

## Basic Usage

### Analyze a Dump

```powershell
# Basic analysis
uv run dump-debugger analyze path\to\dump.dmp --issue "Application crashed on startup"

# Save report to file
uv run dump-debugger analyze crash.dmp --issue "High CPU usage" --output report.md

# Interactive mode (coming soon)
uv run dump-debugger analyze hang.dmp --issue "Application hangs" --interactive
```

### Validate a Dump

```powershell
uv run dump-debugger validate path\to\dump.dmp
```

## Example Scenarios

### Crash Analysis
```powershell
uv run dump-debugger analyze app_crash.dmp --issue "Application crashed with access violation"
```

### Hang Investigation
```powershell
uv run dump-debugger analyze app_hang.dmp --issue "Application stops responding"
```

### Memory Leak
```powershell
uv run dump-debugger analyze memleak.dmp --issue "Memory usage keeps growing"
```

## What to Expect

The tool will:
1. 📋 Create an investigation plan based on your issue
2. 🔧 Generate and execute WinDbg commands dynamically
3. 🧪 Analyze results and extract findings
4. 📝 Generate a comprehensive report

You'll see real-time chain-of-thought output showing:
- What each agent is thinking
- Why commands are being executed
- What was discovered
- Progress through investigation tasks

## Troubleshooting

### "Debugger not found"
Update `CDB_PATH` in `.env` to point to your WinDbg installation:
```
CDB_PATH=C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe
```

### "API key not configured"
Make sure you've set your LLM provider's API key in `.env`:
```
OPENAI_API_KEY=sk-...
```

### Symbol Loading Issues
Configure symbol path in `.env`:
```
SYMBOL_PATH=SRV*c:\symbols*https://msdl.microsoft.com/download/symbols
```

## Advanced Configuration

See `.env.example` for all available configuration options including:
- Different LLM providers (OpenAI, Anthropic, Azure)
- Model selection
- Iteration limits
- Command timeouts
- Logging levels

## Next Steps

After installation:
1. Run `uv run dump-debugger setup` to create your configuration
2. Try validating a dump file with `validate` command
3. Run a full analysis with `analyze` command
4. Check the generated reports for insights
