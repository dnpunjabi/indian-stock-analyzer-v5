import os
import sys
import asyncio
import dotenv

dotenv.load_dotenv()

wa_token = os.environ.get("WHATSAPP_TOKEN", "")
wa_phone_id = os.environ.get("WHATSAPP_PHONE_ID", "")
wa_recipient = os.environ.get("WHATSAPP_RECIPIENT", "")

print("=== WHATSAPP ENVIRONMENT CONFIGURATION ===")
print(f"WHATSAPP_TOKEN set: {bool(wa_token)} (Length: {len(wa_token)})")
print(f"WHATSAPP_PHONE_ID: '{wa_phone_id}'")
print(f"WHATSAPP_RECIPIENT: '{wa_recipient}'")

sys.path.insert(0, os.path.abspath('.'))

from backend.main import get_db, get_fuzzy_summary_for_symbol, _fuzzy_whatsapp_sent_cache

async def run_debug():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT symbol FROM watchlist_items")
        symbols = [row["symbol"] for row in cursor.fetchall()]
        print(f"\nFound {len(symbols)} distinct watchlist symbols: {symbols}")
        
        for symbol in symbols:
            fz = get_fuzzy_summary_for_symbol(conn, symbol)
            print(f"  Symbol: {symbol:<15} | fz: {fz}")
            score = fz.get("fuzzy_score", 0.0)
            if score >= 70.0:
                print(f"    --> TRIGGER: STRONG_BUY (score: {score} >= 70.0)")
            elif score <= -40.0:
                print(f"    --> TRIGGER: AVOID (score: {score} <= -40.0)")
            else:
                print(f"    --> NO TRIGGER (score: {score})")

if __name__ == "__main__":
    asyncio.run(run_debug())
