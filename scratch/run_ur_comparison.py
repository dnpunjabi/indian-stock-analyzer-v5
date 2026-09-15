import sys
import os
import pandas as pd
import numpy as np
import asyncio

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.main import get_db, fetch_history_df
from scratch.test_strict_ur_logic import detect_undercut_and_rally_strict
from backend.swing_utils import clean_float

async def run_test():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, company_name, sector FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%' LIMIT 150")
        stocks = [dict(r) for r in cursor.fetchall()]
        
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
                curr_price = clean_float(closes[-1])
                sma50 = clean_float(pd.Series(closes).rolling(50, min_periods=20).mean().iloc[-1])
                sma200 = clean_float(pd.Series(closes).rolling(200, min_periods=50).mean().iloc[-1])
                yr_ret = (curr_price - closes[0]) / closes[0] * 100.0 if closes[0] > 0 else 0.0
                
                rs_score = 85.0 if (curr_price > sma50 > sma200 and yr_ret > 15.0) else (65.0 if curr_price > sma200 else 40.0)
                
                res = detect_undercut_and_rally_strict(df, rs_score=rs_score)
                if res.get("is_undercut_and_rally"):
                    res["symbol"] = sym
                    return res
                return None
            except Exception:
                return None

    tasks = [scan_item(item) for item in stocks]
    results = [r for r in await asyncio.gather(*tasks) if r is not None]
    
    print(f"\n--- STRICT UNDERCUT & RALLY RESULTS ({len(results)} out of 150 stocks) ---")
    live = [r for r in results if r.get("ur_status") == "UR_LIVE_RECLAIM"]
    forming = [r for r in results if r.get("ur_status") == "UR_FORMING"]
    
    print(f"LIVE Reclaims ({len(live)}):")
    for r in live:
        print(f"  {r['symbol']}: PriorLow={r['prior_swing_low']}, ShakeoutLow={r['shakeout_low']}, VolRatio={r['reclaim_vol_ratio']}x, Risk={r['risk_pct']}%, RS={r['rs_score']}")
        
    print(f"\nFORMING Shakeouts ({len(forming)}):")
    for r in forming[:10]:
        print(f"  {r['symbol']}: PriorLow={r['prior_swing_low']}, ShakeoutLow={r['shakeout_low']}, Risk={r['risk_pct']}%, RS={r['rs_score']}")

if __name__ == "__main__":
    asyncio.run(run_test())
