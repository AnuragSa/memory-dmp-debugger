with open(r'.sessions\session_20260114_175302_maine2\evidence\ev_threads_20260114_175314_216465.txt', 'r') as f:
    lines = f.readlines()

with open('line9_analysis.txt', 'w', encoding='utf-8') as out:
    line9 = lines[8]
    out.write(f'Line 9 length: {len(line9)}\n')
    out.write(f'Line 9 stripped length: {len(line9.rstrip())}\n')
    out.write(f'Line 9 content:\n')
    out.write(repr(line9))
    out.write('\n\nByte by byte (last 30 chars):\n')
    for i, ch in enumerate(line9[-30:]):
        out.write(f'{i}: {repr(ch)} (ord={ord(ch)})\n')

print('Wrote line9_analysis.txt')
