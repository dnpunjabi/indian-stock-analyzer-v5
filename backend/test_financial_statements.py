import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import json

from backend.main import app, get_db

class TestFinancialStatements(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("backend.financial_statements_scraper.make_screener_request")
    def test_scrape_financial_statements_success(self, mock_get):
        # Mock search API response
        mock_search_res = MagicMock()
        mock_search_res.status_code = 200
        mock_search_res.json.return_value = [{"url": "/company/TCS/", "name": "Tata Consultancy Services Limited"}]
        
        # Mock main page response
        mock_page_res = MagicMock()
        mock_page_res.status_code = 200
        mock_page_res.history = []
        mock_page_res.text = """
        <html>
            <body>
                <section id="quarters">
                    <p>Consolidated Figures in Rs. Crores</p>
                    <table>
                        <thead>
                            <tr>
                                <th></th>
                                <th>Jun 2023</th>
                                <th>Sep 2023</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td>Sales +</td>
                                <td>50,000</td>
                                <td>52,000</td>
                            </tr>
                            <tr>
                                <td>Expenses +</td>
                                <td>40,000</td>
                                <td>41,000</td>
                            </tr>
                        </tbody>
                    </table>
                </section>
                <section id="profit-loss">
                    <table>
                        <thead>
                            <tr>
                                <th></th>
                                <th>Mar 2022</th>
                                <th>Mar 2023</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td>Net Profit</td>
                                <td>38,000</td>
                                <td>42,000</td>
                            </tr>
                        </tbody>
                    </table>
                </section>
                <section id="balance-sheet">
                    <table>
                        <thead>
                            <tr>
                                <th></th>
                                <th>Mar 2022</th>
                                <th>Mar 2023</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td>Reserves</td>
                                <td>80,000</td>
                                <td>95,000</td>
                            </tr>
                        </tbody>
                    </table>
                </section>
                <div data-company-id="123"></div>
                <section id="peers">
                    <!-- peers section is loaded dynamically, so it's empty in main HTML -->
                </section>
            </body>
        </html>
        """
        
        # Mock peers API response
        mock_peers_res = MagicMock()
        mock_peers_res.status_code = 200
        mock_peers_res.text = """
        <table>
            <thead>
                <tr>
                    <th>S.No.</th>
                    <th>Name</th>
                    <th>P/E</th>
                    <th>ROCE %</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>1.</td>
                    <td>TCS Ltd</td>
                    <td>28.5</td>
                    <td>45.2</td>
                </tr>
                <tr>
                    <td>2.</td>
                    <td>Infosys</td>
                    <td>24.3</td>
                    <td>38.1</td>
                </tr>
            </tbody>
        </table>
        """
        
        # Configure requests.get calls
        # 1. Search api suggest query
        # 2. Main details page fetch
        # 3. Peers API page fetch
        mock_get.side_effect = [mock_search_res, mock_page_res, mock_peers_res]
        
        from backend.financial_statements_scraper import scrape_financial_statements
        data = scrape_financial_statements("TCS", "consolidated")
        
        self.assertNotIn("error", data)
        self.assertEqual(data["symbol"], "TCS")
        self.assertTrue(data["is_consolidated"])
        self.assertEqual(data["quarters"]["headers"], ["", "Jun 2023", "Sep 2023"])
        self.assertEqual(data["quarters"]["rows"][0]["label"], "Sales")
        self.assertEqual(data["quarters"]["rows"][0]["values"], [50000, 52000])
        
        self.assertIn("peers", data)
        self.assertEqual(data["peers"]["headers"], ["Name", "P/E", "ROCE %"])
        self.assertEqual(data["peers"]["rows"][0]["label"], "TCS Ltd")
        self.assertEqual(data["peers"]["rows"][0]["values"], [28.5, 45.2])

    @patch("backend.financial_statements_scraper.scrape_financial_statements")
    def test_api_financial_statements_cached(self, mock_scrape):
        # Prepare cache DB connection
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT OR REPLACE INTO cached_financial_statements (symbol, view, data_json, last_updated) VALUES (?, ?, ?, datetime('now'))",
                ("INFY", "consolidated", json.dumps({"symbol": "INFY", "is_consolidated": True, "quarters": {"headers": ["", "Dec 2023"], "rows": []}, "cash_flow": {"headers": ["", "Dec 2023"], "rows": []}}))
            )
            conn.commit()
            
        res = self.client.get("/api/stocks/INFY/financial-statements?view=consolidated")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["symbol"], "INFY")
        
        # Ensure scraper is not called because it was resolved from cache
        mock_scrape.assert_not_called()

    @patch("backend.financial_statements_scraper.scrape_financial_statements")
    def test_api_financial_statements_force_refresh(self, mock_scrape):
        mock_scrape.return_value = {
            "symbol": "INFY",
            "is_consolidated": True,
            "quarters": {"headers": ["", "Mar 2024"], "rows": []},
            "cash_flow": {"headers": ["", "Mar 2024"], "rows": []}
        }
        # Prepare cache DB connection
        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT OR REPLACE INTO cached_financial_statements (symbol, view, data_json, last_updated) VALUES (?, ?, ?, datetime('now', '-1 day'))",
                ("INFY", "consolidated", json.dumps({"symbol": "INFY", "is_consolidated": True, "quarters": {"headers": ["", "Dec 2023"], "rows": []}, "cash_flow": {"headers": ["", "Dec 2023"], "rows": []}}))
            )
            conn.commit()
            
        res = self.client.get("/api/stocks/INFY/financial-statements?view=consolidated&force_refresh=true")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["symbol"], "INFY")
        
        # Ensure scraper is called despite the cached entry because force_refresh=true
        mock_scrape.assert_called_once()
        self.assertEqual(mock_scrape.call_args[0][0], "INFY")
        self.assertEqual(mock_scrape.call_args[0][1], "consolidated")

    @patch("backend.llm_config.call_llm_stream")
    def test_api_audit_financials(self, mock_call_llm_stream):
        mock_call_llm_stream.return_value = ["### Key Revenue/Profitability Trends\n* TCS is showing 4% growth."]
        
        payload = {
            "symbol": "TCS",
            "view": "consolidated",
            "statement_type": "quarters",
            "table_data": {
                "headers": ["", "Jun 2023", "Sep 2023"],
                "rows": [
                    {"label": "Sales", "values": [50000, 52000]}
                ]
            }
        }
        
        res = self.client.post("/api/ai/audit-financials", json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text, "### Key Revenue/Profitability Trends\n* TCS is showing 4% growth.")
        mock_call_llm_stream.assert_called_once()

    @patch("backend.main.run_fs_evaluation_internal")
    def test_api_fs_evaluation_success(self, mock_eval):
        mock_eval.return_value = {
            "status": "Warning",
            "scores": {"piotroski_f_score": 6, "altman_z_score": 2.1},
            "alerts": [{"metric": "OPM Trend", "condition": "decreasing", "threshold": 0, "value": -2.5, "severity": "Warning"}],
            "statements": {"symbol": "TCS"}
        }
        res = self.client.get("/api/stocks/TCS/fs-evaluation")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "Warning")
        self.assertEqual(data["scores"]["piotroski_f_score"], 6)
        self.assertEqual(data["alerts"][0]["metric"], "OPM Trend")

if __name__ == "__main__":
    unittest.main()
