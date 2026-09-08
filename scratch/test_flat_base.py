import sys
import os
import json
import urllib.request
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.abspath("."))
from backend.main import get_db
from backend.swing_utils import detect_flat_base_breakout

def fetch_fast_df(symbol: str) -> pd.DataFrame:
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1y&interval=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
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

def process_symbol(st):
    sym = st["symbol"].strip().upper()
    yf_sym = f"{sym}.NS" if not sym.endswith(".NS") else sym
    df = fetch_fast_df(yf_sym)
    if df is None or df.empty or len(df) < 100:
        return None
    res = detect_flat_base_breakout(df, rs_score=75.0)
    if res and res.get("is_flat_base"):
        res["symbol"] = sym
        return res
    return None

def run_test():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, company_name FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%'")
        stocks = [dict(r) for r in cursor.fetchall()]

    print(f"Total stocks in universe: {len(stocks)}")

    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = executor.map(process_symbol, stocks[:150])
        for r in futures:
            if r:
                results.append(r)

    print(f"\n==================================================")
    print(f"FLAT BASE RESULTS ({len(results)} QUALIFIED IN SAMPLE OF 150)")
    print(f"==================================================")
    for r in results:
        print(f"Symbol: {r['symbol']} | Weeks: {r['base_length_weeks']} ({r['base_length_days']}d) | Depth: {r['base_depth_pct']}% | Status: {r['base_status']} | VDU: {r['vdu_ratio']}x | Pivot: Rs.{r['pivot_price']} | Boxes: {r['stacked_boxes_count']}")

if __name__ == "__main__":
    run_test()
