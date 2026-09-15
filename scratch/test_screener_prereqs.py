import sys
import os
import pandas as pd
import numpy as np

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.swing_utils import detect_pocket_pivot, detect_undercut_and_rally

def test_pocket_pivot():
    print("--- 1. Testing Pocket Pivot Detector ---")
    dates = pd.date_range(start="2025-01-01", periods=260, freq="B")
    
    # 260 days uptrend
    prices = np.linspace(100, 200, 260)
    volumes = np.random.uniform(100000, 200000, 260)
    
    # Ensure down days in past 10 days have max volume 220,000
    for i in range(-11, -1):
        if prices[i] < prices[i-1]:
            volumes[i] = 200000
            
    # Bar -1 is Pocket Pivot: Up 2.5%, Volume 450,000 (> 220,000)
    prices[-1] = prices[-2] * 1.025
    volumes[-1] = 450000
    
    df = pd.DataFrame({
        "Open": prices * 0.99,
        "High": prices * 1.01,
        "Low": prices * 0.985,
        "Close": prices,
        "Volume": volumes
    }, index=dates)
    
    # Test with valid RS score
    res = detect_pocket_pivot(df, rs_score=82.0)
    print("Pocket Pivot (RS=82):", res.get("is_pocket_pivot"), "| Status:", res.get("pocket_status"), "| 30W Slope:", res.get("slope_30wk_pct"), "%")
    
    # Test with low RS score
    res_low_rs = detect_pocket_pivot(df, rs_score=40.0)
    print("Pocket Pivot (RS=40):", res_low_rs.get("is_pocket_pivot"), "| Rejection:", res_low_rs.get("rejection_reason"))

def test_undercut_rally():
    print("\n--- 2. Testing Undercut & Rally Detector ---")
    dates = pd.date_range(start="2025-01-01", periods=260, freq="B")
    
    # Stock in Stage 2 uptrend from 100 to 200
    prices = np.linspace(100, 200, 260)
    # Form a clear swing low at bar -20 (price 185.0)
    # Flanked by higher prices (190.0)
    prices[-35:-25] = 192.0
    prices[-25:-15] = 185.0 # swing low around 185.0
    prices[-15:-3] = 190.0 # rally back to 190
    prices[-2] = 183.0 # undercut low to 183.0 (1.08% undercut of 185.0)
    prices[-1] = 187.0 # reclaim close back above 185.0
    
    lows = prices * 0.995
    lows[-25:-15] = 185.0 # swing low level
    lows[-2] = 182.8 # shakeout low (1.19% undercut)
    highs = prices * 1.015
    
    volumes = np.ones(260) * 100000
    volumes[-1] = 260000 # 2.6x volume reclaim
    
    df = pd.DataFrame({
        "Open": prices * 0.99,
        "High": highs,
        "Low": lows,
        "Close": prices,
        "Volume": volumes
    }, index=dates)
    
    res = detect_undercut_and_rally(df, rs_score=78.0)
    print("U&R (RS=78):", res.get("is_undercut_and_rally"), "| Status:", res.get("ur_status"), "| Prior Low:", res.get("prior_swing_low"), "| Shakeout Low:", res.get("shakeout_low"))
    print("Reason:", res.get("reason"))

if __name__ == "__main__":
    test_pocket_pivot()
    test_undercut_rally()
