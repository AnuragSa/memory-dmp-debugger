import re

with open(r'.sessions\session_20260114_175302_maine2\evidence\ev_threads_20260114_175314_216465.txt', 'rb') as f:
    output = f.read().decode('utf-8')

lines = output.split('\r\n')

thread_pattern = re.compile(
    r'^\s*(\d+|XXXX)\s+(\d+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+(\w+)\s+'
    r'([0-9a-fA-F]+:[0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+(\d+)\s+(\w+)(?:\s+(.+))?$'
)

potential_threads = []
for i, line in enumerate(lines):
    # Lines that start with DBG ID pattern but don't match full pattern
    if re.match(r'^\s*(\d+|XXXX)\s+\d+\s+', line):
        match = thread_pattern.match(line)
        if not match:
            potential_threads.append((i+1, line))

print(f"Found {len(potential_threads)} lines that look like threads but don't match regex")
print("\nFirst 5:")
for line_num, line in potential_threads[:5]:
    print(f"\nLine {line_num} (len={len(line)}):")
    print(repr(line))
