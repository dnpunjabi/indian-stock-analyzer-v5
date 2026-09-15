import sqlite3
import os
import json

db_path = "backend/data/watchlist_database.db"

print("Checking db_path:", db_path)
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    table_names = [t[0] for t in tables]
    print("Tables:", table_names)
    
    if "screener_results_cache" in table_names:
        cursor.execute("SELECT screener_name, updated_at FROM screener_results_cache")
        entries = cursor.fetchall()
        print("Screener Cache Entries:", entries)
        
        for name, updated in entries:
            cursor.execute("SELECT results_json FROM screener_results_cache WHERE screener_name = ?", (name,))
            row = cursor.fetchone()
            if row and row[0]:
                data = json.loads(row[0])
                count = len(data) if isinstance(data, list) else (len(data.get("stocks", [])) if isinstance(data, dict) else 0)
                print(f"  -> Screener '{name}': {count} stocks (updated {updated})")
                if isinstance(data, list) and count > 0:
                    sample = data[0]
                    symbol = sample.get("symbol") or sample.get("ticker") or sample
                    print(f"     Sample: {symbol}")
