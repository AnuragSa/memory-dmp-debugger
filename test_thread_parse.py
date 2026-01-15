"""Test thread parsing regex against actual output with proper line ending handling."""
import re

# Read in binary mode first to detect actual line endings
with open(r'.sessions\session_20260114_175302_maine2\evidence\ev_threads_20260114_175314_216465.txt', 'rb') as f:
    raw = f.read()

# Detect line ending
if b'\r\n' in raw:
    line_ending = '\\r\\n'
    output = raw.decode('utf-8')
    lines = output.split('\r\n')
elif b'\n' in raw:
    line_ending = '\\n'
    output = raw.decode('utf-8')
    lines = output.split('\n')
elif b'\r' in raw:
    line_ending = '\\r (old Mac)'
    output = raw.decode('utf-8')
    lines = output.split('\r')
else:
    line_ending = 'NONE - single line'
    output = raw.decode('utf-8')
    lines = [output]

print(f"Detected line ending: {line_ending}")
print(f"Total lines: {len(lines)}")
print(f"First 3 lines:")
for i, line in enumerate(lines[:3]):
    print(f"  {i}: {repr(line[:80])}")

# Thread pattern
thread_pattern = re.compile(
    r'^\s*(\d+|XXXX)\s+(\d+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+(\w+)\s+'
    r'([0-9a-fA-F]+:[0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+(\d+)\s+(\w+)(?:\s+(.+))?$'
)

matched = 0
for line in lines:
    match = thread_pattern.match(line)
    if match:
        matched += 1

print(f"Matched threads: {matched}")
print(f"\nFile shows ThreadCount: 105")
print(f"Expected: 105 threads total")
print(f"Result: {'✓ PASS' if matched == 105 else '✗ FAIL - Missing ' + str(105 - matched) + ' threads'}")
