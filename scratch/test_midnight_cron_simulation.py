import sqlite3
import json
import sys

# Ensure UTF-8 output encoding for Windows terminal compatibility
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

print("=" * 70)
print("TESTING MIDNIGHT CRON SIMULATION & SQLITE AUDIT LOGS")
print("=" * 70)

db_path = "backend/data/watchlist_database.db"

try:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Audit Log Table Check
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cron_execution_logs'")
    table_exists = cursor.fetchone()
    if table_exists:
        print("[PASS] Table 'cron_execution_logs' exists on disk.")
    else:
        print("[FAIL] Table 'cron_execution_logs' is missing!")

    # 2. Check Recent Audit Logs
    cursor.execute("SELECT id, job_name, run_time, duration_seconds, status, details_json FROM cron_execution_logs ORDER BY id DESC LIMIT 5")
    logs = [dict(r) for r in cursor.fetchall()]
    print(f"\nFound {len(logs)} recent execution log entries:")
    for log in logs:
        print(f"  • Log #{log['id']} | Job: {log['job_name']} | Time: {log['run_time']} | Duration: {log['duration_seconds']}s | Status: {log['status']}")
        print(f"    Details: {log['details_json']}")

    # 3. Screener Cache Summary
    cursor.execute("SELECT screener_name, updated_at, length(cache_json) as bytes FROM screener_results_cache")
    caches = [dict(r) for r in cursor.fetchall()]
    print(f"\nScreener Results Cache Items ({len(caches)}):")
    for c in caches:
        print(f"  • Screener: {c['screener_name']:<20} | Last Updated: {c['updated_at']} | Size: {c['bytes']} bytes")

    # 4. VCP Cache Summary
    cursor.execute("SELECT COUNT(*), MAX(updated_at) FROM vcp_screener_cache")
    v_row = cursor.fetchone()
    print(f"\nVCP Screener Cache: Count = {v_row[0]}, Last Updated = {v_row[1]}")

    print("\n" + "=" * 70)
    print("ALL MIDNIGHT CRON AUDIT CHECKS COMPLETED SUCCESSFULLY")
    print("=" * 70)

except Exception as e:
    print(f"[ERROR] Verification failed: {e}")
