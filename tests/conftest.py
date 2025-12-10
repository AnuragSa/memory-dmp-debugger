"""Test configuration."""

import pytest


@pytest.fixture
def mock_dump_path(tmp_path):
    """Create a mock dump file path."""
    dump_file = tmp_path / "test.dmp"
    dump_file.write_bytes(b"MOCK_DUMP_DATA")
    return dump_file


@pytest.fixture
def sample_analysis_state():
    """Create a sample analysis state for testing."""
    return {
        "dump_path": "c:\\test\\crash.dmp",
        "issue_description": "Application crashed",
        "dump_type": "user",
        "investigation_plan": ["Task 1", "Task 2"],
        "current_task": "Task 1",
        "current_task_index": 0,
        "commands_executed": [],
        "findings": [],
        "planner_reasoning": "",
        "debugger_reasoning": "",
        "analyzer_reasoning": "",
        "iteration": 0,
        "max_iterations": 10,
        "should_continue": True,
        "needs_more_investigation": True,
        "final_report": None,
        "confidence_level": None,
        "messages": [],
    }
