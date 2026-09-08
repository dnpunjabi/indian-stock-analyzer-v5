import sqlite3
import json

conn = sqlite3.connect('backend/data/watchlist_database.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("SELECT profile_json FROM cached_profiles LIMIT 1")
row = cursor.fetchone()
if row:
    data = json.loads(row["profile_json"])
    print("Keys in profile_json:", data.keys())
    if "historical_prices" in data:
        print("Historical prices count:", len(data["historical_prices"]))
        print("Sample hist price:", data["historical_prices"][0])
