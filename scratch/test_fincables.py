import sys
import os
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

from backend.swing_utils import (
    detect_flat_base_breakout,
    detect_episodic_pivot,
    detect_pocket_pivot
)

def test_fincables():
    ticker = "FINCABLES.NS"
    print(f"Fetching data for {ticker}...")
    df = yf.download(ticker, period="1y", interval="1d", progress=False)
    if df.empty:
        print("Empty df")
        return
    
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    print(f"Downloaded {len(df)} rows. Last Close: ₹{df['Close'].iloc[-1]:.2f}")
    
    print("\n--- 1. Flat Base Breakout ---")
    flat_res = detect_flat_base_breakout(df)
    print("Qualified:", flat_res.get("is_flat_base"))
    print("Metrics:", flat_res)
    
    print("\n--- 2. Episodic Pivot ---")
    ep_res = detect_episodic_pivot(df)
    print("Qualified:", ep_res.get("is_episodic_pivot"))
    print("Metrics:", ep_res)

    print("\n--- 3. Pocket Pivot ---")
    pp_res = detect_pocket_pivot(df)
    print("Qualified:", pp_res.get("is_pocket_pivot"))
    print("Metrics:", pp_res)

if __name__ == "__main__":
    test_fincables()
