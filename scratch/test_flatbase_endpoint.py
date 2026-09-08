import sys
import os
import asyncio
import traceback

sys.path.insert(0, os.path.abspath("."))
from backend.main import get_flat_base_screener

async def main():
    try:
        print("Testing get_flat_base_screener(force_refresh=True)...")
        res = await get_flat_base_screener(force_refresh=True)
        print("RESULT SUCCESS!")
        print(f"Status: {res.get('status')} | Count: {res.get('count')} | Last Updated: {res.get('last_updated')}")
    except Exception as e:
        print("EXCEPTION CAUGHT:")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
