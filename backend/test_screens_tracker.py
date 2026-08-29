import unittest
import os
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Set database directory environment variable to test database path
os.environ["DATABASE_DIR"] = os.path.join(os.path.dirname(__file__), "test_data")

from backend.main import app
from backend.screens_scraper import scrape_saved_screens, scrape_screen_results

class TestScreensTrackerAPI(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @patch("backend.screens_scraper.make_screener_request")
    def test_scrape_saved_screens_mock(self, mock_get):
        """Verify parsing of custom saved screens list from Screener.in explore dashboard."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = """
        <html>
            <body>
                <div class="card">
                    <h2>Your screens</h2>
                    <a class="screen-item" href="/screens/10123/high-growth-tech/">
                        <div class="font-weight-500">High Growth Tech</div>
                    </a>
                    <a class="screen-item" href="/screens/20456/consistent-roce/">
                        <div class="font-weight-500">Consistent Roce</div>
                    </a>
                </div>
            </body>
        </html>
        """
        mock_get.return_value = mock_response

        screens = scrape_saved_screens("dummy_cookie")
        self.assertEqual(len(screens), 2)
        self.assertEqual(screens[0]["id"], "/screens/10123/high-growth-tech/")
        self.assertEqual(screens[0]["name"], "High Growth Tech")
        self.assertEqual(screens[1]["id"], "/screens/20456/consistent-roce/")
        self.assertEqual(screens[1]["name"], "Consistent Roce")

    @patch("backend.screens_scraper.make_screener_request")
    def test_scrape_screen_results_mock(self, mock_get):
        """Verify parsing of stocks result table from custom saved screen page."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = """
        <html>
            <body>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>S.No.</th>
                            <th>Name</th>
                            <th>Current Price</th>
                            <th>P/E</th>
                            <th>Market Capitalization</th>
                            <th>ROCE</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>1</td>
                            <td><a href="/company/TCS/consolidated/">Tata Consultancy Services Ltd</a></td>
                            <td>3,850.50</td>
                            <td>28.5</td>
                            <td>1400000.0</td>
                            <td>42.5</td>
                        </tr>
                        <tr>
                            <td>2</td>
                            <td><a href="/company/INFY/">Infosys Ltd</a></td>
                            <td>1,520.00</td>
                            <td>24.2</td>
                            <td>630000.0</td>
                            <td>31.8</td>
                        </tr>
                    </tbody>
                </table>
            </body>
        </html>
        """
        mock_get.return_value = mock_response

        data = scrape_screen_results("/screens/10123/high-growth-tech/", "dummy_cookie")
        self.assertIn("companies", data)
        companies = data["companies"]
        self.assertEqual(len(companies), 2)
        
        self.assertEqual(companies[0]["symbol"], "TCS")
        self.assertEqual(companies[0]["name"], "Tata Consultancy Services Ltd")
        self.assertEqual(companies[0]["price"], 3850.5)
        self.assertEqual(companies[0]["pe"], 28.5)
        self.assertEqual(companies[0]["market_cap"], 1400000.0)
        self.assertEqual(companies[0]["roce"], 42.5)

        self.assertEqual(companies[1]["symbol"], "INFY")
        self.assertEqual(companies[1]["name"], "Infosys Ltd")
        self.assertEqual(companies[1]["price"], 1520.0)

    @patch("backend.screens_scraper.make_screener_request")
    def test_api_screener_screens_endpoint(self, mock_get):
        """Test the GET /api/screener-external/screens endpoint behavior when cookie is mock loaded."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = """
        <html>
            <body>
                <div class="card">
                    <h2>Your screens</h2>
                    <a href="/screens/10123/high-growth-tech/"><div class="font-weight-500">High Growth Tech</div></a>
                </div>
            </body>
        </html>
        """
        mock_get.return_value = mock_response

        with patch("backend.main.get_db") as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = {"value": "dummy_cookie"}
            
            response = self.client.get("/api/screener-external/screens")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn("screens", data)
            self.assertTrue(len(data["screens"]) > 0)
            self.assertEqual(data["screens"][0]["id"], "/screens/10123/high-growth-tech/")

    @patch("backend.screens_scraper.make_screener_request")
    def test_api_screener_screens_preview_endpoint(self, mock_get):
        """Test the GET /api/screener-external/screens/{id}/preview endpoint."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = """
        <html>
            <body>
                <table class="data-table">
                    <thead>
                        <tr><th>Name</th><th>CMP</th></tr>
                    </thead>
                    <tbody>
                        <tr><td><a href="/company/TCS/">TCS</a></td><td>3800</td></tr>
                    </tbody>
                </table>
            </body>
        </html>
        """
        mock_get.return_value = mock_response

        with patch("backend.main.get_db") as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = {"value": "dummy_cookie"}
            
            # Using path param containing slashes
            response = self.client.get("/api/screener-external/screens/screens/10123/high-growth-tech/preview")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn("companies", data)
            self.assertTrue(len(data["companies"]) > 0)
            self.assertEqual(data["companies"][0]["symbol"], "TCS")
