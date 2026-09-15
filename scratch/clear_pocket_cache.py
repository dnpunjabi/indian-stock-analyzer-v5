import sys
import os
import sqlite3

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.main import get_db

def clear_pocket_db_cache():
    print("Clearing DB screener_results_cache for 'pocket_pivot'...")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM screener_results_cache WHERE screener_name = 'pocket_pivot'")
        conn.commit()
    print("Cache cleared successfully.")

if __name__ == "__main__":
    clear_pocket_db_cache()
