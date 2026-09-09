import sys
import os
import json
import pandas as pd
import yfinance as yf

sys.path.append(os.path.abspath('.'))
from backend.swing_utils import detect_vcp_pattern

test_symbols = [
    "GVT&D.NS", "CANHLIFE.NS", "ZYDUSWELL.NS", "AXISBANK.NS", "CDSL.NS", "AEGISVOPAK.NS", 
    "ASTERDM.NS", "RELIANCE.NS", "TCS.NS", "INFY.NS", "BHARTIARTL.NS", "USHAMART.NS", "ABB.NS"
]

print("=== VCP & CANSLIM DETAILED FILTER AUDIT ===")

for sym in test_symbols:
    try:
        df = yf.Ticker(sym).history(period="1y")
        if df.empty or len(df) < 150:
            print(f"{sym:15}: Insufficient data ({len(df)} bars)")
            continue
        
        vcp_res = detect_vcp_pattern(df)
        status = vcp_res.get("vcp_status", "NONE")
        is_vcp = vcp_res.get("is_vcp", False)
        contractions = vcp_res.get("contractions", [])
        num_waves = len(contractions)
        
        if is_vcp and status != "NONE":
            print(f"[PASS] {sym:15} | Status: {status:15} | Waves: {num_waves} | Pivot: {vcp_res.get('pivot_price')}")
        else:
            print(f"[FAIL] {sym:15} | Status: {status:15} | Waves: {num_waves} | Depths: {[c['depth_percent'] for c in contractions]}")
    except Exception as e:
        print(f"ERROR on {sym}: {e}")
