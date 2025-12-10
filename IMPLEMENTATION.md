# Implementation Notes

## What's Been Built

A complete AI-powered memory dump debugger with the following components:

### ✅ Core Components

1. **WinDbg/CDB Automation** (`core/debugger.py`)
   - Command execution via subprocess
   - Output parsing (dx and traditional commands)
   - Dump validation
   - Error handling

2. **Multi-Agent System** (`agents/__init__.py`)
   - PlannerAgent: Creates investigation plans
   - DebuggerAgent: Generates and executes commands
   - AnalyzerAgent: Interprets results
   - ReportWriterAgent: Produces final reports
   - All agents use LLM for dynamic decision-making

3. **LangGraph Workflow** (`workflows/__init__.py`)
   - State management
   - Conditional routing
   - Iterative investigation loop
   - Automatic task progression

4. **Rich CLI** (`cli.py`)
   - Beautiful terminal output
   - Real-time chain-of-thought display
   - Progress indicators
   - Markdown report rendering

5. **Configuration System** (`config.py`)
   - Environment-based settings
   - Multiple LLM provider support
   - Flexible debugger paths

## How It Works

### Command Generation Flow

```python
# 1. User provides issue
issue = "Application crashed on startup"

# 2. Planner creates tasks
tasks = llm.generate([
    "Identify exception context",
    "Analyze call stack",
    "Examine exception details"
])

# 3. For each task, Debugger Agent generates command
command = llm.generate_command(
    task="Identify exception context",
    previous_outputs=[...],
    dump_type="user"
)
# Result: "dx @$curprocess.Threads[0].LastException"

# 4. Execute command
result = debugger.execute(command)

# 5. Analyzer interprets
findings = llm.analyze(result)

# 6. Repeat or report
```

### Key Innovations

1. **No Hardcoded Commands**: Every command is LLM-generated based on context
2. **Adaptive Investigation**: Analysis determines next steps
3. **Data Model Preference**: Prefers structured dx commands
4. **Context Management**: Keeps relevant history without token overflow
5. **Transparent Reasoning**: Shows why each decision was made

## Installation Steps

```powershell
# 1. Install uv
pip install uv

# 2. Install dependencies
cd c:\Anurag\projects\debugger\memory-dmp-debugger
uv sync

# 3. Setup configuration
uv run dump-debugger setup

# 4. Edit .env file with your API key
notepad .env
```

## Testing the System

### Without a Real Dump (Dry Run)

You can test the agent logic without a dump file by mocking the debugger:

```python
# tests/test_integration.py (create this)
from dump_debugger.agents import PlannerAgent
from dump_debugger.state import AnalysisState

def test_planner():
    planner = PlannerAgent()
    state: AnalysisState = {
        "dump_type": "user",
        "issue_description": "Crash on startup",
        # ... other required fields
    }
    result = planner.plan(state)
    assert "investigation_plan" in result
    assert len(result["investigation_plan"]) > 0
```

### With a Real Dump

```powershell
# Get a sample dump (create one or use existing)
uv run dump-debugger validate mydump.dmp

# Run full analysis
uv run dump-debugger analyze mydump.dmp --issue "Application crashed"
```

## Common Scenarios

### Scenario 1: Crash Analysis
**Issue**: "Application crashed with exception"
**Commands Generated**:
1. `dx @$curprocess.Threads[0].LastException`
2. `dx @$curprocess.Threads[0].Stack.Frames`
3. `dx @$curprocess.Threads[0].LastException.ExceptionRecord`

### Scenario 2: Hang Analysis  
**Issue**: "Application stops responding"
**Commands Generated**:
1. `dx @$curprocess.Threads`
2. `dx @$curprocess.Threads[X].Stack.Frames` (for each interesting thread)
3. Traditional `!locks` if needed

### Scenario 3: Memory Leak
**Issue**: "Memory usage keeps growing"
**Commands Generated**:
1. `!heap -s` (traditional, no dx equivalent)
2. `dx @$curprocess.Memory`
3. `!heap -stat -h <heap_handle>`

## Extending the System

### Add a New Agent Type

```python
# agents/__init__.py

class SymbolAgent:
    """Agent specialized in symbol-related issues."""
    
    def __init__(self):
        self.llm = get_structured_llm()
    
    def check_symbols(self, state: AnalysisState) -> dict:
        # Check if symbols are properly loaded
        # Generate appropriate symbol commands
        pass

# Add to workflow
workflow.add_node("check_symbols", symbol_agent.check_symbols)
workflow.add_edge("plan", "check_symbols")
workflow.add_edge("check_symbols", "debug")
```

### Add Custom Command Templates

```python
# prompts/__init__.py

SPECIALIZED_COMMANDS = """
For deadlock analysis:
- !locks
- !cs -l
- dx @$curprocess.Threads[?(@.State == "Waiting")]

For handle leaks:
- !handle
- dx @$curprocess.Io.Handles

For heap corruption:
- !heap -p -a <address>
- !gflag +hpa
"""

# Add to DEBUGGER_AGENT_PROMPT
```

### Add New Output Formats

```python
# cli.py

@cli.command()
@click.option("--format", type=click.Choice(["markdown", "html", "json"]))
def analyze(dump_path, issue, format):
    # ... existing code ...
    
    if format == "html":
        generate_html_report(final_state)
    elif format == "json":
        generate_json_report(final_state)
```

## Troubleshooting

### Issue: "Debugger not found"
**Solution**: Update `.env` with correct path
```ini
CDB_PATH=C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe
```

### Issue: "API key not configured"
**Solution**: Add API key to `.env`
```ini
OPENAI_API_KEY=sk-your-key-here
LLM_PROVIDER=openai
```

### Issue: "Command timeout"
**Solution**: Increase timeout in `.env`
```ini
COMMAND_TIMEOUT=300
```

### Issue: Symbols not loading
**Solution**: Configure symbol path
```ini
SYMBOL_PATH=SRV*c:\symbols*https://msdl.microsoft.com/download/symbols
```

## Performance Considerations

### Token Usage
- Each iteration uses ~1000-3000 tokens
- With 15 max iterations: ~15,000-45,000 tokens
- Cost (GPT-4): ~$0.50-$1.50 per analysis
- Cost (GPT-3.5): ~$0.05-$0.15 per analysis

### Optimization Strategies
1. **Truncate long outputs**: Already implemented (1000 char limit)
2. **Summarize findings**: Keep only key points
3. **Use cheaper models**: GPT-3.5 for initial commands, GPT-4 for analysis
4. **Parallel commands**: Not implemented yet, but possible

### Execution Time
- Typical analysis: 2-5 minutes
- Complex analysis: 5-15 minutes
- Depends on:
  - Number of tasks
  - Command execution time
  - LLM response time

## Security Considerations

1. **API Keys**: Store in `.env`, never commit
2. **Dump Files**: May contain sensitive data
3. **Output Reports**: Sanitize before sharing externally
4. **Command Injection**: Already handled (no shell=True in subprocess)

## Next Steps (Phase 2)

### Web UI (React + FastAPI)
- Real-time WebSocket updates
- Visual task graph
- Interactive command approval
- Team collaboration features

### Features to Add
1. **Comparison Mode**: Compare multiple dumps
2. **Pattern Learning**: Remember successful investigation patterns
3. **Custom Plugins**: User-defined agents
4. **Integration**: CI/CD pipeline support
5. **Batch Analysis**: Process multiple dumps
6. **Historical Analysis**: Track issues over time

## Contributing

To contribute:
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure code passes `black` and `ruff`
5. Submit pull request

## License

MIT License - See LICENSE file for details
