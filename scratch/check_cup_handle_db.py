import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.main import _load_screener_db_cache

db_cache = _load_screener_db_cache("cup_with_handle")
if db_cache and db_cache.get("data"):
    data = db_cache["data"]
    print("Cached Count:", len(data))
    if data:
        print("\nSample Item 0 Keys:", list(data[0].keys()))
        print("Sample Item 0:")
        for k, v in data[0].items():
            print(f"  {k}: {v}")

    # Count statuses
    ready = sum(1 for s in data if 'READY' in str(s.get('ch_status') or s.get('base_status') or s.get('pattern_status') or ''))
    forming = sum(1 for s in data if 'FORMING' in str(s.get('ch_status') or s.get('base_status') or s.get('pattern_status') or ''))
    breakout = sum(1 for s in data if 'BREAKOUT' in str(s.get('ch_status') or s.get('base_status') or s.get('pattern_status') or ''))
    print(f"\nStatus Counts -> Ready: {ready}, Forming: {forming}, Breakout: {breakout}, Total: {len(data)}")
else:
    print("No DB cache found for cup_with_handle")
