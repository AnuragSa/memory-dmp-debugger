"""Smoke tests for agent exports.

These tests only verify that the expected agent classes are available for import.
They intentionally avoid instantiation to keep the suite lightweight.
"""

from dump_debugger.agents import PlannerAgentV2, InvestigatorAgent


def test_planner_agent_exported():
    """PlannerAgentV2 should be exposed via the agents package."""
    assert PlannerAgentV2 is not None


def test_investigator_agent_exported():
    """InvestigatorAgent should be exposed via the agents package."""
    assert InvestigatorAgent is not None
