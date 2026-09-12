import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.main import _load_screener_db_cache

db_cache = _load_screener_db_cache("cup_with_handle")
data = db_cache.get("data", []) if db_cache else []

# Simulate app.js KPI summary logic
all_stocks = data
total_cnt = len(all_stocks)

def get_status(s):
    return str(s.get('ch_status') or s.get('base_status') or s.get('pattern_status') or s.get('status') or '').upper()

ready_cnt = sum(1 for s in all_stocks if 'READY' in get_status(s) or 'HANDLE' in get_status(s))
forming_cnt = sum(1 for s in all_stocks if 'FORMING' in get_status(s))
pivot_cnt = sum(1 for s in all_stocks if 'BREAKOUT' in get_status(s) or 'LIVE' in get_status(s))

print("=== KPI Summary Cards Check ===")
print(f"TOTAL CUP SETUPS: {total_cnt}")
print(f"HANDLE READY: {ready_cnt}")
print(f"CUP FORMING: {forming_cnt}")
print(f"NEAR PIVOT ALERT: {pivot_cnt}")

# Simulate filterCupHandleTable logic
def run_filter(q_text, status_opt):
    q = q_text.lower().strip()
    filtered = []
    for s in all_stocks:
        matches_q = not q or q in s['symbol'].lower() or q in (s.get('company_name') or '').lower()
        if not matches_q:
            continue
        p_status = get_status(s)
        if status_opt == 'ALL':
            filtered.append(s)
        elif status_opt == 'HANDLE_READY':
            if 'READY' in p_status or 'HANDLE' in p_status:
                filtered.append(s)
        elif status_opt == 'BREAKOUT_ALERT':
            if 'BREAKOUT' in p_status or 'LIVE' in p_status or 'PIVOT' in p_status:
                filtered.append(s)
        elif status_opt == 'CUP_FORMING':
            if 'FORMING' in p_status:
                filtered.append(s)
    return filtered

print("\n=== Dropdown Filter Checks ===")
print("Filter ALL:", len(run_filter("", "ALL")))
print("Filter HANDLE_READY:", len(run_filter("", "HANDLE_READY")))
print("Filter BREAKOUT_ALERT:", len(run_filter("", "BREAKOUT_ALERT")))
print("Filter CUP_FORMING:", len(run_filter("", "CUP_FORMING")))
print("Search 'CGPOWER':", len(run_filter("cgpower", "ALL")))

print("\n=== Table Row Fields Check (First 3 items) ===")
for s in data[:3]:
    cup_weeks = s.get('cup_length_weeks', s.get('cup_weeks', 0))
    handle_weeks = s.get('handle_length_weeks', s.get('handle_weeks', 0))
    print(f"Symbol: {s['symbol']}, Cup Depth: {s['cup_depth_pct']}%, Cup Weeks: {cup_weeks} Wks, Handle Depth: {s['handle_depth_pct']}%, Handle Weeks: {handle_weeks}W, Status: {s['ch_status']}")

