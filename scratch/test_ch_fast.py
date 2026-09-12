import sys
import os
import json
import urllib.request
import pandas as pd

sys.path.insert(0, os.path.abspath("."))
from backend.swing_utils import detect_cup_with_handle

symbols = ["TATASTEEL.NS", "RELIANCE.NS", "HAL.NS", "DIXON.NS", "LTIM.NS", "TRENT.NS", "BHARTIARTL.NS", "AXISBANK.NS", "BEL.NS", "BHEL.NS"]

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
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None

print("--- TESTING CUP WITH HANDLE DETECTION ON KEY LEADER STOCKS ---")
for sym in symbols:
    df = fetch_fast_df(sym)
    if df is not None and not df.empty:
        res = detect_cup_with_handle(df)
        print(f"\n{sym}:")
        print(f"  Is Cup With Handle: {res.get('is_cup_with_handle')}")
        print(f"  Base Status: {res.get('base_status')}")
        print(f"  Cup Depth: {res.get('cup_depth_pct')}% ({res.get('cup_length_weeks')} wks)")
        print(f"  Handle Depth: {res.get('handle_depth_pct')}% ({res.get('handle_length_weeks')} wks)")
        print(f"  VDU Ratio: {res.get('vdu_ratio')}x")
        print(f"  RS Rating: {res.get('rs_rating')}")
        print(f"  Rejection Reason: {res.get('rejection_reason')}")
