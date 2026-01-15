import re

# Test line from the file
test_line = '   3    1 14b0 000002eabfedcde0    28220 Preemptive  0000000000000000:0000000000000000 000002eabfe9f650 0     Ukn \n'

# Current pattern
pattern = re.compile(
    r'^\s*(\d+|XXXX)\s+(\d+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+(\w+)\s+'
    r'([0-9a-fA-F]+:[0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+(\d+)\s+(\w+)(?:\s+(.+))?$'
)

# Test with newline
match1 = pattern.match(test_line)
print(f"With \\n: {match1 is not None}")

# Test without newline
match2 = pattern.match(test_line.rstrip())
print(f"After rstrip(): {match2 is not None}")

# Test with just strip trailing spaces
match3 = pattern.match(test_line.rstrip('\n'))
print(f"After rstrip('\\n'): {match3 is not None}")

if match3:
    print(f"Groups: {match3.groups()}")
