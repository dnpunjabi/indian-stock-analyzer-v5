import asyncio
import os
import sys

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(__file__))

from backend.main import get_google_ai_overview_endpoint

async def test_google_overview():
    symbol = "RELIANCE.NS"
    print(f"--- Testing Google AI Overview for {symbol} ---")
    res1 = await get_google_ai_overview_endpoint(symbol, force_refresh=True)
    print("Result 1 (fresh):")
    print("  Data Source:", res1.get("data_source"))
    print("  Text length:", len(res1.get("text", "")))
    print("  Sections count:", len(res1.get("sections", [])))
    print("  Sentiment Score:", res1.get("sentiment_score"), res1.get("sentiment_label"))
    print("  Snippet:", res1.get("text", "")[:200])

    print("\n--- Testing Cache Hit for RELIANCE.NS ---")
    res2 = await get_google_ai_overview_endpoint(symbol, force_refresh=False)
    print("Result 2 (cached):")
    print("  From Cache flag:", res2.get("from_cache"))
    print("  Cached text matches original:", res1.get("text") == res2.get("text"))

if __name__ == "__main__":
    asyncio.run(test_google_overview())
