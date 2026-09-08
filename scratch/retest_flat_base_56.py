import sys
import os
import json
import asyncio
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath("."))
from backend.main import get_db, fetch_history_df
from backend.swing_utils import detect_flat_base_breakout

async def retest_cached_flat_base_stocks():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT cache_json, updated_at FROM screener_results_cache WHERE screener_name='flat_base_breakout'")
        row = cursor.fetchone()
        if not row or not row[0]:
            print("No cached data found for flat_base_breakout in database.")
            return
        
        cached_stocks = json.loads(row[0])
        updated_at = row[1]

    print(f"==========================================================================")
    print(f"RETESTING ALL {len(cached_stocks)} QUALIFIED FLAT BASE STOCKS (Cached at {updated_at})")
    print(f"==========================================================================")

    retested_results = []
    
    for idx, item in enumerate(cached_stocks, 1):
        sym = item.get("symbol")
        company = item.get("company_name", sym)
        yf_sym = f"{sym}.NS" if not sym.endswith(".NS") else sym
        
        try:
            df = await fetch_history_df(yf_sym, period="1y", interval="1d")
            if df is None or df.empty or len(df) < 60:
                print(f"[{idx:02d}] {sym:<12} | FAIL: Insufficient price history")
                continue
            
            res = detect_flat_base_breakout(df)
            is_valid = res.get("is_flat_base", False)
            status = res.get("base_status", "NONE")
            weeks = res.get("base_length_weeks", 0)
            days = res.get("base_length_days", 0)
            depth = res.get("base_depth_pct", 0)
            vdu = res.get("vdu_ratio", 0)
            pivot = res.get("pivot_price", 0)
            price = res.get("current_price", 0)
            prior = res.get("prior_advance_pct", 0)
            reason = res.get("rejection_reason", "")
            
            # Diagnostic inspection: Find real ceiling index in df
            closes = df['Close'].values
            highs = df['High'].values
            lows = df['Low'].values
            n = len(df)
            
            # Real highest high in past 75 trading days
            window = min(75, n)
            sub_highs = highs[-window:]
            real_ceiling = float(np.max(sub_highs))
            real_ceiling_offset = window - 1 - np.argmax(sub_highs) # Days since highest high
            
            print(f"[{idx:02d}] {sym:<14} | Valid: {'YES' if is_valid else 'NO '} | Status: {status:<13} | Length: {weeks}w ({days}d) [Real peak: {real_ceiling_offset}d ago] | Depth: {depth}% | VDU: {vdu}x | Prior: +{prior}% | Reason: {reason}")
            
            if is_valid:
                res["symbol"] = sym
                res["company_name"] = company
                res["real_peak_days_ago"] = real_ceiling_offset
                retested_results.append(res)
                
        except Exception as e:
            print(f"[{idx:02d}] {sym:<12} | ERROR: {e}")

    print(f"\n==========================================================================")
    print(f"SUMMARY: {len(retested_results)} of {len(cached_stocks)} STOCKS PASSED RETEST")
    print(f"==========================================================================")

if __name__ == "__main__":
    asyncio.run(retest_cached_flat_base_stocks())
