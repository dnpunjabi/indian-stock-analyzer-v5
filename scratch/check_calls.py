import re

with open("backend/main.py", "r", encoding="utf-8") as f:
    content = f.read()

pocket_calls = [m.start() for m in re.finditer("detect_pocket_pivot", content)]
ur_calls = [m.start() for m in re.finditer("detect_undercut_and_rally", content)]

print(f"Found {len(pocket_calls)} references to detect_pocket_pivot")
for idx in pocket_calls:
    line_no = content[:idx].count("\n") + 1
    print(f"  Line {line_no}: {content[idx:idx+80].splitlines()[0]}")

print(f"\nFound {len(ur_calls)} references to detect_undercut_and_rally")
for idx in ur_calls:
    line_no = content[:idx].count("\n") + 1
    print(f"  Line {line_no}: {content[idx:idx+80].splitlines()[0]}")
