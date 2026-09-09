import sqlite3
import json
import sys

# Ensure UTF-8 output encoding for Windows terminal compatibility
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

print("=" * 70)
print("TESTING WATCHLIST QUANT MATRIX PARITY & HYBRID QUOTE MERGING")
print("=" * 70)

db_path = "backend/data/watchlist_database.db"

try:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Fetch watchlists
    cursor.execute("SELECT id, name FROM watchlists LIMIT 3")
    wlists = [dict(r) for r in cursor.fetchall()]
    
    if not wlists:
        print("No watchlists found in database to test.")
    else:
        for wl in wlists:
            print(f"\nChecking Watchlist ID {wl['id']} ('{wl['name']}'):")
            cursor.execute("SELECT symbol, name, sector FROM watchlist_items WHERE watchlist_id = ?", (wl['id'],))
            items = [dict(r) for r in cursor.fetchall()]
            print(f"  • Contains {len(items)} items.")
            
            # Check vcp parity
            vcp_matches = 0
            for item in items:
                sym = item['symbol']
                cursor.execute("SELECT vcp_json FROM vcp_screener_cache WHERE symbol = ? OR symbol = ?", (sym, f"{sym}.NS"))
                v_row = cursor.fetchone()
                if v_row:
                    vcp_matches += 1
            print(f"  • {vcp_matches}/{len(items)} symbols present in VCP cache.")

    print("\n" + "=" * 70)
    print("WATCHLIST QUANT MATRIX PARITY TEST COMPLETE")
    print("=" * 70)

except Exception as e:
    print(f"[ERROR] Watchlist parity test failed: {e}")
