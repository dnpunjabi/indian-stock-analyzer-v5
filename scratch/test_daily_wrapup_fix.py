import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.daily_wrapup import generate_daily_wrapup_text

async def main():
    print("Testing generate_daily_wrapup_text()...")
    msg = await generate_daily_wrapup_text()
    print(f"Generated Message Length: {len(msg)} characters")
    print("--- PREVIEW (utf-8 safe) ---")
    sys.stdout.buffer.write(msg.encode('utf-8'))
    print("\n--- PREVIEW END ---")

if __name__ == "__main__":
    asyncio.run(main())
