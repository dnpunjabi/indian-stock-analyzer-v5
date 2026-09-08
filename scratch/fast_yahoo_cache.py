import sys
import os
import json
import asyncio
import urllib.request
import pandas as pd
import numpy as np
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, os.path.abspath("."))

from backend.main import get_db
from backend.swing_utils import detect_weinstein_stage2

def fetch_history_fast(symbol: str) -> pd.DataFrame:
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1y&interval=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            result = data['chart']['result'][0]
            timestamps = result['timestamp']
            quote = result['indicators']['quote'][0]
            
            df = pd.DataFrame({
                "Open": quote['open'],
                "High": quote['high'],
                "Low": quote['low'],
                "Close": quote['close'],
                "Volume": quote['volume']
            }, index=pd.to_datetime(timestamps, unit='s'))
            df = df.dropna(subset=['Close'])
            return df
    except Exception:
        return None

def run_fast_clean_scan():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT cache_json FROM screener_results_cache WHERE screener_name='weinstein_stage2'")
        row = cursor.fetchone()
        if not row:
            print("No cached data found for weinstein_stage2")
            return
        items = json.loads(row["cache_json"])
    
    print(f"Fast scanning {len(items)} stocks using direct Yahoo chart API...")

    # Fetch Nifty index for benchmark RS
    b_df = fetch_history_fast("^NSEI")

    clean_results = []
    for idx, item in enumerate(items):
        sym = item["symbol"]
        df = fetch_history_fast(sym)
        if df is not None and not df.empty and len(df) >= 30:
            w_res = detect_weinstein_stage2(df, benchmark_df=b_df)
            if w_res.get("is_stage2") or w_res.get("stage_status") in ["STAGE_2_LAUNCH", "STAGE_2_ADVANCING"]:
                clean_results.append({
                    "symbol": sym,
                    "base_symbol": sym.replace(".NS", "").replace(".BO", ""),
                    "company_name": item["company_name"],
                    "sector": item["sector"],
                    "cap_type": item["cap_type"],
                    "stage_status": w_res["stage_status"],
                    "ma30_slope_pct": w_res["ma30_slope_pct"],
                    "base_length_weeks": w_res["base_length_weeks"],
                    "breakout_vol_ratio": w_res["breakout_vol_ratio"],
                    "mansfield_rs": w_res["mansfield_rs"],
                    "pivot_price": w_res["pivot_price"],
                    "current_price": w_res["current_price"],
                    "day_change_pct": w_res.get("day_change_pct", 0.0)
                })

    clean_results.sort(key=lambda x: (x["stage_status"] == "STAGE_2_LAUNCH", x["breakout_vol_ratio"]), reverse=True)
    print(f"\n==========================================")
    print(f"Final Noise-Filtered Stage 2 Count: {len(clean_results)}")
    print(f"==========================================")

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO screener_results_cache (screener_name, cache_json, updated_at) VALUES (?, ?, ?)",
                       ("weinstein_stage2", json.dumps(clean_results), updated_at))
        conn.commit()
    print("Stage 2 DB cache updated successfully!")

if __name__ == "__main__":
    run_fast_clean_scan()
