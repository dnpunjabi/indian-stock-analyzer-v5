import unittest
import os
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Set database directory environment variable to test database
os.environ["DATABASE_DIR"] = os.path.join(os.path.dirname(__file__), "test_data")

from backend.main import app

class TestPitchbookAPIRoutes(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @patch("backend.main.calculate_dcf_valuation")
    @patch("backend.main.call_llm")
    @patch("backend.main.get_complete_financial_profile")
    @patch("requests.get")
    def test_get_pitchbook_endpoint(self, mock_requests_get, mock_get_profile, mock_call_groq, mock_calc_dcf):
        """Verifies institutional pitchbook data compilation and Groq LLM parsing."""
        mock_calc_dcf.return_value = {
            "wacc": 9.5,
            "revenue_growth": 12.0,
            "opm": 18.0,
            "terminal_growth": 4.5,
            "intrinsic_value": 2800.0,
            "margin_of_safety": 14.3
        }
        # 1. Mock Complete Financial Profile return dictionary
        mock_get_profile.return_value = {
            "symbol": "RELIANCE",
            "ticker": "RELIANCE.NS",
            "company_name": "Reliance Industries Limited",
            "sector": "Energy",
            "industry": "Oil & Gas",
            "fundamentals": {
                "pe_ratio": 22.5,
                "pb_ratio": 2.1,
                "ev_to_ebitda": 15.2,
                "debt_to_equity": 0.4,
                "pricing_power_proxy": "Medium",
                "current_price": 2450.0,
                "market_cap_cr": 15000.0,
                "roce_pct": 12.5,
                "roe_pct": 11.8
            },
            "technicals": {
                "rsi": 54.2,
                "volume_vs_avg20": 1.15,
                "sma_50": 2400.0,
                "sma_200": 2300.0
            },
            "governance": {
                "promoter_pledged_pct": 0.0,
                "auditor_qualifications": "None"
            },
            "dcf_model": {
                "wacc": 11.5,
                "revenue_growth": 10.0,
                "opm": 15.0,
                "terminal_growth": 4.5,
                "intrinsic_value": 2600.0,
                "margin_of_safety": 6.1
            },
            "peers": [
                {"symbol": "TCS.NS", "pe_ratio": 28.0, "debt_to_equity": 0.1, "current_price": 3800.0}
            ]
        }

        # 2. Mock requests.get for yfinance news
        mock_news_response = MagicMock()
        mock_news_response.status_code = 200
        mock_news_response.json.return_value = {
            "news": [
                {"title": "Reliance expanding retail network", "publisher": "Bloomberg", "link": "http://example.com"}
            ]
        }
        mock_requests_get.return_value = mock_news_response

        # 3. Mock Groq LLM return structure
        mock_call_groq.return_value = (
            "# INSTITUTIONAL MEMO\n"
            "## Investment Summary\n"
            "Reliance is a strong hold candidate with stable earnings.\n\n"
            "## Peer Multiples Comparison\n"
            "| Ticker | P/E | D/E |\n"
            "| --- | --- | --- |\n"
            "| RELIANCE.NS | 22.50 | 0.40 |\n"
            "| TCS.NS | 28.00 | 0.10 |"
        )

        # Call endpoint
        response = self.client.get(
            "/api/analyze/pitchbook?symbol=RELIANCE.NS&horizon=Long-term%20(3%2B%20years)&risk=Moderate&wacc=9.5&growth=12.0&opm=18.0&terminal_growth=4.5"
        )
        if response.status_code != 200:
            print("RESPONSE ERROR BODY:", response.text)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertEqual(data["symbol"], "RELIANCE.NS")
        self.assertIn("markdown", data)
        self.assertIn("# INSTITUTIONAL MEMO", data["markdown"])
        self.assertIn("Peer Multiples Comparison", data["markdown"])
        
        # Verify Groq LLM was called with the correct custom DCF parameters
        called_args, called_kwargs = mock_call_groq.call_args
        prompt_text = " ".join(called_args)
        self.assertIn("Applied WACC: 9.5%", prompt_text)

if __name__ == "__main__":
    unittest.main()
