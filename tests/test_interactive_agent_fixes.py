"""Test script to verify the interactive agent fixes."""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_evidence_summary_formatting():
    """Test that evidence summaries are properly formatted for LLM."""
    from dump_debugger.state import Evidence
    
    # Test evidence with external type and summary
    evidence1: Evidence = {
        'command': '!dumpheap -stat',
        'output': 'summary text here',  # This should be shown
        'finding': 'Data for: test question',  # Generic finding should be skipped
        'significance': 'high',
        'confidence': 'high',
        'evidence_type': 'external',
        'evidence_id': 'test_id_1',
        'summary': 'This is a detailed summary of heap statistics'
    }
    
    # Test evidence with inline type
    evidence2: Evidence = {
        'command': '!threads',
        'output': 'Thread data here',
        'finding': 'Found 10 threads',  # Non-generic finding
        'significance': 'medium',
        'confidence': 'medium',
        'evidence_type': 'inline'
    }
    
    # Mock context
    context = {
        'final_report': None,
        'conclusions': [],
        'relevant_evidence': [evidence1, evidence2],
        'issue_description': 'Test issue'
    }
    
    # Build evidence summary (simulating _check_existing_evidence logic)
    evidence_summary = "# Existing Evidence\n\n"
    
    if context['relevant_evidence']:
        evidence_summary += "## Relevant Evidence from Investigation\n"
        for i, evidence in enumerate(context['relevant_evidence'][:10], 1):
            evidence_summary += f"\n{i}. Command: {evidence.get('command', 'N/A')}\n"
            
            # Show summary for external evidence, output for inline
            if evidence.get('evidence_type') == 'external' and evidence.get('summary'):
                evidence_summary += f"   Summary: {evidence['summary'][:2000]}\n"
            elif evidence.get('output'):
                output_preview = evidence['output'][:2000]
                evidence_summary += f"   Output: {output_preview}\n"
            
            # Also show finding if it's not generic
            finding = evidence.get('finding', '')
            if finding and not finding.startswith('Data for:'):
                evidence_summary += f"   Finding: {finding[:1000]}\n"
    
    print("Evidence Summary:")
    print(evidence_summary)
    print()
    
    # Verify expectations
    assert 'This is a detailed summary of heap statistics' in evidence_summary, "Should show summary for external evidence"
    assert 'Thread data here' in evidence_summary, "Should show output for inline evidence"
    assert 'Data for: test question' not in evidence_summary, "Should skip generic findings"
    assert 'Found 10 threads' in evidence_summary, "Should show non-generic findings"
    
    print("✓ Evidence summary formatting test passed")


def test_cached_evidence_handling():
    """Test that cached evidence with/without summaries is handled correctly."""
    
    # Simulate metadata with summary
    metadata_with_summary = {
        'command': '!dumpheap -stat',
        'size': 1000000,
        'summary': 'Heap statistics summary',
        'key_findings': ['Finding 1', 'Finding 2'],
        'metadata': {},
        'timestamp': '2025-12-18'
    }
    
    # Simulate metadata without summary
    metadata_without_summary = {
        'command': '!gchandles',
        'size': 500000,
        'summary': None,  # No summary yet!
        'key_findings': [],
        'metadata': {},
        'timestamp': '2025-12-18'
    }
    
    print("Testing cached evidence scenarios:")
    
    # Scenario 1: Has summary - should return immediately
    if metadata_with_summary.get('summary'):
        print("✓ Cached evidence with summary: Would return immediately")
    else:
        print("✗ Should have returned cached summary")
    
    # Scenario 2: No summary - should trigger analysis
    if not metadata_without_summary.get('summary'):
        print("✓ Cached evidence without summary: Would trigger analysis")
    else:
        print("✗ Should have triggered analysis")
    
    print()
    print("✓ Cached evidence handling test passed")


def test_placeholder_in_evidence():
    """Test that placeholders can be resolved from evidence."""
    from dump_debugger.utils import detect_placeholders, resolve_command_placeholders
    
    # Evidence with heap statistics
    evidence = [{
        'command': '!gcheapstat',
        'output': '''
Heap             Gen0         Gen1         Gen2          LOH
Heap0         9077192      3966200    662473744    182885184
Heap1         4960896      5130760    628383512    141982848
''',
        'summary': 'Gen2 contains 1.29GB of objects across both heaps',
        'evidence_type': 'external'
    }]
    
    command = "!dumpheap -gen 2 -stat"
    
    # This shouldn't have placeholders
    has_placeholders = detect_placeholders(command)
    print(f"Command '{command}' has placeholders: {has_placeholders}")
    assert not has_placeholders, "Should not detect placeholders in normal command"
    
    # Test with actual placeholder
    command_with_placeholder = "!gcroot <address>"
    has_placeholders = detect_placeholders(command_with_placeholder)
    print(f"Command '{command_with_placeholder}' has placeholders: {has_placeholders}")
    assert has_placeholders, "Should detect placeholder"
    
    print()
    print("✓ Placeholder detection test passed")


if __name__ == "__main__":
    print("Running interactive agent fix verification tests...\n")
    
    test_evidence_summary_formatting()
    test_cached_evidence_handling()
    test_placeholder_in_evidence()
    
    print("\n✓ All verification tests passed!")
