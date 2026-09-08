import sys
import os
import json
import asyncio
import pandas as pd
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, os.path.abspath("."))

from backend.main import get_db, fetch_history_df
from backend.swing_utils import detect_weinstein_stage2, detect_3weeks_tight, detect_high_tight_flag

async def run_cache_population():
    print("Fetching screener universe...")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, company_name, sector, cap_type FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%'")
        stocks = [dict(r) for r in cursor.fetchall()]
    
    print(f"Total stocks in universe: {len(stocks)}")
    
    w_results = []
    t_results = []
    h_results = []
    
    # Fetch Nifty index for benchmark RS calculation
    try:
        b_df = await fetch_history_df("^NSEI", period="1y", interval="1d")
    except Exception:
        b_df = None

    print("Running screener analysis across universe...")
    sem = asyncio.Semaphore(15)

    async def analyze_stock(item):
        sym = item["symbol"]
        async with sem:
            try:
                df = await fetch_history_df(sym, period="1y", interval="1d")
                if df is not None and not df.empty and len(df) >= 30:
                    # Stage 2
                    w_res = detect_weinstein_stage2(df, benchmark_df=b_df)
                    if w_res.get("is_stage2") or w_res.get("stage_status") in ["STAGE_2_LAUNCH", "STAGE_2_ADVANCING"]:
                        w_results.append({
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

                    # 3WT
                    t_res = detect_3weeks_tight(df)
                    if t_res.get("is_3wt") or t_res.get("tight_status") in ["3WT_PIVOT_READY", "3WT_FORMING", "3WT_QUALIFIED"]:
                        t_results.append({
                            "symbol": sym,
                            "base_symbol": sym.replace(".NS", "").replace(".BO", ""),
                            "company_name": item["company_name"],
                            "sector": item["sector"],
                            "cap_type": item["cap_type"],
                            "tight_status": t_res["tight_status"],
                            "close_variance_pct": t_res["close_variance_pct"],
                            "weekly_closes": t_res["weekly_closes"],
                            "distance_to_50ema_pct": t_res["distance_to_50ema_pct"],
                            "pivot_price": t_res["pivot_price"],
                            "stop_loss_price": t_res["stop_loss_price"],
                            "current_price": t_res["current_price"],
                            "day_change_pct": t_res.get("day_change_pct", 0.0)
                        })

                    # HTF
                    h_res = detect_high_tight_flag(df)
                    if h_res.get("is_htf") or h_res.get("htf_status") in ["HTF_BREAKOUT_READY", "HTF_FLAG_FORMING", "HTF_QUALIFIED"]:
                        h_results.append({
                            "symbol": sym,
                            "base_symbol": sym.replace(".NS", "").replace(".BO", ""),
                            "company_name": item["company_name"],
                            "sector": item["sector"],
                            "cap_type": item["cap_type"],
                            "htf_status": h_res["htf_status"],
                            "pole_gain_pct": h_res["pole_gain_pct"],
                            "flag_depth_pct": h_res["flag_depth_pct"],
                            "flag_days": h_res["flag_days"],
                            "vdu_ratio": h_res["vdu_ratio"],
                            "pivot_price": h_res["pivot_price"],
                            "current_price": h_res["current_price"],
                            "day_change_pct": h_res.get("day_change_pct", 0.0)
                        })
            except Exception as e:
                pass

    tasks = [analyze_stock(item) for item in stocks]
    await asyncio.gather(*tasks, return_exceptions=True)

    w_results.sort(key=lambda x: (x["stage_status"] == "STAGE_2_LAUNCH", x["breakout_vol_ratio"]), reverse=True)
    t_results.sort(key=lambda x: x["close_variance_pct"])
    h_results.sort(key=lambda x: x["pole_gain_pct"], reverse=True)

    print(f"Final Count Stage 2: {len(w_results)}")
    print(f"Final Count 3WT: {len(t_results)}")
    print(f"Final Count HTF: {len(h_results)}")

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO screener_results_cache (screener_name, cache_json, updated_at) VALUES (?, ?, ?)",
                       ("weinstein_stage2", json.dumps(w_results), updated_at))
        cursor.execute("INSERT OR REPLACE INTO screener_results_cache (screener_name, cache_json, updated_at) VALUES (?, ?, ?)",
                       ("3weeks_tight", json.dumps(t_results), updated_at))
        cursor.execute("INSERT OR REPLACE INTO screener_results_cache (screener_name, cache_json, updated_at) VALUES (?, ?, ?)",
                       ("htf", json.dumps(h_results), updated_at))
        conn.commit()
    print("Database cache updated successfully!")

if __name__ == "__main__":
    asyncio.run(run_cache_population())
