import sys
import os
import sqlite3
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.main import get_db, _load_screener_db_cache

def analyze_pocket_pivot_results():
    print("--- Analyzing Cached Pocket Pivot Screener Data ---")
    cache = _load_screener_db_cache("pocket_pivot")
    if not cache or not cache.get("data"):
        print("No cache found for pocket_pivot in DB.")
        return
    
    data = cache["data"]
    print(f"Total cached candidates: {len(data)}")
    
    live_cnt = sum(1 for x in data if x.get("pocket_status") == "POCKET_PIVOT_LIVE")
    forming_cnt = sum(1 for x in data if x.get("pocket_status") == "POCKET_PIVOT_FORMING")
    other_cnt = len(data) - live_cnt - forming_cnt
    
    print(f"POCKET_PIVOT_LIVE: {live_cnt}")
    print(f"POCKET_PIVOT_FORMING: {forming_cnt}")
    print(f"Other/NONE: {other_cnt}")
    
    print("\nSample Live Pocket Pivots:")
    for x in [d for d in data if d.get("pocket_status") == "POCKET_PIVOT_LIVE"][:10]:
        print(f"  {x.get('symbol')}: Vol Ratio vs Max Down={x.get('vol_ratio_vs_max_down')}, DayChg={x.get('day_change_pct')}%, MA Line={x.get('ma_support_line')}, RS={x.get('rs_score')}")

    print("\nSample Forming Pocket Pivots:")
    for x in [d for d in data if d.get("pocket_status") == "POCKET_PIVOT_FORMING"][:10]:
        print(f"  {x.get('symbol')}: Vol Ratio={x.get('vol_ratio_vs_max_down')}, DayChg={x.get('day_change_pct')}%, MA Line={x.get('ma_support_line')}")

if __name__ == "__main__":
    analyze_pocket_pivot_results()
