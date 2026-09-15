import sys
import os
import pandas as pd
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.swing_utils import clean_float

def detect_pocket_pivot_strict(df: pd.DataFrame, rs_score: float = 0.0) -> dict:
    default_res = {
        "is_pocket_pivot": False,
        "pocket_status": "NONE",
        "vol_ratio_vs_max_down": 0.0,
        "ma_support_line": "50 SMA",
        "pivot_price": 0.0,
        "stop_loss": 0.0,
        "target_1": 0.0,
        "target_2": 0.0,
        "current_price": 0.0,
        "day_change_pct": 0.0,
        "slope_30wk_pct": 0.0,
        "rs_score": clean_float(rs_score),
        "rejection_reason": ""
    }

    if df is None or df.empty or len(df) < 60:
        default_res["rejection_reason"] = "Insufficient daily history (<60 bars)"
        return default_res

    try:
        df = df.sort_index(ascending=True)
        closes = df['Close'].values
        highs = df['High'].values
        lows = df['Low'].values
        volumes = df['Volume'].values if 'Volume' in df.columns else np.ones(len(df))
        n = len(df)

        curr_price = clean_float(closes[-1])
        prev_close = clean_float(closes[-2]) if n >= 2 else curr_price
        day_change_pct = round(((curr_price - prev_close) / prev_close) * 100.0, 2) if prev_close > 0 else 0.0

        # 1. Relative Strength Check (Strict: RS >= 65)
        if rs_score > 0 and rs_score < 65.0:
            default_res["rejection_reason"] = f"Relative Strength (RS) score {rs_score:.1f} below 65 threshold"
            return default_res

        # Moving Averages
        ema10 = pd.Series(closes).ewm(span=min(10, n), adjust=False).mean().values
        ema21 = pd.Series(closes).ewm(span=min(21, n), adjust=False).mean().values
        sma50 = pd.Series(closes).rolling(window=min(50, n), min_periods=20).mean().values
        sma150 = pd.Series(closes).rolling(window=min(150, n), min_periods=40).mean().values
        sma200 = pd.Series(closes).rolling(window=min(200, n), min_periods=50).mean().values

        c_ema10 = clean_float(ema10[-1])
        c_ema21 = clean_float(ema21[-1])
        c_sma50 = clean_float(sma50[-1])
        c_sma150 = clean_float(sma150[-1])
        c_sma200 = clean_float(sma200[-1])

        # 2. 30-Week (200 SMA) & 50 SMA Slope Check
        sma200_20d = clean_float(sma200[-20]) if n >= 20 else c_sma200
        slope_30wk_pct = round(((c_sma200 - sma200_20d) / sma200_20d) * 100.0, 2) if sma200_20d > 0 else 0.0
        default_res["slope_30wk_pct"] = slope_30wk_pct

        if slope_30wk_pct < -0.2:
            default_res["rejection_reason"] = f"30-Week (200 SMA) slope is negative ({slope_30wk_pct:.2f}%)"
            return default_res

        # 3. Strict Stage 2 Trend Template
        if not (curr_price >= c_sma50 * 0.98 and c_sma50 >= c_sma150 * 0.99 and c_sma150 >= c_sma200 * 0.99):
            default_res["rejection_reason"] = "Fails Stage 2 trend alignment (Price >= 50d >= 150d >= 200d SMA)"
            return default_res

        ext_pct = round(((curr_price - c_sma50) / c_sma50) * 100.0, 2)
        if ext_pct > 10.0:
            default_res["rejection_reason"] = f"Price is extended {ext_pct:.1f}% above 50d SMA (max 10% allowed)"
            return default_res

        # 4. 52-Week High Proximity
        h52 = clean_float(np.max(highs[-min(252, n):]))
        dist_52w = round(((h52 - curr_price) / h52) * 100.0, 2) if h52 > 0 else 999.0
        if dist_52w > 20.0:
            default_res["rejection_reason"] = f"Price is {dist_52w:.1f}% below 52W High (exceeds 20% cap)"
            return default_res

        # 5. MA Support Line Touch (within 2.5% of 10 EMA, 21 EMA, or 50 SMA)
        d10 = abs(curr_price - c_ema10) / c_ema10 * 100.0
        d21 = abs(curr_price - c_ema21) / c_ema21 * 100.0
        d50 = abs(curr_price - c_sma50) / c_sma50 * 100.0

        min_ma_dist = min(d10, d21, d50)
        ma_line = "10 EMA" if min_ma_dist == d10 else ("21 EMA" if min_ma_dist == d21 else "50 SMA")

        if min_ma_dist > 2.5:
            default_res["rejection_reason"] = f"Price is not resting near key MA support (closest is {ma_line} at {min_ma_dist:.1f}% distance)"
            return default_res

        # 6. Check Pocket Pivot Volume Signature over last 2 bars (today or yesterday)
        vol50_avg = clean_float(pd.Series(volumes).rolling(window=min(50, n), min_periods=20).mean().iloc[-1])
        curr_vdu = round(clean_float(volumes[-1]) / vol50_avg, 2) if vol50_avg > 0 else 1.0

        pocket_found = False
        ratio_max_down = 0.0
        up_day_vol_val = 0
        max_down_vol_val = 0

        for i in range(1, 3): # Check today (1) or yesterday (2)
            b_idx = n - i
            b_close = clean_float(closes[b_idx])
            b_prev = clean_float(closes[b_idx - 1]) if b_idx > 0 else b_close
            b_low = clean_float(lows[b_idx])
            b_vol = clean_float(volumes[b_idx])

            # Must be a solid UP day (gain >= +0.2%) AND today's close holding above Pocket Pivot bar low
            if b_close >= b_prev * 1.002 and curr_price >= b_low * 0.995:
                # Find max down-day volume in previous 10 trading days before b_idx
                start_look = max(0, b_idx - 10)
                down_vols = [volumes[k] for k in range(start_look, b_idx) if closes[k] < (closes[k-1] if k > 0 else closes[k])]
                max_down_vol = float(np.max(down_vols)) if down_vols else 1.0

                # Volume must exceed max down volume AND be at least 1.0x 50-day average volume
                if b_vol > max_down_vol and b_vol >= vol50_avg * 1.0:
                    pocket_found = True
                    ratio_max_down = round(b_vol / max_down_vol, 2) if max_down_vol > 0 else 1.5
                    up_day_vol_val = int(b_vol)
                    max_down_vol_val = int(max_down_vol)
                    break

        pivot_price = round(h52 if dist_52w <= 8.0 else max(curr_price * 1.02, c_ema10 * 1.03), 2)
        stop_loss = round(min(c_ema21, c_sma50) * 0.99, 2)
        risk_per_share = pivot_price - stop_loss
        if risk_per_share <= 0:
            risk_per_share = pivot_price * 0.035
            stop_loss = round(pivot_price - risk_per_share, 2)

        target_1 = round(pivot_price + (2.0 * risk_per_share), 2)
        target_2 = round(pivot_price + (4.0 * risk_per_share), 2)

        is_qualified = False
        if pocket_found:
            pocket_status = "POCKET_PIVOT_LIVE"
            is_qualified = True
        elif curr_vdu <= 0.65 and min_ma_dist <= 1.8: # Strict VDU dry up (volume <= 0.65x avg)
            pocket_status = "POCKET_PIVOT_FORMING"
            is_qualified = True
        else:
            pocket_status = "NONE"
            default_res["rejection_reason"] = "No live pocket pivot volume signature or strict VDU forming base"

        return {
            "is_pocket_pivot": bool(is_qualified),
            "pocket_status": str(pocket_status),
            "vol_ratio_vs_max_down": clean_float(ratio_max_down if ratio_max_down > 0 else 1.1),
            "up_day_vol": int(up_day_vol_val),
            "max_down_vol_10d": int(max_down_vol_val),
            "ma_support_line": str(ma_line),
            "pivot_price": clean_float(pivot_price),
            "stop_loss": clean_float(stop_loss),
            "target_1": clean_float(target_1),
            "target_2": clean_float(target_2),
            "current_price": clean_float(curr_price),
            "day_change_pct": clean_float(day_change_pct),
            "slope_30wk_pct": clean_float(slope_30wk_pct),
            "rs_score": clean_float(rs_score),
            "rejection_reason": default_res["rejection_reason"] if not is_qualified else ""
        }
    except Exception as e:
        print(f"Error in detect_pocket_pivot_strict: {e}")
        default_res["rejection_reason"] = f"Calculation error: {e}"
        return default_res
