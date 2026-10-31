"""
Quant Screener Full Universe Sweeper CLI
Executes full recalculation sweep across all 12 quantitative screeners + Apex Confluence Leaderboard.
"""
import os
import sys
import asyncio
import time
from dotenv import load_dotenv

# Ensure root directory is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

load_dotenv(override=True)

from backend.main import _run_full_quant_cron_sweep

async def main():
    print("=" * 60)
    print("🚀 APEXQUANT: 12+ QUANT SCREENER FULL UNIVERSE SWEEP")
    print("Recalculating all models across 500+ NSE equities...")
    print("=" * 60)
    t0 = time.time()
    try:
        await _run_full_quant_cron_sweep()
        elapsed = round(time.time() - t0, 2)
        print("=" * 60)
        print(f"✅ Quant sweep successfully completed in {elapsed}s!")
        print("All screeners in screener_results_cache and confluence leaderboard updated.")
        print("=" * 60)
    except Exception as e:
        print(f"❌ Quant sweep failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
