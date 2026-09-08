import sqlite3
import json

conn = sqlite3.connect('backend/data/watchlist_database.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("SELECT cache_json FROM screener_results_cache WHERE screener_name='weinstein_stage2'")
row = cursor.fetchone()
data = json.loads(row["cache_json"]) if row else []
print(f"EXACT STAGE 2 COUNT: {len(data)}")
