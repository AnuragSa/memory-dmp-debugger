# Example Output

This document shows what the tool output looks like during a real analysis.

## Sample Command

```powershell
uv run dump-debugger analyze crash.dmp --issue "Application crashed with access violation"
```

## Console Output

```
🔍 Memory Dump Debugger
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Validating: crash.dmp
✓ Dump validated (user-mode)

Starting Analysis...

📋 Planner Agent
Creating investigation plan...
✓ Plan created with 5 tasks
Complexity: moderate
  1. Identify exception and crash context
  2. Analyze call stack of faulting thread
  3. Examine exception record details
  4. Review loaded modules and versions
  5. Investigate potential root causes

🔧 Debugger Agent (Task: Identify exception and crash context)
Reasoning: We need to start by understanding what exception occurred and in which thread
Command: dx @$curprocess.Threads[0].LastException
Executing: dx @$curprocess.Threads[0].LastException
✓ Command executed successfully

🧪 Analyzer Agent
Analysis: Found access violation (0xC0000005) at address 0x00007FF6A1B2C450
New Findings:
  • Exception Code: 0xC0000005 (Access Violation)
  • Faulting Address: 0x00007FF6A1B2C450
  • Exception occurred in thread 0

🔧 Debugger Agent (Task: Analyze call stack of faulting thread)
Reasoning: Need to see the call stack to understand the code path leading to the crash
Command: dx @$curprocess.Threads[0].Stack.Frames
Executing: dx @$curprocess.Threads[0].Stack.Frames
✓ Command executed successfully

🧪 Analyzer Agent
Analysis: Call stack shows crash in StringCopy function with null pointer
New Findings:
  • Crash occurred in myapp!StringCopy+0x45
  • Called from myapp!ProcessRequest+0x120
  • Null pointer detected in string operation

→ Moving to next task: Examine exception record details

🔧 Debugger Agent (Task: Examine exception record details)
Reasoning: Get detailed exception information including parameters
Command: dx @$curprocess.Threads[0].LastException.ExceptionRecord
Executing: dx @$curprocess.Threads[0].LastException.ExceptionRecord
✓ Command executed successfully

🧪 Analyzer Agent
Analysis: Exception parameters confirm null pointer dereference on read operation
New Findings:
  • Read operation attempted at address 0x0000000000000000
  • Access violation type: Read (not write)
  • No exception handlers were available

→ Moving to next task: Review loaded modules and versions

🔧 Debugger Agent (Task: Review loaded modules and versions)
Reasoning: Check if outdated or mismatched module versions could be involved
Command: dx @$curprocess.Modules
Executing: dx @$curprocess.Modules
✓ Command executed successfully

🧪 Analyzer Agent
Analysis: All modules appear to be current versions, no obvious version mismatches
New Findings:
  • myapp.exe version: 2.5.1.0
  • All system DLLs are up to date
  • No third-party library conflicts detected

→ Moving to next task: Investigate potential root causes

🔧 Debugger Agent (Task: Investigate potential root causes)
Reasoning: Examine the actual parameters and variables at crash location
Command: dx @$curprocess.Threads[0].Stack.Frames[0].LocalVariables
Executing: dx @$curprocess.Threads[0].Stack.Frames[0].LocalVariables
✓ Command executed successfully

🧪 Analyzer Agent
Analysis: Source string parameter was NULL, causing the crash in StringCopy
New Findings:
  • Parameter 'sourceStr' was NULL (0x0000000000000000)
  • No null check before string operation
  • Caller passed invalid parameter

✓ Investigation complete

📝 Report Writer Agent
Generating final report...
✓ Report generated

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Analysis Complete!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

╭─────────────────── 📊 Statistics ────────────────────╮
│                                                       │
│ Commands Executed: 5                                  │
│ Findings: 10                                          │
│ Iterations: 5                                         │
│                                                       │
╰───────────────────────────────────────────────────────╯


╭────────────────── 📝 Analysis Report ─────────────────╮
│                                                        │
│ # Memory Dump Analysis Report                         │
│                                                        │
│ ## Executive Summary                                  │
│                                                        │
│ The application crashed due to an Access Violation    │
│ (0xC0000005) caused by a null pointer dereference in  │
│ the StringCopy function. The root cause is a missing  │
│ null check on the source string parameter before      │
│ attempting a string operation.                        │
│                                                        │
│ ## Issue Identification                               │
│                                                        │
│ **What Happened:**                                    │
│ - Exception Code: 0xC0000005 (Access Violation)       │
│ - Faulting Address: 0x00007FF6A1B2C450                │
│ - Thread: 0                                           │
│ - Operation: Read from address 0x0000000000000000     │
│                                                        │
│ ## Root Cause Analysis                                │
│                                                        │
│ **Why It Happened:**                                  │
│                                                        │
│ The crash occurred in `myapp!StringCopy+0x45` when    │
│ attempting to read from a NULL pointer. Analysis of   │
│ the local variables shows that the `sourceStr`        │
│ parameter was NULL (0x0000000000000000) when passed   │
│ to the StringCopy function.                           │
│                                                        │
│ Call stack trace:                                     │
│ ```                                                   │
│ myapp!StringCopy+0x45                                 │
│ myapp!ProcessRequest+0x120                            │
│ ```                                                   │
│                                                        │
│ ## Evidence                                           │
│                                                        │
│ 1. **Exception Record**: Confirms read access         │
│    violation at NULL address                          │
│ 2. **Stack Analysis**: Shows crash in StringCopy      │
│    function called from ProcessRequest                │
│ 3. **Local Variables**: Parameter 'sourceStr' was     │
│    NULL                                               │
│ 4. **No Handler**: No exception handlers were         │
│    available to catch this error                      │
│                                                        │
│ ## Recommended Actions                                │
│                                                        │
│ 1. **Immediate Fix**: Add null pointer check in       │
│    StringCopy function before string operations       │
│                                                        │
│ ```cpp                                                │
│ void StringCopy(const char* sourceStr) {              │
│     if (sourceStr == NULL) {                          │
│         // Handle error                               │
│         return;                                       │
│     }                                                 │
│     // Continue with string operation                 │
│ }                                                     │
│ ```                                                   │
│                                                        │
│ 2. **Investigate Caller**: Review ProcessRequest      │
│    function to understand why NULL was passed         │
│                                                        │
│ 3. **Add Defensive Programming**: Consider adding     │
│    input validation throughout the call chain         │
│                                                        │
│ 4. **Code Review**: Review similar string handling    │
│    code for the same vulnerability                    │
│                                                        │
│ 5. **Testing**: Add unit tests for NULL parameter     │
│    scenarios                                          │
│                                                        │
│ ## Additional Notes                                   │
│                                                        │
│ - All module versions are current and up-to-date      │
│ - No third-party library conflicts detected           │
│ - Application version: 2.5.1.0                        │
│ - This is a defensive programming issue, not a        │
│   library or system problem                           │
│                                                        │
╰────────────────────────────────────────────────────────╯

Key Findings:
  1. Exception Code: 0xC0000005 (Access Violation)
  2. Faulting Address: 0x00007FF6A1B2C450
  3. Exception occurred in thread 0
  4. Crash occurred in myapp!StringCopy+0x45
  5. Called from myapp!ProcessRequest+0x120
  6. Null pointer detected in string operation
  7. Read operation attempted at address 0x0000000000000000
  8. Access violation type: Read (not write)
  9. No exception handlers were available
  10. Parameter 'sourceStr' was NULL (0x0000000000000000)
```

## Key Features Demonstrated

1. **Chain of Thought**: Every agent shows its reasoning
2. **Dynamic Commands**: Each command is generated based on context
3. **Progressive Discovery**: Findings build on each other
4. **Clear Progress**: Visual indicators for each step
5. **Rich Output**: Colored, formatted, easy to read
6. **Actionable Report**: Specific recommendations with code examples

## Saving to File

```powershell
uv run dump-debugger analyze crash.dmp --issue "Application crashed" --output report.md
```

Output:
```
✓ Report saved to: report.md
```

The saved file contains just the markdown report without the console styling, perfect for sharing with the team or adding to documentation.
