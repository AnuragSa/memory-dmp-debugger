"""Tests for the debugger wrapper."""

import pytest
from pathlib import Path
from dump_debugger.core import DebuggerWrapper, DebuggerError


def test_debugger_wrapper_initialization():
    """Test that debugger wrapper can be initialized with a valid path."""
    # This test would need a real dump file
    # For now, it's a placeholder
    pass


def test_command_parsing():
    """Test that dx command output is parsed correctly."""
    wrapper = DebuggerWrapper.__new__(DebuggerWrapper)
    
    # Test dx output parsing
    dx_output = """
    @$curprocess
        Name             : myapp.exe
        Id               : 0x1234
        Threads          : ...
    """
    
    result = wrapper._parse_dx_output(dx_output)
    assert isinstance(result, dict)
    assert "type" in result or isinstance(result, str)


def test_clean_output():
    """Test output cleaning functionality."""
    wrapper = DebuggerWrapper.__new__(DebuggerWrapper)
    
    noisy_output = """
    Microsoft (R) Windows Debugger Version 10.0
    Loading Dump File [c:\\dumps\\crash.dmp]
    Symbol search path is: SRV*...
    
    Actual useful output here
    More useful information
    """
    
    cleaned = wrapper._clean_output(noisy_output)
    assert "Microsoft (R) Windows Debugger" not in cleaned
    assert "Loading Dump File" not in cleaned
    assert "useful output" in cleaned.lower()
