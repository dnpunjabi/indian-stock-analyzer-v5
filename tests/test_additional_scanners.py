import unittest
import pandas as pd
import numpy as np
from backend.swing_utils import detect_weinstein_stage2, detect_high_tight_flag, detect_3weeks_tight

class TestAdditionalScanners(unittest.TestCase):
    def setUp(self):
        # Create synthetic OHLCV dataframe for testing
        np.random.seed(42)
        dates = pd.date_range("2026-01-01", periods=100)
        base_price = 100.0 + np.cumsum(np.random.normal(0.5, 1.0, 100))
        
        self.df = pd.DataFrame({
            "Open": base_price * 0.99,
            "High": base_price * 1.02,
            "Low": base_price * 0.98,
            "Close": base_price,
            "Volume": np.random.randint(100000, 500000, 100)
        }, index=dates)

    def test_detect_weinstein_stage2(self):
        res = detect_weinstein_stage2(self.df)
        self.assertIn("is_stage2", res)
        self.assertIn("stage_status", res)
        self.assertIn("ma30_slope_pct", res)
        self.assertIn("breakout_vol_ratio", res)

    def test_detect_high_tight_flag(self):
        res = detect_high_tight_flag(self.df)
        self.assertIn("is_htf", res)
        self.assertIn("htf_status", res)
        self.assertIn("pole_gain_pct", res)
        self.assertIn("flag_depth_pct", res)

    def test_detect_3weeks_tight(self):
        res = detect_3weeks_tight(self.df)
        self.assertIn("is_3wt", res)
        self.assertIn("tight_status", res)
        self.assertIn("close_variance_pct", res)
        self.assertIn("weekly_closes", res)

if __name__ == "__main__":
    unittest.main()
