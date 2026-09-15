import asyncio
import sys
import json

sys.path.insert(0, '.')
from backend.main import get_stage_diagnostic

async def main():
    print("--- Testing get_stage_diagnostic for BHEL.NS ---")
    res_bhel = await get_stage_diagnostic("BHEL.NS")
    print("Screener Status:", json.dumps(res_bhel.get("screener_status"), indent=2))
    print("\nScreener Audit:", json.dumps(res_bhel.get("screener_audit"), indent=2))

if __name__ == "__main__":
    asyncio.run(main())
