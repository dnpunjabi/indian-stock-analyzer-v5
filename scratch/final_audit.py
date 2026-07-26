import sys
sys.stdout.reconfigure(encoding='utf-8')

# ===== FRONTEND AUDIT =====
with open('backend/static/app.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()

total = sum(1 for l in lines if 'renderLLMExecutionBadgeHtml' in l and 'function' not in l)
print(f'=== FRONTEND: Total badge rendering calls: {total} ===')

modules = [
    'SCREENER_EXPLAIN_FORMULA', 'PORTFOLIO_OPTIMIZATION', 'SECTOR_REGIME',
    'BACKTEST_REVIEW', 'TECHNICAL_INDICATORS', 'SWING_THESIS', 'SCREENER_SCAN',
    'RISK_SYNTHESIS', 'PORTFOLIO_DOCTOR', 'NEWS_SENTIMENT', 'DAILY_WRAPUP',
    'TECHNICAL_CHAT'
]
all_ok = True
for mod in modules:
    found = False
    for idx, line in enumerate(lines):
        if mod in line:
            for j in range(max(0, idx-15), idx+1):
                if 'renderLLMExecutionBadgeHtml' in lines[j]:
                    found = True
                    break
            break
    status = "OK" if found else "MISSING"
    if not found:
        all_ok = False
    print(f'  {status}: {mod}')

chat_fns = ['appendTvChatMessage', 'appendSolvencyChatMessage', 'appendAuditChatMessage', 'appendMarginChatMessage', 'appendChatMessage']
print('\n=== CHAT FUNCTION SIGNATURES ===')
for fn in chat_fns:
    for idx, line in enumerate(lines):
        if ('function ' + fn) in line:
            has_meta = 'llmMeta' in line
            status = "OK" if has_meta else "MISSING"
            print(f'  {status}: {fn} (L{idx+1})')
            break

print(f'\nAll modules covered: {all_ok}')

# ===== BACKEND AUDIT =====
print('\n=== BACKEND: llm_meta in responses ===')
with open('backend/main.py', 'r', encoding='utf-8') as f:
    main_lines = f.readlines()

# Find all endpoints that should return llm_meta
endpoints = [
    '/api/chat', '/api/chart/chat-analyst', '/api/chart/indicator-synthesis',
    '/api/ai/audit-financials', '/api/analyze-custom', '/api/analyze/pitchbook',
    '/api/analyze/risk-synthesis', '/api/alerts/daily-wrapup/trigger',
    '/api/alerts/telemetry-synthesis', '/api/alerts/parse-nl', '/api/fs-alerts/parse-nl',
    '/api/fuzzy/ask', '/api/fuzzy/commentary', '/api/learning/ask', '/api/learning/scenario',
    '/api/market-news', '/api/portfolio-doctor', '/api/portfolio/backtest-synthesis',
    '/api/portfolio/optimizer-synthesis', '/api/screener/explain-formula',
    '/api/screener/parse-nl-scan', '/api/screener/scan-synthesis',
    '/api/screener/sector-regime/ai-analysis', '/api/screener/sector-regime/ai-chat',
    '/api/swing/synthesis',
]

for ep in endpoints:
    found_ep = False
    has_meta = False
    for idx, line in enumerate(main_lines):
        if ep in line and ('app.' in line or '@app' in line or 'def ' in line):
            found_ep = True
            # Search forward 80 lines for llm_meta
            for j in range(idx, min(len(main_lines), idx + 80)):
                if 'llm_meta' in main_lines[j] or 'get_last_llm_meta' in main_lines[j]:
                    has_meta = True
                    break
            break
    if not found_ep:
        # Try simpler search
        for idx, line in enumerate(main_lines):
            if ep in line:
                found_ep = True
                for j in range(idx, min(len(main_lines), idx + 80)):
                    if 'llm_meta' in main_lines[j] or 'get_last_llm_meta' in main_lines[j]:
                        has_meta = True
                        break
                break
    status = "OK" if has_meta else ("NOT_FOUND" if not found_ep else "MISSING")
    print(f'  {status}: {ep}')
