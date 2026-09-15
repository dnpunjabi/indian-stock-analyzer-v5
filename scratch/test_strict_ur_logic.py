import sys
import os
import pandas as pd
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.swing_utils import clean_float

def detect_undercut_and_rally_strict(df: pd.DataFrame, rs_score: float = 0.0) -> dict:
    default_res = {
        "is_undercut_and_rally": False,
        "is_ur": False,
        "ur_status": "NONE",
        "prior_swing_low": 0.0,
        "shakeout_low": 0.0,
        "stop_loss": 0.0,
        "risk_pct": 0.0,
        "reclaim_vol_ratio": 0.0,
        "slope_30wk_pct": 0.0,
        "rs_score": clean_float(rs_score),
        "reason": "No active Undercut & Rally setup"
    }
    try:
        if df is None or df.empty or len(df) < 60:
            default_res["reason"] = "Insufficient daily history (<60 bars)"
            return default_res

        close_s = df['Close']
        high_s = df['High']
        low_s = df['Low']
        vol_s = df['Volume']
        n = len(df)
        curr_price = float(close_s.iloc[-1])

        # 1. Relative Strength Check (Strict RS >= 65)
        if rs_score > 0 and rs_score < 65.0:
            default_res["reason"] = f"Relative Strength (RS) score {rs_score:.1f} below 65 threshold"
            return default_res

        # 2. Moving Averages & 30-Week Slope Check
        sma50 = float(close_s.tail(min(50, n)).mean())
        sma200 = float(close_s.tail(min(200, n)).mean())
        sma200_20d = float(close_s.iloc[:-20].tail(min(200, n)).mean()) if n >= 40 else sma200
        slope_30wk_pct = round(((sma200 - sma200_20d) / sma200_20d) * 100.0, 2) if sma200_20d > 0 else 0.0
        default_res["slope_30wk_pct"] = slope_30wk_pct

        if slope_30wk_pct < -0.2:
            default_res["reason"] = f"Fails 30-Week (200 SMA) slope requirement ({slope_30wk_pct:.2f}%)"
            return default_res

        # 3. Stage 2 Trend & 52-Week High Proximity (Price >= 200 SMA or >= 50 SMA, within 20% of 52W High)
        high_52w = float(high_s.tail(min(252, n)).max())
        dist_from_high = ((high_52w - curr_price) / high_52w) * 100.0 if high_52w > 0 else 0.0

        if not (curr_price >= sma200 * 0.98 or curr_price >= sma50 * 0.98) or dist_from_high > 20.0:
            default_res["reason"] = f"Stock not in Stage 2 health (Below MAs or {dist_from_high:.1f}% below 52W High)"
            return default_res

        # 4. Find key fractal swing lows in window (-45 to -5 bars)
        window_start = max(0, n - 45)
        window_end = max(1, n - 5)
        
        swing_low_candidates = []
        low_vals = low_s.values

        for idx in range(window_start + 2, window_end - 1):
            # Fractal trough: lower than 2 bars left and 1 bar right
            if low_vals[idx] <= low_vals[idx-1] and low_vals[idx] <= low_vals[idx-2] and low_vals[idx] <= low_vals[idx+1]:
                swing_low_candidates.append(float(low_vals[idx]))

        if not swing_low_candidates:
            recent_slice = low_s.iloc[window_start:window_end]
            if len(recent_slice) >= 5:
                swing_low_candidates.append(float(recent_slice.min()))
            else:
                return default_res

        is_ur_found = False
        target_prior_low = 0.0
        shakeout_low = 0.0
        reclaim_vol_ratio = 0.0
        undercut_pct = 0.0
        avg_vol_20 = float(vol_s.tail(20).mean())

        # Check recent 3 bars for undercut & reclaim
        for prior_low in sorted(swing_low_candidates, reverse=True):
            for offset in range(1, 4):
                idx = -offset
                check_low = float(low_s.iloc[idx])
                check_vol = float(vol_s.iloc[idx])
                check_close = float(close_s.iloc[idx])

                if check_low < prior_low:
                    u_pct = ((prior_low - check_low) / prior_low) * 100.0
                    # Strict Minervini undercut depth: 0.4% to 3.8% max
                    if 0.4 <= u_pct <= 3.8:
                        # Reclaim confirmation: price must close back at or above prior low
                        if curr_price >= prior_low * 0.998:
                            is_ur_found = True
                            target_prior_low = prior_low
                            shakeout_low = check_low
                            undercut_pct = u_pct
                            reclaim_vol_ratio = round(check_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 1.0
                            break
            if is_ur_found:
                break

        if not is_ur_found:
            default_res["prior_swing_low"] = round(swing_low_candidates[0], 2)
            return default_res

        stop_loss = round(shakeout_low * 0.995, 2)
        risk_pct = round(((curr_price - stop_loss) / curr_price) * 100.0, 1)

        # Max risk allowed for a tactical U&R entry: 5.0%
        if risk_pct > 5.0:
            default_res["reason"] = f"Shakeout too deep (Risk {risk_pct}% exceeds 5.0% cap)"
            return default_res

        is_qualified = False
        # Live Reclaim requires elevated volume >= 1.35x 20d avg volume
        if reclaim_vol_ratio >= 1.35:
            ur_status = "UR_LIVE_RECLAIM"
            is_qualified = True
            reason = f"Live U&R Reclaim! Undercut prior low Rs.{target_prior_low:.2f} by {undercut_pct:.1f}% & reclaimed on {reclaim_vol_ratio}x volume."
        # Forming setup requires volume dry up VDU <= 0.70x on the reclaim/tight bar
        elif reclaim_vol_ratio <= 0.70 and risk_pct <= 3.5:
            ur_status = "UR_FORMING"
            is_qualified = True
            reason = f"U&R Shakeout forming above prior low Rs.{target_prior_low:.2f} on tight low volume (Risk: {risk_pct}%)."
        else:
            ur_status = "NONE"
            reason = f"U&R move lacks volume signature (reclaim vol ratio {reclaim_vol_ratio}x is between 0.70x and 1.35x)"

        return {
            "is_undercut_and_rally": bool(is_qualified),
            "is_ur": bool(is_qualified),
            "ur_status": str(ur_status),
            "prior_swing_low": round(target_prior_low, 2),
            "shakeout_low": round(shakeout_low, 2),
            "stop_loss": stop_loss,
            "risk_pct": risk_pct,
            "reclaim_vol_ratio": reclaim_vol_ratio,
            "slope_30wk_pct": slope_30wk_pct,
            "rs_score": clean_float(rs_score),
            "reason": reason if is_qualified else default_res["reason"]
        }
    except Exception as e:
        print(f"Error in detect_undercut_and_rally_strict: {e}")
        default_res["reason"] = f"Error: {e}"
        return default_res
