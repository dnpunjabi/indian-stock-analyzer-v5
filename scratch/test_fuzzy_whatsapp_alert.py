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

from backend.main import check_fuzzy_watchlist_whatsapp_alerts, _fuzzy_whatsapp_sent_cache

async def run_test():
    print("\nResetting fuzzy WhatsApp sent cache for clean test run...")
    _fuzzy_whatsapp_sent_cache.clear()
    
    print("\nRunning check_fuzzy_watchlist_whatsapp_alerts()...")
    await check_fuzzy_watchlist_whatsapp_alerts()
    
    print("\nCache contents after sweep:")
    for sym, state in _fuzzy_whatsapp_sent_cache.items():
        print(f"  {sym}: {state}")

if __name__ == "__main__":
    asyncio.run(run_test())
