import sqlite3
import json
import os

for root, dirs, files in os.walk('backend'):
    for f in files:
        if f.endswith('.db'):
            full_path = os.path.join(root, f)
            try:
                conn = sqlite3.connect(full_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vcp_screener_cache'")
                if cursor.fetchone():
                    cursor.execute("SELECT symbol, vcp_json, canslim_json FROM vcp_screener_cache")
                    rows = cursor.fetchall()
                    print(f"=== Found in {full_path}: {len(rows)} rows ===")
                    for sym, v_json, c_json in rows:
                        v = json.loads(v_json)
                        c = json.loads(c_json)
                        status = v.get("vcp_status")
                        waves = len(v.get("contractions", []))
                        canslim_score = c.get("total_score")
                        stage = v.get("stage")
                        print(f"  Symbol: {sym:15} | Status: {status:15} | Waves: {waves} | Stage: {stage} | CANSLIM Score: {canslim_score}")
                conn.close()
            except Exception as e:
                pass
