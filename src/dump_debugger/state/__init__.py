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
    
    # Planning
    investigation_plan: list[str]  # High-level tasks to investigate
    current_task: str  # Current task being worked on
    current_task_index: int
    
    # Execution history
    commands_executed: list[CommandResult]
    findings: list[str]  # Key findings discovered so far
    
    # Agent reasoning (for chain of thought)
    planner_reasoning: str
    debugger_reasoning: str
    analyzer_reasoning: str
    
    # Control flow
    iteration: int
    max_iterations: int
    should_continue: bool
    needs_more_investigation: bool
    
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
