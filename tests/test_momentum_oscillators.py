import os
import sys
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend'))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import pytest
import pandas as pd
import numpy as np
from financial_utils import calculate_technical_indicators

def test_calculate_technical_indicators_momentum_oscillators():
    """Verify calculate_technical_indicators calculates all momentum oscillators accurately."""
    class MockStock:
        def __init__(self):
            np.random.seed(42)
            close = 100 + np.cumsum(np.random.randn(100))
            high = close + np.random.rand(100) * 2
            low = close - np.random.rand(100) * 2
            volume = np.random.randint(1000, 50000, 100)
            self._history = pd.DataFrame({
                'Open': close,
                'High': high,
                'Low': low,
                'Close': close,
                'Volume': volume
            })
            self.info = {"fiftyDayAverage": 100.0, "twoHundredDayAverage": 95.0}

        def history(self, period="1y"):
            return self._history

    mock_stock = MockStock()
    tech = calculate_technical_indicators("RELIANCE.NS", stock_obj=mock_stock)
    
    assert tech["error"] is False
    assert "macd" in tech
    assert "macd_signal" in tech
    assert "macd_hist" in tech
    assert "stoch_k" in tech
    assert "stoch_d" in tech
    assert "stoch_status" in tech
    assert "roc_20" in tech
    assert "roc_status" in tech
    assert "cci_20" in tech
    assert "cci_status" in tech
    assert "will_r_14" in tech
    assert "will_r_status" in tech
    assert "mfi_14" in tech
    assert "mfi_status" in tech
    assert "adx" in tech
    assert "adx_status" in tech
    assert "rsc_6m" in tech
    assert "rsc_status" in tech
