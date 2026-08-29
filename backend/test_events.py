import unittest
import os
import json
import sqlite3
from datetime import datetime, date, timedelta
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Configure the test database directory
TEST_DIR = os.path.dirname(__file__)
TEST_DATA_DIR = os.path.join(TEST_DIR, "test_data")
os.makedirs(TEST_DATA_DIR, exist_ok=True)
os.environ["DATABASE_DIR"] = TEST_DATA_DIR

from backend.main import app
from backend.events_scraper import (
    _get_db,
    init_events_table,
    _upsert_event,
    _parse_nse_date,
    _classify_corp_action,
    get_market_events,
    get_stock_events_cached,
    is_stock_events_stale,
    cache_stock_events
)

class TestStockEventsCalendar(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        # Clear out the database before each test
        init_events_table()
        with _get_db() as conn:
            conn.execute("DELETE FROM stock_events")
            conn.commit()

    def test_parse_nse_date(self):
        """Verify parsing of various NSE date formats."""
        self.assertEqual(_parse_nse_date("13-Jul-2026"), "2026-07-13")
        self.assertEqual(_parse_nse_date("13-JUL-2026"), "2026-07-13")
        self.assertEqual(_parse_nse_date("13/07/2026"), "2026-07-13")
        self.assertEqual(_parse_nse_date("2026-07-13"), "2026-07-13")
        self.assertIsNone(_parse_nse_date("-"))
        self.assertIsNone(_parse_nse_date(""))

    def test_classify_corp_action(self):
        """Verify classification of corporate actions from subject text."""
        self.assertEqual(_classify_corp_action("Dividend - Rs 18.50 Per Share"), "dividend")
        self.assertEqual(_classify_corp_action("Bonus Issue 1:2"), "bonus")
        self.assertEqual(_classify_corp_action("Sub-division of Shares from Rs 10 to Rs 2"), "split")
        self.assertEqual(_classify_corp_action("Right Issue of shares"), "rights")
        self.assertEqual(_classify_corp_action("Buyback of equity shares"), "buyback")
        self.assertEqual(_classify_corp_action("Annual General Meeting"), "corporate_action")

    def test_database_upsert_and_query(self):
        """Verify database upsert, unique constraints, and cached retrievals."""
        today_str = date.today().isoformat()
        # Insert initial event
        with _get_db() as conn:
            _upsert_event(
                conn,
                symbol="TCS",
                company_name="Tata Consultancy Services Ltd",
                event_type="quarterly_results",
                event_date=today_str,
                description="Q1 Results Board Meeting",
                details={"isin": "INE467B01029"},
                source="nse"
            )
            conn.commit()

        events = get_market_events(days=30)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["symbol"], "TCS")
        self.assertEqual(events[0]["details"]["isin"], "INE467B01029")

        # Test UNIQUE constraint replacement (same symbol, event_type, event_date)
        with _get_db() as conn:
            _upsert_event(
                conn,
                symbol="TCS",
                company_name="Tata Consultancy Services Ltd",
                event_type="quarterly_results",
                event_date=today_str,
                description="Updated Q1 Results Description",
                details={"isin": "INE467B01029", "updated": True},
                source="nse"
            )
            conn.commit()

        events = get_market_events(days=30)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["description"], "Updated Q1 Results Description")
        self.assertTrue(events[0]["details"].get("updated"))

    def test_api_calendar_endpoint(self):
        """Verify the /api/events/calendar REST endpoint."""
        with _get_db() as conn:
            _upsert_event(
                conn, "RELIANCE", "Reliance Industries Ltd", "dividend",
                (date.today() + timedelta(days=5)).isoformat(), "Dividend Rs 9", {}, "nse"
            )
            _upsert_event(
                conn, "INFY", "Infosys Ltd", "quarterly_results",
                (date.today() + timedelta(days=12)).isoformat(), "Q1 Results", {}, "nse"
            )
            _upsert_event(
                conn, "HDFCBANK", "HDFC Bank Ltd", "split",
                (date.today() - timedelta(days=3)).isoformat(), "Split 1:2", {}, "nse"
            )
            conn.commit()

        # Call the endpoint
        resp = self.client.get("/api/events/calendar?days=15")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        self.assertIn("events", data)
        self.assertIn("type_counts", data)
        
        # Verify filtering and counts
        events = data["events"]
        # HDFCBANK is today-3 (within 7 day past window), RELIANCE is today+5, INFY is today+12 (all within 15 days window)
        self.assertEqual(len(events), 3)

        # Filter by type
        resp_div = self.client.get("/api/events/calendar?type=dividend")
        self.assertEqual(resp_div.status_code, 200)
        self.assertEqual(len(resp_div.json()["events"]), 1)
        self.assertEqual(resp_div.json()["events"][0]["symbol"], "RELIANCE")

    @patch("yfinance.Ticker")
    def test_yfinance_enrichment_and_caching(self, mock_ticker_cls):
        """Verify yfinance fallback data fetching, caching, and staleness checks."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker

        future_date1 = datetime.now() + timedelta(days=10)
        future_date2 = datetime.now() + timedelta(days=5)
        future_date3 = datetime.now() + timedelta(days=15)

        # Setup mock .calendar and .info properties
        mock_ticker.calendar = {
            "Earnings Date": [future_date1],
            "Earnings Average": 12.5,
            "Earnings High": 13.0,
            "Earnings Low": 12.0,
            "Revenue Average": 1000000,
        }
        mock_ticker.info = {
            "longName": "Infosys Technologies Ltd",
            "dividendRate": 18.0,
            "dividendYield": 0.012,
            "exDividendDate": int(future_date2.timestamp()),
            "lastSplitDate": int(future_date3.timestamp()),
            "lastSplitFactor": "2:1",
        }

        # Cache events for INFY
        cached = cache_stock_events("INFY.NS")
        self.assertTrue(len(cached) > 0)

        # Verify items loaded in cache
        events = get_stock_events_cached("INFY.NS")
        self.assertTrue(len(events) >= 3)  # Earnings, Dividend, Split

        # Verify staleness checks
        self.assertFalse(is_stock_events_stale("INFY.NS", max_age_hours=12))

        # Call GET endpoint
        resp = self.client.get("/api/events/stock/INFY")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["symbol"], "INFY")
        self.assertTrue(len(resp.json()["events"]) >= 3)

if __name__ == "__main__":
    unittest.main()
