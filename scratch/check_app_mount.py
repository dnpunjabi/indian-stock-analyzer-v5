import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('backend/static/app.js', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f, 1):
        if 'ichart-workspace-mount' in line or 'tv-chart-card' in line or 'openStandaloneInteractiveChart' in line:
            print(f"{i}: {line.strip()[:140]}")
