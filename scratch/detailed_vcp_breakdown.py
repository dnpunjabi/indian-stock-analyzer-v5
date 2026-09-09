import sys
import os
import json
import numpy as np
import pandas as pd
import yfinance as yf

sys.path.append(os.path.abspath('.'))
from backend.swing_utils import detect_vcp_pattern, detect_weinstein_stage3

symbols = ["GVT&D.NS", "CANHLIFE.NS", "ZYDUSWELL.NS", "AXISBANK.NS", "AEGISVOPAK.NS", "ASTERDM.NS"]

for sym in symbols:
    df = yf.Ticker(sym).history(period="1y")
    closes = df['Close'].values
    highs = df['High'].values
    lows = df['Low'].values
    curr_price = float(closes[-1])
    n = len(df)
    
    sma50 = float(pd.Series(closes).rolling(50, min_periods=10).mean().values[-1])
    sma150 = float(pd.Series(closes).rolling(150, min_periods=20).mean().values[-1])
    sma200_series = pd.Series(closes).rolling(200, min_periods=20).mean().values
    sma200 = float(sma200_series[-1])
    sma200_30d = float(sma200_series[-30] if n >= 30 else sma200_series[0])
    
    high_52w = float(np.max(highs[-min(252, n):]))
    low_52w = float(np.min(lows[-min(252, n):]))
    
    near_52w_high = curr_price >= (high_52w * 0.75)
    above_52w_low = curr_price >= (low_52w * 1.30)
    sma200_rising = sma200 > sma200_30d
    ma_order = (curr_price > sma50) and (sma50 > sma150) and (sma150 > sma200)
    
    s3_res = detect_weinstein_stage3(df)
    not_stage3 = not (s3_res.get("is_stage3") or s3_res.get("stage_status") in ["STAGE_3_DISTRIBUTION", "STAGE_3_TOPPING"])
    mansfield_rs = s3_res.get("mansfield_rs", 0.0)
    rs_leadership = mansfield_rs >= 0.0 or near_52w_high
    
    in_stage_2 = ma_order and sma200_rising and near_52w_high and above_52w_low and not_stage3 and rs_leadership
    
    vcp_res = detect_vcp_pattern(df)
    
    print(f"=== {sym} ===")
    print(f"  Price: {curr_price:.2f} | 50SMA: {sma50:.2f} | 150SMA: {sma150:.2f} | 200SMA: {sma200:.2f}")
    print(f"  MA Order: {ma_order} | 200SMA Rising: {sma200_rising} | Near 52W High: {near_52w_high} | Above 52W Low: {above_52w_low}")
    print(f"  Not Stage 3: {not_stage3} | RS Leadership: {rs_leadership} => IN_STAGE_2: {in_stage_2}")
    print(f"  VCP Status: {vcp_res.get('vcp_status')} | is_vcp: {vcp_res.get('is_vcp')} | Waves: {len(vcp_res.get('contractions', []))}")
    print(f"  VDU Ratio: {vcp_res.get('vdu_ratio')} | Pivot: {vcp_res.get('pivot_price')}")
    print()
