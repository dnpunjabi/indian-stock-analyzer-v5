import sys, os, json, sqlite3
sys.path.insert(0, '.')
from backend.fuzzy_engine import evaluate_fuzzy_logic

db_path = 'backend/data/watchlist_database.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    print(f"=== DB: {db_path} ===")
    for sym_search in ['JSWENERGY%', 'MTARTECH%', 'SONACOMS%', 'BOSCHLTD%']:
        row = cur.execute("SELECT symbol, profile_json FROM cached_profiles WHERE symbol LIKE ?", (sym_search,)).fetchone()
        if row:
            p_json = row['profile_json']
            if p_json:
                data = json.loads(p_json)
                res = evaluate_fuzzy_logic(data)
                print(f"Symbol: {row['symbol']}, Score: {res['score']}, Rating: {res['rating']}")
            else:
                print(f"Symbol: {row['symbol']} has NULL profile_json")
        else:
            print(f"Symbol {sym_search} NOT IN cached_profiles")
else:
    print(f"{db_path} does not exist!")
