# Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        User Input                           │
│  (Dump Path + Issue Description)                            │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                   LangGraph Workflow                        │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  1. Planner Agent                                    │  │
│  │     • Analyzes issue description                     │  │
│  │     • Creates investigation plan                     │  │
│  │     • Breaks down into tasks                         │  │
│  │     • LLM generates plan dynamically                 │  │
│  └──────────────┬───────────────────────────────────────┘  │
│                 │                                           │
│                 ▼                                           │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  2. Debugger Agent                                   │  │
│  │     • Receives current task                          │  │
│  │     • LLM generates WinDbg command                   │  │
│  │     • Executes via DebuggerWrapper                   │  │
│  │     • Prefers dx (data model) commands               │  │
│  │     • Returns structured output                      │  │
│  └──────────────┬───────────────────────────────────────┘  │
│                 │                                           │
│                 ▼                                           │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  3. Analyzer Agent                                   │  │
│  │     • Parses command output                          │  │
│  │     • Extracts key findings                          │  │
│  │     • Identifies patterns                            │  │
│  │     • Decides if more investigation needed           │  │
│  │     • Suggests next steps                            │  │
│  └──────────────┬───────────────────────────────────────┘  │
│                 │                                           │
│                 ▼                                           │
│            ┌─────────┐                                      │
│            │Continue?│                                      │
│            └────┬────┘                                      │
│                 │                                           │
│        Yes ◄────┴────► No                                   │
│         │                │                                  │
│         ▼                ▼                                  │
│   Next Task     ┌────────────────────────┐                 │
│   (Loop back)   │  4. Report Writer      │                 │
│                 │     • Synthesizes      │                 │
│                 │       findings         │                 │
│                 │     • Creates report   │                 │
│                 │     • Recommendations  │                 │
│                 └────────────────────────┘                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                   Rich CLI Output                           │
│  • Real-time chain-of-thought display                       │
│  • Progress indicators                                      │
│  • Colored output by agent                                  │
│  • Command execution logs                                   │
│  • Final markdown report                                    │
└─────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. DebuggerWrapper (`core/debugger.py`)
- Wraps WinDbg/CDB command execution
- Handles subprocess management
- Parses dx (data model) output into structured format
- Cleans debugger noise from output
- Validates dump files

### 2. LangGraph State (`state/__init__.py`)
- `AnalysisState`: Main state flowing through workflow
- Tracks investigation plan, executed commands, findings
- Maintains agent reasoning for chain-of-thought
- Controls iteration and continuation logic

### 3. Agents (`agents/__init__.py`)

#### PlannerAgent
- Input: Issue description, dump type
- Output: Investigation plan (4-6 tasks)
- Uses LLM to create adaptive plans

#### DebuggerAgent  
- Input: Current task, previous outputs
- Output: Next WinDbg command to execute
- **Key Feature**: LLM generates commands dynamically
- Prefers dx commands for structure

#### AnalyzerAgent
- Input: Command output
- Output: Findings, continuation decision
- Interprets results, identifies root causes

#### ReportWriterAgent
- Input: Complete investigation history
- Output: Markdown report
- Synthesizes findings into actionable insights

### 4. LLM Provider (`llm.py`)
- Supports: OpenAI, Anthropic, Azure OpenAI
- Configurable via environment variables
- JSON mode for structured outputs

### 5. CLI (`cli.py`)
- Built with Click + Rich
- Commands: analyze, validate, setup
- Real-time progress display
- Markdown report rendering

## Data Flow

```
Issue → Plan → [Task Loop: Command → Execute → Analyze → Next?] → Report
```

## Key Design Decisions

### 1. LLM-Generated Commands ✨
- **Why**: Adaptive to any dump scenario
- **How**: Context-aware command generation
- **Benefit**: Not limited by hardcoded scripts

### 2. Data Model (dx) First
- **Why**: Structured output easier to parse
- **How**: Prompts guide LLM to prefer dx
- **Benefit**: Reduces token usage, better reasoning

### 3. Iterative Investigation
- **Why**: Real debugging is exploratory
- **How**: Analyzer decides if more work needed
- **Benefit**: Thorough analysis without wasted commands

### 4. Chain of Thought Visibility
- **Why**: User trust and transparency
- **How**: Rich CLI shows all reasoning
- **Benefit**: User understands what's happening

### 5. State-Based Workflow
- **Why**: Complex branching logic
- **How**: LangGraph StateGraph
- **Benefit**: Easy to extend, debug, modify

## Extensibility

### Adding New Agent Types
1. Create new agent class in `agents/`
2. Add to workflow graph
3. Define prompts in `prompts/`

### Supporting New Dump Types
1. Add detection in `DebuggerWrapper.get_dump_type()`
2. Update planner prompts
3. Add specialized commands to debugger agent prompts

### Custom Reporting
1. Extend `ReportWriterAgent`
2. Add templates
3. Support different output formats (HTML, PDF, etc.)

## Future Enhancements (Phase 2)

1. **Web UI**: React + FastAPI backend
2. **Interactive Mode**: Human-in-the-loop approvals
3. **Comparison Analysis**: Compare multiple dumps
4. **Pattern Library**: Learn from previous analyses
5. **Team Collaboration**: Share analyses
6. **Integration**: CI/CD pipeline integration
