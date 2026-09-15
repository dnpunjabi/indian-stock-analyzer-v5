import re

with open("backend/main.py", "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

matches = [m.start() for m in re.finditer(r"watchlist", content, re.IGNORECASE)]
print(f"Found {len(matches)} matches for 'watchlist' in main.py!")

for idx in matches[:20]:
    line_no = content[:idx].count("\n") + 1
    snippet = content[max(0, idx-30):min(len(content), idx+80)].replace("\n", " ")
    print(f"  Line {line_no}: ...{snippet}...")
