import asyncio
import json
import sys
import pandas as pd
import yfinance as yf

sys.path.append('backend')
from swing_utils import detect_high_tight_flag

# Load nifty500 stocks list from backend/nifty500_stocks.json
try:
    with open('backend/nifty500_stocks.json', 'r') as f:
        stocks = json.load(f)
except Exception as e:
    print(f"Error loading nifty500_stocks.json: {e}")
    stocks = []

print(f"Loaded {len(stocks)} stocks.")

# Let's test top 100 liquid/momentum stocks or a batch
sample_symbols = [item['symbol'] if isinstance(item, dict) else item for item in stocks[:80]]
# Add well known momentum stocks
extra = ["CochinShipyard.NS", "MAZDOCK.NS", "FACT.NS", "IREDA.NS", "BHEL.NS", "TRENT.NS", "DIXON.NS", "KAYNES.NS", "BEL.NS", "HAL.NS", "RVNL.NS", "IRFC.NS"]
for e in extra:
    if e not in sample_symbols:
        sample_symbols.append(e)

print(f"Testing {len(sample_symbols)} stocks...")

results = []

for sym in sample_symbols:
    try:
        df = yf.download(sym, period="6mo", interval="1d", progress=False)
        if df is not None and not df.empty and len(df) >= 30:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            res = detect_high_tight_flag(df)
            res['symbol'] = sym
            results.append(res)
    except Exception as err:
        pass

results.sort(key=lambda x: x['pole_gain_pct'], reverse=True)

print("\n=== TOP 20 STOCKS BY POLE GAIN % ===")
print(f"{'Symbol':<18} | {'Pole Gain %':<12} | {'Flag Depth %':<12} | {'Flag Days':<10} | {'VDU':<6} | {'Qualified':<10} | {'Status'}")
print("-" * 95)
for r in results[:20]:
    print(f"{r['symbol']:<18} | {r['pole_gain_pct']:<12} | {r['flag_depth_pct']:<12} | {r['flag_days']:<10} | {r['vdu_ratio']:<6} | {str(r['is_htf']):<10} | {r['htf_status']}")

qualified = [r for r in results if r['is_htf']]
print(f"\nTotal Qualified HTF setups in sample: {len(qualified)}")
if qualified:
    for q in qualified:
        print(f"Qualified: {q['symbol']} -> {q}")
