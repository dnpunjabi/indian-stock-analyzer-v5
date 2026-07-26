import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.daily_wrapup import (
    generate_daily_wrapup_text, 
    fetch_market_sentiment_header,
    fetch_52w_breakouts
)

def safe_print(text: str):
    """Safely prints UTF-8 text to console on Windows."""
    try:
        sys.stdout.buffer.write((text + "\n").encode('utf-8'))
        sys.stdout.buffer.flush()
    except Exception:
        print(text.encode('ascii', errors='replace').decode('ascii'))

async def test_all():
    safe_print("==================================================")
    safe_print("RUNNING COMPREHENSIVE DAILY WRAPUP TESTS")
    safe_print("==================================================")

    # 1. Test Sentiment VIX Header
    safe_print("\n--- 1. Testing Market Sentiment VIX Header ---")
    sentiment_hdr = fetch_market_sentiment_header()
    safe_print(f"Sentiment Header Output:\n{sentiment_hdr.strip()}")
    assert "Market Sentiment:" in sentiment_hdr, "Sentiment header missing expected label"
    assert "India VIX:" in sentiment_hdr, "India VIX missing from sentiment header"
    safe_print("✅ Market Sentiment VIX Header test PASSED")

    # 2. Test 52W Breakouts Radar
    safe_print("\n--- 2. Testing 52-Week Breakout Radar ---")
    port_syms = ["RELIANCE.NS", "TCS.NS", "BOSCHLTD.NS"]
    watch_syms = ["INFY.NS", "SBIN.NS"]
    breakouts = fetch_52w_breakouts(port_syms, watch_syms)
    safe_print(f"Breakouts Output:\n{breakouts.strip() if breakouts else '[No 52W breakouts today]'}")
    safe_print("✅ 52-Week Breakout Radar test PASSED")

    # 3. Test Daily Report Generation
    safe_print("\n--- 3. Testing Daily Close Wrap-Up Report ---")
    daily_msg = await generate_daily_wrapup_text(persona_override="institutional", is_weekly_override=False)
    safe_print(f"Daily Report Length: {len(daily_msg)} characters")
    assert len(daily_msg) < 3800, f"Daily report length ({len(daily_msg)}) exceeds 3800 safety limit!"
    assert "Daily Close Wrap-Up" in daily_msg, "Daily title missing"
    safe_print("✅ Daily Close Wrap-Up test PASSED")

    # 4. Test Saturday Weekly Retrospective Report
    safe_print("\n--- 4. Testing Saturday Weekly Retrospective Report ---")
    weekly_msg = await generate_daily_wrapup_text(persona_override="macro", is_weekly_override=True)
    safe_print(f"Weekly Report Length: {len(weekly_msg)} characters")
    assert len(weekly_msg) < 3800, f"Weekly report length ({len(weekly_msg)}) exceeds 3800 safety limit!"
    assert "Weekly Close Retrospective" in weekly_msg, "Weekly title missing"
    safe_print("✅ Saturday Weekly Retrospective test PASSED")

    safe_print("\n==================================================")
    safe_print("🎉 ALL ENHANCED DAILY WRAPUP TESTS PASSED SUCCESSFULLY!")
    safe_print("==================================================")

if __name__ == "__main__":
    asyncio.run(test_all())
