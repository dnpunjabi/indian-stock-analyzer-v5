import re

with open('backend/static/index.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("--- TAB SECTIONS ---")
for i, line in enumerate(lines, 1):
    if 'id="tab-' in line or 'id="sec-' in line or 'class="tab-pane' in line or 'id="screener' in line.lower():
        print(f"Line {i}: {line.strip()[:120]}")
