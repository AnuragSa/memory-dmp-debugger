"""Debug line wrapping in thread output."""
import re

with open(r'.sessions\session_20260114_175302_maine2\evidence\ev_threads_20260114_175314_216465.txt', 'r') as f:
    lines = f.readlines()

print("Looking for wrapped lines...")
print("=" * 80)

for i, line in enumerate(lines):
    # Show lines that look like thread starts
    if re.match(r'^\s*(\d+|XXXX)\s+\d+\s+', line):
        # Check line length
        if len(line.rstrip()) > 110:
            print(f"Line {i+1} (len={len(line.rstrip())}): {repr(line[:80])}...")
        # Check if next line might be continuation
        if i + 1 < len(lines):
            next_line = lines[i+1]
            if next_line.strip() and not re.match(r'^\s*(\d+|XXXX)\s+\d+\s+', next_line):
                print(f"  Line {i+1}: {repr(line.rstrip())}")
                print(f"  Next {i+2}: {repr(next_line.rstrip())}")
                print()
