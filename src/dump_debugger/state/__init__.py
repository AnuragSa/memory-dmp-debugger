"""State definitions for the LangGraph workflow."""

from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import add_messages


class Evidence(TypedDict):
    """A single piece of evidence collected during investigation."""
    command: str  # Command that generated this evidence
    output: str  # Raw command output (may be truncated if stored externally)
    finding: str  # What was discovered
    significance: str  # Why it matters
    confidence: str  # "high", "medium", or "low"
    # External storage fields (for large outputs)
    evidence_type: str  # "inline" or "external"
    evidence_id: str | None  # ID in evidence store (if external)
    summary: str | None  # Summary of findings (from analyzer)


class HypothesisTest(TypedDict):
    """A hypothesis and its test results."""
    hypothesis: str  # The hypothesis being tested
    test_commands: list[str]  # Commands to test the hypothesis
    expected_confirmed: str  # What would confirm it
    expected_rejected: str  # What would reject it
    result: Literal["confirmed", "rejected", "inconclusive"] | None
    evidence: list[Evidence]  # Evidence from testing
    evaluation_reasoning: str  # Why we reached the result
    inconclusive_count: int  # How many times this test was inconclusive


class CommandResult(TypedDict):
    """Result from executing a debugger command."""
    command: str
    output: str
    success: bool
    error: str | None


class ChatMessage(TypedDict):
    """A message in the interactive chat session."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: str
    commands_executed: list[str]
    evidence_used: list[str]


class AnalysisState(TypedDict):
    """State for hypothesis-driven workflow: Hypothesis → Test → Investigate → Reason → Report."""
    
    # Input
    dump_path: str
    issue_description: str
    dump_type: str  # "user" or "kernel"
    supports_dx: bool  # Whether data model commands are available
    thread_info: dict[str, Any] | None  # Cached !threads output from startup
    
    # Session management (NEW - for evidence isolation)
    session_dir: str  # Path to session directory for this analysis
    
    # Hypothesis phase (NEW - expert-level thinking)
    current_hypothesis: str  # Current hypothesis being tested
    hypothesis_confidence: str  # "high", "medium", "low"
    hypothesis_reasoning: str  # Why we think this is the cause
    hypothesis_tests: list[HypothesisTest]  # All hypothesis tests conducted
    alternative_hypotheses: list[str]  # Backup hypotheses if main one rejected
    hypothesis_status: str  # "testing", "confirmed", "rejected"
    
    # Planning phase (after hypothesis confirmed)
    investigation_plan: list[str]  # List of tasks to investigate (3-5 tasks)
    planner_reasoning: str
    
    # Investigation phase (per task)
    current_task: str  # Currently investigating task
    current_task_index: int
    evidence_inventory: dict[str, list[Evidence]]  # Task → List of evidence found
    
    # Execution tracking
    commands_executed: list[str]  # All commands run (for reference)
    iteration: int
    max_iterations: int
    
    # Reasoning phase
    analysis_summary: str  # Direct answer to user's question (1-3 sentences)
    key_findings: list[str]  # 3-5 supporting facts/evidence
    reasoner_analysis: str  # Detailed numbered analysis
    conclusions: list[str]  # Key conclusions (deprecated, use key_findings)
    confidence_level: Literal["high", "medium", "low"] | None
    reasoning_iterations: int  # Number of times reasoning has been performed
    needs_deeper_investigation: bool  # Whether reasoner identified gaps requiring more investigation
    investigation_requests: list[dict[str, str]]  # Specific investigation requests from reasoner
    
    # Critique phase (NEW - quality review)
    critique_round: int  # Current critique iteration (0-based)
    critique_result: dict[str, Any]  # Critic's findings {issues_found, critical_issues, evidence_gaps, severity}
    has_unresolved_issues: bool  # Whether issues remain after max rounds
    needs_evidence_collection: bool  # Whether critic identified evidence gaps requiring investigation
    critique_triggered_investigation: bool  # Whether current investigation was triggered by critique feedback
    
    # Final output
    final_report: str | None
    
    # Utility flags
    sos_loaded: bool
    show_command_output: bool
    should_continue: bool
    
    # Interactive mode
    interactive_mode: bool
    chat_history: list[ChatMessage]
    chat_active: bool
    user_requested_report: bool


class PlannerOutput(TypedDict):
    """Output from the planner agent."""
    investigation_plan: list[str]
    reasoning: str


class InvestigatorOutput(TypedDict):
    """Output from investigator agent after completing a task."""
    evidence_found: list[Evidence]
    task_complete: bool
    reasoning: str


class ReasonerOutput(TypedDict):
    """Output from reasoner agent analyzing all evidence."""
    analysis: str
    conclusions: list[str]
    confidence_level: Literal["high", "medium", "low"]
    needs_deeper_investigation: bool  # Whether gaps require more investigation
    investigation_requests: list[dict[str, str]]  # Requests for deeper investigation
