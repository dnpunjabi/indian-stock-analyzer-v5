import sqlite3
import json

conn = sqlite3.connect('backend/data/watchlist_database.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) as cnt FROM cached_profiles")
print("Cached profiles count:", cursor.fetchone()["cnt"])

cursor.execute("SELECT cache_json FROM screener_results_cache WHERE screener_name='weinstein_stage2'")
row = cursor.fetchone()
items = json.loads(row["cache_json"]) if row else []
print("Total Stage 2 items:", len(items))
if items:
    print("Item keys:", items[0].keys())
    print("Item 0:", items[0])
