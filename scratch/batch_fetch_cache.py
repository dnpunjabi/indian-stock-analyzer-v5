import sys
import os
import json
import asyncio
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, os.path.abspath("."))

from backend.main import get_db, fetch_history_df
from backend.swing_utils import detect_weinstein_stage2

async def run_stage2_clean_scan():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT cache_json FROM screener_results_cache WHERE screener_name='weinstein_stage2'")
        row = cursor.fetchone()
        if not row:
            print("No cached data found for weinstein_stage2")
            return
        items = json.loads(row["cache_json"])
    
    print(f"Loaded {len(items)} candidate stocks to evaluate...")

    # Fetch Nifty index for benchmark RS
    try:
        b_df = await fetch_history_df("^NSEI", period="1y", interval="1d")
    except Exception:
        b_df = None

    clean_results = []
    sem = asyncio.Semaphore(2)  # Strict limit of 2 concurrent requests to avoid rate limits

    async def evaluate_stock(item, idx):
        sym = item["symbol"]
        async with sem:
            await asyncio.sleep(0.12)  # 120ms rate-limit padding
            try:
                df = await fetch_history_df(sym, period="1y", interval="1d")
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
                        print(f"[{idx+1}/{len(items)}] QUALIFIED Stage 2: {sym} (RS: {w_res['mansfield_rs']})")
                    else:
                        print(f"[{idx+1}/{len(items)}] DISQUALIFIED: {sym} -> {w_res.get('reason', 'Failed Stage 2 rules')}")
                else:
                    print(f"[{idx+1}/{len(items)}] No data for {sym}")
            except Exception as e:
                print(f"[{idx+1}/{len(items)}] Error analyzing {sym}: {e}")

    tasks = [evaluate_stock(item, i) for i, item in enumerate(items)]
    await asyncio.gather(*tasks, return_exceptions=True)

    clean_results.sort(key=lambda x: (x["stage_status"] == "STAGE_2_LAUNCH", x["breakout_vol_ratio"]), reverse=True)
    print(f"\n==========================================")
    print(f"Final Refined Stage 2 Count: {len(clean_results)}")
    print(f"==========================================")

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO screener_results_cache (screener_name, cache_json, updated_at) VALUES (?, ?, ?)",
                       ("weinstein_stage2", json.dumps(clean_results), updated_at))
        conn.commit()
    print("Stage 2 DB cache successfully updated with clean dataset!")

if __name__ == "__main__":
    asyncio.run(run_stage2_clean_scan())
