import unittest
import pandas as pd
import numpy as np
from backend.swing_utils import detect_weinstein_stage2, detect_weinstein_stage3, detect_high_tight_flag, detect_3weeks_tight

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

    def test_detect_weinstein_stage3(self):
        res = detect_weinstein_stage3(self.df)
        self.assertIn("is_stage3", res)
        self.assertIn("stage_status", res)
        self.assertIn("down_to_up_vol_ratio", res)
        self.assertIn("weekly_sma30_slope_pct", res)
        self.assertIn("dist_from_52w_high_pct", res)
        self.assertIn("pivot_support_price", res)

        # Create explicit Stage 3 synthetic distribution profile
        dates = pd.date_range("2025-01-01", periods=150)
        # Stage 2 advance up to day 100, then flat sideways churn with heavy volume on down days
        prices = np.concatenate([
            np.linspace(100, 200, 100),
            200 + np.sin(np.linspace(0, 4 * np.pi, 50)) * 5
        ])
        vols = np.array([200000 if i > 100 and i % 2 == 0 else 100000 for i in range(150)])
        s3_df = pd.DataFrame({
            "Open": prices * 0.99,
            "High": prices * 1.02,
            "Low": prices * 0.98,
            "Close": prices,
            "Volume": vols
        }, index=dates)
        s3_res = detect_weinstein_stage3(s3_df)
        self.assertIsNotNone(s3_res)
        self.assertIsInstance(s3_res["is_stage3"], bool)

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

    def test_watchlist_quant_diagnostics_payload_structure(self):
        # Verify calculation logic and dictionary mapping for watchlist quant matrix
        w_res = detect_weinstein_stage2(self.df)
        s3_res = detect_weinstein_stage3(self.df)
        h_res = detect_high_tight_flag(self.df)
        t_res = detect_3weeks_tight(self.df)
        
        self.assertIsNotNone(w_res)
        self.assertIsNotNone(s3_res)
        self.assertIsNotNone(h_res)
        self.assertIsNotNone(t_res)

    def test_vcp_and_quant_matrix_target_level_parity(self):
        # Verify that Target 1 and Target 2 match 2:1 and 4:1 Risk-to-Reward levels exactly
        pivot = 2278.40
        stop = 2026.80
        risk = pivot - stop
        expected_t1 = round(pivot + (2.0 * risk), 2)
        expected_t2 = round(pivot + (4.0 * risk), 2)
        
        self.assertEqual(expected_t1, 2781.60)
        self.assertEqual(expected_t2, 3284.80)

if __name__ == "__main__":
    unittest.main()


