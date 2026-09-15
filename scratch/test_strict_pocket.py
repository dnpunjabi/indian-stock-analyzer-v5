import sys
import os
import pandas as pd
import numpy as np
import asyncio

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.main import get_db, fetch_history_df, _get_nifty_index_df
from backend.swing_utils import detect_pocket_pivot, clean_float

async def test_strict_pocket_pivot():
    print("--- Testing Strict Institutional Pocket Pivot Parameters on Universe ---")
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, company_name, sector FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%' LIMIT 150")
        stocks = [dict(r) for r in cursor.fetchall()]
        
    print(f"Testing on {len(stocks)} stocks...")
    
    sem = asyncio.Semaphore(25)
    
    async def scan_item(item):
        async with sem:
            sym = item["symbol"].strip().upper()
            sym_yf = f"{sym}.NS" if not sym.endswith(".NS") else sym
            try:
                df = await fetch_history_df(sym_yf, period="1y", interval="1d")
                if df is None or df.empty or len(df) < 60:
                    return None
                
                closes = df['Close'].values
                n = len(df)
                curr_price = clean_float(closes[-1])
                sma50 = clean_float(pd.Series(closes).rolling(50, min_periods=20).mean().iloc[-1])
                sma200 = clean_float(pd.Series(closes).rolling(200, min_periods=50).mean().iloc[-1])
                
                # Approximate RS score based on price vs 200 SMA and 1-yr momentum
                yr_ret = (curr_price - closes[0]) / closes[0] * 100.0 if closes[0] > 0 else 0
                rs_score = 80.0 if (curr_price > sma50 > sma200 and yr_ret > 15) else (60.0 if curr_price > sma200 else 40.0)
                
                res = detect_pocket_pivot(df, rs_score=rs_score)
                if res.get("is_pocket_pivot"):
                    res["symbol"] = sym
                    return res
                return None
            except Exception as e:
                return None

    tasks = [scan_item(item) for item in stocks]
    results = [r for r in await asyncio.gather(*tasks) if r is not None]
    
    print(f"\nTotal Qualified Candidates: {len(results)} out of {len(stocks)}")
    live = [r for r in results if r.get("pocket_status") == "POCKET_PIVOT_LIVE"]
    forming = [r for r in results if r.get("pocket_status") == "POCKET_PIVOT_FORMING"]
    
    print(f"LIVE Pocket Pivots: {len(live)}")
    print(f"FORMING Pocket Pivots: {len(forming)}")
    
    print("\nLive Candidates:")
    for r in live:
        print(f"  {r['symbol']}: VolRatio={r['vol_ratio_vs_max_down']}, DayChg={r['day_change_pct']}%, RS={r['rs_score']}, MA={r['ma_support_line']}")

if __name__ == "__main__":
    asyncio.run(test_strict_pocket_pivot())
