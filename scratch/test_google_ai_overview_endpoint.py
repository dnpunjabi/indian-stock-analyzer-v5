import sys
import os
sys.path.insert(0, os.path.abspath("."))

import asyncio
import json
from backend.main import get_google_ai_overview, init_db

async def main():
    init_db()
    print("Test 1: Fetching (force_refresh=False)...")
    res1 = await get_google_ai_overview("POLYCAB", force_refresh=False)
    print("Cache Status 1:", res1.get("from_cache"))

    print("\nTest 2: Fetching again (should hit SQLite cache)...")
    res2 = await get_google_ai_overview("POLYCAB", force_refresh=False)
    print("Cache Status 2:", res2.get("from_cache"))
    print("Data Source 2:", res2.get("data_source"))

if __name__ == "__main__":
    asyncio.run(main())
