with open(r'.sessions\session_20260114_175302_maine2\evidence\ev_threads_20260114_175314_216465.txt', 'rb') as f:
    content = f.read()

print(f'Total bytes: {len(content)}')
print(f'\\r\\n count: {content.count(b"\\r\\n")}')
print(f'\\n count: {content.count(b"\\n")}')  
print(f'\\r count: {content.count(b"\\r")}')
print(f'Standalone \\n: {content.count(b"\\n") - content.count(b"\\r\\n")}')

# Check line 9 in detail - split by \\r\\n first
lines_rn = content.split(b'\\r\\n')
if len(lines_rn) > 8:
    line9 = lines_rn[8]
    print(f'\nLine 9 (via \\r\\n split):')
    print(f'  Length: {len(line9)}')
    print(f'  Contains \\n: {b"\\n" in line9}')
    print(f'  Repr: {repr(line9[:120])}')
    if b'\\n' in line9:
        parts = line9.split(b'\\n')
        print(f'  Parts when split by \\n: {len(parts)}')
        for i, p in enumerate(parts):
            print(f'    Part {i}: {repr(p[:60])}')
