import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('backend/static/index.html', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f, 1):
        if 'tv-chart' in line or 'ichart' in line or 'I-CHART' in line:
            if 'id=' in line or 'class=' in line or 'data-tab=' in line or 'data-subtab=' in line:
                print(f"{i}: {line.strip()[:140]}")
