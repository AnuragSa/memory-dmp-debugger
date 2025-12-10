# Project Structure

```
memory-dmp-debugger/
│
├── 📄 README.md                    # Main project documentation
├── 📄 QUICKSTART.md                # Quick installation & usage guide
├── 📄 ARCHITECTURE.md              # System architecture & design
├── 📄 IMPLEMENTATION.md            # Implementation details & notes
├── 📄 EXAMPLE_OUTPUT.md            # Sample output demonstration
├── 📄 pyproject.toml               # Poetry dependencies & config
├── 📄 .env.example                 # Environment variables template
├── 📄 .gitignore                   # Git ignore rules
│
├── 📁 src/dump_debugger/           # Main source code
│   ├── 📄 __init__.py              # Package initialization
│   ├── 📄 config.py                # Configuration management
│   ├── 📄 llm.py                   # LLM provider utilities
│   ├── 📄 cli.py                   # CLI interface (Click + Rich)
│   │
│   ├── 📁 core/                    # Core debugger functionality
│   │   ├── 📄 __init__.py
│   │   └── 📄 debugger.py          # WinDbg/CDB wrapper
│   │
│   ├── 📁 agents/                  # Agent implementations
│   │   └── 📄 __init__.py          # All agents:
│   │                                 • PlannerAgent
│   │                                 • DebuggerAgent
│   │                                 • AnalyzerAgent
│   │                                 • ReportWriterAgent
│   │
│   ├── 📁 state/                   # LangGraph state definitions
│   │   └── 📄 __init__.py          # State types & schemas
│   │
│   ├── 📁 prompts/                 # System prompts for agents
│   │   └── 📄 __init__.py          # All agent prompts
│   │
│   └── 📁 workflows/               # LangGraph workflow
│       └── 📄 __init__.py          # Workflow definition & orchestration
│
└── 📁 tests/                       # Test suite
    ├── 📄 __init__.py
    ├── 📄 conftest.py              # Test fixtures
    ├── 📄 test_debugger.py         # Debugger tests
    └── 📄 test_agents.py           # Agent tests
```

## File Descriptions

### Root Level

| File | Purpose |
|------|---------|
| `README.md` | Project overview, features, installation |
| `QUICKSTART.md` | Fast-track guide to get started |
| `ARCHITECTURE.md` | Detailed system design & diagrams |
| `IMPLEMENTATION.md` | Technical implementation notes |
| `EXAMPLE_OUTPUT.md` | Sample analysis output |
| `pyproject.toml` | Python dependencies (Poetry) |
| `.env.example` | Environment configuration template |
| `.gitignore` | Version control ignore rules |

### Source Code (`src/dump_debugger/`)

| Module | Purpose | Key Classes/Functions |
|--------|---------|----------------------|
| `config.py` | Settings management | `Settings`, `settings` |
| `llm.py` | LLM provider abstraction | `get_llm()`, `get_structured_llm()` |
| `cli.py` | Command-line interface | `analyze()`, `validate()`, `setup()` |

### Core Module (`core/`)

| File | Purpose | Key Components |
|------|---------|---------------|
| `debugger.py` | WinDbg automation | `DebuggerWrapper`, command execution, output parsing |

### Agents Module (`agents/`)

| Agent | Purpose | Input | Output |
|-------|---------|-------|--------|
| `PlannerAgent` | Creates investigation plan | Issue description | Task list |
| `DebuggerAgent` | Generates & executes commands | Current task | Command result |
| `AnalyzerAgent` | Interprets command output | Command result | Findings |
| `ReportWriterAgent` | Creates final report | All findings | Markdown report |

### State Module (`state/`)

| Type | Purpose |
|------|---------|
| `AnalysisState` | Main workflow state (TypedDict) |
| `PlannerOutput` | Planner agent output schema |
| `DebuggerOutput` | Debugger agent output schema |
| `AnalyzerOutput` | Analyzer agent output schema |
| `CommandResult` | Command execution result |

### Prompts Module (`prompts/`)

| Constant | Purpose |
|----------|---------|
| `PLANNER_PROMPT` | Instructs planner on creating investigation plans |
| `DEBUGGER_AGENT_PROMPT` | Guides command generation (includes dx examples) |
| `ANALYZER_AGENT_PROMPT` | Helps interpret debugger output |
| `REPORT_WRITER_PROMPT` | Formats comprehensive reports |
| `LLM_SYSTEM_CONTEXT` | General system context for all agents |

### Workflows Module (`workflows/`)

| Function | Purpose |
|----------|---------|
| `create_workflow()` | Builds LangGraph StateGraph |
| `run_analysis()` | Executes complete analysis |

### Tests Module (`tests/`)

| File | Purpose |
|------|---------|
| `conftest.py` | Shared test fixtures |
| `test_debugger.py` | Tests for WinDbg wrapper |
| `test_agents.py` | Tests for agent logic |

## Module Dependencies

```
cli.py
  ├─→ workflows/ (run_analysis)
  └─→ core/ (DebuggerWrapper)

workflows/
  ├─→ agents/ (all agents)
  ├─→ core/ (DebuggerWrapper)
  ├─→ state/ (AnalysisState)
  └─→ config/ (settings)

agents/
  ├─→ llm/ (get_llm)
  ├─→ prompts/ (all prompts)
  ├─→ state/ (type definitions)
  └─→ core/ (DebuggerWrapper)

core/debugger.py
  └─→ config/ (settings)

llm.py
  └─→ config/ (settings)
```

## Command Entry Points

```
uv run dump-debugger
  ├─→ analyze     (Main analysis command)
  ├─→ validate    (Dump validation)
  └─→ setup       (Configuration wizard)
```

## Data Flow Through System

```
User Input
    ↓
CLI (cli.py)
    ↓
Workflow (workflows/)
    ↓
┌─────────────────────────────┐
│  LangGraph State Machine    │
│                             │
│  Planner → Debugger →       │
│  Analyzer → [Loop] →        │
│  Report Writer              │
└─────────────────────────────┘
    ↓
Rich Console Output + Report
```

## Key Files to Understand

For understanding the system, read in this order:

1. **README.md** - Overview
2. **ARCHITECTURE.md** - High-level design
3. **state/__init__.py** - Data structures
4. **prompts/__init__.py** - Agent instructions
5. **agents/__init__.py** - Agent implementations
6. **workflows/__init__.py** - Orchestration logic
7. **core/debugger.py** - WinDbg integration
8. **cli.py** - User interface

## Lines of Code

- Core logic: ~1,200 lines
- Documentation: ~1,500 lines
- Total: ~2,700 lines

## Technologies Used

- **LangChain/LangGraph**: Agent orchestration
- **Rich**: Terminal UI
- **Click**: CLI framework
- **Pydantic**: Configuration & validation
- **uv**: Fast Python package manager
- **pytest**: Testing
