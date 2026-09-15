import sys
import os
import asyncio

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.main import get_db, get_undercut_and_rally_screener

def clear_ur_db_cache():
    print("Clearing DB screener_results_cache for 'undercut_and_rally'...")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM screener_results_cache WHERE screener_name = 'undercut_and_rally'")
        conn.commit()
    print("Cache cleared successfully.")

async def test_fresh_ur_scan():
    clear_ur_db_cache()
    print("--- Running Fresh Undercut & Rally Screener with Strict Rules ---")
    res = await get_undercut_and_rally_screener(force_refresh=True)
    data = res.get("data", [])
    print(f"Total Fresh U&R Candidates: {len(data)}")
    live = [x for x in data if x.get("ur_status") == "UR_LIVE_RECLAIM"]
    forming = [x for x in data if x.get("ur_status") == "UR_FORMING"]
    print(f"UR_LIVE_RECLAIM: {len(live)}")
    print(f"UR_FORMING: {len(forming)}")
    
    print("\nLive U&R Candidates:")
    for x in live:
        print(f"  {x.get('symbol')}: PriorLow={x.get('prior_swing_low')}, ShakeoutLow={x.get('shakeout_low')}, Vol Ratio={x.get('reclaim_vol_ratio')}x, Risk={x.get('risk_pct')}%, RS={x.get('rs_score')}")

if __name__ == "__main__":
    asyncio.run(test_fresh_ur_scan())
