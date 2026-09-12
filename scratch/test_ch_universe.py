import sys
import os
import json
import urllib.request
import pandas as pd
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, os.path.abspath("."))

from backend.main import get_db
from backend.swing_utils import detect_cup_with_handle, clean_float

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

def main():
    print("Fetching screener universe...")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, company_name, sector, cap_type FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%' LIMIT 100")
        stocks = [dict(r) for r in cursor.fetchall()]

    print(f"Testing Cup With Handle on sample {len(stocks)} stocks...")
    
    ch_results = []

    for st in stocks:
        sym = st["symbol"].strip().upper()
        yf_sym = f"{sym}.NS" if not sym.endswith(".NS") and not sym.endswith(".BO") else sym
        
        df = fetch_fast_df(yf_sym)
        if df is None or df.empty or len(df) < 60:
            continue
        
        res = detect_cup_with_handle(df)
        if res.get("is_cup_with_handle"):
            ch_results.append((sym, res))

    print(f"\n==========================================")
    print(f"CUP WITH HANDLE QUALIFIED STOCKS: {len(ch_results)}")
    print(f"==========================================")
    for sym, r in ch_results:
        print(f"Symbol: {sym:<15} | Status: {r['base_status']:<18} | Cup Depth: -{r['cup_depth_pct']}% ({r['cup_length_weeks']}w) | Handle Depth: -{r['handle_depth_pct']}% ({r['handle_length_weeks']}w) | VDU: {r['vdu_ratio']}x | RS: {r['rs_rating']}")

if __name__ == '__main__':
    main()
