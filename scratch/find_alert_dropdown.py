import re

for filepath in ['backend/static/index.html', 'backend/static/app.js']:
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    matches = re.findall(r'<select[^>]*id=["\']alert-condition["\'].*?</select>', content, re.DOTALL | re.IGNORECASE)
    print(f"File {filepath}: found {len(matches)} dropdowns")
    for m in matches:
        print(m)
