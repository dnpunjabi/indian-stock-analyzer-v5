import sqlite3
import glob
import os

backend_dir = os.path.dirname(__file__)
db_files = glob.glob(os.path.join(backend_dir, "*.db")) + glob.glob(os.path.join(backend_dir, "data", "*.db"))

cleared_tables = ["cached_profiles", "cached_financial_statements", "cached_trades", "cached_shareholdings", "cached_timeframe_indicators", "cached_news_impact"]

for db_file in db_files:
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = set(r[0] for r in cursor.fetchall())
        
        for table in cleared_tables:
            if table in existing_tables:
                cursor.execute(f"DELETE FROM {table}")
                conn.commit()
                print(f"Cleared table '{table}' in {os.path.basename(db_file)}")
        conn.close()
    except Exception as e:
        print(f"Error checking {db_file}: {e}")

print("[Cache] Cache successfully cleared across all database files!")
