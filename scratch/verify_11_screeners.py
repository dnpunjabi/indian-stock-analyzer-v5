import sys
import os
import pandas as pd
import numpy as np
import asyncio

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

def test_detectors():
    print("==================================================")
    print("1. Testing detector algorithms in swing_utils.py")
    print("==================================================")
    from backend.swing_utils import detect_rs_line_new_high, detect_undercut_and_rally

    # Generate synthetic price data (260 trading days)
    dates = pd.date_range(end=pd.Timestamp.today(), periods=260, freq="B")
    
    # Nifty index trending steadily
    nifty_close = np.linspace(20000, 24000, 260)
    nifty_df = pd.DataFrame({"Close": nifty_close}, index=dates)

    # Stock outperforms Nifty towards recent days (RS New High)
    stock_close = np.linspace(100, 200, 260)
    stock_close[-10:] = np.linspace(200, 300, 10) # Surge at the end -> RS peak
    stock_high = stock_close * 1.02
    stock_low = stock_close * 0.98
    stock_vol = np.full(260, 100000)

    stock_df = pd.DataFrame({
        "Open": stock_close * 0.99,
        "High": stock_high,
        "Low": stock_low,
        "Close": stock_close,
        "Volume": stock_vol
    }, index=dates)

    rs_res = detect_rs_line_new_high(stock_df, nifty_df=nifty_df)
    print("RS Line New High Result:")
    print("  is_rs_new_high:", rs_res.get("is_rs_new_high"))
    print("  rsnh_status:", rs_res.get("rsnh_status"))
    print("  rs_ratio_current:", rs_res.get("rs_ratio_current"))
    print("  rs_ratio_max_252d:", rs_res.get("rs_ratio_max_252d"))
    print("  reason:", rs_res.get("reason"))
    assert rs_res.get("is_rs_new_high") == True, "RS Line New High detection failed!"

    # Test Undercut & Rally
    # Create a base with a prior swing low at day -25, a brief shakeout 1% below it 2 days ago, reclaimed today on 2.0x volume
    ur_close = np.full(260, 500.0)
    ur_high = ur_close * 1.01
    ur_low = ur_close * 0.99
    ur_vol = np.full(260, 100000.0)

    # Prior swing low at index -25 (e.g. ₹480)
    ur_low[-30:-10] = 480.0
    ur_close[-30:-10] = 485.0
    
    # Shakeout at index -2 (dips 1.5% below 480 to 472.8, then reclaims)
    ur_low[-2] = 472.8
    ur_close[-2] = 482.0
    ur_vol[-2] = 250000.0 # 2.5x volume surge

    # Current day
    ur_close[-1] = 490.0
    ur_high[-1] = 492.0
    ur_low[-1] = 485.0
    ur_vol[-1] = 200000.0

    ur_df = pd.DataFrame({
        "Open": ur_close * 0.99,
        "High": ur_high,
        "Low": ur_low,
        "Close": ur_close,
        "Volume": ur_vol
    }, index=dates)

    ur_res = detect_undercut_and_rally(ur_df)
    print("\nUndercut & Rally Result:")
    print("  is_undercut_and_rally:", ur_res.get("is_undercut_and_rally"))
    print("  ur_status:", ur_res.get("ur_status"))
    print("  prior_swing_low:", ur_res.get("prior_swing_low"))
    print("  shakeout_low:", ur_res.get("shakeout_low"))
    print("  stop_loss:", ur_res.get("stop_loss"))
    print("  risk_pct:", ur_res.get("risk_pct"))
    print("  reclaim_vol_ratio:", ur_res.get("reclaim_vol_ratio"))
    print("  reason:", ur_res.get("reason"))
    assert ur_res.get("is_undercut_and_rally") == True, "Undercut & Rally detection failed!"

    print("\n✅ All detector algorithm assertions passed successfully!")

if __name__ == "__main__":
    test_detectors()
