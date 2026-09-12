import sys
import os
import asyncio
import pandas as pd
import numpy as np

# Ensure backend can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.swing_utils import detect_cup_with_handle

def test_detector_synthetic():
    print("--- 1. Testing detect_cup_with_handle on Synthetic Cup & Handle Data ---")
    dates = pd.date_range(end='2026-09-11', periods=400, freq='B')
    
    # 0 to 150: Base at 75
    prices = list(np.linspace(70, 75, 100))
    # 100 to 250: Prior advance from 75 to 153 (+104%)
    prices.extend(np.linspace(75, 153, 150))
    # 250 to 310: Cup decline from 153 to 110 (-28.1% depth)
    prices.extend(np.linspace(153, 110, 60))
    # 310 to 385: Right lip recovery from 110 to 152
    prices.extend(np.linspace(110, 152, 75))
    # 385 to 400: Handle consolidation from 152 to 147 (-3.3% depth, 15 days)
    prices.extend(np.linspace(152, 147, 15))

    volumes = [100000] * 385 + [30000] * 15

    df = pd.DataFrame({
        'Open': prices,
        'High': [p * 1.002 for p in prices],
        'Low': [p * 0.998 for p in prices],
        'Close': prices,
        'Volume': volumes
    }, index=dates)

    res = detect_cup_with_handle(df, rs_score=85.0)
    print("Cup with Handle Detection Result:")
    for k, v in res.items():
        print(f"  {k}: {v}")
    
    assert res["is_cup_handle"] == True, f"Expected Cup & Handle to qualify! Rejection reason: {res.get('rejection_reason')}"
    print("[OK] Synthetic Cup & Handle detector test PASSED!")

async def test_backend_endpoints():
    print("\n--- 2. Testing Stage Diagnostic & 9-Screener API Integration ---")
    from backend.main import get_stage_diagnostic, _eval_watchlist_quant_diagnostics
    
    # Test Stage Diagnostic for DIXON
    diag = await get_stage_diagnostic("DIXON")
    print(f"DIXON Stage Diagnostic Status: {diag.get('status')}")
    assert diag.get("status") == "success", "Expected stage diagnostic status success"
    
    screener_status = diag.get("screener_status", {})
    screener_audit = diag.get("screener_audit", {})
    
    print("Screener Status Keys:", list(screener_status.keys()))
    assert "cup_with_handle" in screener_status, "Missing cup_with_handle in screener_status!"
    assert "cup_with_handle" in screener_audit, "Missing cup_with_handle in screener_audit!"
    
    print(f"Cup with Handle Status for DIXON: {screener_status['cup_with_handle']}")
    
    # Test Watchlist Quant Matrix Evaluation
    wl_res = await _eval_watchlist_quant_diagnostics(["DIXON", "TATASTEEL"])
    print(f"Watchlist Matrix Diagnostics Count: {wl_res.get('count')}")
    assert wl_res.get("status") == "success", "Expected watchlist matrix status success"
    if wl_res.get("data"):
        first_item = wl_res["data"][0]
        print("Watchlist Item Keys:", list(first_item.keys()))
        assert "cup_qualified" in first_item, "Missing cup_qualified in watchlist diagnostic item!"
        assert "cup_status" in first_item, "Missing cup_status in watchlist diagnostic item!"
        print(f"DIXON Watchlist Matrix Record: cup_qualified={first_item['cup_qualified']}, qual_count={first_item['qual_count']}")
    
    print("[OK] Backend API 9-screener diagnostic integration test PASSED!")

if __name__ == "__main__":
    test_detector_synthetic()
    asyncio.run(test_backend_endpoints())
