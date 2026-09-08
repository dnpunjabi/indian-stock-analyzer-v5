import sys
import os
import yfinance as yf
import pandas as pd

sys.path.insert(0, os.path.abspath('.'))
from backend.swing_utils import (
    detect_vcp_pattern,
    detect_weinstein_stage2,
    detect_high_tight_flag,
    detect_3weeks_tight
)

sym = "JSWINFRA.NS"
print(f"Fetching data for {sym}...")
df = yf.download(sym, period="1y", interval="1d", progress=False)

if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)

print(f"Data rows fetched: {len(df)}")
curr_price = df['Close'].iloc[-1]
print(f"Current Close Price: {curr_price:.2f}")

print("\n--- 1. Mark Minervini VCP ---")
vcp = detect_vcp_pattern(df)
print(f"is_vcp: {vcp['is_vcp']} | vcp_status: {vcp['vcp_status']}")
print(f"Contractions: {vcp.get('contractions')}")
print(f"Volume Dry-Up Ratio: {vcp.get('volume_dryup_ratio')}")
print(f"Pivot Price: {vcp.get('pivot_price')} | Stop Loss: {vcp.get('stop_loss')}")

print("\n--- 2. Stan Weinstein Stage 2 ---")
ws2 = detect_weinstein_stage2(df)
print(f"is_stage2: {ws2['is_stage2']} | stage_status: {ws2['stage_status']}")
print(f"30W MA Slope: {ws2.get('ma30_slope_pct')}% | Breakout Vol Ratio: {ws2.get('breakout_vol_ratio')}")
print(f"Base Length Weeks: {ws2.get('base_length_weeks')} | Pivot Price: {ws2.get('pivot_price')}")

print("\n--- 3. David Ryan High-Tight Flag (HTF) ---")
htf = detect_high_tight_flag(df)
print(f"is_htf: {htf['is_htf']} | htf_status: {htf['htf_status']}")
print(f"Pole Gain: {htf.get('pole_gain_pct')}% | Flag Depth: {htf.get('flag_depth_pct')}% | Flag Days: {htf.get('flag_days')}")

print("\n--- 4. David Ryan 3-Weeks Tight (3WT) ---")
twt = detect_3weeks_tight(df)
print(f"is_3wt: {twt['is_3wt']} | tight_status: {twt['tight_status']}")
print(f"Weekly Closes: {twt.get('weekly_closes')} | Variance %: {twt.get('close_variance_pct')}%")
