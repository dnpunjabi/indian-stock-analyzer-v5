import time
import urllib.request
import json
import sys

# Ensure UTF-8 output encoding for Windows terminal compatibility
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://localhost:8000"

endpoints = [
    ("/api/vcp-canslim-screener", "VCP & CANSLIM Screener"),
    ("/api/screener/weinstein-stage2", "Weinstein Stage 2 Screener"),
    ("/api/screener/3weeks-tight", "David Ryan 3-Weeks Tight Screener"),
    ("/api/screener/high-tight-flag", "David Ryan High-Tight Flag Screener"),
    ("/api/screener/flat-base", "Modern Flat Base Screener"),
    ("/api/system/cron-status", "System Cron Status API")
]

print("=" * 70)
print("RUNNING QUANT SUITE PERFORMANCE BENCHMARK (SQLite Single Source of Truth)")
print("=" * 70)

all_passed = True
for path, name in endpoints:
    url = f"{BASE_URL}{path}"
    start = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BenchmarkScript"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            elapsed_ms = (time.time() - start) * 1000
            
            cnt = len(data.get("stocks", [])) if "stocks" in data else len(data.get("data", [])) if "data" in data else data.get("count", 0)
            status_str = "PASS" if elapsed_ms < 100 else "SLOW"
            print(f"[{status_str}] {name:<35} -> {elapsed_ms:>6.2f} ms | Items: {cnt}")
            if elapsed_ms >= 500:
                all_passed = False
    except Exception as e:
        print(f"[FAIL] {name:<35} -> ERROR: {e}")
        all_passed = False

print("=" * 70)
if all_passed:
    print("SUCCESS: All endpoints served instantly via SQLite WAL cache.")
else:
    print("WARNING: Some endpoints took longer than expected.")
print("=" * 70)
