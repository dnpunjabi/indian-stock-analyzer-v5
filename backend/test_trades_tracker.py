import unittest
import os
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Set database directory environment variable to test database path
os.environ["DATABASE_DIR"] = os.path.join(os.path.dirname(__file__), "test_data")

from backend.main import app
from backend.trades_scraper import scrape_trades

class TestTradesTrackerAPI(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @patch("backend.trades_scraper.make_screener_request")
    def test_scrape_trades_mock(self, mock_get):
        """Verify stock-specific bulk, block, SAST, and insider trades scraping."""
        # 1. Mock responses: search query Suggest suggest API and the trades company details page
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = [{"id": "123", "name": "Infosys Ltd", "url": "/company/INFY/"}]
        
        trades_response = MagicMock()
        trades_response.status_code = 200
        
        # Simple mock HTML with tables for insider-trades, bulk-deals, block-deals, and sast-trades
        mock_html = """
        <html>
            <body>
                <!-- Company ID tag -->
                <div data-company-id="123"></div>
                
                <!-- Insider Trades Table -->
                <div id="trades-insider-trades">
                    <table>
                        <tbody>
                            <tr>
                                <td colspan="4">01 Jul 2026</td>
                            </tr>
                            <tr>
                                <td>INFOSYS LTD<br><span class="text-muted">Promoter Group</span></td>
                                <td>10,000</td>
                                <td>1,500.00</td>
                                <td>150.00</td>
                            </tr>
                        </tbody>
                    </table>
                </div>

                <!-- Bulk Deals Table -->
                <div id="trades-bulk-deals">
                    <table>
                        <tbody>
                            <tr>
                                <td colspan="4">30 Jun 2026</td>
                            </tr>
                            <tr>
                                <td>TATA SONS PVT LTD</td>
                                <td>BUY</td>
                                <td>50,000</td>
                                <td>3,800.00</td>
                            </tr>
                        </tbody>
                    </table>
                </div>

                <!-- SAST Trades Table -->
                <div id="trades-sast-trades">
                    <table>
                        <tbody>
                            <tr>
                                <td colspan="5">29 Jun 2026</td>
                            </tr>
                            <tr>
                                <td>Nandan M Nilekani</td>
                                <td>ACQ</td>
                                <td>Market</td>
                                <td>25,000</td>
                                <td>0.01%</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </body>
        </html>
        """
        trades_response.text = mock_html
        
        # mock_get needs to handle multiple calls (suggest search Suggest API and the actual trades page fetch)
        mock_get.side_effect = [search_response, trades_response]

        # Test scraper method
        result = scrape_trades("INFY", session_cookie="dummy_cookie")
        
        self.assertIn("insider_trades", result)
        self.assertIn("bulk_deals", result)
        self.assertIn("block_deals", result)
        self.assertIn("sast_deals", result)
        
        # Validate insider trades extraction
        insider = result["insider_trades"]
        self.assertTrue(len(insider) > 0)
        self.assertEqual(insider[0]["person"], "INFOSYS LTD")
        self.assertEqual(insider[0]["relation"], "Promoter Group")
        self.assertEqual(insider[0]["type"], "Buy")
        self.assertEqual(insider[0]["quantity"], 10000)
        self.assertEqual(insider[0]["value"], 15000000) # 150.00 lacs = 1.5 Cr = 15,000,000

        # Validate bulk deals extraction
        bulk = result["bulk_deals"]
        self.assertTrue(len(bulk) > 0)
        self.assertEqual(bulk[0]["person"], "TATA SONS PVT LTD")
        self.assertEqual(bulk[0]["type"], "Buy")
        self.assertEqual(bulk[0]["quantity"], 50000)
        self.assertEqual(bulk[0]["price"], 3800.0)
        self.assertEqual(bulk[0]["value"], 190000000)

        # Validate SAST extraction
        sast = result["sast_deals"]
        self.assertTrue(len(sast) > 0)
        self.assertEqual(sast[0]["person"], "Nandan M Nilekani")
        self.assertEqual(sast[0]["type"], "Buy")
        self.assertEqual(sast[0]["quantity"], 25000)
        self.assertEqual(sast[0]["relation"], "Market - 0.01%")

    def test_global_scanner_endpoint(self):
        """Test API scanner route returns expected list structure."""
        from backend.main import get_db
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT OR REPLACE INTO cached_trades (symbol, data_json, last_updated) VALUES (?, ?, ?)",
                (
                    "INFY",
                    json.dumps({
                        "insider_trades": [{"symbol": "INFY", "person": "Nilekani", "type": "Buy", "value": 100000, "date": "2026-07-01"}],
                        "bulk_deals": [],
                        "block_deals": [],
                        "sast_deals": []
                    }),
                    "2026-07-01 10:00:00"
                )
            )
            conn.commit()

        response = self.client.get("/api/trades/global-scanner")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)

    @patch("backend.trades_scraper.make_screener_request")
    def test_stock_specific_endpoint(self, mock_get):
        """Test stock-specific trades details endpoint."""
        # Clear cache for INFY to force scraping/mock path
        from backend.main import get_db
        with get_db() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM cached_trades WHERE symbol = ?", ("INFY",))
            conn.commit()

        # Mock suggest endpoint then trade page
        search_res = MagicMock()
        search_res.status_code = 200
        search_res.json.return_value = [{"id": "123", "name": "Infosys Ltd"}]
        
        trades_res = MagicMock()
        trades_res.status_code = 200
        trades_res.text = """
        <html>
            <body>
                <div id="trades-insider-trades">
                    <table>
                        <tbody>
                            <tr>
                                <td colspan="4">29 Jun 2026</td>
                            </tr>
                            <tr>
                                <td>N R Narayana Murthy<br><span class="text-muted">Promoter (Buy)</span></td>
                                <td>5,000</td>
                                <td>1,500.00</td>
                                <td>75.00</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </body>
        </html>
        """
        mock_get.side_effect = [search_res, trades_res]

        with patch("backend.main.get_db") as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = {"value": "dummy_cookie"}

            response = self.client.get("/api/stocks/INFY/trades")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn("insider_trades", data)
            self.assertTrue(len(data["insider_trades"]) > 0)
            self.assertEqual(data["insider_trades"][0]["person"], "N R Narayana Murthy")
            self.assertEqual(data["insider_trades"][0]["value"], 7500000)
