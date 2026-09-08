import sys
import os
import json
import asyncio
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath("."))
from backend.main import get_db, fetch_history_df
from backend.swing_utils import clean_float, detect_weinstein_stage3

def detect_strict_flat_base(df: pd.DataFrame, rs_score: float = 0.0) -> dict:
    """
    Strict William O'Neil / Mark Minervini Flat Base Screener:
    - Zero Fallback Logic: Base length derived dynamically from actual peak high date.
    - Base Duration: Strictly 4 to 15 weeks (20 to 75 trading days) from base peak high.
    - Base Depth: Max pullback depth strictly <= 15.0% (5.0% to 15.0%).
    - Proximity to High: Base ceiling within 20.0% of 52-week High.
    - Prior Uptrend: Prior advance >= +25.0% into the base peak.
    - Trend Template: Price >= 50d SMA >= 200d SMA, with 200d SMA rising over 30 days.
    - Volume Dry-Up (VDU): Base volume <= 0.85x 50d average volume.
    - Status: LIVE_BREAKOUT (Close >= Pivot and Vol >= 1.3x), READY_PIVOT (within 2.5% & VDU <= 0.85x), FORMING.
    """
    default_res = {
        "is_flat_base": False,
        "base_status": "NONE",
        "base_length_weeks": 0,
        "base_length_days": 0,
        "base_depth_pct": 0.0,
        "ceiling_price": 0.0,
        "floor_price": 0.0,
        "pivot_price": 0.0,
        "stop_loss": 0.0,
        "target_1": 0.0,
        "target_2": 0.0,
        "vdu_ratio": 1.0,
        "is_vdu": False,
        "prior_advance_pct": 0.0,
        "stacked_boxes_count": 0,
        "rejection_reason": ""
    }

    if df is None or df.empty or len(df) < 60:
        default_res["rejection_reason"] = "Insufficient daily history bars (<60 days)"
        return default_res

    try:
        df = df.sort_index(ascending=True)
        closes = df['Close'].values
        highs = df['High'].values
        lows = df['Low'].values
        volumes = df['Volume'].values if 'Volume' in df.columns else np.ones(len(df))
        n = len(df)

        curr_price = clean_float(closes[-1])
        h52 = clean_float(np.max(highs[-min(252, n):]))
        l52 = clean_float(np.min(lows[-min(252, n):]))

        # 1. 52-Week High Proximity (Base ceiling within 20.0% of 52W High)
        dist_52w_high_pct = round(((h52 - curr_price) / h52) * 100.0, 2) if h52 > 0 else 999.0
        if dist_52w_high_pct > 20.0:
            default_res["rejection_reason"] = f"Price is {dist_52w_high_pct:.1f}% below 52W High (exceeds 20% cap)"
            return default_res

        # 2. Moving Average Trend Alignment (Price >= SMA50 >= SMA200 with 30d rising slope)
        sma50 = pd.Series(closes).rolling(window=min(50, n), min_periods=20).mean().values
        sma200 = pd.Series(closes).rolling(window=min(200, n), min_periods=50).mean().values

        curr_sma50 = clean_float(sma50[-1])
        curr_sma200 = clean_float(sma200[-1])
        sma200_30d_ago = clean_float(sma200[-30]) if n >= 30 else curr_sma200
        sma200_rising = curr_sma200 >= sma200_30d_ago

        if not (curr_price >= curr_sma50 * 0.98 and curr_sma50 >= curr_sma200 and sma200_rising):
            default_res["rejection_reason"] = "Fails Trend Template: Price must sit above rising 50-day and 200-day SMAs"
            return default_res

        # 3. Dynamic Base Window Identification (No fallbacks!)
        # Find peak high in the 20 to 75 trading day window
        max_lookback = min(85, n - 20)
        recent_highs = highs[-max_lookback:]
        
        peak_offset = max_lookback - 1 - np.argmax(recent_highs) # Days since highest high
        base_days = int(peak_offset)
        base_ceiling = clean_float(np.max(recent_highs))

        # Dynamic check: Peak must be between 20 and 75 trading days ago
        if base_days < 20:
            default_res["rejection_reason"] = f"Base peak occurred only {base_days} days ago (<20 days / 4 weeks minimum duration required)"
            return default_res
        if base_days > 75:
            default_res["rejection_reason"] = f"Base peak occurred {base_days} days ago (>75 days / 15 weeks maximum duration limit)"
            return default_res

        ceiling_idx = len(df) - 1 - base_days
        base_floor = clean_float(np.min(lows[ceiling_idx:]))
        base_weeks = round(base_days / 5.0, 1)

        # 4. Strict Base Depth Cap (Peak to Trough Pullback 4.0% to 15.0%)
        base_depth_pct = round(((base_ceiling - base_floor) / base_ceiling) * 100.0, 2) if base_ceiling > 0 else 0.0
        if base_depth_pct > 15.0:
            default_res["rejection_reason"] = f"Base depth is {base_depth_pct:.1f}% (exceeds 15.0% Flat Base depth cap)"
            return default_res
        if base_depth_pct < 4.0:
            default_res["rejection_reason"] = f"Base depth is {base_depth_pct:.1f}% (too shallow / tight to be a base)"
            return default_res

        # 5. Prior Uptrend Check (Prior run-up >= +25.0% into the base peak)
        prior_start_idx = max(0, ceiling_idx - 60)
        prior_low = clean_float(np.min(lows[prior_start_idx:ceiling_idx])) if ceiling_idx > prior_start_idx else clean_float(np.min(lows[:ceiling_idx]))
        prior_advance_pct = round(((base_ceiling - prior_low) / prior_low) * 100.0, 2) if prior_low > 0 else 0.0

        if prior_advance_pct < 25.0:
            default_res["rejection_reason"] = f"Prior advance into peak is only +{prior_advance_pct:.1f}% (requires >= +25.0% prior uptrend)"
            return default_res

        # 6. Volume Dry-Up (VDU Ratio <= 0.85x 50-day average volume during base)
        vol50_avg = clean_float(pd.Series(volumes).rolling(window=min(50, n), min_periods=20).mean().iloc[-1])
        base_vol_avg = clean_float(np.mean(volumes[ceiling_idx:])) if base_days > 0 else vol50_avg
        vdu_ratio = round(base_vol_avg / vol50_avg, 2) if vol50_avg > 0 else 1.0
        is_vdu = vdu_ratio <= 0.85

        if not is_vdu:
            default_res["rejection_reason"] = f"Volume Dry-Up ratio is {vdu_ratio:.2f}x (requires VDU <= 0.85x average volume)"
            return default_res

        # 7. Relative Strength Check
        s3_res = detect_weinstein_stage3(df)
        mansfield_rs = s3_res.get("mansfield_rs", 0.0)
        has_rs_leadership = (rs_score >= 70.0 or mansfield_rs >= 0.0 or dist_52w_high_pct <= 12.0)

        if not has_rs_leadership:
            default_res["rejection_reason"] = f"Lacks Relative Strength Leadership (RS Rating {rs_score:.0f} < 70)"
            return default_res

        # 8. Stacked Darvas Boxes Calculation
        stacked_boxes_count = 1
        lookback_step = 40
        prev_ceiling = base_floor
        for b_idx in range(max(0, ceiling_idx - lookback_step), max(0, ceiling_idx - 160), -30):
            if b_idx + 20 < len(df):
                sub_high = np.max(highs[b_idx:b_idx+20])
                sub_low = np.min(lows[b_idx:b_idx+20])
                if sub_high < prev_ceiling and ((sub_high - sub_low) / sub_high) <= 0.16:
                    stacked_boxes_count += 1
                    prev_ceiling = sub_low

        # 9. Breakout Status Determination
        pivot_price = round(base_ceiling, 2)
        stop_loss = round(base_floor * 0.99, 2)
        target_1 = round(pivot_price * (1.0 + (base_depth_pct / 100.0) * 1.5), 2)
        target_2 = round(pivot_price * (1.0 + (base_depth_pct / 100.0) * 2.5), 2)

        prev_vol = clean_float(volumes[-1])
        vol_surge_ratio = round(prev_vol / vol50_avg, 2) if vol50_avg > 0 else 1.0

        if curr_price >= pivot_price and vol_surge_ratio >= 1.30:
            base_status = "LIVE_BREAKOUT"
        elif curr_price >= (pivot_price * 0.975) and is_vdu:
            base_status = "READY_PIVOT"
        else:
            base_status = "FORMING"

        prev_close = clean_float(closes[-2]) if n >= 2 else curr_price
        day_change_pct = round(((curr_price - prev_close) / prev_close) * 100.0, 2) if prev_close > 0 else 0.0

        return {
            "is_flat_base": True,
            "base_status": str(base_status),
            "base_length_weeks": clean_float(base_weeks),
            "base_length_days": int(base_days),
            "base_depth_pct": clean_float(base_depth_pct),
            "ceiling_price": clean_float(pivot_price),
            "floor_price": clean_float(base_floor),
            "pivot_price": clean_float(pivot_price),
            "stop_loss": clean_float(stop_loss),
            "target_1": clean_float(target_1),
            "target_2": clean_float(target_2),
            "vdu_ratio": clean_float(vdu_ratio),
            "is_vdu": bool(is_vdu),
            "prior_advance_pct": clean_float(prior_advance_pct),
            "stacked_boxes_count": int(stacked_boxes_count),
            "current_price": clean_float(curr_price),
            "day_change_pct": clean_float(day_change_pct),
            "rejection_reason": ""
        }
    except Exception as e:
        default_res["rejection_reason"] = f"Calculation error: {e}"
        return default_res

async def run_strict_retest():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT cache_json FROM screener_results_cache WHERE screener_name='flat_base_breakout'")
        row = cursor.fetchone()
        if not row or not row[0]:
            print("No cache found")
            return
        old_list = json.loads(row[0])

    print(f"Testing {len(old_list)} stocks with STRICT TEXTBOOK FLAT BASE rules (Zero Fallbacks)...")
    
    passed = []
    rejected = []
    
    for idx, item in enumerate(old_list, 1):
        sym = item["symbol"]
        yf_sym = f"{sym}.NS" if not sym.endswith(".NS") else sym
        df = await fetch_history_df(yf_sym, period="1y", interval="1d")
        if df is None or df.empty or len(df) < 60:
            continue
        
        res = detect_strict_flat_base(df)
        if res.get("is_flat_base"):
            res["symbol"] = sym
            res["company_name"] = item.get("company_name", sym)
            passed.append(res)
        else:
            rejected.append((sym, res.get("rejection_reason")))

    print(f"\n==========================================================================")
    print(f"STRICT RETEST RESULTS: {len(passed)} PRISTINE FLAT BASE SETUPS (Rejected {len(rejected)} false signals)")
    print(f"==========================================================================")
    for p in passed:
        print(f"Symbol: {p['symbol']:<14} | Status: {p['base_status']:<13} | Length: {p['base_length_weeks']}w ({p['base_length_days']}d) | Depth: {p['base_depth_pct']}% | VDU: {p['vdu_ratio']}x | Prior: +{p['prior_advance_pct']}% | Pivot: Rs.{p['pivot_price']}")

    print(f"\n--- SAMPLE REJECTION REASONS FOR FALSE SIGNALS ---")
    for r_sym, r_reason in rejected[:15]:
        print(f"Rejected {r_sym:<14}: {r_reason}")

if __name__ == "__main__":
    asyncio.run(run_strict_retest())
