with open(r"c:\Users\dheer\Desktop\AI\indian-stock-analyzer - 5.0\backend\static\styles.css", "r", encoding="utf-8") as f:
    lines = f.readlines()

for idx, line in enumerate(lines):
    if "position: sticky" in line or "position:sticky" in line:
        print(f"--- Sticky at Line {idx+1} ---")
        start = max(0, idx - 5)
        end = min(len(lines), idx + 8)
        for i in range(start, end):
            print(f"  {i+1}: {lines[i].rstrip()}")
