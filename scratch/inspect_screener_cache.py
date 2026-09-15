import sys
import sqlite3
import os
import json

sys.stdout.reconfigure(encoding='utf-8')

db_path = "backend/data/watchlist_database.db"

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("PRAGMA table_info(screener_results_cache)")
columns = [col[1] for col in cursor.fetchall()]

cursor.execute("SELECT * FROM screener_results_cache")
rows = cursor.fetchall()

screener_results = {}
for row in rows:
    screener_name = row[0]
    for val in row:
        if isinstance(val, str) and (val.startswith("[") or val.startswith("{")):
            try:
                parsed = json.loads(val)
                screener_results[screener_name] = parsed
                break
            except Exception:
                pass

print("Screeners Found:")
for k, v in screener_results.items():
    cnt = len(v) if isinstance(v, list) else len(v.get("stocks", [])) if isinstance(v, dict) else 0
    print(f"- {k}: {cnt} stocks")

stock_scores = {}
for s_name, data in screener_results.items():
    items = data if isinstance(data, list) else data.get("stocks", []) if isinstance(data, dict) else []
    for item in items:
        sym = item.get("symbol") if isinstance(item, dict) else (item.get("ticker") if isinstance(item, dict) else item)
        company = item.get("company_name") or item.get("name") or sym if isinstance(item, dict) else sym
        close_p = item.get("close") or item.get("current_price") or item.get("pivot_price") if isinstance(item, dict) else "N/A"
        
        if not sym:
            continue
        if sym not in stock_scores:
            stock_scores[sym] = {
                "symbol": sym,
                "company_name": company,
                "close": close_p,
                "screeners": [],
                "details": {}
            }
        stock_scores[sym]["screeners"].append(s_name)
        if isinstance(item, dict):
            stock_scores[sym]["details"][s_name] = item

sorted_stocks = sorted(stock_scores.values(), key=lambda x: len(x["screeners"]), reverse=True)

print("\n=== TOP CONFLUENCE STOCKS (QUALIFIED IN MULTIPLE SCREENERS) ===")
for s in sorted_stocks[:30]:
    print(f"[{len(s['screeners'])} Screeners] {s['symbol']} ({s['company_name']}) - Price: ₹{s['close']}")
    print(f"   Screeners: {', '.join(s['screeners'])}")
