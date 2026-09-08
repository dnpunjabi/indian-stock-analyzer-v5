import asyncio
import json
import sys
import pandas as pd

import os
sys.path.insert(0, os.path.abspath('.'))
from backend.main import get_db, fetch_history_df
from backend.swing_utils import detect_high_tight_flag

async def main():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, company_name, sector, cap_type FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%'")
        stocks = [dict(r) for r in cursor.fetchall()]

    print(f"Total stocks in screener_universe: {len(stocks)}")

    sem = asyncio.Semaphore(25)

    async def check_item(item):
        sym = item['symbol']
        try:
            df = await fetch_history_df(sym, period="6mo", interval="1d")
            if df is not None and not df.empty:
                res = detect_high_tight_flag(df)
                res['symbol'] = sym
                res['company_name'] = item['company_name']
                return res
        except Exception:
            pass
        return None

    tasks = [check_item(item) for item in stocks]
    results = await asyncio.gather(*tasks)
    results = [r for r in results if r is not None]

    results.sort(key=lambda x: x['pole_gain_pct'], reverse=True)

    print(f"\nSuccessfully evaluated {len(results)} stocks.")
    print("\n=== TOP 25 STOCKS BY POLE GAIN % ===")
    print(f"{'Symbol':<18} | {'Pole Gain %':<12} | {'Flag Depth %':<12} | {'Flag Days':<10} | {'VDU':<6} | {'Qualified':<10} | {'Status'}")
    print("-" * 95)
    for r in results[:25]:
        print(f"{r['symbol']:<18} | {r['pole_gain_pct']:<12} | {r['flag_depth_pct']:<12} | {r['flag_days']:<10} | {r['vdu_ratio']:<6} | {str(r['is_htf']):<10} | {r['htf_status']}")

    qualified = [r for r in results if r['is_htf']]
    print(f"\nTotal Qualified HTF setups in full universe: {len(qualified)}")

if __name__ == "__main__":
    asyncio.run(main())
