import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.main import _load_screener_db_cache

db_cache = _load_screener_db_cache("cup_with_handle")
data = db_cache.get("data", []) if db_cache else []

all_stocks = data
total_cnt = len(all_stocks)

def get_status(s):
    return str(s.get('ch_status') or s.get('base_status') or s.get('pattern_status') or s.get('status') or '').upper()

ready_cnt = sum(1 for s in all_stocks if ('READY' in get_status(s) or get_status(s) == 'HANDLE_READY') and 'FORMING' not in get_status(s))
forming_cnt = sum(1 for s in all_stocks if 'FORMING' in get_status(s))
pivot_cnt = sum(1 for s in all_stocks if 'BREAKOUT' in get_status(s) or 'LIVE' in get_status(s))

print("=== REFIXED KPI Summary Cards Check ===")
print(f"TOTAL CUP SETUPS: {total_cnt}")
print(f"HANDLE READY: {ready_cnt}")
print(f"CUP FORMING: {forming_cnt}")
print(f"NEAR PIVOT ALERT: {pivot_cnt}")
print(f"SUM CHECK: {ready_cnt} + {forming_cnt} + {pivot_cnt} = {ready_cnt + forming_cnt + pivot_cnt}")
