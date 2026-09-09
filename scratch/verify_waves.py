import sys
import os
import json
import pandas as pd
import yfinance as yf

sys.path.append(os.path.abspath('.'))
from backend.swing_utils import detect_vcp_pattern

symbols = ["GVT&D.NS", "CANHLIFE.NS", "ZYDUSWELL.NS"]

print("=== VERIFYING WAVE CONTRACTION CALCULATIONS ===")

for sym in symbols:
    df = yf.Ticker(sym).history(period="1y")
    vcp_res = detect_vcp_pattern(df)
    
    print(f"\nStock: {sym}")
    print(f"VCP Status: {vcp_res.get('vcp_status')}")
    print(f"Pivot Price: {vcp_res.get('pivot_price')} | Stop Loss: {vcp_res.get('stop_loss')}")
    print(f"Total Waves Detected: {len(vcp_res.get('contractions', []))}")
    
    for c in vcp_res.get("contractions", []):
        print(f"  * {c['stage']}: High Rs.{c['high_price']} -> Low Rs.{c['low_price']} | Drop: {c['depth_percent']}% | Duration: {c['days']} trading days")
