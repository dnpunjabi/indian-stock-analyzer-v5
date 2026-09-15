import re

with open("backend/static/app.js", "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

matches = [m.start() for m in re.finditer(r"watchlist", content, re.IGNORECASE)]
print(f"Found {len(matches)} matches for 'watchlist' in app.js!")

for idx in matches[:15]:
    line_no = content[:idx].count("\n") + 1
    snippet = content[max(0, idx-40):min(len(content), idx+60)].replace("\n", " ")
    print(f"  Line {line_no}: ...{snippet}...")
