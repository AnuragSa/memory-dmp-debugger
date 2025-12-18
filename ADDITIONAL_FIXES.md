# Additional Fixes - Interactive Agent Loop Issues

## Issues Addressed

Based on the user's follow-up question output showing:
- **"✗ Error: None"** still appearing for cached large outputs
- **Agent repeating identical investigation rationale** across all 3 rounds
- **Agent not recognizing already-executed commands** 
- **Agent stuck in loop** without incorporating gathered evidence

## Root Causes Identified

### 1. Cached Evidence Without Summary Returns Empty Output
**Location:** `debugger.py:execute_command_with_analysis()` lines 595-609

**Problem:** When a large command output is reused from cache (`find_recent_duplicate`), the code retrieves metadata and returns `metadata.get('summary', '')`. If the evidence was stored but never analyzed (no summary), this returns an empty string, making the interactive agent think the command failed.

**Fix:** Check if summary exists before returning cached evidence. If no summary, fall through to analysis logic to analyze it now.

```python
# Before
result['output'] = metadata.get('summary', '')  # Could be empty!
return result

# After  
if metadata.get('summary'):
    result['output'] = metadata.get('summary')
    result['cached'] = True
    return result
else:
    # Fall through to analyze now
    console.print("Evidence has no analysis yet, analyzing now...")
```

### 2. Evidence Not Properly Updated
**Location:** `debugger.py:execute_command_with_analysis()` lines 645-660

**Problem:** The code checked `if result.get('cached')` to update existing evidence, but didn't handle the `existing_evidence_id` case (evidence found via `find_recent_duplicate`).

**Fix:** Also check for `existing_evidence_id` when deciding whether to update vs create.

```python
# Before
if result.get('cached'):
    evidence_id = result.get('evidence_id')
    # Update...

# After
if result.get('cached') or existing_evidence_id:
    evidence_id = result.get('evidence_id') or existing_evidence_id
    # Update...
```

### 3. Evidence Checker Not Seeing Actual Data
**Location:** `interactive_agent.py:_check_existing_evidence()` lines 247-256

**Problem:** When building evidence summary for the LLM, only showing `finding` field which for newly gathered evidence is just "Data for: {question}". The actual command output/summary wasn't being included!

**Fix:** Show `summary` for external evidence and `output` for inline evidence. Skip generic findings.

```python
# Before
finding = evidence.get('finding', '')
if finding:
    evidence_summary += f"   Finding: {finding[:1000]}\n"

# After
if evidence.get('evidence_type') == 'external' and evidence.get('summary'):
    evidence_summary += f"   Summary: {evidence['summary'][:2000]}\n"
elif evidence.get('output'):
    output_preview = evidence['output'][:2000]
    evidence_summary += f"   Output: {output_preview}\n"

# Also show finding if it's not generic
finding = evidence.get('finding', '')
if finding and not finding.startswith('Data for:'):
    evidence_summary += f"   Finding: {finding[:1000]}\n"
```

**Additional Improvement:** Increased evidence limit from 5 to 10 pieces to provide more context.

## Expected Behavior Changes

### Before
```
Running: !dumpheap -stat
Reusing recent evidence ev_dumpheap_-stat_... (identical output)
  ✗ Error: None

[Round 2]
Investigation: We have NO data about GC statistics...
Running: !dumpheap -stat  (again!)
```

### After
```
Running: !dumpheap -stat
Reusing recent evidence ev_dumpheap_-stat_... (identical output)
Evidence has no analysis yet, analyzing now...
  ✓ (cached) Heap statistics: Gen2 contains 1.29GB across both heaps...

[Round 2]
Evidence available:
1. Command: !dumpheap -stat
   Summary: Heap statistics show Gen2 contains 1,291,857,256 bytes...
   
Investigation: We now have GC statistics showing Gen2 is 1.29GB. Need to investigate what's in Gen2...
```

## Test Coverage

Created `tests/test_interactive_agent_fixes.py` with:

1. **Evidence Summary Formatting Test**
   - Verifies external evidence shows summary
   - Verifies inline evidence shows output
   - Verifies generic findings ("Data for:") are skipped
   - Verifies non-generic findings are included

2. **Cached Evidence Handling Test**
   - Verifies evidence with summary returns immediately
   - Verifies evidence without summary triggers analysis

3. **Placeholder Detection Test**
   - Verifies normal commands don't trigger placeholder detection
   - Verifies actual placeholders are detected

All tests pass ✓

## Files Modified

1. **src/dump_debugger/core/debugger.py**
   - Fixed cached evidence return logic (check for summary before returning)
   - Fixed evidence update logic (handle `existing_evidence_id`)

2. **src/dump_debugger/interactive_agent.py**
   - Fixed evidence summary building (show actual output/summary, not just generic findings)
   - Increased evidence context limit (5 → 10 pieces)

3. **tests/test_interactive_agent_fixes.py** (new)
   - Comprehensive tests for all fixes

## Impact

These fixes ensure the iterative investigation loop works as intended:

1. **No More Empty Cache Returns:** Cached evidence always provides actual data
2. **Agent Recognizes Gathered Evidence:** LLM sees summaries/output, not just "Data for:"
3. **Investigation Progresses:** Each round builds on previous round's findings
4. **No More Duplicate Commands:** Agent sees it already has GC statistics in round 2

## Testing Recommendations

Test with a real follow-up question that requires multiple rounds:

1. Ask about GC/memory issue
2. Verify first round executes commands like `!eeheap -gc`, `!gcheapstat`
3. Verify second round recognizes this data exists (doesn't repeat same commands)
4. Verify agent reasoning references the actual data ("Gen2 contains 1.29GB")
5. Verify cached large outputs show summaries, not "Error: None"
