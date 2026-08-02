import unittest
import os
import json
import sqlite3
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

# Set database directory environment variable to a test database directory before importing main
os.environ["DATABASE_DIR"] = os.path.join(os.path.dirname(__file__), "test_data")
import backend.main as main
from backend.main import app, get_db
from backend.financial_utils import resolve_company_ticker, calculate_dcf_valuation

class TestFinancialModels(unittest.TestCase):
    
    def test_ticker_resolution(self):
        """Verifies name to ticker mappings."""
        res1 = resolve_company_ticker("Reliance Industries")
        self.assertEqual(res1["yf_ticker"], "RELIANCE.NS")
        self.assertEqual(res1["base_symbol"], "RELIANCE")
        
        res2 = resolve_company_ticker("TCS")
        self.assertEqual(res2["yf_ticker"], "TCS.NS")
        
        res3 = resolve_company_ticker("Tata Motors")
        self.assertEqual(res3["yf_ticker"], "TATAMOTORS.NS")
        
    def test_dcf_math(self):
        """Verifies multi-stage DCF and margin of safety calculations."""
        dcf = calculate_dcf_valuation(
            "RELIANCE.NS",
            rev_growth_5y=12.0,
            target_opm=25.0,
            wacc=10.5,
            terminal_growth=4.5
        )
        
        self.assertGreater(dcf["intrinsic_value"], 0.0)
        self.assertGreater(dcf["current_price"], 0.0)
        self.assertIn("valuation_rating", dcf)
        self.assertTrue(len(dcf["cash_flow_projections"]) == 10)
        
        # Verify years 1-10 projections are positive and sequenced
        for idx, item in enumerate(dcf["cash_flow_projections"]):
            self.assertEqual(item["year"], idx + 1)
            self.assertGreater(item["fcf"], 0.0)
            self.assertGreater(item["discount_factor"], 0.0)
            self.assertGreater(item["discounted_fcf"], 0.0)
            
    @patch("yfinance.Ticker")
    def test_capture_ratios(self, mock_ticker):
        """Verifies calculation of Up/Down-Market Capture Ratios."""
        from backend.financial_utils import calculate_capture_ratios
        
        # 1. Mock stock and benchmark historical data
        mock_stock_inst = MagicMock()
        mock_bench_inst = MagicMock()
        
        # We need a side effect so yf.Ticker returns mock stock for ticker_symbol and mock bench for benchmark_symbol
        def ticker_side_effect(symbol):
            if symbol == "^NSEI":
                return mock_bench_inst
            return mock_stock_inst
            
        mock_ticker.side_effect = ticker_side_effect
        
        import pandas as pd
        # Create a mock return series over 12 months (indices: standard dates)
        dates = pd.date_range(end="2026-05-29", periods=12, freq="ME")
        
        # Benchmark returns (Nifty is always rising in this mock to guarantee Positive months!)
        bench_close = [100.0 * (1.05**i) for i in range(12)]
        # Stock rises slightly faster to guarantee Up-Capture > 100%!
        stock_close = [100.0 * (1.06**i) for i in range(12)]
        
        df_bench = pd.DataFrame({"Close": bench_close}, index=dates)
        df_stock = pd.DataFrame({"Close": stock_close}, index=dates)
        
        mock_bench_inst.history.return_value = df_bench
        mock_stock_inst.history.return_value = df_stock
        
        # Run calculation
        capture = calculate_capture_ratios("SIEMENS.NS", stock_obj=mock_stock_inst)
        
        # Assertions
        self.assertEqual(capture["benchmark_symbol"], "^NSEI")
        self.assertGreater(capture["up_capture"], 100.0) # rises faster, so Up-Capture > 100
        
        # Try a Sensex ticker
        capture_bo = calculate_capture_ratios("SIEMENS.BO", stock_obj=mock_stock_inst)
        self.assertEqual(capture_bo["benchmark_symbol"], "^BSESN")


class TestAPIEndpoints(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        # Ensure clean database environment
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DROP TABLE IF EXISTS watchlist_items")
            cursor.execute("DROP TABLE IF EXISTS watchlists")
            cursor.execute("DROP TABLE IF EXISTS alerts")
            conn.commit()
        # Initialize database tables
        main.init_db()

    def tearDown(self):
        # Reset database tables between tests
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM watchlist_items")
            cursor.execute("DELETE FROM watchlists")
            cursor.execute("DELETE FROM alerts")
            cursor.execute("DELETE FROM screener_universe")
            conn.commit()

    def test_search_ticker_endpoint(self):
        """Verifies search ticker endpoint returns successfully."""
        response = self.client.get("/api/search?q=Reliance")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["yf_ticker"], "RELIANCE.NS")
        self.assertEqual(data["base_symbol"], "RELIANCE")

    @patch("backend.financial_utils.calculate_capture_ratios")
    def test_interactive_capture_endpoint(self, mock_calculate):
        """Verifies GET /api/stock/capture returns correct JSON keys and supports polymorphic params."""
        mock_calculate.return_value = {
            "up_capture": 120.5,
            "down_capture": 85.2,
            "benchmark_symbol": "^NSEI"
        }
        
        # 1. Verify legacy 'years' parameter maps to standard time_horizon (e.g. 3 -> '3y')
        response = self.client.get("/api/stock/capture?symbol=SIEMENS.NS&years=3")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["up_capture"], 120.5)
        self.assertEqual(data["down_capture"], 85.2)
        self.assertEqual(data["benchmark_symbol"], "^NSEI")
        mock_calculate.assert_called_with("SIEMENS.NS", None, "3y")
        
        # 2. Verify new 'period' parameter (e.g. '3m')
        response_short = self.client.get("/api/stock/capture?symbol=SIEMENS.NS&period=3m")
        self.assertEqual(response_short.status_code, 200)
        data_short = response_short.json()
        self.assertEqual(data_short["up_capture"], 120.5)
        mock_calculate.assert_called_with("SIEMENS.NS", None, "3m")

    @patch("yfinance.Ticker")
    def test_compare_chart_endpoint(self, mock_ticker):
        """Verifies GET /api/stock/compare-chart handles input lists, resolves benchmarks, and normalizes arrays."""
        mock_stock = MagicMock()
        mock_ticker.return_value = mock_stock
        
        # Mock yfinance return history
        import pandas as pd
        dates = pd.date_range(end="2026-05-29", periods=5, freq="D")
        df = pd.DataFrame({"Close": [100.0, 105.0, 110.0, 105.0, 120.0]}, index=dates)
        mock_stock.history.return_value = df
        
        response = self.client.get("/api/stock/compare-chart?symbols=SIEMENS,TCS&period=1y")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("dates", data)
        self.assertIn("series", data)
        self.assertIn("benchmark_symbol", data)
        self.assertEqual(data["benchmark_symbol"], "^NSEI")
        self.assertIn("SIEMENS.NS", data["series"])
        self.assertIn("TCS.NS", data["series"])
        # Check normalized data points: starts at 100.0, first step goes to 105.0
        self.assertEqual(data["series"]["SIEMENS.NS"][0], 100.0)
        self.assertEqual(data["series"]["SIEMENS.NS"][1], 105.0)

    @patch("backend.main.run_ai_stock_screener")
    def test_discover_stocks_endpoint(self, mock_screener):
        """Verifies discover endpoint calls screener engine correctly."""
        mock_screener.return_value = [
            {"symbol": "INFY", "name": "Infosys", "sector": "Technology", "score": 85, "action": "STRONG BUY"}
        ]
        response = self.client.get("/api/discover?strategy=hybrid&universe=large")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["symbol"], "INFY")
        mock_screener.assert_called_once_with("hybrid", "large", "Long-term (3+ years)", "Moderate", "all", None, None)

    @patch("backend.main.run_ai_stock_screener")
    def test_discover_stocks_with_style_endpoint(self, mock_screener):
        """Verifies discover endpoint calls screener engine with style overlay."""
        mock_screener.return_value = [
            {"symbol": "INFY", "name": "Infosys", "score": 85, "action": "STRONG BUY"}
        ]
        response = self.client.get("/api/discover?strategy=hybrid&universe=large&style=value")
        self.assertEqual(response.status_code, 200)
        mock_screener.assert_called_once_with("hybrid", "large", "Long-term (3+ years)", "Moderate", "value", None, None)

    def test_get_universe_endpoint(self):
        """Verifies the GET /api/universe endpoint returns registered constituents."""
        # 1. Insert mock index constituents into DB and ensure cached profiles is clean for isolation
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM cached_profiles WHERE symbol = ?", ("TCS.NS",))
            cursor.execute(
                "INSERT INTO screener_universe (symbol, base_symbol, company_name, sector, cap_type, last_rebalanced) VALUES (?, ?, ?, ?, ?, ?)",
                ("TCS.NS", "TCS", "Tata Consultancy Services", "Technology", "large", "2026-05-26T12:00:00")
            )
            conn.commit()

        # 2. Query endpoint
        response = self.client.get("/api/universe?cap_type=large")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["symbol"], "TCS.NS")
        self.assertEqual(data[0]["company_name"], "Tata Consultancy Services")
        self.assertEqual(data[0]["is_cached"], 0)

    def test_watchlist_management_flow(self):
        """Verifies the complete CRUD flow of Watchlist Console."""
        # 1. Create a watchlist
        response = self.client.post("/api/watchlists", json={"name": "Growth Stocks"})
        self.assertEqual(response.status_code, 200)
        wl_data = response.json()
        wl_id = wl_data["id"]
        self.assertEqual(wl_data["name"], "Growth Stocks")
        
        # 2. Duplicate name validation
        dup_response = self.client.post("/api/watchlists", json={"name": "Growth Stocks"})
        self.assertEqual(dup_response.status_code, 400)
        
        # 3. Rename watchlist
        rename_response = self.client.put(f"/api/watchlists/{wl_id}", json={"name": "Super Growth"})
        self.assertEqual(rename_response.status_code, 200)
        self.assertEqual(rename_response.json()["name"], "Super Growth")

        # 4. Add items to watchlist (with mock profile fetching)
        mock_profile = {
            "company_name": "TCS Ltd",
            "sector": "Technology"
        }
        with patch("backend.main.get_complete_financial_profile", return_value=mock_profile):
            item_response = self.client.post(f"/api/watchlists/{wl_id}/items", json={"symbol": "TCS"})
            self.assertEqual(item_response.status_code, 200)
            item_data = item_response.json()
            self.assertEqual(item_data["symbol"], "TCS")
            self.assertEqual(item_data["name"], "TCS Ltd")
            self.assertEqual(item_data["sector"], "Technology")
        # 4b. Duplicate watchlist
        dup_wl_resp = self.client.post(f"/api/watchlists/{wl_id}/duplicate")
        self.assertEqual(dup_wl_resp.status_code, 200)
        dup_wl_data = dup_wl_resp.json()
        self.assertTrue(dup_wl_data["name"].startswith("Super Growth (Copy"))
        self.assertEqual(dup_wl_data["items_count"], 1)
        
        # Cleanup duplicated watchlist
        self.client.delete(f"/api/watchlists/{dup_wl_data['id']}")

        # 5. List watchlists with constituents
        list_response = self.client.get("/api/watchlists")
        self.assertEqual(list_response.status_code, 200)
        lists = list_response.json()
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0]["name"], "Super Growth")
        self.assertEqual(len(lists[0]["items"]), 1)
        self.assertEqual(lists[0]["items"][0]["symbol"], "TCS")

        # 6. Batch analyze watchlist
        mock_full_profile = {
            "company_name": "TCS Ltd",
            "sector": "Technology",
            "score_metrics": {"final_score": 90, "action": "STRONG BUY"},
            "fundamentals": {"current_price": 3800.0, "pe_ratio": 28.0, "roe_pct": 35.0},
            "dcf_model": {"margin_of_safety": 15.5},
            "technicals": {"rsi": 62.0, "trend_50_vs_200": "Bullish"}
        }
        with patch("backend.main.get_complete_financial_profile", return_value=mock_full_profile):
            analysis_response = self.client.get(f"/api/watchlists/{wl_id}/analyze")
            self.assertEqual(analysis_response.status_code, 200)
            res_data = analysis_response.json()
            self.assertEqual(len(res_data["results"]), 1)
            self.assertEqual(res_data["results"][0]["symbol"], "TCS")
            self.assertEqual(res_data["results"][0]["score"], 90)
            self.assertEqual(res_data["results"][0]["action"], "STRONG BUY")

        # 7. Remove item from watchlist
        remove_response = self.client.delete(f"/api/watchlists/{wl_id}/items/TCS")
        self.assertEqual(remove_response.status_code, 200)
        
        # Verify removal
        list_response = self.client.get("/api/watchlists")
        self.assertEqual(len(list_response.json()[0]["items"]), 0)

        # 8. Delete watchlist
        delete_response = self.client.delete(f"/api/watchlists/{wl_id}")
        self.assertEqual(delete_response.status_code, 200)
        
        # Verify deletion
        list_response = self.client.get("/api/watchlists")
        self.assertEqual(len(list_response.json()), 0)

    def test_alert_persistence_and_check(self):
        """Verifies setting, listing, checking, and deleting alert criteria."""
        # 1. Set alert rule
        alert_payload = {
            "ticker": "RELIANCE",
            "condition_type": "PRICE",
            "operator": "<",
            "value": "2500"
        }
        response = self.client.post("/api/alerts/set", json=alert_payload)
        self.assertEqual(response.status_code, 200)
        alert_data = response.json()
        alert_id = alert_data["id"]
        self.assertEqual(alert_data["ticker"], "RELIANCE")
        self.assertEqual(alert_data["condition_type"], "PRICE")
        
        # 2. List alerts
        list_response = self.client.get("/api/alerts/list")
        self.assertEqual(list_response.status_code, 200)
        alerts = list_response.json()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["id"], alert_id)
        self.assertEqual(alerts[0]["status"], "Active")

        # 3. Check active alerts (under price trigger threshold)
        mock_low_price_profile = {
            "fundamentals": {"current_price": 2400.0, "pe_ratio": 22.0},
            "technicals": {"rsi": 45.0, "sma_200": 2300.0}
        }
        with patch("backend.main.get_complete_financial_profile", return_value=mock_low_price_profile):
            check_response = self.client.get("/api/alerts/check")
            self.assertEqual(check_response.status_code, 200)
            res_data = check_response.json()
            self.assertEqual(len(res_data["triggers"]), 1)
            self.assertIn("ALERT TRIGGERED: RELIANCE reached Price: Rs. 2400.00", res_data["triggers"][0])
            self.assertEqual(res_data["alerts"][0]["status"], "Triggered")

        # 4. Delete alert rule
        delete_response = self.client.delete(f"/api/alerts/{alert_id}")
        self.assertEqual(delete_response.status_code, 200)
        
        # Verify empty alerts list
        list_response = self.client.get("/api/alerts/list")
        self.assertEqual(len(list_response.json()), 0)


class TestDatabaseAndScreenerUpgrade(unittest.TestCase):
    
    def setUp(self):
        # Clear DB before test
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM screener_universe")
            cursor.execute("DELETE FROM cached_profiles")
            conn.commit()

    def tearDown(self):
        # Clear DB after test
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM screener_universe")
            cursor.execute("DELETE FROM cached_profiles")
            conn.commit()

    def test_database_tables_exist(self):
        """Verifies database tables for caching and screener universe exist."""
        with get_db() as conn:
            cursor = conn.cursor()
            # Check screener_universe table structure
            cursor.execute("PRAGMA table_info(screener_universe)")
            columns = {col["name"] for col in cursor.fetchall()}
            self.assertIn("symbol", columns)
            self.assertIn("company_name", columns)
            self.assertIn("cap_type", columns)

            # Check cached_profiles table structure
            cursor.execute("PRAGMA table_info(cached_profiles)")
            columns_cached = {col["name"] for col in cursor.fetchall()}
            self.assertIn("symbol", columns_cached)
            self.assertIn("profile_json", columns_cached)

    @patch("requests.get")
    def test_rebalance_index_universe(self, mock_get):
        """Verifies NSE csv sync successfully parses and inserts symbols."""
        mock_csv_data = (
            "Company Name,Industry,Symbol,Series,ISIN Code\n"
            "Reliance Industries Ltd,Oil Gas & Fuels,RELIANCE,EQ,INE002A01018\n"
            "Infosys Ltd,IT,INFY,EQ,INE009A01021\n"
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = mock_csv_data
        mock_get.return_value = mock_response

        # Execute rebalance
        count = main.rebalance_index_universe()
        
        # Reliance and Infosys are returned for large, mid, and small cap lists since mock returns same for all urls
        self.assertGreater(count, 0)
        
        # Verify db contents
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, company_name, cap_type FROM screener_universe WHERE symbol = ?", ("RELIANCE.NS",))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["company_name"], "Reliance Industries Ltd")

    def test_run_ai_stock_screener_from_cache(self):
        """Verifies updated screener scans cached SQLite profiles instead of random samples."""
        from backend.agent import run_ai_stock_screener
        
        # Insert a mock constituent into screener_universe
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO screener_universe (symbol, base_symbol, company_name, sector, cap_type, last_rebalanced) VALUES (?, ?, ?, ?, ?, ?)",
                ("INFY.NS", "INFY", "Infosys Ltd", "Technology", "large", "2026-05-26T12:00:00")
            )
            
            # Insert a mock profile into cached_profiles
            mock_profile = {
                "base_symbol": "INFY",
                "company_name": "Infosys Ltd",
                "sector": "Technology",
                "fundamentals": {
                    "current_price": 1400.0,
                    "pe_ratio": 25.0,
                    "roe_pct": 28.0,
                    "roce_pct": 32.0,
                    "net_margin_pct": 18.0,
                    "debt_to_equity": 0.05,
                    "interest_coverage": 15.0,
                    "current_ratio": 1.5,
                    "cfo_to_pat": 0.95,
                    "eps_growth_3y_pct": 14.0,
                    "promoter_holding_pct": 30.0,  # Fails bottom-up quality gate (<40.0) but passes top-down floor (>=25.0)
                    "promoter_pledge_pct": 0.0
                },
                "technicals": {
                    "sma_200": 1350.0,
                    "sma_50": 1380.0,
                    "adx": 25.0,
                    "rsi": 55.0
                },
                "dcf_model": {
                    "margin_of_safety": 12.0
                },
                "shareholding": {
                    "promoter_holding_pct": 30.0,
                    "promoter_pledge_pct": 0.0
                },
                "score_metrics": {
                    "final_score": 85,
                    "fundamental_score": 25,
                    "valuation_score": 20,
                    "technical_score": 22,
                    "action": "BUY"
                }
            }
            cursor.execute(
                "INSERT INTO cached_profiles (symbol, profile_json) VALUES (?, ?)",
                ("INFY.NS", json.dumps(mock_profile))
            )
            conn.commit()

        # Run screener under bottom_up strategy - INFY fails promoter holding gate, so it should be skipped
        results_bottom_up = run_ai_stock_screener("bottom_up", "large")
        self.assertEqual(len(results_bottom_up), 0)

        # Run screener under top_down strategy - no quality gates are enforced, so it should return INFY
        results_top_down = run_ai_stock_screener("top_down", "large")
        self.assertEqual(len(results_top_down), 1)
        self.assertEqual(results_top_down[0]["symbol"], "INFY.NS")
        self.assertEqual(results_top_down[0]["score"], 85)

    def test_style_screener_gates(self):
        """Verifies that style-based filtration gates (Value, Growth, Contra) work correctly."""
        from backend.agent import run_ai_stock_screener
        
        # 1. Insert a mock "Value" stock that fails "Growth" gates
        # And a mock "Contra" stock that passes contrarian entry and solvency rules
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Value stock setup
            cursor.execute(
                "INSERT INTO screener_universe (symbol, base_symbol, company_name, sector, cap_type, last_rebalanced) VALUES (?, ?, ?, ?, ?, ?)",
                ("TCS.NS", "TCS", "Tata Consultancy Services", "Technology", "large", "2026-05-26T12:00:00")
            )
            val_profile = {
                "base_symbol": "TCS",
                "company_name": "Tata Consultancy Services",
                "sector": "Technology",
                "fundamentals": {
                    "current_price": 3200.0,
                    "pe_ratio": 15.0, # Passes Value PE
                    "roe_pct": 14.0, # Passes Value >=12, Fails Growth >=18
                    "roce_pct": 15.0, # Passes, Fails Growth >=18
                    "net_margin_pct": 15.0,
                    "debt_to_equity": 0.1,
                    "interest_coverage": 10.0,
                    "current_ratio": 1.4,
                    "cfo_to_pat": 0.9,
                    "eps_growth_3y_pct": 10.0, # Passes, Fails Growth >=15
                    "sales_growth_3y_pct": 8.0, # Fails Growth >=12
                    "promoter_holding_pct": 55.0,
                    "promoter_pledge_pct": 0.0,
                    "dividend_yield_pct": 1.5 # Passes Value >= 0.5
                },
                "technicals": {
                    "sma_200": 3000.0,
                    "sma_50": 3100.0,
                    "adx": 22.0,
                    "rsi": 50.0
                },
                "dcf_model": {
                    "margin_of_safety": 15.0 # Passes Value MoS >= 0
                },
                "shareholding": {
                    "promoter_holding_pct": 55.0,
                    "promoter_pledge_pct": 0.0,
                    "FIIs": 15.0,
                    "DIIs": 15.0
                },
                "score_metrics": {
                    "final_score": 75,
                    "fundamental_score": 20,
                    "valuation_score": 18,
                    "technical_score": 16,
                    "peg_ratio": 1.2
                }
            }
            cursor.execute(
                "INSERT INTO cached_profiles (symbol, profile_json) VALUES (?, ?)",
                ("TCS.NS", json.dumps(val_profile))
            )

            # Contra stock setup
            cursor.execute(
                "INSERT INTO screener_universe (symbol, base_symbol, company_name, sector, cap_type, last_rebalanced) VALUES (?, ?, ?, ?, ?, ?)",
                ("SBI.NS", "SBIN", "State Bank of India", "Banking", "large", "2026-05-26T12:00:00")
            )
            contra_profile = {
                "base_symbol": "SBIN",
                "company_name": "State Bank of India",
                "sector": "Banking",
                "fundamentals": {
                    "current_price": 500.0,
                    "pe_ratio": 12.0,
                    "roe_pct": 10.0, # Passes Contra >=8.0, Fails standard bottom-up >=15.0
                    "roce_pct": 10.0, # Passes Contra >=8.0, Fails standard bottom-up >=12.0
                    "net_margin_pct": 12.0, # Passes Contra >=5.0, Fails standard bottom-up >=8.0 (wait, 12 >= 8 is True but ROE/ROCE will fail bottom-up anyway)
                    "debt_to_equity": 0.2, # Passes Contra <=0.5
                    "interest_coverage": 4.0, # Passes Contra >=2.0
                    "current_ratio": 1.4,
                    "cfo_to_pat": 0.8,
                    "eps_growth_3y_pct": 8.0,
                    "sales_growth_3y_pct": 6.0,
                    "promoter_holding_pct": 45.0, # Passes Contra >=30.0
                    "promoter_pledge_pct": 5.0, # Passes Contra <=20.0
                    "dividend_yield_pct": 1.0
                },
                "technicals": {
                    "sma_200": 480.0, # 500 is within 15% of 480 (500 <= 480 * 1.15) -> Passes Contra
                    "sma_50": 490.0,
                    "adx": 18.0,
                    "rsi": 38.0 # Passes Contra RSI <= 45
                },
                "dcf_model": {
                    "margin_of_safety": 5.0
                },
                "shareholding": {
                    "promoter_holding_pct": 45.0,
                    "promoter_pledge_pct": 5.0,
                    "FIIs": 8.0,
                    "DIIs": 8.0 # Inst holding = 16.0 >= 10.0 -> Passes Contra
                },
                "earnings_quality": {
                    "piotroski_score": 5, # Passes Contra >=4
                    "altman_z_score": 2.2, # Passes Contra >=1.81
                    "altman_zone": "Safe Zone"
                },
                "score_metrics": {
                    "final_score": 68,
                    "fundamental_score": 18,
                    "valuation_score": 15,
                    "technical_score": 10,
                    "peg_ratio": 1.5
                }
            }
            cursor.execute(
                "INSERT INTO cached_profiles (symbol, profile_json) VALUES (?, ?)",
                ("SBI.NS", json.dumps(contra_profile))
            )
            
            conn.commit()

        # TCS is Value stock. It has ROE 14 (fails growth), eps_growth_3y 10 (fails growth).
        # Standard bottom-up filters TCS out because standard bottom-up ROE requires >=15 (for moderate risk).
        # Wait, TCS ROE is 14. Let's run TCS under bottom-up with "all" styles to see if it fails.
        # Yes, standard bottom-up ROE requires >= 15.0. So TCS should be filtered out.
        # But wait! If we run under "value" style overlay, TCS passes the Value gates! 
        # But wait, standard bottom-up has ROE >= 15.0 gate. TCS has ROE 14.0, so even under Value style,
        # it would fail the Bottom-Up core quality gate first!
        # Ah! That's correct. Post-pipeline style gates are applied *after* the core strategy gates pass!
        # So to test Value style gates on TCS, we should use a strategy like Top-Down (which has a lower floor of ROE - actually no ROE floor, only net margin >=3.0).
        # Let's check Top-Down + Value style overlay:
        # TCS has PE 15 <= 22, MoS 15 >= 0, ROE 14 >= 12, promoter pledge 0 <= 10.
        # So TCS passes Top-Down + Value!
        results_val = run_ai_stock_screener("top_down", "large", style="value")
        self.assertTrue(any(x["symbol"] == "TCS.NS" for x in results_val))
        
        # But if we run Top-Down + Growth style overlay:
        # TCS has ROE 14 < 18, so it fails Growth style overlay!
        results_growth = run_ai_stock_screener("top_down", "large", style="growth")
        self.assertFalse(any(x["symbol"] == "TCS.NS" for x in results_growth))

        # SBI.NS is Contra stock. Under Bottom-Up, standard bottom-up ROE requires >=15, so SBI (ROE 10) fails standard Bottom-Up + All.
        # But what about under Bottom-Up + Contra?
        # Under Bottom-Up + Contra, wait! Does SBI pass Bottom-Up core quality gates?
        # Standard Bottom-Up quality gates require ROE >= 15 (Moderate), net margin >= 8.
        # So SBI (ROE 10) would fail Bottom-Up core gates.
        # But under Top-Down + Contra:
        # SBI passes Top-Down quality floor (net margin 12 >= 3, debt_eq 0.2 <= 2, current_ratio 1.4 >= 0.8)
        # And passes Contra style gates (RSI 38 <= 45, price 500 <= 480 * 1.15, D/E 0.2 <= 0.5, Altman 2.2 >= 1.81, Piotroski 5 >= 4, Inst holding 16 >= 10).
        results_contra = run_ai_stock_screener("top_down", "large", style="contra")
        self.assertTrue(any(x["symbol"] == "SBI.NS" for x in results_contra))


class TestPortfolioAPI(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DROP TABLE IF EXISTS portfolio_items")
            conn.commit()
        main.init_db()

    def setUp(self):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM portfolio_items")
            cursor.execute("DELETE FROM watchlist_items")
            cursor.execute("DELETE FROM watchlists")
            cursor.execute("DELETE FROM screener_universe")
            conn.commit()

    def test_portfolio_crud_flow(self):
        """Verifies full GET, POST, PUT, DELETE flow of Standalone AI Portfolio Doctor."""
        # 1. Initially empty
        get_res = self.client.get("/api/portfolio")
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(len(get_res.json()), 0)

        # 2. Add custom stock (with mock financial profile to resolve metadata online)
        mock_profile = {
            "company_name": "Bharat Heavy Electricals",
            "sector": "Industrials",
            "ticker": "BHEL.NS",
            "analysis": {
                "suggested_buy_price_range": "Rs. 220 - Rs. 230",
                "suggested_sell_price_range": "Rs. 260 - Rs. 280",
                "target_12m": 270.0,
                "stop_loss_12m": 210.0
            }
        }
        with patch("backend.main.get_complete_financial_profile", return_value=mock_profile), \
             patch("backend.main.run_cio_parent_agent", new_callable=AsyncMock) as mock_agent:
            mock_agent.return_value = mock_profile
            post_payload = {"symbol": "BHEL", "quantity": 150.0, "purchase_price": 240.0}
            post_res = self.client.post("/api/portfolio", json=post_payload)
            self.assertEqual(post_res.status_code, 200)
            added = post_res.json()
            self.assertTrue(added["symbol"].startswith("BHEL"))
            self.assertEqual(added["name"], "Bharat Heavy Electricals")
            self.assertEqual(added["sector"], "Industrials")
            self.assertEqual(added["quantity"], 150.0)
            resolved_symbol = added["symbol"]

        # 3. Get portfolio and check content
        list_res = self.client.get("/api/portfolio")
        self.assertEqual(len(list_res.json()), 1)
        self.assertEqual(list_res.json()[0]["symbol"], resolved_symbol)

        # 4. Update holdings
        put_payload = {"quantity": 200.0, "purchase_price": 245.0}
        put_res = self.client.put(f"/api/portfolio/{resolved_symbol}", json=put_payload)
        self.assertEqual(put_res.status_code, 200)

        # Verify update
        check_res = self.client.get("/api/portfolio")
        self.assertEqual(check_res.json()[0]["quantity"], 200.0)
        self.assertEqual(check_res.json()[0]["purchase_price"], 245.0)

        # 5. Delete item
        del_res = self.client.delete(f"/api/portfolio/{resolved_symbol}")
        self.assertEqual(del_res.status_code, 200)

        # Verify empty
        get_res = self.client.get("/api/portfolio")
        self.assertEqual(len(get_res.json()), 0)

    def test_portfolio_fifo_netting(self):
        """Verifies that the portfolio API dynamically nets buy and sell transactions using FIFO."""
        mock_profile = {
            "company_name": "Bharat Heavy Electricals",
            "sector": "Industrials",
            "ticker": "BHEL.NS",
            "analysis": {
                "suggested_buy_price_range": "Rs. 220 - Rs. 230",
                "suggested_sell_price_range": "Rs. 260 - Rs. 280",
                "target_12m": 270.0,
                "stop_loss_12m": 210.0
            }
        }
        with patch("backend.main.get_complete_financial_profile", return_value=mock_profile), \
             patch("backend.main.run_cio_parent_agent", new_callable=AsyncMock) as mock_agent:
            mock_agent.return_value = mock_profile

            # 1. Buy 100 shares of BHEL
            b1 = self.client.post("/api/portfolio", json={"symbol": "BHEL", "quantity": 100.0, "purchase_price": 240.0, "transaction_type": "buy"})
            self.assertEqual(b1.status_code, 200)

            # 2. Buy 50 shares of BHEL
            b2 = self.client.post("/api/portfolio", json={"symbol": "BHEL", "quantity": 50.0, "purchase_price": 250.0, "transaction_type": "buy"})
            self.assertEqual(b2.status_code, 200)

            # 3. Sell 60 shares of BHEL
            s1 = self.client.post("/api/portfolio", json={"symbol": "BHEL", "quantity": 60.0, "purchase_price": 260.0, "transaction_type": "sell"})
            self.assertEqual(s1.status_code, 200)

        # 4. Get computed active holdings - FIFO should net 60 shares off the first tranche (100 -> 40 remaining)
        active_res = self.client.get("/api/portfolio")
        self.assertEqual(active_res.status_code, 200)
        active = active_res.json()
        
        # We should have exactly 2 active tranches: one of 40 shares and one of 50 shares
        self.assertEqual(len(active), 2)
        active_sorted = sorted(active, key=lambda x: x["quantity"])
        self.assertEqual(active_sorted[0]["quantity"], 40.0)
        self.assertEqual(active_sorted[1]["quantity"], 50.0)

        # 5. Get complete raw transactions list
        txs_res = self.client.get("/api/portfolio/transactions")
        self.assertEqual(txs_res.status_code, 200)
        txs = txs_res.json()
        self.assertEqual(len(txs), 3)
        self.assertEqual(txs[0]["transaction_type"], "sell")
        self.assertEqual(txs[1]["transaction_type"], "buy")
        self.assertEqual(txs[2]["transaction_type"], "buy")

    def test_search_suggestions_endpoint(self):
        """Verifies that search suggestions autocomplete route works offline and online."""
        # Insert a mock constituent into screener_universe to test offline suggestions
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO screener_universe (symbol, base_symbol, company_name, sector, cap_type, last_rebalanced) VALUES (?, ?, ?, ?, ?, ?)",
                ("HAL.NS", "HAL", "Hindustan Aeronautics", "Aerospace & Defense", "large", "2026-05-26")
            )
            conn.commit()

        # Query suggestions matching "HAL"
        res = self.client.get("/api/search/suggestions?q=HAL")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreater(len(data), 0)
        self.assertEqual(data[0]["base_symbol"], "HAL")
        self.assertEqual(data[0]["name"], "Hindustan Aeronautics")

    @patch("yfinance.Ticker")
    def test_portfolio_backtest_endpoints(self, mock_ticker):
        """Verifies portfolio backtesting execution and LLM synthesis endpoints."""
        mock_stock_inst = MagicMock()
        mock_bench_inst = MagicMock()
        
        def ticker_side_effect(symbol):
            if symbol == "^NSEI":
                return mock_bench_inst
            return mock_stock_inst
            
        mock_ticker.side_effect = ticker_side_effect
        
        import pandas as pd
        dates = pd.date_range(start="2023-01-01", end="2023-12-31", freq="D")
        
        bench_close = [100.0 + i * 0.1 for i in range(len(dates))]
        stock_close = [100.0 + i * 0.2 for i in range(len(dates))]
        divs = [0.0] * len(dates)
        divs[100] = 2.0
        
        df_bench = pd.DataFrame({"Close": bench_close}, index=dates)
        df_stock = pd.DataFrame({"Close": stock_close, "Dividends": divs}, index=dates)
        
        mock_bench_inst.history.return_value = df_bench
        mock_stock_inst.history.return_value = df_stock
        
        payload = {
            "tickers": ["TATAMOTORS", "INFY"],
            "weights": [60.0, 40.0],
            "start_date": "2023-01-01",
            "end_date": "2023-12-31",
            "rebalance_freq": "semiannually",
            "starting_capital": 100000.0,
            "transaction_fee_pct": 0.1
        }
        
        res = self.client.post("/api/portfolio/backtest", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("dates", data)
        self.assertIn("portfolio_values", data)
        self.assertIn("benchmark_values", data)
        self.assertIn("metrics", data)
        self.assertIn("rebalancing_history", data["metrics"])
        self.assertGreater(len(data["metrics"]["rebalancing_history"]), 0)
        self.assertGreater(data["metrics"]["portfolio"]["final_value"], 100000.0)
        self.assertGreater(data["metrics"]["portfolio"]["total_dividends"], 0.0)
        
        synth_payload = {
            "metrics": data["metrics"],
            "tickers_weights": [{"symbol": "TATAMOTORS", "weight": 60.0}, {"symbol": "INFY", "weight": 40.0}]
        }
        mock_summary = "### 🔬 Backtest Summary\nThe portfolio outperformed the benchmark."
        with patch("backend.main.generate_backtest_synthesis", return_value=mock_summary):
            synth_res = self.client.post("/api/portfolio/backtest-synthesis", json=synth_payload)
            self.assertEqual(synth_res.status_code, 200)
            self.assertEqual(synth_res.json()["synthesis"], mock_summary)

    @patch("backend.agent.get_complete_financial_profile")
    def test_stock_audit_endpoint(self, mock_profile_call):
        """Verifies that the /api/stock/audit endpoint returns simulated checks for all combinations."""
        mock_profile = {
            "base_symbol": "TCS",
            "company_name": "Tata Consultancy Services",
            "sector": "Technology",
            "fundamentals": {
                "current_price": 3200.0,
                "pe_ratio": 15.0,
                "roe_pct": 24.5,
                "roce_pct": 25.0,
                "net_margin_pct": 15.0,
                "debt_to_equity": 0.1,
                "interest_coverage": 10.0,
                "current_ratio": 1.4,
                "cfo_to_pat": 0.9,
                "eps_growth_3y_pct": 14.0,
                "sales_growth_3y_pct": 12.0,
                "promoter_holding_pct": 55.0,
                "promoter_pledge_pct": 0.0,
                "dividend_yield_pct": 1.5
            },
            "technicals": {
                "sma_200": 3000.0,
                "sma_50": 3100.0,
                "adx": 22.0,
                "rsi": 50.0
            },
            "dcf_model": {
                "margin_of_safety": 15.0
            },
            "shareholding": {
                "promoter_holding_pct": 55.0,
                "promoter_pledge_pct": 0.0,
                "FIIs": 15.0,
                "DIIs": 15.0
            },
            "earnings_quality": {
                "piotroski_score": 6,
                "altman_z_score": 3.5,
                "altman_zone": "Safe Zone"
            },
            "score_metrics": {
                "final_score": 75,
                "fundamental_score": 20,
                "valuation_score": 18,
                "technical_score": 16,
                "peg_ratio": 1.2,
                "action": "BUY"
            }
        }
        mock_profile_call.return_value = mock_profile

        # Query stock audit for TCS.NS
        res = self.client.get("/api/stock/audit?symbol=TCS.NS")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["symbol"], "TCS.NS")
        self.assertEqual(len(data["combinations"]), 12)
        # Verify first combination has keys strategy, style, passed, score, gates
        first = data["combinations"][0]
        self.assertIn("strategy", first)
        self.assertIn("style", first)
        self.assertIn("passed", first)
        self.assertIn("score", first)
        self.assertIn("gates", first)

    @patch("backend.agent.get_complete_financial_profile")
    def test_wise_pe_valuation_check(self, mock_profile_call):
        """Verifies that a stock with high absolute PE passes Value style gates if it is cheaper than peers."""
        mock_profile = {
            "symbol": "HIGHPE.NS",
            "base_symbol": "HIGHPE",
            "company_name": "High PE Champ Ltd",
            "sector": "Industrials",
            "fundamentals": {
                "current_price": 5000.0,
                "pe_ratio": 95.0,  # Fails static absolute PE (95.0 > 22.0)
                "roe_pct": 25.0,
                "roce_pct": 26.0,
                "net_margin_pct": 20.0,
                "debt_to_equity": 0.05,
                "interest_coverage": 15.0,
                "current_ratio": 1.5,
                "cfo_to_pat": 1.1,
                "eps_growth_3y_pct": 40.0,
                "sales_growth_3y_pct": 35.0,
                "promoter_holding_pct": 60.0,
                "promoter_pledge_pct": 0.0,
                "dividend_yield_pct": 1.2
            },
            "technicals": {
                "sma_200": 4000.0,
                "sma_50": 4500.0,
                "adx": 28.0,
                "rsi": 50.0
            },
            "dcf_model": {
                "margin_of_safety": 10.0
            },
            "shareholding": {
                "promoter_holding_pct": 60.0,
                "promoter_pledge_pct": 0.0,
                "FIIs": 12.0,
                "DIIs": 18.0
            },
            "earnings_quality": {
                "piotroski_score": 7,
                "altman_z_score": 4.2,
                "altman_zone": "Safe Zone"
            },
            "score_metrics": {
                "final_score": 85,
                "fundamental_score": 25,
                "valuation_score": 15,
                "technical_score": 20,
                "peg_ratio": 1.1,
                "action": "BUY"
            },
            "pe_bands": {
                "median_pe": 60.0,  # Fails self-relative PE (95.0 > 60.0 * 1.1)
                "mean_pe": 55.0,
                "min_pe": 10.0,
                "max_pe": 200.0
            },
            "peers": [
                {"Name": "Peer A", "P/E": "120.0"},
                {"Name": "Peer B", "P/E": "110.0"},
                {"Name": "Peer C", "P/E": "100.0"}  # Median is 110.0. 95.0 <= 110.0 * 1.1 passes peer PE!
            ]
        }
        mock_profile_call.return_value = mock_profile

        # Call single stock audit
        res = self.client.get("/api/stock/audit?symbol=HIGHPE.NS")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        # Find Value Style overlay combo
        value_combo = next(
            c for c in data["combinations"]
            if c["strategy"] == "bottom_up" and c["style"] == "value"
        )
        
        # Check if "Wise PE Valuation Call" gate exists and passed
        pe_gate = next(g for g in value_combo["gates"] if g["name"] == "Wise PE Valuation Call")
        self.assertTrue(pe_gate["passed"])

import pandas as pd

class TestAlertsEnhancements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        main.init_db()

    def setUp(self):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM alerts")
            cursor.execute("DELETE FROM alert_settings")
            conn.commit()

    def test_alert_settings_endpoints(self):
        """Verifies alerts settings GET and POST endpoints."""
        response = self.client.get("/api/alerts/settings")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["slack_webhook"], "")
        self.assertEqual(data["discord_webhook"], "")

        payload = {
            "slack_webhook": "https://hooks.slack.com/services/test-slack",
            "discord_webhook": "https://discord.com/api/webhooks/test-discord"
        }
        save_response = self.client.post("/api/alerts/settings", json=payload)
        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(save_response.json()["status"], "success")

        response_saved = self.client.get("/api/alerts/settings")
        self.assertEqual(response_saved.status_code, 200)
        data_saved = response_saved.json()
        self.assertEqual(data_saved["slack_webhook"], "https://hooks.slack.com/services/test-slack")
        self.assertEqual(data_saved["discord_webhook"], "https://discord.com/api/webhooks/test-discord")

    @patch("backend.main.get_complete_financial_profile")
    @patch("backend.main.fetch_history_df")
    def test_alert_evaluations(self, mock_fetch_history, mock_get_profile):
        """Tests the evaluation of crossovers, SMA50 difference, and Fibonacci proximity."""
        mock_get_profile.return_value = {
            "fundamentals": {"current_price": 100.0},
            "technicals": {"rsi": 50.0, "sma_200": 90.0}
        }

        dates = pd.date_range(end="2026-06-09", periods=250, freq="D")
        close_prices = [100.0] * 200 + [80.0] * 49 + [2000.0]
        volumes = [500000] * 250
        df_history = pd.DataFrame({"Close": close_prices, "Volume": volumes}, index=dates)
        mock_fetch_history.return_value = df_history

        set_payload = {
            "ticker": "RELIANCE",
            "condition_type": "DMA_CROSS",
            "operator": ">",
            "value": "0"
        }
        set_res = self.client.post("/api/alerts/set", json=set_payload)
        self.assertEqual(set_res.status_code, 200)
        alert_id = set_res.json()["id"]

        check_res = self.client.get("/api/alerts/check")
        self.assertEqual(check_res.status_code, 200)
        check_data = check_res.json()
        
        triggered_alert = next((a for a in check_data["alerts"] if a["id"] == alert_id), None)
        self.assertIsNotNone(triggered_alert)
        self.assertTrue(triggered_alert["triggered"])
        self.assertEqual(triggered_alert["status"], "Triggered")

    @patch("backend.main.get_complete_financial_profile")
    @patch("backend.main.fetch_history_df")
    def test_fibonacci_level_and_sma50_triggers(self, mock_fetch_history, mock_get_profile):
        """Tests SMA50 percent difference and Fibonacci retracement proximity alerts."""
        mock_get_profile.return_value = {
            "fundamentals": {"current_price": 100.0},
            "technicals": {"rsi": 50.0}
        }

        dates = pd.date_range(end="2026-06-09", periods=120, freq="D")
        close_prices = [100.0] * 60 + [200.0] * 59 + [151.0]
        df_history = pd.DataFrame({"Close": close_prices, "Volume": [100000]*120}, index=dates)
        mock_fetch_history.return_value = df_history

        fib_payload = {
            "ticker": "TCS",
            "condition_type": "FIB_LEVEL",
            "operator": "==",
            "value": "1.5"
        }
        set_res = self.client.post("/api/alerts/set", json=fib_payload)
        self.assertEqual(set_res.status_code, 200)
        fib_alert_id = set_res.json()["id"]

        # Set FIB_500 Alert (should trigger since price 151 is near 50% level of 150)
        fib500_payload = {
            "ticker": "TCS",
            "condition_type": "FIB_500",
            "operator": "==",
            "value": "1.5"
        }
        set_res3 = self.client.post("/api/alerts/set", json=fib500_payload)
        self.assertEqual(set_res3.status_code, 200)
        fib500_alert_id = set_res3.json()["id"]

        # Set FIB_382 Alert (should NOT trigger since price 151 is far from 38.2% level of 161.8)
        fib382_payload = {
            "ticker": "TCS",
            "condition_type": "FIB_382",
            "operator": "==",
            "value": "1.5"
        }
        set_res4 = self.client.post("/api/alerts/set", json=fib382_payload)
        self.assertEqual(set_res4.status_code, 200)
        fib382_alert_id = set_res4.json()["id"]

        sma50_payload = {
            "ticker": "TCS",
            "condition_type": "SMA50",
            "operator": "<",
            "value": "-20"
        }
        set_res2 = self.client.post("/api/alerts/set", json=sma50_payload)
        self.assertEqual(set_res2.status_code, 200)
        sma_alert_id = set_res2.json()["id"]

        check_res = self.client.get("/api/alerts/check")
        self.assertEqual(check_res.status_code, 200)
        check_data = check_res.json()

        fib_alert = next((a for a in check_data["alerts"] if a["id"] == fib_alert_id), None)
        self.assertIsNotNone(fib_alert)
        self.assertTrue(fib_alert["triggered"])

        fib500_alert = next((a for a in check_data["alerts"] if a["id"] == fib500_alert_id), None)
        self.assertIsNotNone(fib500_alert)
        self.assertTrue(fib500_alert["triggered"])

        fib382_alert = next((a for a in check_data["alerts"] if a["id"] == fib382_alert_id), None)
        self.assertIsNotNone(fib382_alert)
        self.assertFalse(fib382_alert["triggered"])

        sma_alert = next((a for a in check_data["alerts"] if a["id"] == sma_alert_id), None)
        self.assertIsNotNone(sma_alert)
        self.assertTrue(sma_alert["triggered"])

    @patch("backend.main.get_complete_financial_profile")
    @patch("backend.main.fetch_history_df")
    def test_all_other_triggers(self, mock_fetch_history, mock_get_profile):
        """Tests RSI, PE, RATING, PRICE, SMA, EMA_CROSS, VOL_BREAKOUT, BB_CROSS, MACD_CROSS, and 52W_PROXIMITY alert triggers."""
        mock_get_profile.return_value = {
            "fundamentals": {
                "current_price": 100.0,
                "pe_ratio": 15.0
            },
            "technicals": {
                "rsi": 28.0,
                "sma_200": 110.0
            },
            "analysis": {
                "recommendation": "Strong Buy"
            },
            "pe_bands": {
                "median_pe": 20.0
            }
        }

        dates = pd.date_range(end="2026-06-09", periods=250, freq="D")
        
        df_rsi = pd.DataFrame({"Close": [100.0]*250, "Volume": [100000]*250}, index=dates)
        df_ema = pd.DataFrame({"Close": [100.0]*200 + [80.0]*49 + [2000.0], "Volume": [100000]*250}, index=dates)
        df_vol = pd.DataFrame({"Close": [100.0]*250, "Volume": [500000]*249 + [2000000]}, index=dates)
        df_bb = pd.DataFrame({"Close": [100.0]*248 + [90.0] + [500.0], "Volume": [100000]*250}, index=dates)
        df_macd = pd.DataFrame({"Close": [100.0]*248 + [95.0] + [150.0], "Volume": [100000]*250}, index=dates)
        df_prox = pd.DataFrame({"Close": [100.0]*249 + [99.0], "Volume": [100000]*250}, index=dates)

        def history_side_effect(ticker, period, interval):
            if ticker == "EMA":
                return df_ema
            elif ticker == "VOL":
                return df_vol
            elif ticker == "BB":
                return df_bb
            elif ticker == "MACD":
                return df_macd
            elif ticker == "PROX":
                return df_prox
            return df_rsi

        mock_fetch_history.side_effect = history_side_effect

        alerts_to_set = [
            ("TEST", "RSI", "<", "30"),
            ("TEST", "PE", "<", "MEDIAN"),
            ("TEST", "RATING", "==", "Strong Buy"),
            ("TEST", "PRICE", "<", "150"),
            ("TEST", "SMA", "<", "0"),
            ("EMA", "EMA_CROSS", ">", "0"),
            ("VOL", "VOL_BREAKOUT", ">", "2.0"),
            ("BB", "BB_CROSS", ">", "0"),
            ("MACD", "MACD_CROSS", ">", "0"),
            ("PROX", "52W_PROXIMITY", ">", "3.0")
        ]

        alert_ids = []
        for ticker, cond, op, val in alerts_to_set:
            res = self.client.post("/api/alerts/set", json={
                "ticker": ticker,
                "condition_type": cond,
                "operator": op,
                "value": val
            })
            self.assertEqual(res.status_code, 200)
            alert_ids.append(res.json()["id"])

        check_res = self.client.get("/api/alerts/check")
        self.assertEqual(check_res.status_code, 200)
        check_data = check_res.json()

        for aid in alert_ids:
            alert = next((a for a in check_data["alerts"] if a["id"] == aid), None)
            self.assertIsNotNone(alert, f"Alert ID {aid} was not found in response.")
            self.assertTrue(alert["triggered"], f"Alert of type {alert['condition_type']} failed to trigger.")

    @patch("backend.main.get_complete_financial_profile")
    @patch("backend.main.fetch_history_df")
    def test_crossover_triggers_with_nonzero_buffers(self, mock_fetch_history, mock_get_profile):
        """Verifies DMA_CROSS, EMA_CROSS, MACD_CROSS, and SMA with non-zero threshold buffers."""
        mock_get_profile.return_value = {
            "fundamentals": {"current_price": 100.0},
            "technicals": {"rsi": 50.0, "sma_200": 90.0}
        }

        dates = pd.date_range(end="2026-06-09", periods=250, freq="D")
        
        df_dma = pd.DataFrame({"Close": [100.0]*200 + [80.0]*49 + [2000.0], "Volume": [100000]*250}, index=dates)
        df_ema = pd.DataFrame({"Close": [100.0]*200 + [80.0]*49 + [2000.0], "Volume": [100000]*250}, index=dates)
        df_macd = pd.DataFrame({"Close": [100.0]*248 + [95.0] + [150.0], "Volume": [100000]*250}, index=dates)
        df_dma_death = pd.DataFrame({"Close": [100.0]*200 + [90.0]*49 + [20.0], "Volume": [100000]*250}, index=dates)

        def history_side_effect(ticker, period, interval):
            if ticker == "DMA_GOLD_TRIG":
                return df_dma
            elif ticker == "DMA_GOLD_NOTRIG":
                return df_dma
            elif ticker == "DMA_DEATH_TRIG":
                return df_dma_death
            elif ticker == "DMA_DEATH_NOTRIG":
                return df_dma_death
            elif ticker == "EMA_GOLD_TRIG":
                return df_ema
            elif ticker == "EMA_GOLD_NOTRIG":
                return df_ema
            elif ticker == "MACD_TRIG":
                return df_macd
            elif ticker == "MACD_NOTRIG":
                return df_macd
            return df_dma

        mock_fetch_history.side_effect = history_side_effect

        alerts_to_test = [
            ("DMA_GOLD_TRIG", "DMA_CROSS", ">", "5.0", True),
            ("DMA_GOLD_NOTRIG", "DMA_CROSS", ">", "20.0", False),
            ("DMA_DEATH_TRIG", "DMA_CROSS", "<", "8.0", True),
            ("DMA_DEATH_NOTRIG", "DMA_CROSS", "<", "10.0", False),
            ("EMA_GOLD_TRIG", "EMA_CROSS", ">", "2.0", True),
            ("EMA_GOLD_NOTRIG", "EMA_CROSS", ">", "50.0", False),
            ("MACD_TRIG", "MACD_CROSS", ">", "1.0", True),
            ("MACD_NOTRIG", "MACD_CROSS", ">", "4.0", False),
            ("SMA_TRIG", "SMA", ">", "5.0", True),
            ("SMA_NOTRIG", "SMA", ">", "15.0", False),
        ]

        alert_ids = []
        for ticker, cond, op, val, expected_trigger in alerts_to_test:
            res = self.client.post("/api/alerts/set", json={
                "ticker": ticker,
                "condition_type": cond,
                "operator": op,
                "value": val
            })
            self.assertEqual(res.status_code, 200)
            alert_ids.append((res.json()["id"], expected_trigger, cond, val))

        check_res = self.client.get("/api/alerts/check")
        self.assertEqual(check_res.status_code, 200)
        check_data = check_res.json()

        for aid, expected_trigger, cond, val in alert_ids:
            alert = next((a for a in check_data["alerts"] if a["id"] == aid), None)
            self.assertIsNotNone(alert, f"Alert ID {aid} not found.")
            self.assertEqual(alert["triggered"], 1 if expected_trigger else 0,
                             f"Alert {cond} with value {val} trigger state mismatch: expected {expected_trigger}, got {alert['triggered']}")

    @patch("backend.llm_config.call_llm")
    def test_parse_natural_language_prompt(self, mock_call_llm):
        """Verifies parsing of plain English alert builder request."""
        mock_call_llm.return_value = '{"ticker_query": "RELIANCE", "condition_type": "PRICE", "operator": ">", "value": "3500"}'
        
        response = self.client.post("/api/alerts/parse-nl", json={
            "prompt": "Alert me if Reliance Industries goes above Rs. 3500"
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["ticker"], "RELIANCE.NS")
        self.assertEqual(data["condition_type"], "PRICE")
        self.assertEqual(data["operator"], ">")
        self.assertEqual(data["value"], "3500")

    @patch("backend.llm_config.call_llm")
    @patch("backend.main.get_complete_financial_profile")
    @patch("backend.main.fetch_history_df")
    def test_alerts_contextual_warning_generation(self, mock_fetch_history, mock_get_profile, mock_call_llm):
        """Verifies that triggered alerts generate an AI contextual warning."""
        mock_get_profile.return_value = {
            "fundamentals": {"current_price": 350.0},
            "technicals": {"rsi": 82.0, "sma_200": 300.0}
        }
        mock_fetch_history.return_value = pd.DataFrame({"Close": [300, 310, 320, 330, 350]})
        mock_call_llm.return_value = "ALERT: INFY.NS crossed RSI > 80. Extremely overbought, watch key consolidation support."

        # Setup standard alert
        res = self.client.post("/api/alerts/set", json={
            "ticker": "INFY.NS",
            "condition_type": "RSI",
            "operator": ">",
            "value": "80.0"
        })
        self.assertEqual(res.status_code, 200)
        alert_id = res.json()["id"]

        # Run alert check sweep
        check_res = self.client.get("/api/alerts/check")
        self.assertEqual(check_res.status_code, 200)
        check_data = check_res.json()

        # Find the triggered alert and assert context warning is filled
        alert = next((a for a in check_data["alerts"] if a["id"] == alert_id), None)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["triggered"], 1)
        self.assertEqual(alert["ai_context"], "ALERT: INFY.NS crossed RSI > 80. Extremely overbought, watch key consolidation support.")


class TestRuleScannerAPI(unittest.TestCase):
    """Tests for the Rule Scanner (Custom Trigger-Condition Scanner) API endpoints."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        main.init_db()

    def setUp(self):
        """Insert mock universe and cached profiles for scanner tests."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM screener_universe")
            cursor.execute("DELETE FROM cached_profiles")

            # Stock 1: Low RSI, low PE, value candidate
            cursor.execute(
                "INSERT INTO screener_universe (symbol, base_symbol, company_name, sector, cap_type, last_rebalanced) VALUES (?, ?, ?, ?, ?, ?)",
                ("INFY.NS", "INFY", "Infosys Ltd", "Technology", "large", "2026-06-01T00:00:00")
            )
            infy_profile = {
                "fundamentals": {
                    "current_price": 1400.0,
                    "pe_ratio": 22.0,
                    "year_high": 1800.0,
                    "year_low": 1200.0,
                    "debt_to_equity": 0.05,
                    "altman_z": 3.2,
                    "target_discount": 18.5,
                    "cfo_pat_divergence": 0.85,
                    "dividend_yield": 4.5
                },
                "technicals": {
                    "rsi": 28.0,
                    "sma_200": 1450.0,
                    "sma_50": 1420.0,
                    "ema_50": 1415.0,
                    "ema_200": 1440.0,
                    "volume_ratio": 2.5,
                    "bb_lower": 1410.0,
                    "bb_upper": 1500.0,
                    "macd": -2.5,
                    "signal": -1.0,
                    "atr": 45.0
                },
                "analysis": {
                    "recommendation": "BUY",
                    "score": 78,
                    "composite_score": 78
                }
            }
            cursor.execute(
                "INSERT INTO cached_profiles (symbol, profile_json) VALUES (?, ?)",
                ("INFY.NS", json.dumps(infy_profile))
            )

            # Stock 2: High RSI, high PE, growth stock
            cursor.execute(
                "INSERT INTO screener_universe (symbol, base_symbol, company_name, sector, cap_type, last_rebalanced) VALUES (?, ?, ?, ?, ?, ?)",
                ("TCS.NS", "TCS", "Tata Consultancy Services", "Technology", "large", "2026-06-01T00:00:00")
            )
            tcs_profile = {
                "fundamentals": {
                    "current_price": 3800.0,
                    "pe_ratio": 32.0,
                    "year_high": 4200.0,
                    "year_low": 3000.0,
                    "debt_to_equity": 0.1,
                    "altman_z": 4.5,
                    "target_discount": 5.0,
                    "cfo_pat_divergence": 1.1,
                    "dividend_yield": 2.0
                },
                "technicals": {
                    "rsi": 72.0,
                    "sma_200": 3600.0,
                    "sma_50": 3750.0,
                    "ema_50": 3740.0,
                    "ema_200": 3610.0,
                    "volume_ratio": 0.8,
                    "bb_lower": 3500.0,
                    "bb_upper": 3780.0,
                    "macd": 15.0,
                    "signal": 10.0,
                    "atr": 80.0
                },
                "analysis": {
                    "recommendation": "HOLD",
                    "score": 65,
                    "composite_score": 65
                }
            }
            cursor.execute(
                "INSERT INTO cached_profiles (symbol, profile_json) VALUES (?, ?)",
                ("TCS.NS", json.dumps(tcs_profile))
            )

            # Stock 3: Mid-cap stock in different sector
            cursor.execute(
                "INSERT INTO screener_universe (symbol, base_symbol, company_name, sector, cap_type, last_rebalanced) VALUES (?, ?, ?, ?, ?, ?)",
                ("BHARATFORG.NS", "BHARATFORG", "Bharat Forge Ltd", "Industrials", "mid", "2026-06-01T00:00:00")
            )
            bf_profile = {
                "fundamentals": {
                    "current_price": 950.0,
                    "pe_ratio": 40.0,
                    "year_high": 1100.0,
                    "year_low": 700.0,
                    "debt_to_equity": 0.8,
                    "altman_z": 1.5,
                    "target_discount": 12.0,
                    "cfo_pat_divergence": 0.45,
                    "dividend_yield": 1.2
                },
                "technicals": {
                    "rsi": 55.0,
                    "sma_200": 900.0,
                    "sma_50": 930.0,
                    "volume_ratio": 1.2,
                    "bb_lower": 880.0,
                    "bb_upper": 980.0,
                    "macd": 3.0,
                    "signal": 2.5,
                    "atr": 30.0
                },
                "analysis": {
                    "recommendation": "STRONG BUY",
                    "score": 82,
                    "composite_score": 82
                }
            }
            cursor.execute(
                "INSERT INTO cached_profiles (symbol, profile_json) VALUES (?, ?)",
                ("BHARATFORG.NS", json.dumps(bf_profile))
            )

            conn.commit()

    def tearDown(self):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM screener_universe")
            cursor.execute("DELETE FROM cached_profiles")
            conn.commit()

    # ─── NL Prompt Parsing Tests ────────────────────────────────────────

    @patch("backend.llm_config.call_llm")
    def test_parse_nl_scan_rsi_prompt(self, mock_llm):
        """Verifies NL parser correctly extracts RSI condition from plain English."""
        mock_llm.return_value = json.dumps({
            "condition_type": "RSI",
            "operator": "<",
            "value": "35",
            "universe": "mid"
        })

        response = self.client.post("/api/screener/parse-nl-scan", json={
            "prompt": "Find mid cap stocks with RSI below 35"
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["condition_type"], "RSI")
        self.assertEqual(data["operator"], "<")
        self.assertEqual(data["value"], "35")
        self.assertEqual(data["universe"], "mid")

    @patch("backend.llm_config.call_llm")
    def test_parse_nl_scan_golden_cross(self, mock_llm):
        """Verifies NL parser correctly extracts DMA_CROSS condition from crossover prompt."""
        mock_llm.return_value = '```json\n{"condition_type": "DMA_CROSS", "operator": ">", "value": "0.0", "universe": "large"}\n```'

        response = self.client.post("/api/screener/parse-nl-scan", json={
            "prompt": "Scan large cap stocks for golden cross"
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["condition_type"], "DMA_CROSS")
        self.assertEqual(data["operator"], ">")
        self.assertEqual(data["universe"], "large")

    @patch("backend.llm_config.call_llm")
    def test_parse_nl_scan_handles_markdown_wrapping(self, mock_llm):
        """Verifies NL parser strips markdown code fences from LLM response."""
        mock_llm.return_value = '```json\n{"condition_type": "PE", "operator": "<", "value": "15", "universe": "all"}\n```'

        response = self.client.post("/api/screener/parse-nl-scan", json={
            "prompt": "Show me stocks with PE less than 15"
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["condition_type"], "PE")
        self.assertEqual(data["value"], "15")

    # ─── Scan Trigger Tests ─────────────────────────────────────────────

    def test_scan_trigger_rsi_below(self):
        """Verifies RSI < 30 scan matches only INFY (RSI=28)."""
        response = self.client.get("/api/screener/scan-trigger?condition_type=RSI&operator=<&value=30&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["matched"], 1)
        self.assertGreater(data["scanned"], 0)
        self.assertEqual(data["results"][0]["symbol"], "INFY.NS")
        self.assertIn("RSI: 28.0", data["results"][0]["trigger_value"])

    def test_scan_trigger_rsi_above(self):
        """Verifies RSI > 70 scan matches only TCS (RSI=72)."""
        response = self.client.get("/api/screener/scan-trigger?condition_type=RSI&operator=>&value=70&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 1)
        self.assertEqual(data["results"][0]["symbol"], "TCS.NS")

    def test_scan_trigger_pe_below(self):
        """Verifies PE < 25 scan matches only INFY (PE=22)."""
        response = self.client.get("/api/screener/scan-trigger?condition_type=PE&operator=<&value=25&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 1)
        self.assertEqual(data["results"][0]["symbol"], "INFY.NS")

    def test_scan_trigger_pe_above(self):
        """Verifies PE > 35 scan matches only BHARATFORG (PE=40)."""
        response = self.client.get("/api/screener/scan-trigger?condition_type=PE&operator=>&value=35&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 1)
        self.assertEqual(data["results"][0]["symbol"], "BHARATFORG.NS")

    def test_scan_trigger_rating_filter(self):
        """Verifies RATING == 'BUY' matches only INFY."""
        response = self.client.get("/api/screener/scan-trigger?condition_type=RATING&operator===&value=BUY&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 1)
        self.assertEqual(data["results"][0]["symbol"], "INFY.NS")
        self.assertEqual(data["results"][0]["rating"], "BUY")

    def test_scan_trigger_price_below(self):
        """Verifies PRICE < 1000 matches only BHARATFORG (price=950)."""
        response = self.client.get("/api/screener/scan-trigger?condition_type=PRICE&operator=<&value=1000&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 1)
        self.assertEqual(data["results"][0]["symbol"], "BHARATFORG.NS")

    def test_scan_trigger_sma_below_200(self):
        """Verifies SMA deviation < 0 matches INFY (price 1400 < SMA200 1450 = -3.4%)."""
        response = self.client.get("/api/screener/scan-trigger?condition_type=SMA&operator=<&value=0&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # INFY: (1400-1450)/1450 * 100 = -3.4% < 0 => match
        # TCS: (3800-3600)/3600 * 100 = +5.5% > 0 => no match
        # BHARATFORG: (950-900)/900 * 100 = +5.5% > 0 => no match
        self.assertEqual(data["matched"], 1)
        self.assertEqual(data["results"][0]["symbol"], "INFY.NS")

    def test_scan_trigger_volume_breakout(self):
        """Verifies VOL_BREAKOUT > 2.0 matches only INFY (vol_ratio=2.5)."""
        response = self.client.get("/api/screener/scan-trigger?condition_type=VOL_BREAKOUT&operator=>&value=2.0&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 1)
        self.assertEqual(data["results"][0]["symbol"], "INFY.NS")

    def test_scan_trigger_macd_cross_bullish(self):
        """Verifies MACD_CROSS > 0 matches TCS (MACD 15 - Signal 10 = 5 > 0) and BHARATFORG (3-2.5=0.5)."""
        response = self.client.get("/api/screener/scan-trigger?condition_type=MACD_CROSS&operator=>&value=0&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # TCS: 15 - 10 = 5 > 0, BHARATFORG: 3 - 2.5 = 0.5 > 0, INFY: -2.5 - (-1.0) = -1.5 < 0
        self.assertEqual(data["matched"], 2)
        symbols = [r["symbol"] for r in data["results"]]
        self.assertIn("TCS.NS", symbols)
        self.assertIn("BHARATFORG.NS", symbols)

    def test_scan_trigger_bb_lower_touch(self):
        """Verifies BB_CROSS < 0 matches INFY (price 1400 < bb_lower 1410)."""
        response = self.client.get("/api/screener/scan-trigger?condition_type=BB_CROSS&operator=<&value=0&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 1)
        self.assertEqual(data["results"][0]["symbol"], "INFY.NS")

    def test_scan_trigger_bb_upper_touch(self):
        """Verifies BB_CROSS > 0 matches TCS (price 3800 >= bb_upper 3780)."""
        response = self.client.get("/api/screener/scan-trigger?condition_type=BB_CROSS&operator=>&value=0&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 1)
        self.assertEqual(data["results"][0]["symbol"], "TCS.NS")

    def test_scan_trigger_52w_near_high(self):
        """Verifies 52W_PROXIMITY > 15 (within 15% of 52w high) matches TCS."""
        # TCS: (4200-3800)/4200 * 100 = 9.5% < 15% => match
        # INFY: (1800-1400)/1800 * 100 = 22.2% > 15% => no match
        # BHARATFORG: (1100-950)/1100 * 100 = 13.6% < 15% => match
        response = self.client.get("/api/screener/scan-trigger?condition_type=52W_PROXIMITY&operator=>&value=15&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 2)
        symbols = [r["symbol"] for r in data["results"]]
        self.assertIn("TCS.NS", symbols)
        self.assertIn("BHARATFORG.NS", symbols)

    def test_scan_trigger_fib_level(self):
        """Verifies FIB_LEVEL scan checks proximity to any Fibonacci level."""
        # BHARATFORG: high=1100, low=700, swing=400
        # Fib 38.2% = 1100 - 0.382*400 = 947.2 => price 950, diff = 0.3% < 2% => match
        response = self.client.get("/api/screener/scan-trigger?condition_type=FIB_LEVEL&operator===&value=2&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(data["matched"], 1)
        symbols = [r["symbol"] for r in data["results"]]
        self.assertIn("BHARATFORG.NS", symbols)

    def test_scan_trigger_altman_z(self):
        """Verifies ALTMAN_Z condition scan works."""
        # TCS has altman_z = 4.5, INFY has altman_z = 3.2, BHARATFORG has altman_z = 1.5
        # Scan for altman_z > 3.0 => TCS & INFY
        response = self.client.get("/api/screener/scan-trigger?condition_type=ALTMAN_Z&operator=>&value=3.0&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 2)
        symbols = [r["symbol"] for r in data["results"]]
        self.assertIn("TCS.NS", symbols)
        self.assertIn("INFY.NS", symbols)

    def test_scan_trigger_target_discount(self):
        """Verifies TARGET_DISCOUNT condition scan works."""
        # INFY target_discount = 18.5, BHARATFORG target_discount = 12.0, TCS target_discount = 5.0
        # Scan for target_discount > 10.0 => INFY & BHARATFORG
        response = self.client.get("/api/screener/scan-trigger?condition_type=TARGET_DISCOUNT&operator=>&value=10.0&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 2)
        symbols = [r["symbol"] for r in data["results"]]
        self.assertIn("INFY.NS", symbols)
        self.assertIn("BHARATFORG.NS", symbols)

    def test_scan_trigger_cfo_pat_divergence(self):
        """Verifies CFO_PAT_DIVERGENCE condition scan works."""
        # BHARATFORG cfo_pat_divergence = 0.45, INFY cfo_pat_divergence = 0.85, TCS cfo_pat_divergence = 1.1
        # Scan for cfo_pat_divergence < 0.6 => BHARATFORG
        response = self.client.get("/api/screener/scan-trigger?condition_type=CFO_PAT_DIVERGENCE&operator=<&value=0.6&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 1)
        self.assertEqual(data["results"][0]["symbol"], "BHARATFORG.NS")

    def test_scan_trigger_dividend_yield_floor(self):
        """Verifies DIVIDEND_YIELD_FLOOR condition scan works."""
        # INFY dividend_yield = 4.5, TCS dividend_yield = 2.0, BHARATFORG dividend_yield = 1.2
        # Scan for dividend_yield >= 3.0 => INFY
        response = self.client.get("/api/screener/scan-trigger?condition_type=DIVIDEND_YIELD_FLOOR&operator=>&value=3.0&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 1)
        self.assertEqual(data["results"][0]["symbol"], "INFY.NS")

    def test_scan_trigger_atr_volatility_shock(self):
        """Verifies ATR_VOLATILITY_SHOCK condition scan works."""
        # TCS atr = 80.0, INFY atr = 45.0, BHARATFORG atr = 30.0
        # Scan for atr > 50.0 => TCS
        response = self.client.get("/api/screener/scan-trigger?condition_type=ATR_VOLATILITY_SHOCK&operator=>&value=50.0&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 1)
        self.assertEqual(data["results"][0]["symbol"], "TCS.NS")

    # ─── Universe Filter Tests ──────────────────────────────────────────

    def test_scan_trigger_universe_filter_large(self):
        """Verifies universe=large only scans large-cap stocks."""
        response = self.client.get("/api/screener/scan-trigger?condition_type=RSI&operator=>&value=0&universe=large")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Only INFY and TCS are large cap
        self.assertEqual(data["scanned"], 2)
        symbols = [r["symbol"] for r in data["results"]]
        self.assertNotIn("BHARATFORG.NS", symbols)

    def test_scan_trigger_universe_filter_mid(self):
        """Verifies universe=mid only scans mid-cap stocks."""
        response = self.client.get("/api/screener/scan-trigger?condition_type=RSI&operator=>&value=0&universe=mid")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["scanned"], 1)
        self.assertEqual(data["results"][0]["symbol"], "BHARATFORG.NS")

    def test_scan_trigger_empty_universe(self):
        """Verifies scanner handles an empty universe gracefully."""
        response = self.client.get("/api/screener/scan-trigger?condition_type=RSI&operator=<&value=30&universe=small")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 0)
        self.assertEqual(data["results"], [])

    # ─── Result Structure Tests ─────────────────────────────────────────

    def test_scan_trigger_result_structure(self):
        """Verifies each result object contains all expected fields."""
        response = self.client.get("/api/screener/scan-trigger?condition_type=RSI&operator=<&value=30&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 1)

        result = data["results"][0]
        expected_keys = ["symbol", "company_name", "sector", "cap_type", "price", "pe", "rsi", "trigger_value", "rating", "score", "de_ratio"]
        for key in expected_keys:
            self.assertIn(key, result, f"Missing key: {key}")

        self.assertEqual(result["symbol"], "INFY.NS")
        self.assertEqual(result["company_name"], "Infosys Ltd")
        self.assertEqual(result["sector"], "Technology")
        self.assertEqual(result["cap_type"], "large")
        self.assertEqual(result["price"], 1400.0)
        self.assertEqual(result["pe"], 22.0)
        self.assertEqual(result["rsi"], 28.0)
        self.assertEqual(result["rating"], "BUY")
        self.assertEqual(result["score"], 78.0)
        self.assertEqual(result["de_ratio"], 0.05)

    def test_scan_trigger_response_metadata(self):
        """Verifies the top-level response contains correct metadata."""
        response = self.client.get("/api/screener/scan-trigger?condition_type=PE&operator=<&value=25&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["universe"], "all")
        self.assertEqual(data["condition"], "PE < 25")
        self.assertIsInstance(data["scanned"], int)
        self.assertIsInstance(data["matched"], int)

    # ─── Synthesis Tests ────────────────────────────────────────────────

    @patch("backend.llm_config.call_llm")
    def test_scan_synthesis_generation(self, mock_llm):
        """Verifies AI synthesis endpoint generates a summary from scan results."""
        mock_llm.return_value = "The RSI < 30 scan reveals concentration in the Technology sector with INFY showing deep oversold momentum at RSI 28. Valuation remains attractive at PE 22 with strong institutional sentiment reflected in the BUY rating."

        response = self.client.post("/api/screener/scan-synthesis", json={
            "results": [
                {"symbol": "INFY.NS", "trigger_value": "RSI: 28.0", "sector": "Technology", "cap_type": "large", "pe": 22.0, "rsi": 28.0, "rating": "BUY"}
            ],
            "condition_desc": "RSI < 30 (Universe: all)"
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("Technology", data["synthesis"])
        self.assertIn("RSI", data["synthesis"])

    @patch("backend.llm_config.call_llm")
    def test_scan_synthesis_truncates_to_20_results(self, mock_llm):
        """Verifies synthesis endpoint caps input to 20 results maximum."""
        mock_llm.return_value = "Large scan synthesis."

        results = [{"symbol": f"STOCK{i}.NS", "sector": "Technology"} for i in range(30)]
        response = self.client.post("/api/screener/scan-synthesis", json={
            "results": results,
            "condition_desc": "RSI < 50"
        })
        self.assertEqual(response.status_code, 200)

        # Verify the LLM was called with at most 20 results in the prompt
        call_args = mock_llm.call_args
        user_prompt = call_args[0][2]
        stock_lines = [line for line in user_prompt.split("\n") if line.strip().startswith("- STOCK")]
        self.assertLessEqual(len(stock_lines), 20)

    # ─── DMA/EMA Cross Tests ───────────────────────────────────────────

    def test_scan_trigger_dma_golden_cross(self):
        """Verifies DMA_CROSS > 0 matches stocks where SMA50 > SMA200 (golden cross)."""
        # TCS: SMA50=3750, SMA200=3600 => diff = +4.2% > 0 => match
        # BHARATFORG: SMA50=930, SMA200=900 => diff = +3.3% > 0 => match
        # INFY: SMA50=1420, SMA200=1450 => diff = -2.1% < 0 => no match
        response = self.client.get("/api/screener/scan-trigger?condition_type=DMA_CROSS&operator=>&value=0&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 2)
        symbols = [r["symbol"] for r in data["results"]]
        self.assertIn("TCS.NS", symbols)
        self.assertIn("BHARATFORG.NS", symbols)
        self.assertNotIn("INFY.NS", symbols)

    def test_scan_trigger_dma_death_cross(self):
        """Verifies DMA_CROSS < 0 matches stocks where SMA50 < SMA200 (death cross)."""
        # INFY: SMA50=1420, SMA200=1450 => diff = -2.1% < 0 => match
        response = self.client.get("/api/screener/scan-trigger?condition_type=DMA_CROSS&operator=<&value=0&universe=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["matched"], 1)
        self.assertEqual(data["results"][0]["symbol"], "INFY.NS")

    def test_generate_swot_analysis_and_price_performance(self):
        """Verifies swot rules engine and calculate_price_performance run correctly."""
        from backend.financial_utils import generate_swot_analysis, calculate_price_performance
        
        # Test SWOT with mock inputs
        screener_data = {
            "ratios": {
                "Stock P/E": 12.0,
                "ROE": 22.0,
                "ROCE": 25.0,
                "Debt to Equity": 0.0
            },
            "shareholding": {
                "Promoter": 65.0,
                "Promoter_prev": 64.0,
                "FIIs": 12.0,
                "FIIs_prev": 13.0,
                "Promoter Pledging %": 0.0
            },
            "quarterly_results": {
                "sales": [100, 110, 120, 130],
                "net_profit": [10, 12, 14, 16],
                "eps": [1.0, 1.2, 1.4, 1.6],
                "opm": [10.0, 11.0, 11.5, 12.0]
            }
        }
        technicals = {
            "current_price": 100.0,
            "high_52w": 102.0,
            "low_52w": 50.0,
            "dist_high_52w_pct": 2.0,
            "dist_low_52w_pct": 100.0,
            "volume_vs_avg20": 1.8,
            "rsi": 55.0,
            "sma_200": 80.0,
            "sma_50": 95.0,
            "ema_20": 98.0
        }
        dcf_data = {
            "margin_of_safety": 25.0
        }
        performance = {
            "1W": 5.0,
            "1M": 18.0,
            "3M": 40.0,
            "YTD": 35.0,
            "1Y": 110.0,
            "3Y": 250.0
        }
        
        swot = generate_swot_analysis("INFY.NS", screener_data, technicals, dcf_data, performance)
        self.assertIn("Promoter Increasing Holding QoQ", swot["strengths"])
        self.assertIn("Company with No Debt (Debt-Free)", swot["strengths"])
        self.assertIn("Company with Zero Promoter Pledge", swot["strengths"])
        self.assertIn("Increasing Revenue every Quarter for the past 4 Quarters", swot["strengths"])
        self.assertIn("Increasing profits every quarter for the past 4 quarters", swot["strengths"])
        self.assertIn("Quarterly EPS Improving for last 3 Quarters", swot["strengths"])
        self.assertIn("Growth in operating margins (OPM% QoQ)", swot["strengths"])
        self.assertIn("Growth in Net Profit with increasing Profit Margin (QoQ)", swot["strengths"])
        self.assertIn("Strong QoQ Net Profit Growth in recent result", swot["strengths"])
        self.assertIn("Multi-Year Wealth Creator (+250.0% Return over 3 Years)", swot["strengths"])
        
        self.assertIn("FII/FPI decreased their shareholding last quarter", swot["weaknesses"])
        
        self.assertIn("Highest Recovery from 52 Week Low (+100.0%)", swot["opportunities"])
        self.assertIn("Buying with Strong Volumes (1.8x of 20D average)", swot["opportunities"])
        self.assertIn("Trading Above 200 DMA (Long-term Bullish)", swot["opportunities"])

        # Test calculate_price_performance with mock yfinance stock
        import pandas as pd
        mock_stock = MagicMock()
        idx = pd.date_range(end="2026-06-15", periods=50, freq="7D")
        closes = [100.0 + i * 2.0 for i in range(50)]
        mock_stock.history.return_value = pd.DataFrame({"Close": closes}, index=idx)
        
        perf_res = calculate_price_performance(mock_stock)
        self.assertIn("1W", perf_res)
        self.assertIn("1Y", perf_res)
        self.assertIn("3Y", perf_res)


class TestWhatsAppDailyWrapup(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        main.init_db()
        from backend.events_scraper import init_events_table
        init_events_table()

    def setUp(self):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM alert_settings WHERE key LIKE 'daily_wrapup_%'")
            cursor.execute("DELETE FROM portfolio_items")
            cursor.execute("DELETE FROM watchlist_items")
            cursor.execute("DELETE FROM stock_events")
            cursor.execute("DELETE FROM cached_trades")
            conn.commit()

    def test_settings_flow(self):
        """Verifies retrieving and saving daily wrap-up schedule settings."""
        # 1. Check default seeded state
        res = self.client.get("/api/alerts/daily-wrapup/settings")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("enabled", data)
        self.assertIn("time", data)
        self.assertIn("persona", data)
        self.assertIn("include_events", data)
        self.assertIn("include_deals", data)

        # 2. Save new settings
        payload = {"enabled": False, "time": "17:30", "persona": "momentum", "include_events": False, "include_deals": False}
        post_res = self.client.post("/api/alerts/daily-wrapup/settings", json=payload)
        self.assertEqual(post_res.status_code, 200)
        self.assertEqual(post_res.json()["status"], "success")

        # 3. Retrieve and verify updated settings
        get_res = self.client.get("/api/alerts/daily-wrapup/settings")
        self.assertEqual(get_res.status_code, 200)
        updated = get_res.json()
        self.assertFalse(updated["enabled"])
        self.assertEqual(updated["time"], "17:30")
        self.assertEqual(updated["persona"], "momentum")
        self.assertFalse(updated["include_events"])
        self.assertFalse(updated["include_deals"])

    @patch("backend.daily_wrapup.yf.download")
    @patch("backend.daily_wrapup.call_llm")
    def test_trigger_wrapup(self, mock_llm, mock_yf_download):
        """Verifies compilation flow of the wrap-up summary."""
        # Setup mocks
        mock_llm.return_value = "AI commentary: Markets consolidated inside positive momentum channels."
        
        import pandas as pd
        closes = [100.0, 105.0]
        dates = pd.date_range(end="2026-06-15", periods=2)
        mock_df = pd.DataFrame({"Close": closes}, index=dates)
        
        mock_yf_download.return_value = mock_df

        # Seed a portfolio item
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO watchlists (id, name) VALUES (?, ?)",
                (1, "Default Watchlist")
            )
            cursor.execute(
                "INSERT INTO portfolio_items (symbol, name, sector, quantity, purchase_price, transaction_type) VALUES (?, ?, ?, ?, ?, ?)",
                ("INFY.NS", "Infosys Ltd", "Technology", 10, 100.0, "buy")
            )
            cursor.execute(
                "INSERT INTO watchlist_items (watchlist_id, symbol, name, sector) VALUES (?, ?, ?, ?)",
                (1, "TCS.NS", "Tata Consultancy Services", "Technology")
            )
            
            # Seed mock event for INFY
            from datetime import date, timedelta
            tomorrow_str = (date.today() + timedelta(days=1)).isoformat()
            cursor.execute(
                """INSERT OR REPLACE INTO stock_events 
                   (symbol, company_name, event_type, event_date, description, details_json, fetched_at) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("INFY", "Infosys Ltd", "quarterly_results", tomorrow_str, "Q1 Results", "{}", "2026-07-06T00:00:00Z")
            )
            
            # Seed mock deals for INFY
            today_str = date.today().isoformat()
            deal_data = {
                "insider_trades": [{
                    "date": today_str,
                    "person": "Promoter Guy",
                    "type": "Buy",
                    "quantity": 1000,
                    "price": 1500.0,
                    "value": 1500000
                }],
                "bulk_deals": [],
                "block_deals": [],
                "sast_deals": []
            }
            cursor.execute(
                "INSERT OR REPLACE INTO cached_trades (symbol, data_json, last_updated) VALUES (?, ?, ?)",
                ("INFY", json.dumps(deal_data), "2026-07-06 00:00:00")
            )
            conn.commit()

        # Trigger wrap-up
        res = self.client.post("/api/alerts/daily-wrapup/trigger")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("message_body", data)
        self.assertIn("APEX EQUITIES WORKSTATION", data["message_body"])
        self.assertIn("PORTFOLIO DAILY STATUS", data["message_body"])
        self.assertIn("UPCOMING PORTFOLIO EVENTS", data["message_body"])
        self.assertIn("PORTFOLIO INSIDER FLOWS", data["message_body"])
        self.assertIn("AI COPILOT BRIEFING", data["message_body"])

    def test_screener_cookie_endpoints(self):
        """Verifies cookie setting CRUD API."""
        # 1. Post a new cookie
        res = self.client.post("/api/settings/screener-cookie", json={"cookie": "test_cookie_12345"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "success"})

        # 2. Get the cookie
        res_get = self.client.get("/api/settings/screener-cookie")
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.json(), {"cookie": "test_cookie_12345"})

    @patch("backend.shareholding_scraper.scrape_shareholding_pattern")
    def test_shareholding_endpoint(self, mock_scrape):
        """Verifies shareholding endpoint loads from cache/scraper."""
        mock_scrape.return_value = {
            "quarters": ["Jun 2026", "Sep 2026"],
            "categories": {
                "Promoters": [50.0, 50.0],
                "FIIs": [15.0, 16.0],
                "DIIs": [15.0, 14.0],
                "Public": [20.0, 20.0]
            },
            "detailed": {
                "promoters": {},
                "fii": {},
                "dii": {
                    "SBI Bluechip Fund": {"Jun 2026": 2.5, "Sep 2026": 2.6}
                },
                "public": {}
            }
        }

        # Clear cache first to ensure cache-miss scrapes
        with get_db() as conn:
            conn.execute("DELETE FROM cached_shareholdings")
            conn.commit()

        # Query shareholding for INFY
        res = self.client.get("/api/stocks/INFY/shareholding")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("quarters", data)
        self.assertEqual(data["quarters"], ["Jun 2026", "Sep 2026"])
        self.assertEqual(data["categories"]["Promoters"], [50.0, 50.0])
        
        # Verify it cached the result
        with get_db() as conn:
            row = conn.execute("SELECT data_json FROM cached_shareholdings WHERE symbol = 'INFY'").fetchone()
            self.assertIsNotNone(row)
            cached_data = json.loads(row[0])
            self.assertEqual(cached_data["quarters"], ["Jun 2026", "Sep 2026"])


if __name__ == "__main__":
    unittest.main()
