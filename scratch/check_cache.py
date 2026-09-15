import sys
import io
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from backend.main import _load_screener_db_cache

keys = [
    'weinstein_stage2', 'htf', '3weeks_tight', 'flat_base_breakout',
    'episodic_pivot', 'pocket_pivot', 'oliver_kell_reversal',
    'cup_with_handle', 'rs_line_new_high', 'undercut_and_rally'
]

print("=== CRAWLING CACHE FOR LALPATHLAB ===")
for k in keys:
    cached = _load_screener_db_cache(k)
    if cached and cached.get("data"):
        for item in cached["data"]:
            if "LALPATHLAB" in item.get("symbol", ""):
                print(f"Screener: {k} -> Found {item.get('symbol')}, Updated At: {cached.get('last_updated')}")
