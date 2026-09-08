import sqlite3
import json

conn = sqlite3.connect('backend/data/watchlist_database.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("SELECT cache_json FROM screener_results_cache WHERE screener_name='weinstein_stage2'")
row = cursor.fetchone()
data = json.loads(row["cache_json"]) if row else []

print(f"Total current items in Stage 2 DB cache: {len(data)}")

launch = [s for s in data if s.get('stage_status') in ['STAGE_2_LAUNCH', 'STAGE_2_BREAKOUT']]
advancing = [s for s in data if s.get('stage_status') == 'STAGE_2_ADVANCING']

print(f"STAGE_2_LAUNCH (Breakouts): {len(launch)}")
print(f"STAGE_2_ADVANCING: {len(advancing)}")

# Check RS thresholds
rs_gt_20 = [s for s in data if s.get('mansfield_rs', 0) >= 20.0]
rs_gt_25 = [s for s in data if s.get('mansfield_rs', 0) >= 25.0]
rs_gt_30 = [s for s in data if s.get('mansfield_rs', 0) >= 30.0]

print(f"Items with Mansfield RS >= 20.0: {len(rs_gt_20)}")
print(f"Items with Mansfield RS >= 25.0: {len(rs_gt_25)}")
print(f"Items with Mansfield RS >= 30.0: {len(rs_gt_30)}")

print("\nTop 10 Stage 2 Candidates:")
for s in data[:10]:
    print(f"  {s['symbol']:<15} RS: {s.get('mansfield_rs', 0):<6} Status: {s.get('stage_status')}")
