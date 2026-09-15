import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.main import _load_screener_db_cache

def analyze_ur_cache():
    print("--- Analyzing Cached Undercut & Rally (U&R) Screener Data ---")
    cache = _load_screener_db_cache("undercut_and_rally")
    if not cache or not cache.get("data"):
        print("No cache found for undercut_and_rally in DB.")
        return
    
    data = cache["data"]
    print(f"Total cached candidates: {len(data)}")
    
    live_cnt = sum(1 for x in data if x.get("ur_status") == "UR_LIVE_RECLAIM")
    forming_cnt = sum(1 for x in data if x.get("ur_status") == "UR_FORMING")
    other_cnt = len(data) - live_cnt - forming_cnt
    
    print(f"UR_LIVE_RECLAIM: {live_cnt}")
    print(f"UR_FORMING: {forming_cnt}")
    print(f"Other/NONE: {other_cnt}")
    
    print("\nSample Live U&R Candidates:")
    for x in [d for d in data if d.get("ur_status") == "UR_LIVE_RECLAIM"][:10]:
        print(f"  {x.get('symbol')}: PriorLow={x.get('prior_swing_low')}, ShakeoutLow={x.get('shakeout_low')}, VolRatio={x.get('reclaim_vol_ratio')}, Risk={x.get('risk_pct')}%, RS={x.get('rs_score')}")

    print("\nSample Forming U&R Candidates:")
    for x in [d for d in data if d.get("ur_status") == "UR_FORMING"][:10]:
        print(f"  {x.get('symbol')}: PriorLow={x.get('prior_swing_low')}, ShakeoutLow={x.get('shakeout_low')}, VolRatio={x.get('reclaim_vol_ratio')}, RS={x.get('rs_score')}")

if __name__ == "__main__":
    analyze_ur_cache()
