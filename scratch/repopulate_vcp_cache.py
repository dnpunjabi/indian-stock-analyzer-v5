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
from backend.swing_utils import detect_vcp_pattern, calculate_canslim_score, clean_float

def fetch_fast_df(symbol: str) -> pd.DataFrame:
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
            }, index=pd.to_datetime(timestamps, unit='s')).dropna(subset=['Close'])
            return df
    except Exception:
        return None

def run_vcp_repopulation():
    print("Fetching screener universe...")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, company_name, sector, cap_type FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%'")
        stocks = [dict(r) for r in cursor.fetchall()]

    print(f"Total stocks in universe to scan for VCP: {len(stocks)}")
    
    clean_vcp_results = []
    
    # Clear old vcp_screener_cache table first
    with get_db() as conn:
        conn.execute("DELETE FROM vcp_screener_cache")
        conn.commit()

    for idx, st in enumerate(stocks):
        sym = st["symbol"].strip().upper()
        yf_sym = f"{sym}.NS" if not sym.endswith(".NS") else sym
        
        try:
            df = fetch_fast_df(yf_sym)
            if df is None or df.empty or len(df) < 40:
                continue

            vcp_res = detect_vcp_pattern(df)
            if not vcp_res.get("is_vcp"):
                continue

            with get_db() as conn:
                canslim_res = calculate_canslim_score(sym, conn, df=df)
            
            c_score = canslim_res["canslim_score"]
            v_status = vcp_res["vcp_status"]
            v_stage = vcp_res["vcp_stage"]
            r_pct = vcp_res["risk_percent"]

            curr_p = clean_float(df['Close'].iloc[-1])
            prev_p = clean_float(df['Close'].iloc[-2]) if len(df) > 1 else curr_p
            chg_pct = round(((curr_p - prev_p) / prev_p) * 100.0, 2) if prev_p > 0 else 0.0

            res_dict = {
                "symbol": sym,
                "company_name": st["company_name"],
                "sector": st["sector"],
                "current_price": curr_p,
                "change_percent": chg_pct,
                "is_vcp": True,
                "vcp_status": v_status,
                "vcp_stage": v_stage,
                "pivot_price": vcp_res["pivot_price"],
                "stop_loss": vcp_res["stop_loss"],
                "target_1": vcp_res["target_1"],
                "target_2": vcp_res["target_2"],
                "risk_percent": r_pct,
                "risk_reward_ratio": vcp_res["risk_reward_ratio"],
                "volume_dryup_ratio": vcp_res["volume_dryup_ratio"],
                "contractions": vcp_res["contractions"],
                "tightness_score": vcp_res["tightness_score"],
                "canslim_score": c_score,
                "grade": canslim_res["grade"],
                "canslim_factors": canslim_res["factors"]
            }

            vcp_json_str = json.dumps(res_dict)
            canslim_json_str = json.dumps({"canslim_score": c_score, "grade": canslim_res["grade"], "factors": canslim_res["factors"]})
            
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO vcp_screener_cache (symbol, vcp_json, canslim_json, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (sym, vcp_json_str, canslim_json_str)
                )
                conn.commit()

            clean_vcp_results.append(res_dict)
            print(f"[{idx+1}/{len(stocks)}] QUALIFIED VCP: {sym} (Status: {v_status}, Tightness: {vcp_res['tightness_score']}, CANSLIM: {c_score})")
        except Exception as e:
            print(f"[{idx+1}/{len(stocks)}] Error scanning {sym}: {e}")

    print(f"\n==========================================")
    print(f"Final Authentic VCP Setups Count: {len(clean_vcp_results)}")
    print(f"==========================================")

if __name__ == "__main__":
    run_vcp_repopulation()
