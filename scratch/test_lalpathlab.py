import asyncio
import sys
import io
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from backend.main import get_stage_diagnostic

async def main():
    sym = "LALPATHLAB.NS"
    print(f"=== Diagnosing {sym} ===")
    
    # 1. Live Diagnostic
    res = await get_stage_diagnostic(sym)
    print("Stage Diagnosis:", res.get("stage_name"), f"(Stage {res.get('stage_number')})")
    
    screener_audit = res.get("screener_audit", {})
    qual_count = sum(1 for item in screener_audit.values() if isinstance(item, dict) and item.get("qualified"))
    print(f"\nLive 11-Screener Diagnostic Parity: {qual_count} Qualified / {len(screener_audit)} Total\n")
    
    print("Detailed Screener Breakdown:")
    for k, item in screener_audit.items():
        if isinstance(item, dict):
            status = "QUALIFIED" if item.get("qualified") else "REJECTED"
            print(f" [{status}] {item.get('name', k)}")
            print(f"   Reason:   {item.get('reason')}")
            print(f"   Required: {item.get('required')}")
            print(f"   Actual:   {item.get('actual')}\n")

if __name__ == "__main__":
    asyncio.run(main())
