import sys
import os
import asyncio

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.abspath('.'))
from backend.main import get_stage_diagnostic

async def main():
    res = await get_stage_diagnostic("JSWINFRA.NS", force_refresh=True)
    print("Status:", res.get("status"))
    print("Stage Name:", res.get("stage_name"))
    print("\n--- SCREENER AUDIT KEYS ---")
    audit = res.get("screener_audit", {})
    for key, val in audit.items():
        print(f"\n[{key.upper()}]")
        print("  Name:", val.get("name"))
        print("  Required:", val.get("required"))
        print("  Actual:", val.get("actual"))
        print("  Qualified:", val.get("qualified"))
        print("  Reason:", val.get("reason"))

if __name__ == "__main__":
    asyncio.run(main())
