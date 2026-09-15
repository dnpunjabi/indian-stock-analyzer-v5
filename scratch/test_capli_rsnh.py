import asyncio
import sys
import io
import json

sys.path.insert(0, '.')
from backend.main import fetch_history_df, _get_nifty_index_df, _load_screener_db_cache
from backend.swing_utils import detect_rs_line_new_high

async def main():
    print("--- Testing RS Line New High for CAPLIPOINT.NS ---")
    df = await fetch_history_df('CAPLIPOINT.NS', period='1y', interval='1d')
    nifty_df = await _get_nifty_index_df()
    
    r1 = detect_rs_line_new_high(df, nifty_df=nifty_df)
    print("Without rs_score:", json.dumps(r1, indent=2))
    
    r2 = detect_rs_line_new_high(df, nifty_df=nifty_df, rs_score=85)
    print("With rs_score=85:", json.dumps(r2, indent=2))

    print("\n--- Checking Screener DB Cache for rs_line_new_high ---")
    cache = _load_screener_db_cache("rs_line_new_high")
    if cache and cache.get("data"):
        capli_entry = next((x for x in cache["data"] if "CAPLI" in x.get("symbol", "")), None)
        print("Capli entry in cached rs_line_new_high:", json.dumps(capli_entry, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
