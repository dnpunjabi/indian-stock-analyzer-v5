import re

with open("backend/static/app.js", "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

# Search for function declarations related to watchlist
fn_matches = [m.start() for m in re.finditer(r"function\s+[a-zA-Z0-9_]*watchlist[a-zA-Z0-9_]*", content, re.IGNORECASE)]
print(f"Found {len(fn_matches)} function declarations matching 'watchlist':")

for idx in fn_matches:
    line_no = content[:idx].count("\n") + 1
    snippet = content[idx:idx+90].split("{")[0].strip()
    print(f"  Line {line_no}: {snippet}")

print("\n--- Searching for localStorage / Save Watchlist logic ---")
ls_matches = [m.start() for m in re.finditer(r"watchlistsList\s*=", content)]
for idx in ls_matches[:10]:
    line_no = content[:idx].count("\n") + 1
    snippet = content[max(0, idx-30):min(len(content), idx+100)].replace("\n", " ")
    print(f"  Line {line_no}: ...{snippet}...")
