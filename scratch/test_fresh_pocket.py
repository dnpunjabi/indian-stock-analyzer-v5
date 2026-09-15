import sys
import os
import asyncio

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.main import get_pocket_pivot_screener

async def test_fresh_scan():
    print("--- Running Fresh Pocket Pivot Screener with Strict Rules ---")
    res = await get_pocket_pivot_screener(force_refresh=True)
    data = res.get("data", [])
    print(f"Total Fresh Candidates: {len(data)}")
    live = [x for x in data if x.get("pocket_status") == "POCKET_PIVOT_LIVE"]
    forming = [x for x in data if x.get("pocket_status") == "POCKET_PIVOT_FORMING"]
    print(f"POCKET_PIVOT_LIVE: {len(live)}")
    print(f"POCKET_PIVOT_FORMING: {len(forming)}")
    
    print("\nLive Pocket Pivot Candidates:")
    for x in live:
        print(f"  {x.get('symbol')}: Vol Ratio={x.get('vol_ratio_vs_max_down')}, DayChg={x.get('day_change_pct')}%, RS={x.get('rs_score')}")

if __name__ == "__main__":
    asyncio.run(test_fresh_scan())
