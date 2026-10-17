"""
backend/test_shark_radar.py — Integration and Unit Tests for Shark Radar
"""

import sys
import unittest

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from backend.main import get_db
from backend.shark_scraper import (
    init_shark_tables,
    sync_shark_directory,
    sync_investor_portfolio,
    get_shark_consensus,
    clone_shark_to_watchlist,
    get_sharks_for_stock
)

class TestSharkRadar(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        print("\n--- Initializing Shark Radar Tables ---")
        init_shark_tables()
        
    def test_01_init_tables(self):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'cached_shark_%'")
            tables = [r[0] for r in cursor.fetchall()]
            self.assertIn("cached_shark_investors", tables)
            self.assertIn("cached_shark_portfolios", tables)
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='shark_stock_lookup'")
            self.assertIsNotNone(cursor.fetchone())
            print("[OK] Database tables verified.")

    def test_02_sync_directory(self):
        print("\n--- Testing Directory Sync ---")
        investors = sync_shark_directory(force=False)
        self.assertIsInstance(investors, list)
        self.assertGreater(len(investors), 10, "Should have parsed at least 10 superstar investors")
        
        first = investors[0]
        self.assertIn("name", first)
        self.assertIn("id", first)
        self.assertIn("net_worth_cr", first)
        print(f"[OK] Successfully synced {len(investors)} superstar investors.")
        print(f"  Sample: {first['name']} (AUM: {first['net_worth_str']}, Stocks: {first['stocks_count']})")

    def test_03_sync_portfolio(self):
        print("\n--- Testing Portfolio Sync (Ashish Kacholia ID: 53746) ---")
        portfolio = sync_investor_portfolio("53746", force=False)
        self.assertIsInstance(portfolio, dict)
        self.assertIn("holdings", portfolio)
        self.assertGreater(len(portfolio["holdings"]), 0)
        
        first_holding = portfolio["holdings"][0]
        print(f"[OK] Synced {len(portfolio['holdings'])} holdings for {portfolio.get('investor_name')}.")
        print(f"  Top holding: {first_holding['stock_name']} ({first_holding['symbol']}) -> Value: {first_holding['holding_value_str']}, Stake: {first_holding['latest_stake_pct']}%")

    def test_04_clone_to_watchlist(self):
        print("\n--- Testing 1-Click Watchlist Clone (Option 6) ---")
        res = clone_shark_to_watchlist("53746", custom_name="Test Shark Ashish Kacholia")
        self.assertEqual(res["status"], "success")
        self.assertGreater(res["total_stocks"], 0)
        print(f"[OK] Watchlist cloned successfully: {res['watchlist_name']} (Watchlist ID: {res['watchlist_id']}, Total Stocks: {res['total_stocks']})")
        
        # Verify in database
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM watchlist_items WHERE watchlist_id = ?", (res["watchlist_id"],))
            count = cursor.fetchone()[0]
            self.assertEqual(count, res["total_stocks"])
            print(f"[OK] Verified {count} items exist in watchlist_items table.")

    def test_05_reverse_stock_lookup(self):
        print("\n--- Testing Reverse Stock Lookup for Profile Research ---")
        portfolio = sync_investor_portfolio("53746")
        symbol = portfolio["holdings"][0]["symbol"]
        sharks = get_sharks_for_stock(symbol)
        self.assertIsInstance(sharks, list)
        self.assertGreater(len(sharks), 0)
        print(f"[OK] Stock {symbol} is held by {len(sharks)} shark(s): {[s['investor_name'] for s in sharks]}")

if __name__ == "__main__":
    unittest.main()
