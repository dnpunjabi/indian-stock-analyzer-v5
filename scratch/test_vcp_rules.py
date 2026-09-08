import sqlite3
import json
import urllib.request
import pandas as pd
import numpy as np

# Load VCP DB cache
conn = sqlite3.connect('backend/data/watchlist_database.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("SELECT symbol, vcp_json FROM vcp_screener_cache")
rows = cursor.fetchall()

print(f"Total current items in VCP cache: {len(rows)}")

def fetch_fast_df(sym):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d"
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

refined_vcp = []
for idx, r in enumerate(rows[:100]): # Test first 100
    sym = r["symbol"]
    item = json.loads(r["vcp_json"])
    yf_sym = f"{sym}.NS" if not sym.endswith(".NS") else sym
    df = fetch_fast_df(yf_sym)
    if df is not None and len(df) >= 50:
        closes = df['Close'].values
        highs = df['High'].values
        lows = df['Low'].values
        volumes = df['Volume'].values
        n = len(closes)
        cp = float(closes[-1])
        
        # 1. Trend Template Alignment (Price > 50 EMA > 200 EMA & Near 52W High)
        ema50 = float(pd.Series(closes).ewm(span=50, adjust=False).mean().iloc[-1])
        ema200 = float(pd.Series(closes).ewm(span=200, adjust=False).mean().iloc[-1])
        h52w = float(np.max(highs[-min(252, n):]))
        
        near_52w = cp >= (h52w * 0.85) # Within 15% of 52W High
        in_uptrend = (cp >= ema50) and (ema50 >= ema200) and near_52w
        
        # 2. Real contraction tightness (final wave <= 10% depth)
        contractions = item.get("contractions", [])
        if contractions:
            final_depth = abs(contractions[-1].get("depth_percent", 99))
            tight_pivot = final_depth <= 10.0
        else:
            tight_pivot = False
            
        # 3. Volume dry up
        vdu = item.get("volume_dryup_ratio", 1.0) <= 0.85
        
        if in_uptrend and tight_pivot:
            refined_vcp.append((sym, final_depth, cp, h52w))

print(f"Sample Refined VCP Count (out of 100 tested): {len(refined_vcp)}")
print("Sample qualifying VCP candidates:")
for v in refined_vcp[:10]:
    print(v)
