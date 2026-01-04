"""
Agent modules for the memory dump debugger.

All agents follow LangGraph's stateless pattern:
- Take AnalysisState as input
- Return dict with state updates
- No mutable instance state (only config/dependencies in __init__)
"""
from dump_debugger.agents.critic import CriticAgent
from dump_debugger.agents.hypothesis import HypothesisDrivenAgent
from dump_debugger.agents.interactive_chat import InteractiveChatAgent
from dump_debugger.agents.investigator import InvestigatorAgent
from dump_debugger.agents.planner import PlannerAgentV2
from dump_debugger.agents.reasoner import ReasonerAgent
from dump_debugger.agents.report_writer import ReportWriterAgentV2

__all__ = [
    'CriticAgent',
    'HypothesisDrivenAgent',
    'InteractiveChatAgent',
    'InvestigatorAgent',
    'PlannerAgentV2',
    'ReasonerAgent',
    'ReportWriterAgentV2',
]
