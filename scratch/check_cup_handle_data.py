import asyncio
import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.main import get_cup_with_handle_screener

async def check():
    res = await get_cup_with_handle_screener(force_refresh=True)
    print("Status:", res.get("status"))
    print("Count:", res.get("count"))
    data = res.get("data", [])
    if data:
        print("\nSample Item 0 Keys:", list(data[0].keys()))
        print("Sample Item 0:")
        for k, v in data[0].items():
            print(f"  {k}: {v}")
    
    # Count statuses
    ready = sum(1 for s in data if 'READY' in (s.get('ch_status') or s.get('base_status') or ''))
    forming = sum(1 for s in data if 'FORMING' in (s.get('ch_status') or s.get('base_status') or ''))
    breakout = sum(1 for s in data if 'BREAKOUT' in (s.get('ch_status') or s.get('base_status') or ''))
    print(f"\nStatus Counts -> Ready: {ready}, Forming: {forming}, Breakout: {breakout}, Total: {len(data)}")

if __name__ == "__main__":
    asyncio.run(check())
