import unittest
import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.getcwd()))
sys.path.insert(0, os.getcwd())

from swing_utils import detect_vcp_pattern, calculate_canslim_score

class TestVcpCanslim(unittest.TestCase):

    def test_detect_vcp_pattern_synthetic(self):
        """Tests VCP contraction identification on a synthetic contracting OHLCV series."""
        n = 100
        dates = pd.date_range(end='2026-09-04', periods=n, freq='D')
        
        # Build synthetic VCP price series (T1: -18%, T2: -8%, T3: -2.5%)
        np.random.seed(42)
        close_prices = np.zeros(n)
        
        # Base wave H0 to L1
        for i in range(0, 30):
            close_prices[i] = 1000.0 - (i * 5.0) # 1000 down to 850 (-15%)
        # Wave L1 to H1
        for i in range(30, 55):
            close_prices[i] = 850.0 + ((i - 30) * 5.5) # 850 up to 987
        # Wave H1 to L2
        for i in range(55, 75):
            close_prices[i] = 987.0 - ((i - 55) * 3.5) # 987 down to 917 (-7%)
        # Wave L2 to H2
        for i in range(75, 90):
            close_prices[i] = 917.0 + ((i - 75) * 4.4) # 917 up to 983
        # Tight Wave H2 to L3
        for i in range(90, 100):
            close_prices[i] = 983.0 - ((i - 90) * 1.5) # 983 down to 968 (-1.5%)
            
        high_prices = close_prices * 1.01
        low_prices = close_prices * 0.99
        volumes = np.random.randint(100000, 500000, size=n)
        volumes[-5:] = 30000 # Volume dry up on last 5 days
        
        df = pd.DataFrame({
            "Open": close_prices,
            "High": high_prices,
            "Low": low_prices,
            "Close": close_prices,
            "Volume": volumes
        }, index=dates)
        
        res = detect_vcp_pattern(df)
        self.assertTrue(res["is_vcp"])
        self.assertIn(res["vcp_status"], ["READY_PIVOT", "FORMING", "LIVE_BREAKOUT"])
        self.assertGreater(res["pivot_price"], 900.0)
        self.assertLess(res["stop_loss"], res["pivot_price"])
        self.assertGreater(res["target_1"], res["pivot_price"])

    def test_calculate_canslim_score(self):
        """Tests 7-letter CANSLIM score output structure."""
        res = calculate_canslim_score("TRENT")
        self.assertIn("canslim_score", res)
        self.assertIn("grade", res)
        self.assertIn("factors", res)
        self.assertIn("C", res["factors"])
        self.assertIn("A", res["factors"])
        self.assertIn("N", res["factors"])
        self.assertIn("S", res["factors"])
        self.assertIn("L", res["factors"])
        self.assertIn("I", res["factors"])
        self.assertIn("M", res["factors"])

if __name__ == '__main__':
    unittest.main()
