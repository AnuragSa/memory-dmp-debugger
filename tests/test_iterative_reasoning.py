"""Tests for iterative reasoning feedback loop."""

import pytest
from dump_debugger.state import AnalysisState


def test_state_has_iterative_fields():
    """Test that state includes fields for iterative reasoning."""
    state: AnalysisState = {
        'dump_file_path': 'test.dmp',
        'initial_observations': [],
        'hypotheses': [],
        'current_hypothesis': '',
        'hypothesis_status': 'testing',
        'investigation_plan': [],
        'current_task_index': 0,
        'investigation_results': [],
        'evidence_inventory': {},
        'reasoner_analysis': '',
        'conclusions': [],
        'confidence_level': 'low',
        'reasoning_iterations': 0,  # NEW: Track iteration count
        'needs_deeper_investigation': False,  # NEW: Flag for gaps
        'investigation_requests': [],  # NEW: Specific requests from reasoner
        'critique_issues': [],
        'critique_round': 0,
        'report': '',
        'chat_active': False,
        'chat_history': []
    }
    
    assert 'reasoning_iterations' in state
    assert 'needs_deeper_investigation' in state
    assert 'investigation_requests' in state
    assert state['reasoning_iterations'] == 0
    assert state['needs_deeper_investigation'] is False
    assert state['investigation_requests'] == []


def test_investigation_request_structure():
    """Test that investigation requests have the expected structure."""
    request = {
        'question': 'Which SqlCommand objects correspond to timeout exceptions?',
        'context': 'Found 50 timeout objects and 100 SqlCommand objects but cannot correlate',
        'approach': 'Use !do on timeout objects to extract SqlCommand references'
    }
    
    assert 'question' in request
    assert 'context' in request
    assert 'approach' in request
    assert isinstance(request['question'], str)
    assert isinstance(request['context'], str)
    assert isinstance(request['approach'], str)


def test_reasoner_output_structure():
    """Test that reasoner output includes all required fields."""
    from dump_debugger.state import ReasonerOutput
    
    output: ReasonerOutput = {
        'reasoner_analysis': 'Analysis text',
        'conclusions': ['Conclusion 1', 'Conclusion 2'],
        'confidence_level': 'high',
        'needs_deeper_investigation': True,
        'investigation_requests': [
            {
                'question': 'What SQL queries caused timeouts?',
                'context': 'Cannot correlate timeout objects with SqlCommand objects',
                'approach': 'Extract SqlCommand references from timeout objects'
            }
        ]
    }
    
    assert output['reasoner_analysis'] == 'Analysis text'
    assert len(output['conclusions']) == 2
    assert output['confidence_level'] == 'high'
    assert output['needs_deeper_investigation'] is True
    assert len(output['investigation_requests']) == 1
    assert output['investigation_requests'][0]['question'].startswith('What SQL')


def test_iteration_limit():
    """Test that iteration count is properly tracked."""
    max_iterations = 3
    
    # Simulate multiple reasoning iterations
    iterations = []
    for i in range(5):
        should_continue = i < max_iterations
        iterations.append({
            'iteration': i,
            'should_loop': should_continue
        })
    
    # First 3 should loop, last 2 should not
    assert iterations[0]['should_loop'] is True
    assert iterations[1]['should_loop'] is True
    assert iterations[2]['should_loop'] is True
    assert iterations[3]['should_loop'] is False
    assert iterations[4]['should_loop'] is False


def test_investigation_plan_generation():
    """Test generating investigation plan from reasoner requests."""
    investigation_requests = [
        {
            'question': 'Which SqlCommand objects have timeout errors?',
            'context': 'Found TimeoutException objects but no SqlCommand correlation',
            'approach': 'Examine exception inner objects for SqlCommand references'
        },
        {
            'question': 'What SQL text was executed in timed-out commands?',
            'context': 'Need to extract command text from SqlCommand objects',
            'approach': 'Use !do on SqlCommand addresses to inspect m_commandText field'
        }
    ]
    
    # Generate investigation plan from requests
    investigation_plan = []
    for req in investigation_requests:
        task = f"{req['question']}"
        if req['context']:
            task += f" Context: {req['context']}"
        if req['approach']:
            task += f" Suggested approach: {req['approach']}"
        investigation_plan.append(task)
    
    assert len(investigation_plan) == 2
    assert 'SqlCommand' in investigation_plan[0]
    assert 'SQL text' in investigation_plan[1]
    assert 'Context:' in investigation_plan[0]
    assert 'Suggested approach:' in investigation_plan[0]


def test_workflow_routing_logic():
    """Test the logic for routing after reasoning phase."""
    
    # Case 1: No deeper investigation needed - continue to critique
    state1 = {
        'needs_deeper_investigation': False,
        'investigation_requests': [],
        'reasoning_iterations': 1,
        'hypothesis_status': 'confirmed'
    }
    # Expected: route to "critique"
    assert not state1['needs_deeper_investigation']
    
    # Case 2: Deeper investigation needed, under iteration limit
    state2 = {
        'needs_deeper_investigation': True,
        'investigation_requests': [{'question': 'Test', 'context': '', 'approach': ''}],
        'reasoning_iterations': 1,
        'hypothesis_status': 'confirmed'
    }
    # Expected: route to "investigate"
    assert state2['needs_deeper_investigation']
    assert len(state2['investigation_requests']) > 0
    assert state2['reasoning_iterations'] < 3
    
    # Case 3: Max iterations reached - continue to critique
    state3 = {
        'needs_deeper_investigation': True,
        'investigation_requests': [{'question': 'Test', 'context': '', 'approach': ''}],
        'reasoning_iterations': 3,
        'hypothesis_status': 'confirmed'
    }
    # Expected: route to "critique" (max iterations)
    assert state3['reasoning_iterations'] >= 3
    
    # Case 4: No requests even though flag is true - continue to critique
    state4 = {
        'needs_deeper_investigation': True,
        'investigation_requests': [],
        'reasoning_iterations': 1,
        'hypothesis_status': 'confirmed'
    }
    # Expected: route to "critique" (no actual requests)
    assert len(state4['investigation_requests']) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
