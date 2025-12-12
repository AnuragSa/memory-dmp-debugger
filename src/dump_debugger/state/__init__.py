"""State definitions for the LangGraph workflow."""

from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import add_messages


class CommandResult(TypedDict):
    """Result from executing a debugger command."""
    command: str
    output: str
    parsed: Any
    success: bool
    error: str | None
    reasoning: str  # Why this command was chosen


class AnalysisState(TypedDict):
    """State that flows through the LangGraph workflow."""
    
    # Input
    dump_path: str
    issue_description: str
    dump_type: str  # "user" or "kernel"
    supports_dx: bool  # Whether data model commands are available
    
    # Planning
    investigation_plan: list[str]  # High-level tasks to investigate
    current_task: str  # Current task being worked on
    current_task_index: int
    
    # Execution history
    commands_executed: list[CommandResult]
    findings: list[str]  # Key findings discovered so far
    discovered_properties: dict[str, list[str]]  # Track verified object properties
    
    # Agent reasoning (for chain of thought)
    planner_reasoning: str
    debugger_reasoning: str
    analyzer_reasoning: str
    
    # Analyzer data request (step 2 in sequence)
    data_request: str  # Specific data the analyzer wants the debugger to collect
    data_request_reasoning: str  # Why this data is needed
    
    # Control flow
    iteration: int
    max_iterations: int
    should_continue: bool
    needs_more_investigation: bool
    task_complete: bool  # Whether current task is complete
    failed_commands_current_task: int  # Track failed commands for current task to prevent infinite loops
    analyzer_feedback: str  # Feedback from analyzer to guide next command
    recent_data_requests: list[str]  # Track recent requests to detect repetitive loops
    commands_executed_current_task: list[str]  # Track commands per task to detect repetition
    sos_loaded: bool  # Track if SOS extension is loaded for .NET debugging
    _sos_load_attempted: bool  # Internal flag to prevent repeated SOS load attempts
    show_commands: bool  # Whether to display debugger command outputs
    syntax_errors: list[dict[str, str]]  # Track syntax errors: [{"command": "...", "error": "..."}]
    
    # Final output
    final_report: str | None
    confidence_level: Literal["high", "medium", "low"] | None
    
    # Messages for LLM conversation (using LangGraph's add_messages reducer)
    messages: Annotated[list[dict[str, Any]], add_messages]


class PlannerOutput(TypedDict):
    """Output from the planner agent."""
    investigation_plan: list[str]
    reasoning: str
    estimated_complexity: Literal["simple", "moderate", "complex"]


class DebuggerOutput(TypedDict):
    """Output from the debugger agent."""
    command: str
    reasoning: str
    expected_insights: str  # What we expect to learn from this command


class AnalyzerOutput(TypedDict):
    """Output from the analyzer agent."""
    findings: list[str]
    reasoning: str
    needs_more_investigation: bool
    suggested_next_steps: list[str] | None
