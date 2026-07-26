import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('backend/static/app.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()

targets = [13877, 21341, 28887, 44004]
for ml in targets:
    print(f'===== Line {ml} =====')
    start = max(0, ml - 5)
    end = min(len(lines), ml + 40)
    for j in range(start, end):
        print(f'  {j+1}: {lines[j].rstrip()[:150]}')
    print()
