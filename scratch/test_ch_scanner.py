import sqlite3
import pandas as pd
import json
import sys
import os

sys.path.append(os.path.abspath('.'))
from backend.swing_utils import detect_cup_with_handle

db_path = 'indian_stocks.db'
if not os.path.exists(db_path):
    print("Database file not found!")
    sys.exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Fetch daily price data from stock_historical_data
cursor.execute("SELECT DISTINCT symbol FROM stock_historical_data")
symbols = [row[0] for row in cursor.fetchall()]

print(f"Total symbols found in DB: {len(symbols)}")

ch_results = []

for sym in symbols:
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume FROM stock_historical_data WHERE symbol = ? ORDER BY date ASC",
        conn,
        params=(sym,)
    )
    if len(df) < 200:
        continue
    
    # Standardize column names if needed
    df['date'] = pd.to_datetime(df['date'])
    res = detect_cup_with_handle(df)
    if res.get("is_cup_with_handle"):
        ch_results.append((sym, res))

print(f"\n--- CUP WITH HANDLE QUALIFIED STOCKS: {len(ch_results)} ---")
for sym, r in ch_results:
    print(f"Symbol: {sym:<15} | Status: {r['base_status']:<18} | Cup Depth: -{r['cup_depth_pct']}% ({r['cup_length_weeks']}w) | Handle Depth: -{r['handle_depth_pct']}% ({r['handle_length_weeks']}w) | VDU: {r['vdu_ratio']}x | RS: {r['rs_rating']}")

conn.close()
