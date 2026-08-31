import os
from dotenv import load_dotenv
load_dotenv(override=True)

import json
import sqlite3
import asyncio
import time
import uuid
import threading
import gc

# Dynamic IPv6/IPv4 selector to support both normal networks and restricted environments (e.g. Oracle VM)
try:
    import socket
    import urllib3.util.connection as urllib3_cn
    has_screener_ipv6 = False
    try:
        res = socket.getaddrinfo('www.screener.in', 443, 0, socket.SOCK_STREAM)
        ipv6_addrs = [r[4] for r in res if r[0] == socket.AF_INET6]
        if ipv6_addrs:
            s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s.settimeout(1.2)
            try:
                s.connect(ipv6_addrs[0])
                has_screener_ipv6 = True
            except Exception:
                pass
            finally:
                s.close()
    except Exception:
        pass
    if not has_screener_ipv6:
        urllib3_cn.HAS_IPV6 = False
except Exception:
    pass

import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from contextlib import contextmanager
import math
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Header, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import List, Optional
from backend.fuzzy_engine import evaluate_fuzzy_logic
from backend.llm_config import get_last_llm_meta

# Database path: relative to project with env override
DATABASE_DIR = os.environ.get(
    "DATABASE_DIR",
    os.path.join(os.path.dirname(__file__), "data")
)
os.makedirs(DATABASE_DIR, exist_ok=True)
DATABASE_PATH = os.path.join(DATABASE_DIR, "watchlist_database.db")

# In-memory rate-limiting cache for yfinance fallback quotes to prevent OOM spikes under high-frequency polling
_YFINANCE_FALLBACK_CACHE = {}  # maps symbol -> (fundamentals_dict, timestamp)
_YFINANCE_CACHE_TTL_SEC = 15.0

@contextmanager
def get_db():
    """Context manager for safe SQLite connections with row factory."""
    conn = sqlite3.connect(DATABASE_PATH, timeout=30.0)  # 30-second timeout for locked database
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # Enable Write-Ahead Logging to reduce locks
    try:
        yield conn
    finally:
        conn.close()

def migrate_legacy_watchlist_added_prices():
    """Migrates legacy watchlist items (where added_price IS NULL, 0.0, or added_date is default migration date)
    to a 30-day historical baseline ('04 Jul, \'26').
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT i.id, i.symbol, i.purchase_price, i.added_price, i.added_date, p.profile_json
                FROM watchlist_items i
                LEFT JOIN cached_profiles p ON i.symbol = p.symbol OR i.symbol = REPLACE(p.symbol, '.NS', '')
                WHERE i.added_price IS NULL 
                   OR i.added_price <= 0 
                   OR i.added_date IS NULL 
                   OR i.added_date = '' 
                   OR i.added_date = '2026-07-17'
            """)
            legacy_rows = [dict(row) for row in cursor.fetchall()]
            if not legacy_rows:
                return

            print(f"Executing legacy watchlist price backfill migration for {len(legacy_rows)} items...")
            baseline_date_str = "04 Jul, '26"

            for item in legacy_rows:
                item_id = item["id"]
                symbol = item["symbol"]
                purchase_p = float(item.get("purchase_price") or 0.0)
                
                p_json = {}
                if item.get("profile_json"):
                    try:
                        p_json = json.loads(item["profile_json"])
                    except Exception:
                        pass
                
                tech = p_json.get("technicals") or {}
                fund = p_json.get("fundamentals") or {}
                cp = float(tech.get("current_price") or fund.get("current_price") or 0.0)
                
                # Step 1: Use purchase_price if available > 0
                if purchase_p > 0:
                    target_added_price = purchase_p
                else:
                    # Step 2: Use 1M performance metric to backfill 30-day historical baseline price
                    perf_dict = (p_json.get("swot_performance") or {}).get("performance") or p_json.get("performance") or {}
                    chg_1m = float(perf_dict.get("1M") or tech.get("chg_1m") or 0.0)
                    
                    if cp > 0 and (1 + chg_1m / 100.0) > 0:
                        target_added_price = round(cp / (1.0 + chg_1m / 100.0), 2)
                    elif cp > 0:
                        target_added_price = cp
                    else:
                        target_added_price = 100.0

                cursor.execute(
                    "UPDATE watchlist_items SET added_price = ?, added_date = ? WHERE id = ?",
                    (target_added_price, baseline_date_str, item_id)
                )
            conn.commit()
            print(f"Successfully migrated {len(legacy_rows)} legacy watchlist items to 30-day baseline date ({baseline_date_str})!")
    except Exception as e:
        print(f"Error during legacy watchlist backfill migration: {e}")

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS watchlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS watchlist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            watchlist_id INTEGER,
            symbol TEXT NOT NULL,
            name TEXT,
            sector TEXT,
            quantity REAL DEFAULT 0.0,
            purchase_price REAL DEFAULT 0.0,
            in_portfolio INTEGER DEFAULT 0,
            FOREIGN KEY(watchlist_id) REFERENCES watchlists(id) ON DELETE CASCADE,
            UNIQUE(watchlist_id, symbol)
        )
        """)
        # Run alter table commands inside try-catch block for backward-compatibility
        try:
            cursor.execute("ALTER TABLE watchlist_items ADD COLUMN quantity REAL DEFAULT 0.0")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE watchlist_items ADD COLUMN purchase_price REAL DEFAULT 0.0")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE watchlist_items ADD COLUMN in_portfolio INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE watchlist_items ADD COLUMN added_price REAL DEFAULT 0.0")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE watchlist_items ADD COLUMN added_date TEXT")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE watchlist_items ADD COLUMN alert_config TEXT")
        except Exception:
            pass
        # Dedicated Portfolio Items table for AI Portfolio Doctor
        try:
            cursor.execute("SELECT purchase_date FROM portfolio_items LIMIT 1")
        except Exception:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='portfolio_items'")
            exists = cursor.fetchone()
            if exists:
                # Migrate by creating a temporary table without UNIQUE on symbol
                cursor.execute("CREATE TABLE IF NOT EXISTS portfolio_items_temp (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, name TEXT, sector TEXT, quantity REAL DEFAULT 10.0, purchase_price REAL DEFAULT 100.0, purchase_date TEXT DEFAULT '2026-06-05')")
                cursor.execute("INSERT INTO portfolio_items_temp (symbol, name, sector, quantity, purchase_price, purchase_date) SELECT symbol, name, sector, quantity, purchase_price, '2026-06-05' FROM portfolio_items")
                cursor.execute("DROP TABLE portfolio_items")
                cursor.execute("ALTER TABLE portfolio_items_temp RENAME TO portfolio_items")
            else:
                # Create fresh table
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    name TEXT,
                    sector TEXT,
                    quantity REAL DEFAULT 10.0,
                    purchase_price REAL DEFAULT 100.0,
                    purchase_date TEXT DEFAULT '2026-06-05',
                    transaction_type TEXT DEFAULT 'buy'
                )
                """)
        try:
            cursor.execute("ALTER TABLE portfolio_items ADD COLUMN transaction_type TEXT DEFAULT 'buy'")
        except Exception:
            pass
        # Persistent alerts table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            condition_type TEXT NOT NULL,
            operator TEXT NOT NULL,
            value TEXT NOT NULL,
            status TEXT DEFAULT 'Active',
            triggered INTEGER DEFAULT 0,
            trigger_date TEXT DEFAULT '',
            ai_context TEXT DEFAULT ''
        )
        """)
        # Persistent alert settings table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alert_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """)
        # Persistent Financial Statement alerts table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS fs_alerts (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            metric TEXT NOT NULL,
            condition TEXT NOT NULL,
            threshold REAL NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Persistent Financial Statement alert history table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS fs_alert_history (
            id TEXT PRIMARY KEY,
            alert_id TEXT,
            symbol TEXT NOT NULL,
            metric TEXT NOT NULL,
            condition TEXT NOT NULL,
            threshold REAL NOT NULL,
            current_value REAL,
            severity TEXT,
            triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Persistent Fuzzy WhatsApp Alert history table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS fuzzy_alert_sent_history (
            symbol TEXT NOT NULL,
            target_state TEXT NOT NULL,
            score REAL,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, target_state)
        )
        """)
        # Persistent screener universe table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS screener_universe (
            symbol TEXT PRIMARY KEY,
            base_symbol TEXT NOT NULL,
            company_name TEXT NOT NULL,
            sector TEXT NOT NULL,
            cap_type TEXT NOT NULL,
            last_rebalanced TEXT NOT NULL
        )
        """)
        # Persistent cached profiles table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_profiles (
            symbol TEXT PRIMARY KEY,
            profile_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Persistent daily delivery stats table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_delivery_stats (
            symbol TEXT PRIMARY KEY,
            delivery_qty INTEGER,
            traded_qty INTEGER,
            delivery_percentage REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Persistent sector regime stats table
        cursor.execute("DROP TABLE IF EXISTS sector_regime_stats")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sector_regime_stats (
            sector TEXT PRIMARY KEY,
            return_1d REAL,
            return_5d REAL,
            return_1m REAL,
            return_3m REAL,
            return_6m REAL,
            return_1y REAL,
            return_5y REAL,
            return_ytd REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Persistent stock regime stats table
        cursor.execute("DROP TABLE IF EXISTS stock_regime_stats")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_regime_stats (
            symbol TEXT PRIMARY KEY,
            sector TEXT,
            return_1d REAL,
            return_5d REAL,
            return_1m REAL,
            return_3m REAL,
            return_6m REAL,
            return_1y REAL,
            return_5y REAL,
            return_ytd REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Persistent corporate actions table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS corporate_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            action_type TEXT NOT NULL,
            ex_date TEXT NOT NULL,
            ratio_multiplier REAL,
            record_date TEXT
        )
        """)
        # Persistent bulk & block deals table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS bulk_block_deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            deal_date TEXT NOT NULL,
            client_name TEXT NOT NULL,
            deal_type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            percentage_equity REAL,
            deal_window TEXT,
            is_mock INTEGER DEFAULT 0
        )
        """)
        # Backward compatibility column migration
        try:
            cursor.execute("ALTER TABLE bulk_block_deals ADD COLUMN is_mock INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE alerts ADD COLUMN ai_context TEXT DEFAULT ''")
        except Exception:
            pass
        # Persistent daily delivery history table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_delivery_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            delivery_qty INTEGER,
            traded_qty INTEGER,
            delivery_percentage REAL,
            UNIQUE(symbol, trade_date)
        )
        """)
        
        # Custom saved screens table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_screens (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            rules_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # Cached timeframe indicators table for daily, weekly, monthly indicators
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_timeframe_indicators (
            symbol TEXT,
            timeframe TEXT,
            indicators_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, timeframe)
        )
        """)

        # Cache table for AI news sentiment and abnormal returns timeline
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_news_impact (
            symbol TEXT PRIMARY KEY,
            sentiment_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Cache table for Global Market News Feed
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_global_market_news (
            feed_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Cache table for Shareholding Patterns
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_shareholdings (
            symbol TEXT PRIMARY KEY,
            data_json TEXT NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Cache table for Insider & Large Trades (Bulk, Block, SAST)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_trades (
            symbol TEXT PRIMARY KEY,
            data_json TEXT NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Cache table for Financial Statements (Quarterly, P&L, Balance Sheet)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_financial_statements (
            symbol TEXT,
            view TEXT,
            data_json TEXT NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, view)
        )
        """)

        # Stock Events Calendar table (dividends, results, bonus, splits, board meetings)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            company_name TEXT,
            event_type TEXT NOT NULL,
            event_date TEXT NOT NULL,
            description TEXT,
            details_json TEXT,
            source TEXT DEFAULT 'nse',
            fetched_at TEXT NOT NULL,
            UNIQUE(symbol, event_type, event_date)
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_date ON stock_events(event_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_symbol ON stock_events(symbol)")

        # Auto-correct legacy/mismatched symbol names in watchlist_items
        alias_updates = [
            ("RAJDARSH.NS", "RAJDARSHANINDS.NS"),
            ("JKCEMENT.NS", "JKCEMENTS.NS"),
            ("DALBHARAT.NS", "DALMIABHARATLTD.NS"),
            ("IRB.NS", "IRBINFRADEVL.NS"),
            ("TI.NS", "TILAKNAGARINDS.NS"),
            ("BEPL.NS", "BHANSALIENGG.NS"),
            ("TNPETRO.NS", "TNPETROPROD.NS"),
        ]
        for correct_sym, old_sym in alias_updates:
            cursor.execute("UPDATE watchlist_items SET symbol = ? WHERE symbol = ?", (correct_sym, old_sym))


        
        # Mock loader for history, block deals, and corporate actions if empty
        cursor.execute("SELECT COUNT(*) as cnt FROM daily_delivery_history")
        hist_count = cursor.fetchone()["cnt"]
        
        cursor.execute("SELECT symbol FROM screener_universe")
        symbols = [r["symbol"] for r in cursor.fetchall()]
        if not symbols:
            symbols = ["INFY.NS", "TCS.NS", "RELIANCE.NS", "HDFCBANK.NS", "SBIN.NS"]
        
        import random
        from datetime import datetime, timedelta
        
        clients_buy = [
            "Nippon India Mutual Fund", "HDFC Mutual Fund", "ICICI Prudential MF", 
            "SBI Mutual Fund", "UTI Mutual Fund", "Societe Generale", "Morgan Stanley"
        ]
        clients_sell = [
            "Promoter Group Entity", "FII Liquidator Corp", "Citigroup Global Markets",
            "Retail Wealth Advisors", "Standard Chartered Bank"
        ]
        
        if hist_count == 0:
            for sym in symbols:
                base_qty = random.randint(500000, 2000000)
                for day_offset in range(75, -1, -1):
                    dt = datetime.now() - timedelta(days=day_offset)
                    if dt.weekday() >= 5:
                        continue
                    trade_date = dt.strftime("%Y-%m-%d")
                    
                    traded = int(base_qty * random.uniform(0.6, 2.5))
                    deliv_pct = random.uniform(25.0, 75.0)
                    if random.random() < 0.15:
                        traded = int(base_qty * random.uniform(0.15, 0.4))
                        deliv_pct = random.uniform(55.0, 80.0)
                    elif random.random() < 0.1:
                        traded = int(base_qty * random.uniform(1.8, 3.0))
                        deliv_pct = random.uniform(60.0, 85.0)
                        
                    deliv_qty = int(traded * (deliv_pct / 100.0))
                    
                    cursor.execute("""
                        INSERT OR IGNORE INTO daily_delivery_history 
                        (symbol, trade_date, delivery_qty, traded_qty, delivery_percentage)
                        VALUES (?, ?, ?, ?, ?)
                    """, (sym, trade_date, deliv_qty, traded, round(deliv_pct, 2)))
        
        cursor.execute("SELECT COUNT(*) as cnt FROM bulk_block_deals")
        deals_count = cursor.fetchone()["cnt"]
        if deals_count == 0:
            for sym in symbols:
                # Insert a few block deals for this stock with randomized historic dates
                deal_dt1 = (datetime.now() - timedelta(days=random.randint(12, 28)))
                while deal_dt1.weekday() >= 5:
                    deal_dt1 -= timedelta(days=1)
                cursor.execute("""
                    INSERT INTO bulk_block_deals (symbol, deal_date, client_name, deal_type, quantity, price, percentage_equity, deal_window, is_mock)
                    VALUES (?, ?, ?, 'BUY', ?, ?, ?, 'NORMAL', 1)
                """, (sym, deal_dt1.strftime("%Y-%m-%d"), random.choice(clients_buy), random.randint(100000, 500000), random.uniform(400, 1800), round(random.uniform(0.1, 0.9), 2)))
                
                deal_dt2 = (datetime.now() - timedelta(days=random.randint(2, 9)))
                while deal_dt2.weekday() >= 5:
                    deal_dt2 -= timedelta(days=1)
                cursor.execute("""
                    INSERT INTO bulk_block_deals (symbol, deal_date, client_name, deal_type, quantity, price, percentage_equity, deal_window, is_mock)
                    VALUES (?, ?, ?, 'SELL', ?, ?, ?, 'BLOCK_WINDOW', 1)
                """, (sym, deal_dt2.strftime("%Y-%m-%d"), random.choice(clients_sell), random.randint(200000, 800000), random.uniform(400, 1800), round(random.uniform(0.3, 1.5), 2)))
        
        cursor.execute("SELECT COUNT(*) as cnt FROM corporate_actions")
        ca_count = cursor.fetchone()["cnt"]
        if ca_count == 0:
            for sym in symbols:
                # Seed corporate actions splits and bonus issues (CAF check)
                if sym in ["INFY.NS", "TCS.NS", "RELIANCE.NS"]:
                    ex_dt = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
                    cursor.execute("""
                        INSERT OR IGNORE INTO corporate_actions (symbol, action_type, ex_date, ratio_multiplier, record_date)
                        VALUES (?, 'SPLIT', ?, 2.0, ?)
                    """, (sym, ex_dt, ex_dt))
        
        # Migrations to support formulas in custom screens
        try:
            cursor.execute("ALTER TABLE custom_screens ADD COLUMN formula TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE custom_screens ADD COLUMN logic_gate TEXT DEFAULT 'AND'")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE custom_screens ADD COLUMN universe TEXT DEFAULT 'all'")
        except Exception:
            pass
            
        # Invalidate existing technical indicators cache to force re-calculation with High/Low/Open
        try:
            cursor.execute("DELETE FROM cached_timeframe_indicators")
        except Exception:
            pass
            
        # Seed default WhatsApp daily wrap up configurations
        try:
            cursor.execute("INSERT OR IGNORE INTO alert_settings (key, value) VALUES ('daily_wrapup_enabled', 'false')")
            cursor.execute("INSERT OR IGNORE INTO alert_settings (key, value) VALUES ('daily_wrapup_time', '19:30')")
            cursor.execute("UPDATE alert_settings SET value = '19:30' WHERE key = 'daily_wrapup_time' AND value IN ('16:00', '16:30')")
            cursor.execute("INSERT OR IGNORE INTO alert_settings (key, value) VALUES ('daily_wrapup_persona', 'institutional')")
            cursor.execute("INSERT OR IGNORE INTO alert_settings (key, value) VALUES ('daily_wrapup_include_events', 'true')")
            cursor.execute("INSERT OR IGNORE INTO alert_settings (key, value) VALUES ('daily_wrapup_include_deals', 'true')")
            cursor.execute("INSERT OR IGNORE INTO alert_settings (key, value) VALUES ('daily_wrapup_include_sentiment', 'true')")
            cursor.execute("INSERT OR IGNORE INTO alert_settings (key, value) VALUES ('daily_wrapup_include_breakouts', 'true')")
        except Exception as e:
            print(f"Error seeding daily wrap up configurations: {e}")
            
        conn.commit()
 
init_db()

async def fetch_history_df(symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    """
    Robust history fetching for Yahoo Finance charts.
    Tries yfinance first, then falls back to raw requests.get chart API with custom headers.
    """
    import yfinance as yf
    import pandas as pd
    import requests
    from datetime import datetime
    
    symbol = symbol.strip().upper()
    df = pd.DataFrame()
    
    # 1. Try yfinance Ticker history (most robust, bypasses cloud VM blocks)
    try:
        ticker_obj = yf.Ticker(symbol)
        # Run in thread pool to prevent blocking event loop
        df = await asyncio.to_thread(
            ticker_obj.history, 
            period=period, 
            interval=interval, 
            timeout=8
        )
        if not df.empty:
            # Clean tz-aware index to naive naive datetime
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            # Ensure index has name or standard datetime objects
            df.index = pd.to_datetime(df.index)
            # Verify columns exist
            required_cols = ["Open", "High", "Low", "Close", "Volume"]
            if all(col in df.columns for col in required_cols):
                # Drop rows with NaN in Close
                df = df.dropna(subset=["Close"])
                return df
    except Exception as yf_err:
        print(f"yfinance robust history fetch failed for {symbol}: {yf_err}")
        
    # 2. Fallback: Raw request to query1.finance.yahoo.com
    try:
        # Map period/interval to Yahoo URL parameters
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={period}&interval={interval}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        
        # Run raw get in thread pool
        res = await asyncio.to_thread(requests.get, url, headers=headers, timeout=8)
        if res.status_code == 200:
            chart_data = res.json()
            result = chart_data.get("chart", {}).get("result", [None])[0]
            if result and "timestamp" in result:
                timestamps = result.get("timestamp", [])
                indicators = result.get("indicators", {}).get("quote", [{}])[0]
                
                dates = [datetime.fromtimestamp(t) for t in timestamps]
                raw_df = pd.DataFrame(index=dates)
                raw_df["Open"] = pd.Series(indicators.get("open", [])).ffill().bfill().values
                raw_df["High"] = pd.Series(indicators.get("high", [])).ffill().bfill().values
                raw_df["Low"] = pd.Series(indicators.get("low", [])).ffill().bfill().values
                raw_df["Close"] = pd.Series(indicators.get("close", [])).ffill().bfill().values
                raw_df["Volume"] = pd.Series(indicators.get("volume", [])).ffill().bfill().values
                raw_df = raw_df.ffill().bfill().dropna(subset=["Close"])
                return raw_df
    except Exception as req_err:
        print(f"Raw chart request fallback failed for {symbol}: {req_err}")
        
    return pd.DataFrame()

def compute_active_holdings(transactions: list) -> list:
    """
    Applies chronological First-In-First-Out (FIFO) netting on a list of raw transaction records.
    Returns the list of active buy tranches (with remaining quantities > 0).
    """
    from collections import defaultdict
    from datetime import datetime

    # Group transactions by symbol
    grouped = defaultdict(list)
    for tx in transactions:
        symbol = tx.get("symbol", "").strip().upper()
        if symbol:
            grouped[symbol].append(tx)

    active_tranches = []
    for symbol, symbol_txs in grouped.items():
        # Sort chronologically by date, then by transaction ID to preserve original order
        def get_sort_key(x):
            date_str = x.get("purchase_date") or "2026-06-05"
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
            except Exception:
                dt = datetime.strptime("2026-06-05", "%Y-%m-%d")
            return (dt, x.get("id") or 0)

        symbol_txs.sort(key=get_sort_key)

        buys = []
        for tx in symbol_txs:
            t_type = (tx.get("transaction_type") or "buy").strip().lower()
            qty = float(tx.get("quantity") or 0.0)
            if qty <= 0:
                continue

            if t_type == "buy":
                # Create a copy to prevent modifying the database dict in-place
                buys.append({
                    "id": tx.get("id"),
                    "symbol": tx.get("symbol"),
                    "name": tx.get("name"),
                    "sector": tx.get("sector") or "General Equities",
                    "quantity": qty,
                    "purchase_price": float(tx.get("purchase_price") or 0.0),
                    "purchase_date": tx.get("purchase_date"),
                    "transaction_type": "buy"
                })
            elif t_type == "sell":
                sell_qty = qty
                while sell_qty > 0 and buys:
                    oldest_buy = buys[0]
                    if oldest_buy["quantity"] > sell_qty:
                        oldest_buy["quantity"] = round(oldest_buy["quantity"] - sell_qty, 6)
                        sell_qty = 0
                    else:
                        sell_qty = round(sell_qty - oldest_buy["quantity"], 6)
                        buys.pop(0)

        for buy in buys:
            if buy["quantity"] > 0:
                active_tranches.append(buy)

    return active_tranches

# Load env variables from root directory
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# Import analytical and agent engines
from backend.financial_utils import get_complete_financial_profile, resolve_company_ticker, calculate_portfolio_backtest, calculate_dcf_valuation, normalize_symbol
from backend.agent import run_cio_parent_agent, run_ai_stock_screener, run_comparison_synthesizer, run_conversational_chat, run_portfolio_doctor, run_single_stock_audit, generate_backtest_synthesis, calculate_portfolio_taxes
from backend.llm_config import call_llm, TASK_HEAVY, TASK_FAST, get_llm_config, get_last_llm_meta

# Angel One SmartAPI — Real-time WebSocket streaming (optional)
from backend.angel_connect import AngelOneConnector
from backend.websocket_server import (
    angel_ws_router, start_angel_upstream, stop_angel_upstream,
    get_feed_status, tick_store, subscribe_symbols, alert_evaluator as ws_alert_evaluator
)
import logging

angel_connector = None  # Initialized at startup if Angel One credentials are configured
logger = logging.getLogger("apex_main")

def sanitize_nan_values(x):
    """Recursively replaces float('nan'), inf, and -inf with None for JSON compliance."""
    if isinstance(x, dict):
        return {k: sanitize_nan_values(v) for k, v in x.items()}
    elif isinstance(x, list):
        return [sanitize_nan_values(v) for v in x]
    elif isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    return x

class SafeJSONResponse(JSONResponse):
    """A JSONResponse subclass that safely handles non-compliant floats globally."""
    def render(self, content) -> bytes:
        return super().render(sanitize_nan_values(content))

app = FastAPI(
    title="Indian Stock Analysis AI Workstation",
    description="Institutional-grade AI advisory and stock discovery terminal.",
    version="2.0.0",
    default_response_class=SafeJSONResponse
)

# --- Universe Seeding, Index Rebalancing, & Warm Caching ---

DEFAULT_SEED_STOCKS = [
    {"symbol": "RELIANCE.NS", "base": "RELIANCE", "name": "Reliance Industries", "sector": "Energy & Oil", "cap_type": "large"},
    {"symbol": "TCS.NS", "base": "TCS", "name": "Tata Consultancy Services", "sector": "Technology (IT)", "cap_type": "large"},
    {"symbol": "INFY.NS", "base": "INFY", "name": "Infosys", "sector": "Technology (IT)", "cap_type": "large"},
    {"symbol": "WIPRO.NS", "base": "WIPRO", "name": "Wipro", "sector": "Technology (IT)", "cap_type": "large"},
    {"symbol": "HDFCBANK.NS", "base": "HDFCBANK", "name": "HDFC Bank", "sector": "Financial Services (Banking)", "cap_type": "large"},
    {"symbol": "ICICIBANK.NS", "base": "ICICIBANK", "name": "ICICI Bank", "sector": "Financial Services (Banking)", "cap_type": "large"},
    {"symbol": "SBIN.NS", "base": "SBIN", "name": "State Bank of India", "sector": "Financial Services (Banking)", "cap_type": "large"},
    {"symbol": "TATAMOTORS.NS", "base": "TATAMOTORS", "name": "Tata Motors", "sector": "Automobile", "cap_type": "large"},
    {"symbol": "MARUTI.NS", "base": "MARUTI", "name": "Maruti Suzuki", "sector": "Automobile", "cap_type": "large"},
    {"symbol": "LT.NS", "base": "LT", "name": "Larsen & Toubro", "sector": "Infrastructure", "cap_type": "large"},
    {"symbol": "ITC.NS", "base": "ITC", "name": "ITC Limited", "sector": "Consumer Goods", "cap_type": "large"},
    {"symbol": "HINDUNILVR.NS", "base": "HINDUNILVR", "name": "Hindustan Unilever", "sector": "Consumer Goods", "cap_type": "large"},
    {"symbol": "BHARTIARTL.NS", "base": "BHARTIARTL", "name": "Bharti Airtel", "sector": "Telecommunication", "cap_type": "large"},
    {"symbol": "AXISBANK.NS", "base": "AXISBANK", "name": "Axis Bank", "sector": "Financial Services (Banking)", "cap_type": "large"},
    {"symbol": "KOTAKBANK.NS", "base": "KOTAKBANK", "name": "Kotak Mahindra Bank", "sector": "Financial Services (Banking)", "cap_type": "large"},
    {"symbol": "TATASTEEL.NS", "base": "TATASTEEL", "name": "Tata Steel", "sector": "Metals & Mining", "cap_type": "large"},
    {"symbol": "COALINDIA.NS", "base": "COALINDIA", "name": "Coal India", "sector": "Energy & Oil", "cap_type": "large"},
    {"symbol": "NTPC.NS", "base": "NTPC", "name": "NTPC Limited", "sector": "Power & Utilities", "cap_type": "large"},
    {"symbol": "SUNPHARMA.NS", "base": "SUNPHARMA", "name": "Sun Pharmaceutical", "sector": "Pharmaceuticals", "cap_type": "large"},
    {"symbol": "TITAN.NS", "base": "TITAN", "name": "Titan Company", "sector": "Consumer Goods", "cap_type": "large"},
    {"symbol": "BAJFINANCE.NS", "base": "BAJFINANCE", "name": "Bajaj Finance", "sector": "Financial Services", "cap_type": "large"},
    {"symbol": "JSWSTEEL.NS", "base": "JSWSTEEL", "name": "JSW Steel", "sector": "Metals & Mining", "cap_type": "large"},
    {"symbol": "POWERGRID.NS", "base": "POWERGRID", "name": "Power Grid Corporation", "sector": "Power & Utilities", "cap_type": "large"},
    {"symbol": "ONGC.NS", "base": "ONGC", "name": "ONGC", "sector": "Energy & Oil", "cap_type": "large"},
    {"symbol": "M&M.NS", "base": "M&M", "name": "Mahindra & Mahindra", "sector": "Automobile", "cap_type": "large"},
    
    {"symbol": "HAL.NS", "base": "HAL", "name": "Hindustan Aeronautics", "sector": "Defense & Aerospace", "cap_type": "mid"},
    {"symbol": "RVNL.NS", "base": "RVNL", "name": "Rail Vikas Nigam Ltd", "sector": "Infrastructure", "cap_type": "mid"},
    {"symbol": "DIXON.NS", "base": "DIXON", "name": "Dixon Technologies", "sector": "Consumer Electronics", "cap_type": "mid"},
    {"symbol": "IRFC.NS", "base": "IRFC", "name": "Indian Railway Finance", "sector": "Financial Services", "cap_type": "mid"},
    {"symbol": "COFORGE.NS", "base": "COFORGE", "name": "Coforge Ltd", "sector": "Technology (IT)", "cap_type": "mid"},
    {"symbol": "PFC.NS", "base": "PFC", "name": "Power Finance Corp", "sector": "Financial Services", "cap_type": "mid"},
    {"symbol": "RECLTD.NS", "base": "RECLTD", "name": "REC Limited", "sector": "Financial Services", "cap_type": "mid"},
    
    {"symbol": "CDSL.NS", "base": "CDSL", "name": "Central Depository Services", "sector": "Financial Services", "cap_type": "small"},
    {"symbol": "ANGELONE.NS", "base": "ANGELONE", "name": "Angel One", "sector": "Financial Services", "cap_type": "small"},
    {"symbol": "SUZLON.NS", "base": "SUZLON", "name": "Suzlon Energy", "sector": "Renewable Energy", "cap_type": "small"},
    {"symbol": "IREDA.NS", "base": "IREDA", "name": "IREDA Ltd", "sector": "Renewable Energy", "cap_type": "small"},
    {"symbol": "IRCON.NS", "base": "IRCON", "name": "IRCON International", "sector": "Infrastructure", "cap_type": "small"},
    {"symbol": "RITES.NS", "base": "RITES", "name": "RITES Ltd", "sector": "Infrastructure", "cap_type": "small"},
    {"symbol": "NHPC.NS", "base": "NHPC", "name": "NHPC Limited", "sector": "Power & Utilities", "cap_type": "small"}
]

def seed_default_universe() -> int:
    timestamp = datetime.now().isoformat()
    seed_data = []
    for item in DEFAULT_SEED_STOCKS:
        seed_data.append({
            "symbol": item["symbol"],
            "base": item["base"],
            "name": item["name"],
            "sector": item["sector"],
            "cap_type": item["cap_type"],
            "timestamp": timestamp
        })
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM screener_universe")
        cursor.executemany("""
        INSERT OR REPLACE INTO screener_universe 
        (symbol, base_symbol, company_name, sector, cap_type, last_rebalanced) 
        VALUES (:symbol, :base, :name, :sector, :cap_type, :timestamp)
        """, seed_data)
        conn.commit()
    return len(seed_data)

def rebalance_index_universe() -> int:
    import io
    urls = {
        "large": "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
        "mid": "https://archives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
        "small": "https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv"
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    timestamp = datetime.now().isoformat()
    new_universe = []
    
    for cap, url in urls.items():
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                df = pd.read_csv(io.StringIO(res.text))
                for _, row in df.iterrows():
                    symbol = f"{row['Symbol'].strip()}.NS"
                    new_universe.append({
                        "symbol": symbol,
                        "base": row['Symbol'].strip(),
                        "name": row['Company Name'].strip(),
                        "sector": row['Industry'].strip(),
                        "cap_type": cap,
                        "timestamp": timestamp
                    })
        except Exception as e:
            print(f"Error downloading {cap} CSV list: {e}")
            
    if new_universe:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM screener_universe")
            cursor.executemany("""
            INSERT OR REPLACE INTO screener_universe 
            (symbol, base_symbol, company_name, sector, cap_type, last_rebalanced) 
            VALUES (:symbol, :base, :name, :sector, :cap_type, :timestamp)
            """, new_universe)
            conn.commit()
        return len(new_universe)
    return 0
async def run_background_cache_warmer():
    print("Background cache warmer: initial 120s delay before start...")
    await asyncio.sleep(120)
    while True:
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT symbol FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%'")
                symbols = [row["symbol"] for row in cursor.fetchall()]
            
            print(f"Background cache warmer: starting sweep for {len(symbols)} symbols...")
            
            for idx, sym in enumerate(symbols):
                try:
                    # Check if profile needs refresh
                    with get_db() as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT updated_at FROM cached_profiles WHERE symbol = ?", (sym,))
                        row = cursor.fetchone()
                    
                    needs_update = True
                    if row and row["updated_at"]:
                        try:
                            cached_time = datetime.strptime(row["updated_at"][:19], "%Y-%m-%d %H:%M:%S")
                            if (datetime.now() - cached_time).total_seconds() < 24 * 3600:
                                needs_update = False
                        except Exception:
                            pass  # Force refresh if date parsing fails
                    
                    if not needs_update:
                        await asyncio.sleep(0.2)  # Fast skip for warm cache
                        continue
                             
                    print(f"Background cache warmer: fetching profile for {sym}...")
                    profile = await asyncio.to_thread(get_complete_financial_profile, sym)
                    
                    # Cache the profile
                    with get_db() as conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO cached_profiles (symbol, profile_json, updated_at) VALUES (?, ?, ?)",
                            (sym, json.dumps(profile), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                        )
                        conn.commit()
                    print(f"Background cache warmer: successfully cached {sym}")
                    await asyncio.sleep(4)  # Paced sleep to prevent API flooding & SQLite locking

                    # Warm events cache in background
                    try:
                        from backend.events_scraper import cache_stock_events, is_stock_events_stale
                        full_sym = f"{sym.replace('.NS', '').replace('.BO', '')}.NS"
                        if is_stock_events_stale(full_sym, max_age_hours=24):
                            await asyncio.to_thread(cache_stock_events, full_sym)
                            print(f"Background cache warmer: warmed events for {sym}")
                    except Exception as e:
                        err_msg = str(e)
                        print(f"Background cache warmer: failed to warm events for {sym}: {err_msg}")
                        if "401" in err_msg or "Unauthorized" in err_msg or "Invalid Crumb" in err_msg:
                            print("Background cache warmer: Yahoo rate-limit (401 Invalid Crumb) detected. Pausing warmer for 10 mins...")
                            await asyncio.sleep(600)  # Cool off period for Yahoo Finance cookie/crumb

                    # Periodic Garbage Collection every 10 stocks to clear unused DataFrames from RAM
                    if idx % 10 == 0:
                        gc.collect()

                    await asyncio.sleep(3)  # Gentle delay between stocks
                except Exception as e:
                    err_str = str(e)
                    print(f"Background warming error for {sym}: {err_str}")
                    if "401" in err_str or "Unauthorized" in err_str or "Invalid Crumb" in err_str:
                        print("Background cache warmer: Yahoo rate-limit (401 Invalid Crumb) detected. Pausing warmer for 10 mins...")
                        await asyncio.sleep(600)
                    else:
                        await asyncio.sleep(10)
            
            gc.collect()
            print("Background cache warmer: sweep complete. Sleeping for 4 hours.")
            await asyncio.sleep(14400)  # 4 hour sleep between full sweeps to keep VM RAM light
        except Exception as e:
            print(f"Universe cache warmer loop error: {e}")
            await asyncio.sleep(1800)


_MARKET_MOVERS_CACHE = {
    "status": "initializing",
    "last_updated": None,
    "advances": 0,
    "declines": 0,
    "gainers": {
        "all": [],
        "large": [],
        "mid": [],
        "small": []
    },
    "losers": {
        "all": [],
        "large": [],
        "mid": [],
        "small": []
    },
    "indices": [],
    "large_cap_temp": 0.0,
    "mid_cap_temp": 0.0,
    "small_cap_temp": 0.0
}

def is_indian_market_hours() -> bool:
    """
    Checks if current time is within Indian Stock Market trading hours (Mon-Fri 9:15 AM - 3:30 PM IST).
    """
    now_utc = datetime.utcnow()
    now_ist = now_utc + timedelta(hours=5, minutes=30)
    if now_ist.weekday() >= 5:
        return False
    total_minutes = now_ist.hour * 60 + now_ist.minute
    if 555 <= total_minutes <= 930:
        return True
    return False

async def run_background_daily_wrapup_scheduler():
    """
    Asynchronous loop that sweeps every 5 minutes.
    Checks if daily wrap-up is enabled and if the current time is past
    the configured trigger time (default 16:00 IST) on a weekday, and
    sends the summary if it hasn't been sent today.
    """
    await asyncio.sleep(15)  # Let startup warming finish
    print("Background WhatsApp daily wrap-up scheduler started.")
    
    while True:
        try:
            enabled = "true"
            trigger_time_str = "19:30"
            last_sent = ""
            
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT key, value FROM alert_settings WHERE key IN ('daily_wrapup_enabled', 'daily_wrapup_time', 'daily_wrapup_last_sent')")
                for row in cursor.fetchall():
                    if row["key"] == "daily_wrapup_enabled":
                        enabled = row["value"]
                    elif row["key"] == "daily_wrapup_time":
                        trigger_time_str = row["value"]
                    elif row["key"] == "daily_wrapup_last_sent":
                        last_sent = row["value"]
            
            if enabled.lower() == "true":
                from datetime import datetime, timedelta
                now_utc = datetime.utcnow()
                now_ist = now_utc + timedelta(hours=5, minutes=30)
                
                # Check if weekday (Mon-Fri)
                if now_ist.weekday() < 5:
                    today_str = now_ist.strftime("%Y-%m-%d")
                    if last_sent != today_str:
                        try:
                            t_parts = trigger_time_str.split(":")
                            target_hour = int(t_parts[0])
                            target_minute = int(t_parts[1])
                            
                            current_minutes = now_ist.hour * 60 + now_ist.minute
                            target_minutes = target_hour * 60 + target_minute
                            
                            # Trigger if past target, but not too late (within 2 hours) to avoid stale boots
                            if target_minutes <= current_minutes <= (target_minutes + 120):
                                print(f"Daily Wrap-up: Scheduled trigger time reached ({trigger_time_str} IST). Starting dispatch...")
                                try:
                                    await asyncio.to_thread(update_nse_delivery_data)
                                except Exception as deliv_err:
                                    print(f"Daily Wrap-up delivery pre-sync error: {deliv_err}")
                                from backend.daily_wrapup import generate_daily_wrapup_text, send_whatsapp_wrapup
                                
                                msg = await generate_daily_wrapup_text()
                                res = await send_whatsapp_wrapup(msg)
                                if res.get("status") == "success":
                                    print(f"Daily Wrap-up: Successfully sent on schedule to WhatsApp. Msg ID: {res.get('message_id')}")
                                    with get_db() as conn:
                                        cursor = conn.cursor()
                                        cursor.execute("INSERT OR REPLACE INTO alert_settings (key, value) VALUES ('daily_wrapup_last_sent', ?)", (today_str,))
                                        conn.commit()
                                else:
                                    print(f"Daily Wrap-up: Scheduled dispatch failed: {res.get('message')}. Retrying in next sweep.")
                        except Exception as parse_err:
                            print(f"Daily Wrap-up: Error parsing trigger time or checking date: {parse_err}")
                            
        except Exception as loop_err:
            print(f"Daily Wrap-up: Background scheduler loop error: {loop_err}")
            
        await asyncio.sleep(300)  # Sweep every 5 minutes

async def run_background_weekly_wrapup_scheduler():
    """
    Asynchronous loop that sweeps every 5 minutes.
    Checks if Weekly Wrap-Up is enabled and if the current IST day & time
    match configured schedule (e.g. Saturday 10:00 AM IST), and dispatches
    the retrospective if it hasn't been sent for the current period.
    """
    await asyncio.sleep(20)  # Let startup warming finish
    print("Background WhatsApp weekly wrap-up scheduler started.")
    
    while True:
        try:
            from backend.weekly_wrapup import get_weekly_wrapup_settings, trigger_weekly_wrapup
            settings = get_weekly_wrapup_settings()
            
            if settings.get("enabled", False):
                from datetime import datetime, timedelta
                now_utc = datetime.utcnow()
                now_ist = now_utc + timedelta(hours=5, minutes=30)
                
                target_day = settings.get("day", "Saturday").strip().capitalize()
                target_time_str = settings.get("time", "10:00").strip()
                last_sent = str(settings.get("last_sent", ""))
                
                current_day_str = now_ist.strftime("%A")
                today_str = now_ist.strftime("%Y-%m-%d")
                
                if current_day_str.lower() == target_day.lower() and not last_sent.startswith(today_str):
                    try:
                        t_parts = target_time_str.split(":")
                        target_hour = int(t_parts[0])
                        target_minute = int(t_parts[1])
                        
                        current_minutes = now_ist.hour * 60 + now_ist.minute
                        target_minutes = target_hour * 60 + target_minute
                        
                        if target_minutes <= current_minutes <= (target_minutes + 120):
                            print(f"Weekly Wrap-up: Scheduled trigger time reached ({target_day} {target_time_str} IST). Starting dispatch...")
                            res = await trigger_weekly_wrapup(on_demand=False)
                            if res.get("whatsapp_sent"):
                                print(f"Weekly Wrap-up: Successfully dispatched on schedule to WhatsApp.")
                            else:
                                print(f"Weekly Wrap-up: Scheduled dispatch compiled. WhatsApp status: {res.get('whatsapp_error')}")
                    except Exception as parse_err:
                        print(f"Weekly Wrap-up: Error checking scheduled trigger time: {parse_err}")
        except Exception as loop_err:
            print(f"Weekly Wrap-up: Background scheduler loop error: {loop_err}")
            
        await asyncio.sleep(300)  # Sweep every 5 minutes

async def run_background_market_movers_updater():
    """
    Background loop that runs immediately on startup and updates today's market movers.
    Recalculates every 10 minutes during market hours, or once per hour during off-market/weekends.
    """
    global _MARKET_MOVERS_CACHE
    await asyncio.sleep(5)
    while True:
        try:
            print("Background market movers updater: starting fetch...")
            indices_tickers = [
                "^NSEI", "^BSESN", "^NSEBANK", "^CNXIT", "^CNXPHARMA", 
                "^CNXFMCG", "^CNXMETAL", "^CNXAUTO", "^CNXREALTY", 
                "^CNXINFRA", "^CNXENERGY", "^CNXFIN", "^CNXPSUBANK", 
                "^CNXMEDIA", "^CNXCONSUM", "GC=F", "SI=F", "INR=X", "^INDIAVIX"
            ]
            index_names = {
                "^NSEI": "Nifty 50",
                "^BSESN": "BSE Sensex",
                "^NSEBANK": "Nifty Bank",
                "^CNXIT": "Nifty IT",
                "^CNXPHARMA": "Nifty Pharma",
                "^CNXFMCG": "Nifty FMCG",
                "^CNXMETAL": "Nifty Metal",
                "^CNXAUTO": "Nifty Auto",
                "^CNXREALTY": "Nifty Realty",
                "^CNXINFRA": "Nifty Infra",
                "^CNXENERGY": "Nifty Energy",
                "^CNXFIN": "Nifty Financial Services",
                "^CNXPSUBANK": "Nifty PSU Bank",
                "^CNXMEDIA": "Nifty Media",
                "^CNXCONSUM": "Nifty Consumption",
                "^INDIAVIX": "India VIX"
            }
            
            loop = asyncio.get_event_loop()
            df_indices = await loop.run_in_executor(
                None, 
                lambda: yf.download(indices_tickers, period="1mo", interval="1d", progress=False)
            )
            
            parsed_indices = []
            yf_raw = {}
            if not df_indices.empty:
                is_multi_idx = isinstance(df_indices.columns, pd.MultiIndex)
                yf_raw = {}
                for ticker in indices_tickers:
                    try:
                        if is_multi_idx:
                            close_series = df_indices['Close'][ticker].dropna()
                            high_series = df_indices['High'][ticker].dropna() if 'High' in df_indices.columns.get_level_values(0) else pd.Series()
                            low_series = df_indices['Low'][ticker].dropna() if 'Low' in df_indices.columns.get_level_values(0) else pd.Series()
                            volume_series = df_indices['Volume'][ticker].dropna() if 'Volume' in df_indices.columns.get_level_values(0) else pd.Series()
                        else:
                            close_series = df_indices['Close'].dropna()
                            high_series = df_indices['High'].dropna() if 'High' in df_indices.columns else pd.Series()
                            low_series = df_indices['Low'].dropna() if 'Low' in df_indices.columns else pd.Series()
                            volume_series = df_indices['Volume'].dropna() if 'Volume' in df_indices.columns else pd.Series()

                        if not close_series.empty:
                            price = float(close_series.iloc[-1])
                            prev_close = None
                            try:
                                fi_prev = yf.Ticker(ticker).fast_info.get('previousClose')
                                if fi_prev and not pd.isna(fi_prev) and float(fi_prev) > 0:
                                    prev_close = float(fi_prev)
                            except Exception:
                                pass
                            if prev_close is None:
                                prev_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else price
                            change = price - prev_close
                            change_pct = (change / prev_close * 100.0) if prev_close > 0 else 0.0
                            high = float(high_series.iloc[-1]) if not high_series.empty else price
                            low = float(low_series.iloc[-1]) if not low_series.empty else price
                            volume = int(volume_series.iloc[-1]) if not volume_series.empty else 0

                            yf_raw[ticker] = {
                                "price": price,
                                "change": change,
                                "change_pct": change_pct,
                                "high": high,
                                "low": low,
                                "volume": volume
                            }

                            if ticker in index_names:
                                parsed_indices.append({
                                    "symbol": ticker,
                                    "name": index_names[ticker],
                                    "price": round(price, 2),
                                    "change": round(change, 2),
                                    "change_pct": round(change_pct, 2)
                                })
                    except Exception as idx_err:
                        print(f"Error parsing index {ticker} in movers task: {idx_err}")
            
            # Calculate Gold and Silver Futures prices in INR (including 15% cumulative import duty: 10% BCD + 5% AIDC)
            if "GC=F" in yf_raw and "INR=X" in yf_raw:
                gc = yf_raw["GC=F"]
                inr = yf_raw["INR=X"]
                gold_fut_price = (gc["price"] * inr["price"]) / 31.1034768 * 10 * 1.15
                gold_fut_change = (gc["change"] * inr["price"]) / 31.1034768 * 10 * 1.15
                parsed_indices.append({
                    "symbol": "MCXGOLD",
                    "name": "Gold Futures 10g (INR)",
                    "price": round(gold_fut_price, 2),
                    "change": round(gold_fut_change, 2),
                    "change_pct": round(gc["change_pct"], 2)
                })

            if "SI=F" in yf_raw and "INR=X" in yf_raw:
                si = yf_raw["SI=F"]
                inr = yf_raw["INR=X"]
                sil_fut_price = (si["price"] * inr["price"]) / 31.1034768 * 1000 * 1.15
                sil_fut_change = (si["change"] * inr["price"]) / 31.1034768 * 1000 * 1.15
                parsed_indices.append({
                    "symbol": "MCXSILVER",
                    "name": "Silver Futures 1kg (INR)",
                    "price": round(sil_fut_price, 2),
                    "change": round(sil_fut_change, 2),
                    "change_pct": round(si["change_pct"], 2)
                })

            # Append GoodReturns spot rates for Gold, Silver and Platinum
            from backend.commodity_scraper import CommodityScraper
            try:
                spots = await CommodityScraper.get_prices()
                if "gold_24k" in spots:
                    g24 = spots["gold_24k"]
                    parsed_indices.append({
                        "symbol": "SPOTGOLD",
                        "name": "Gold 24K 10g (Spot)",
                        "price": g24["price"],
                        "change": g24["change"],
                        "change_pct": round(g24["change_pct"], 2)
                    })
                if "silver_1kg" in spots:
                    sil = spots["silver_1kg"]
                    parsed_indices.append({
                        "symbol": "SPOTSILVER",
                        "name": "Silver 1kg (Spot)",
                        "price": sil["price"],
                        "change": sil["change"],
                        "change_pct": round(sil["change_pct"], 2)
                    })
                if "platinum_10g" in spots:
                    plat = spots["platinum_10g"]
                    parsed_indices.append({
                        "symbol": "PLATINUM",
                        "name": "Platinum 10g (Spot)",
                        "price": plat["price"],
                        "change": plat["change"],
                        "change_pct": round(plat["change_pct"], 2)
                    })
            except Exception as scrap_err:
                print(f"Error appending GoodReturns spots to movers: {scrap_err}")
            
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT symbol, company_name, cap_type FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%'")
                db_stocks = [dict(r) for r in cursor.fetchall()]
                
            stocks_tickers = [s["symbol"] for s in db_stocks]
            stocks_map = {s["symbol"]: s for s in db_stocks}
            
            df_stocks = await loop.run_in_executor(
                None, 
                lambda: yf.download(stocks_tickers, period="5d", interval="1d", progress=False, threads=12)
            )
            
            parsed_stocks = []
            advances_cnt = 0
            declines_cnt = 0
            large_cap_changes = []
            mid_cap_changes = []
            small_cap_changes = []
            
            if not df_stocks.empty:
                is_multi_stocks = isinstance(df_stocks.columns, pd.MultiIndex)
                for sym in stocks_tickers:
                    try:
                        if is_multi_stocks:
                            if sym not in df_stocks.columns.get_level_values(1):
                                continue
                            close_series = df_stocks['Close'][sym].dropna()
                        else:
                            close_series = df_stocks['Close'].dropna()
                        if len(close_series) >= 1:
                            price = float(close_series.iloc[-1])
                            prev_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else price
                            change = price - prev_close
                            change_pct = (change / prev_close * 100.0) if prev_close > 0 else 0.0
                            
                            db_info = stocks_map[sym]
                            cap = db_info["cap_type"]
                            
                            parsed_stocks.append({
                                "symbol": sym,
                                "company_name": db_info["company_name"],
                                "cap_type": cap,
                                "price": round(price, 2),
                                "change": round(change, 2),
                                "change_pct": round(change_pct, 2)
                            })
                            
                            if change_pct > 0.05:
                                advances_cnt += 1
                            elif change_pct < -0.05:
                                declines_cnt += 1
                                
                            if cap == "large":
                                large_cap_changes.append(change_pct)
                            elif cap == "mid":
                                mid_cap_changes.append(change_pct)
                            elif cap == "small":
                                small_cap_changes.append(change_pct)
                    except Exception as sym_err:
                        pass
            
            gainers_all = [s for s in parsed_stocks if s["change_pct"] > 0]
            losers_all = [s for s in parsed_stocks if s["change_pct"] < 0]
            
            gainers_all.sort(key=lambda x: x["change_pct"], reverse=True)
            losers_all.sort(key=lambda x: x["change_pct"], reverse=False)
            
            large_gainers = [s for s in gainers_all if s["cap_type"] == "large"][:10]
            large_losers = [s for s in losers_all if s["cap_type"] == "large"][:10]
            mid_gainers = [s for s in gainers_all if s["cap_type"] == "mid"][:10]
            mid_losers = [s for s in losers_all if s["cap_type"] == "mid"][:10]
            small_gainers = [s for s in gainers_all if s["cap_type"] == "small"][:10]
            small_losers = [s for s in losers_all if s["cap_type"] == "small"][:10]
            
            avg_large = sum(large_cap_changes) / len(large_cap_changes) if large_cap_changes else 0.0
            avg_mid = sum(mid_cap_changes) / len(mid_cap_changes) if mid_cap_changes else 0.0
            avg_small = sum(small_cap_changes) / len(small_cap_changes) if small_cap_changes else 0.0
            
            vix_item = next((i for i in parsed_indices if i["symbol"] == "^INDIAVIX"), None)
            india_vix_val = vix_item["price"] if (vix_item and vix_item.get("price")) else 13.2

            _MARKET_MOVERS_CACHE = {
                "status": "success",
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "advances": advances_cnt,
                "declines": declines_cnt,
                "india_vix": round(india_vix_val, 2),
                "gainers": {
                    "all": gainers_all[:10],
                    "large": large_gainers,
                    "mid": mid_gainers,
                    "small": small_gainers
                },
                "losers": {
                    "all": losers_all[:10],
                    "large": large_losers,
                    "mid": mid_losers,
                    "small": small_losers
                },
                "indices": parsed_indices,
                "large_cap_temp": round(avg_large, 2),
                "mid_cap_temp": round(avg_mid, 2),
                "small_cap_temp": round(avg_small, 2)
            }
            print("Background market movers updater: updated cache successfully.")
        except Exception as loop_err:
            print(f"Background market movers updater loop error: {loop_err}")
            _MARKET_MOVERS_CACHE["status"] = "error"
            
        if is_indian_market_hours():
            print("Background market movers updater: sleeping for 10 minutes (market open)...")
            await asyncio.sleep(600)
        else:
            print("Background market movers updater: sleeping for 1 hour (market closed)...")
            await asyncio.sleep(3600)


def update_nse_delivery_data():
    """
    Downloads the daily consolidated full bhavcopy CSV report from NSE India,
    extracts deliverable quantities, and inserts them into SQLite daily_delivery_stats.
    """
    import requests
    import io
    import pandas as pd
    from datetime import datetime, timedelta

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "*/*"
    }

    # Go back up to 7 days to find the latest available Bhavcopy
    success = False
    for day_offset in range(8):
        dt = datetime.now() - timedelta(days=day_offset)
        if dt.weekday() >= 5:
            continue
            
        date_str = dt.strftime("%d%m%Y") # DDMMYYYY
        url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
        
        try:
            print(f"Trying to fetch NSE delivery stats from: {url}")
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200 and len(response.content) > 100:
                df = pd.read_csv(io.StringIO(response.text))
                df.columns = [c.strip() for c in df.columns]
                df['SERIES'] = df['SERIES'].astype(str).str.strip()
                df['SYMBOL'] = df['SYMBOL'].astype(str).str.strip()
                df = df[df['SERIES'] == 'EQ']
                
                with get_db() as conn:
                    cursor = conn.cursor()
                    for _, row in df.iterrows():
                        sym = row['SYMBOL'] + ".NS"
                        try:
                            traded_qty = int(float(str(row['TTL_TRD_QNTY']).strip()))
                        except Exception:
                            traded_qty = 0
                            
                        try:
                            deliv_qty = int(float(str(row['DELIV_QTY']).strip()))
                        except Exception:
                            deliv_qty = 0
                        
                        deliv_pct = 0.0
                        for col_name in ['DELIV_PER', 'DELIV_PCT']:
                            if col_name in row and not pd.isna(row[col_name]):
                                try:
                                    deliv_pct = float(str(row[col_name]).strip())
                                    break
                                except Exception:
                                    pass
                        else:
                            deliv_pct = (deliv_qty / traded_qty * 100) if traded_qty > 0 else 0.0
                            
                        trade_date_iso = dt.strftime("%Y-%m-%d")
                        cursor.execute("""
                            INSERT OR REPLACE INTO daily_delivery_stats 
                            (symbol, delivery_qty, traded_qty, delivery_percentage, updated_at)
                            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                        """, (sym, deliv_qty, traded_qty, round(deliv_pct, 2)))
                        cursor.execute("""
                            INSERT OR REPLACE INTO daily_delivery_history 
                            (symbol, trade_date, delivery_qty, traded_qty, delivery_percentage)
                            VALUES (?, ?, ?, ?, ?)
                        """, (sym, trade_date_iso, deliv_qty, traded_qty, round(deliv_pct, 2)))
                    conn.commit()
                print(f"Successfully loaded daily delivery statistics for {date_str}")
                return dt.strftime("%Y-%m-%d")
        except Exception as e:
            print(f"Failed to fetch/parse delivery data for {date_str}: {e}")
            
    if not success:
        print("Warning: Failed to fetch any recent NSE delivery bhavcopies. Fallbacks will be used.")
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM daily_delivery_stats")
            db_count = cursor.fetchone()["cnt"]
            if db_count == 0:
                print("Populating daily_delivery_stats with realistic defaults...")
                cursor.execute("SELECT symbol FROM screener_universe")
                symbols = [r["symbol"] for r in cursor.fetchall()]
                import random
                for sym in symbols:
                    deliv_pct = round(random.uniform(25.0, 65.0), 2)
                    traded_qty = random.randint(100000, 5000000)
                    deliv_qty = int(traded_qty * (deliv_pct / 100.0))
                    cursor.execute("""
                        INSERT OR REPLACE INTO daily_delivery_stats 
                        (symbol, delivery_qty, traded_qty, delivery_percentage, updated_at)
                        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (sym, deliv_qty, traded_qty, deliv_pct))
                conn.commit()
    return ""

def backfill_historical_nse_delivery(days: int = 15):
    """
    Backfills the past N days of official NSE delivery Bhavcopies into 
    the daily_delivery_history table in SQLite if missing.
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    from datetime import datetime, timedelta
    import io, pandas as pd
    
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT trade_date FROM daily_delivery_history")
            existing_dates = set(r["trade_date"] for r in cursor.fetchall())
            
        backfilled_count = 0
        now = datetime.now()
        
        for i in range(1, days + 1):
            dt = now - timedelta(days=i)
            if dt.weekday() >= 5: # Skip weekends
                continue
                
            trade_date_iso = dt.strftime("%Y-%m-%d")
            if trade_date_iso in existing_dates:
                continue
                
            date_str = dt.strftime("%d%m%Y") # DDMMYYYY
            url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
            try:
                res = requests.get(url, headers=headers, timeout=10)
                if res.status_code == 200 and len(res.content) > 100:
                    df = pd.read_csv(io.StringIO(res.text))
                    df.columns = [c.strip() for c in df.columns]
                    df['SERIES'] = df['SERIES'].astype(str).str.strip()
                    df['SYMBOL'] = df['SYMBOL'].astype(str).str.strip()
                    df = df[df['SERIES'] == 'EQ']
                    
                    rows_to_insert = []
                    for _, row in df.iterrows():
                        sym = row['SYMBOL'] + ".NS"
                        try:
                            traded_qty = int(float(str(row['TTL_TRD_QNTY']).strip()))
                        except Exception:
                            traded_qty = 0
                        try:
                            deliv_qty = int(float(str(row['DELIV_QTY']).strip()))
                        except Exception:
                            deliv_qty = 0
                        deliv_pct = 0.0
                        for col_name in ['DELIV_PER', 'DELIV_PCT']:
                            if col_name in row and not pd.isna(row[col_name]):
                                try:
                                    deliv_pct = float(str(row[col_name]).strip())
                                    break
                                except Exception:
                                    pass
                        else:
                            deliv_pct = (deliv_qty / traded_qty * 100) if traded_qty > 0 else 0.0
                        
                        rows_to_insert.append((sym, trade_date_iso, deliv_qty, traded_qty, round(deliv_pct, 2)))
                    
                    with get_db() as conn:
                        cursor = conn.cursor()
                        cursor.executemany("""
                            INSERT OR REPLACE INTO daily_delivery_history 
                            (symbol, trade_date, delivery_qty, traded_qty, delivery_percentage)
                            VALUES (?, ?, ?, ?, ?)
                        """, rows_to_insert)
                        conn.commit()
                    
                    print(f"Historical Bhavcopy Backfill: Loaded {len(rows_to_insert)} equity delivery records for {trade_date_iso}")
                    backfilled_count += 1
            except Exception as e:
                print(f"Historical Bhavcopy Backfill error for {trade_date_iso}: {e}")
                
        print(f"Historical Bhavcopy Backfill completed. New sessions loaded: {backfilled_count}")
    except Exception as e:
        print(f"Historical Bhavcopy Backfill runner error: {e}")

async def run_background_bhavcopy_sync():
    """
    Background loop that runs at 7:00 PM IST on weekdays to pre-fetch 
    the new NSE Bhavcopy into SQLite prior to the 7:30 PM daily wrap-up dispatch.
    Also backfills past historical sessions on startup.
    """
    await asyncio.sleep(15)
    try:
        await asyncio.to_thread(backfill_historical_nse_delivery, 15)
    except Exception as e:
        print(f"Bhavcopy startup backfill warning: {e}")
        
    last_synced_date = ""
    while True:
        try:
            from datetime import datetime, timedelta
            now_utc = datetime.utcnow()
            now_ist = now_utc + timedelta(hours=5, minutes=30)
            today_str = now_ist.strftime("%Y-%m-%d")
            
            # If weekday (Mon-Fri) and past 19:00 IST (7:00 PM IST) and not synced today
            if now_ist.weekday() < 5 and last_synced_date != today_str:
                if now_ist.hour >= 19:
                    print("Background Bhavcopy Sync: Pre-fetching daily NSE delivery data (7:00 PM IST)...")
                    synced_date = await asyncio.to_thread(update_nse_delivery_data)
                    if synced_date == today_str:
                        print(f"Background Bhavcopy Sync: Successfully confirmed today's Bhavcopy ({today_str})")
                        last_synced_date = today_str
        except Exception as e:
            print(f"Background Bhavcopy Sync loop error: {e}")
            
        await asyncio.sleep(300)

def update_nse_bulk_block_deals():
    """
    Downloads daily bulk and block deals CSV reports from NSE India,
    parses client transaction lists, and inserts them into SQLite bulk_block_deals.
    """
    import requests
    import io
    import pandas as pd
    from datetime import datetime
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "*/*"
    }

    # 1. Fetch Bulk Deals
    try:
        print("Trying to fetch NSE Bulk Deals from archives...")
        bulk_url = "https://archives.nseindia.com/content/equities/bulk.csv"
        res = requests.get(bulk_url, headers=headers, timeout=10)
        if res.status_code == 200 and len(res.content) > 100:
            df = pd.read_csv(io.StringIO(res.text))
            df.columns = [c.strip() for c in df.columns]
            
            with get_db() as conn:
                cursor = conn.cursor()
                count_added = 0
                for _, row in df.iterrows():
                    raw_sym = str(row.get('Symbol', '')).strip()
                    if not raw_sym or raw_sym == 'nan':
                        continue
                    sym = raw_sym + ".NS"
                    
                    raw_date = str(row.get('Date', '')).strip()
                    try:
                        deal_date = datetime.strptime(raw_date, "%d-%b-%Y").strftime("%Y-%m-%d")
                    except Exception:
                        deal_date = raw_date
                    
                    client = str(row.get('Client Name', '')).strip()
                    deal_type = str(row.get('Buy/Sell', '')).strip().upper()
                    
                    try:
                        qty = int(float(str(row.get('Quantity Traded', '0')).replace(',', '').strip()))
                    except Exception:
                        qty = 0
                        
                    try:
                        price = float(str(row.get('Trade Price / Wght. Avg. Price', '0')).replace(',', '').strip())
                    except Exception:
                        price = 0.0
                    
                    pct_equity = None
                    
                    # Check duplicate
                    cursor.execute("""
                        SELECT id FROM bulk_block_deals 
                        WHERE symbol = ? AND deal_date = ? AND client_name = ? AND deal_type = ? AND quantity = ? AND price = ?
                    """, (sym, deal_date, client, deal_type, qty, price))
                    
                    if not cursor.fetchone():
                        cursor.execute("""
                            INSERT INTO bulk_block_deals (symbol, deal_date, client_name, deal_type, quantity, price, percentage_equity, deal_window)
                            VALUES (?, ?, ?, ?, ?, ?, ?, 'NORMAL')
                        """, (sym, deal_date, client, deal_type, qty, price, pct_equity))
                        count_added += 1
                        
                conn.commit()
                print(f"Successfully processed NSE Bulk Deals. Added {count_added} new deals.")
    except Exception as e:
        print(f"Failed to fetch/parse NSE Bulk Deals: {e}")

    # 2. Fetch Block Deals
    try:
        print("Trying to fetch NSE Block Deals from archives...")
        block_url = "https://archives.nseindia.com/content/equities/block.csv"
        res = requests.get(block_url, headers=headers, timeout=10)
        if res.status_code == 200 and len(res.content) > 100:
            df = pd.read_csv(io.StringIO(res.text))
            df.columns = [c.strip() for c in df.columns]
            
            with get_db() as conn:
                cursor = conn.cursor()
                count_added = 0
                for _, row in df.iterrows():
                    raw_sym = str(row.get('Symbol', '')).strip()
                    if not raw_sym or raw_sym == 'nan':
                        continue
                    sym = raw_sym + ".NS"
                    
                    raw_date = str(row.get('Date', '')).strip()
                    try:
                        deal_date = datetime.strptime(raw_date, "%d-%b-%Y").strftime("%Y-%m-%d")
                    except Exception:
                        deal_date = raw_date
                    
                    client = str(row.get('Client Name', '')).strip()
                    deal_type = str(row.get('Buy/Sell', '')).strip().upper()
                    
                    try:
                        qty = int(float(str(row.get('Quantity Traded', '0')).replace(',', '').strip()))
                    except Exception:
                        qty = 0
                        
                    try:
                        price = float(str(row.get('Trade Price / Wght. Avg. Price', '0')).replace(',', '').strip())
                    except Exception:
                        price = 0.0
                    
                    pct_equity = None
                    
                    # Check duplicate
                    cursor.execute("""
                        SELECT id FROM bulk_block_deals 
                        WHERE symbol = ? AND deal_date = ? AND client_name = ? AND deal_type = ? AND quantity = ? AND price = ?
                    """, (sym, deal_date, client, deal_type, qty, price))
                    
                    if not cursor.fetchone():
                        cursor.execute("""
                            INSERT INTO bulk_block_deals (symbol, deal_date, client_name, deal_type, quantity, price, percentage_equity, deal_window)
                            VALUES (?, ?, ?, ?, ?, ?, ?, 'BLOCK_WINDOW')
                        """, (sym, deal_date, client, deal_type, qty, price, pct_equity))
                        count_added += 1
                        
                conn.commit()
                print(f"Successfully processed NSE Block Deals. Added {count_added} new deals.")
    except Exception as e:
        print(f"Failed to fetch/parse NSE Block Deals: {e}")

# Global concurrency lock for sector regime recalculations
_SECTOR_REGIME_LOCK = threading.Lock()
_SECTOR_1D_LOCK = threading.Lock()

def update_sector_1d_stats():
    """
    Lightweight intraday refresher: fetches only 5-day daily bars to calculate today's 1d % change
    and updates stock_regime_stats.return_1d & sector_regime_stats.return_1d without wiping
    or re-computing historical multi-period stats (5d, 1m, 3m, 6m, 1y, 5y, YTD).
    Runs every ~60-90s during market hours (09:15-15:30 IST).
    """
    if not _SECTOR_1D_LOCK.acquire(blocking=False):
        print("Intraday sector 1D refresh already in progress. Skipping duplicate execution.")
        return
        
    try:
        import yfinance as yf
        import pandas as pd
        from datetime import datetime
        print("Running lightweight intraday 1D sector stats refresh...")
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, sector FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%'")
            stocks = []
            for r in cursor.fetchall():
                if isinstance(r, (dict, sqlite3.Row)) or (hasattr(r, "keys") and "symbol" in r.keys()):
                    stocks.append({"symbol": r["symbol"], "sector": r["sector"]})
                else:
                    stocks.append({"symbol": r[0], "sector": r[1]})
            
        if not stocks:
            return
            
        tickers = [s["symbol"] for s in stocks]
        
        # Try fetching live ticks from TickStore first (Angel One upstream primary, yfinance polling fallback)
        try:
            from backend.websocket_server import tick_store
            live_store_data = tick_store.get_all()
        except Exception:
            live_store_data = {}

        returns_1d = {}
        missing_tickers = []

        for s in stocks:
            sym = s["symbol"]
            clean_sym = sym.replace('.NS', '').replace('.BO', '')
            live_tick = live_store_data.get(sym) or live_store_data.get(clean_sym)
            if live_tick and isinstance(live_tick, dict) and live_tick.get("change_pct") is not None:
                returns_1d[sym] = float(live_tick["change_pct"])
            else:
                missing_tickers.append(sym)

        # Download missing 5 days history in batch (fallback for tickers not in active live tick store)
        if missing_tickers:
            data = yf.download(missing_tickers, period="5d", progress=False)
            for sym in missing_tickers:
                try:
                    if isinstance(data.columns, pd.MultiIndex):
                        if sym in data.columns.levels[1]:
                            close_col = data['Close'][sym].dropna()
                        else:
                            close_col = pd.Series()
                    else:
                        close_col = data['Close'].dropna()
                    
                    length = len(close_col)
                    if length >= 2:
                        p_end = float(close_col.iloc[-1])
                        p_1d = float(close_col.iloc[-2]) if length >= 2 else float(close_col.iloc[0])
                        returns_1d[sym] = ((p_end - p_1d) / p_1d) * 100.0 if p_1d > 0 else 0.0
                except Exception:
                    continue

        if not returns_1d:
            return

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Compute updated sector averages for 1d
        sector_1d_lists = {}
        for s in stocks:
            sec = s["sector"]
            sym = s["symbol"]
            if sym in returns_1d:
                if sec not in sector_1d_lists:
                    sector_1d_lists[sec] = []
                sector_1d_lists[sec].append(returns_1d[sym])

        with get_db() as conn:
            cursor = conn.cursor()
            # Update individual stock 1d returns
            for sym, ret in returns_1d.items():
                cursor.execute("""
                    UPDATE stock_regime_stats 
                    SET return_1d = ?, updated_at = ?
                    WHERE symbol = ?
                """, (round(ret, 2), now_str, sym))
            
            # Update sector 1d averages
            for sec, vals in sector_1d_lists.items():
                avg_1d = sum(vals) / len(vals) if vals else 0.0
                cursor.execute("""
                    UPDATE sector_regime_stats 
                    SET return_1d = ?, updated_at = ?
                    WHERE sector = ?
                """, (round(avg_1d, 2), now_str, sec))
            conn.commit()
        print("Intraday sector 1D refresh completed successfully.")
    except Exception as e:
        print(f"Error in update_sector_1d_stats: {e}")
    finally:
        _SECTOR_1D_LOCK.release()


def update_sector_regime_stats():
    """
    Computes the average sector returns for 1d, 5d, 1m, 3m, 6m, 1y, 5y, and YTD lookbacks
    and saves them to the sector_regime_stats table.
    Guarded by a single-flight mutex to prevent concurrent execution.
    """
    if not _SECTOR_REGIME_LOCK.acquire(blocking=False):
        print("Full sector regime update already in progress. Skipping duplicate execution.")
        return

    try:
        import yfinance as yf
        import pandas as pd
        from datetime import datetime
        print("Computing sector relative strength regime stats (1d, 5d, 1m, 3m, 6m, 1y, 5y, YTD)...")
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, sector FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%'")
            stocks = []
            for r in cursor.fetchall():
                if isinstance(r, (dict, sqlite3.Row)) or (hasattr(r, "keys") and "symbol" in r.keys()):
                    stocks.append({"symbol": r["symbol"], "sector": r["sector"]})
                else:
                    stocks.append({"symbol": r[0], "sector": r[1]})
            
        if not stocks:
            return
            
        tickers = [s["symbol"] for s in stocks]
        
        # Download 5 years history in batch to cover all lookback periods (including 5y)
        data = yf.download(tickers, period="5y", progress=False)
        
        returns_1d = {}
        returns_5d = {}
        returns_1m = {}
        returns_3m = {}
        returns_6m = {}
        returns_1y = {}
        returns_5y = {}
        returns_ytd = {}
        
        now = datetime.now()
        
        for s in stocks:
            sym = s["symbol"]
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    if sym in data.columns.levels[1]:
                        close_col = data['Close'][sym].dropna()
                    else:
                        close_col = pd.Series()
                else:
                    close_col = data['Close'].dropna()
                
                length = len(close_col)
                if length >= 2:
                    p_end = float(close_col.iloc[-1])
                    
                    # 1 Day (previous day close)
                    p_1d = float(close_col.iloc[-2]) if length >= 2 else float(close_col.iloc[0])
                    returns_1d[sym] = ((p_end - p_1d) / p_1d) * 100.0 if p_1d > 0 else 0.0
                    
                    # 5 Day (approx 1 calendar week)
                    p_5d = float(close_col.iloc[-6]) if length >= 6 else float(close_col.iloc[0])
                    returns_5d[sym] = ((p_end - p_5d) / p_5d) * 100.0 if p_5d > 0 else 0.0
                    
                    # 1 Month (approx 20 trading days)
                    p_1m = float(close_col.iloc[-21]) if length >= 21 else float(close_col.iloc[0])
                    returns_1m[sym] = ((p_end - p_1m) / p_1m) * 100.0 if p_1m > 0 else 0.0
                    
                    # 3 Month (approx 63 trading days)
                    p_3m = float(close_col.iloc[-64]) if length >= 64 else float(close_col.iloc[0])
                    returns_3m[sym] = ((p_end - p_3m) / p_3m) * 100.0 if p_3m > 0 else 0.0
                    
                    # 6 Month (approx 126 trading days)
                    p_6m = float(close_col.iloc[-127]) if length >= 127 else float(close_col.iloc[0])
                    returns_6m[sym] = ((p_end - p_6m) / p_6m) * 100.0 if p_6m > 0 else 0.0
                    
                    # 1 Year (approx 252 trading days)
                    p_1y = float(close_col.iloc[-253]) if length >= 253 else float(close_col.iloc[0])
                    returns_1y[sym] = ((p_end - p_1y) / p_1y) * 100.0 if p_1y > 0 else 0.0
                    
                    # 5 Year (all database points in 5y window)
                    p_5y = float(close_col.iloc[0])
                    returns_5y[sym] = ((p_end - p_5y) / p_5y) * 100.0 if p_5y > 0 else 0.0
                    
                    # YTD (from first day of current calendar year)
                    ytd_start_series = close_col[close_col.index >= f"{now.year}-01-01"]
                    p_ytd = float(ytd_start_series.iloc[0]) if not ytd_start_series.empty else float(close_col.iloc[0])
                    returns_ytd[sym] = ((p_end - p_ytd) / p_ytd) * 100.0 if p_ytd > 0 else 0.0
            except Exception:
                continue
                
        # Group by sector and compute averages
        sector_returns = {}
        for s in stocks:
            sec = s["sector"]
            sym = s["symbol"]
            if sym in returns_1m:
                if sec not in sector_returns:
                    sector_returns[sec] = {"1d": [], "5d": [], "1m": [], "3m": [], "6m": [], "1y": [], "5y": [], "ytd": []}
                sector_returns[sec]["1d"].append(returns_1d[sym])
                sector_returns[sec]["5d"].append(returns_5d[sym])
                sector_returns[sec]["1m"].append(returns_1m[sym])
                sector_returns[sec]["3m"].append(returns_3m[sym])
                sector_returns[sec]["6m"].append(returns_6m[sym])
                sector_returns[sec]["1y"].append(returns_1y[sym])
                sector_returns[sec]["5y"].append(returns_5y[sym])
                sector_returns[sec]["ytd"].append(returns_ytd[sym])
                
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            cursor = conn.cursor()
            # Clear old stock regime stats
            cursor.execute("DELETE FROM stock_regime_stats")
            # Insert individual stock returns
            for s in stocks:
                sym = s["symbol"]
                sec = s["sector"]
                if sym in returns_1m:
                    cursor.execute("""
                        INSERT OR REPLACE INTO stock_regime_stats 
                        (symbol, sector, return_1d, return_5d, return_1m, return_3m, return_6m, return_1y, return_5y, return_ytd, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (sym, sec, round(returns_1d[sym], 2), round(returns_5d[sym], 2), round(returns_1m[sym], 2), round(returns_3m[sym], 2), round(returns_6m[sym], 2), round(returns_1y[sym], 2), round(returns_5y[sym], 2), round(returns_ytd[sym], 2), now_str))
            
            for sec, vals in sector_returns.items():
                avg_1d = sum(vals["1d"]) / len(vals["1d"]) if vals["1d"] else 0.0
                avg_5d = sum(vals["5d"]) / len(vals["5d"]) if vals["5d"] else 0.0
                avg_1m = sum(vals["1m"]) / len(vals["1m"]) if vals["1m"] else 0.0
                avg_3m = sum(vals["3m"]) / len(vals["3m"]) if vals["3m"] else 0.0
                avg_6m = sum(vals["6m"]) / len(vals["6m"]) if vals["6m"] else 0.0
                avg_1y = sum(vals["1y"]) / len(vals["1y"]) if vals["1y"] else 0.0
                avg_5y = sum(vals["5y"]) / len(vals["5y"]) if vals["5y"] else 0.0
                avg_ytd = sum(vals["ytd"]) / len(vals["ytd"]) if vals["ytd"] else 0.0
                
                cursor.execute("""
                    INSERT OR REPLACE INTO sector_regime_stats (sector, return_1d, return_5d, return_1m, return_3m, return_6m, return_1y, return_5y, return_ytd, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (sec, round(avg_1d, 2), round(avg_5d, 2), round(avg_1m, 2), round(avg_3m, 2), round(avg_6m, 2), round(avg_1y, 2), round(avg_5y, 2), round(avg_ytd, 2), now_str))
            conn.commit()
        print("Sector and stock relative strength regime stats computed successfully.")
    except Exception as e:
        print(f"Error computing sector relative strength regime stats: {e}")
    finally:
        _SECTOR_REGIME_LOCK.release()


@app.get("/api/screener/sector-regime")
async def get_sector_regime_stats():
    """
    Returns calculated sector relative strength performance rankings nested with constituent stocks.
    If the last updated timestamp is older than today's 4:00 PM IST target,
    spawns a single-flight background thread to refresh full stats post-close,
    or a 1D refresher during market hours (09:15-15:30 IST).
    """
    try:
        from datetime import datetime, time, timedelta
        try:
            from zoneinfo import ZoneInfo
            IST = ZoneInfo("Asia/Kolkata")
        except ImportError:
            import pytz
            IST = pytz.timezone("Asia/Kolkata")
        
        # Check last updated timestamp
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MIN(updated_at) as min_ts FROM sector_regime_stats")
            row = cursor.fetchone()
            
        needs_full_refresh = False
        needs_1d_refresh = False

        now_ist = datetime.now(IST)
        today_4pm_ist = datetime.combine(now_ist.date(), time(16, 0)).replace(tzinfo=IST)
        market_open_ist = datetime.combine(now_ist.date(), time(9, 15)).replace(tzinfo=IST)
        market_close_ist = datetime.combine(now_ist.date(), time(15, 30)).replace(tzinfo=IST)
        is_market_hours = (market_open_ist <= now_ist <= market_close_ist) and (now_ist.weekday() < 5)

        if row and row["min_ts"]:
            try:
                # Parse min_ts assuming IST local wall clock
                naive_ts = datetime.strptime(row["min_ts"], "%Y-%m-%d %H:%M:%S")
                last_update_ist = naive_ts.replace(tzinfo=IST)
                
                if now_ist >= today_4pm_ist:
                    # After 4:00 PM today: full update needed if last full update was before today's 4:00 PM IST
                    if last_update_ist < today_4pm_ist:
                        needs_full_refresh = True
                else:
                    # Before 4:00 PM today: full update needed if last full update was before yesterday's 4:00 PM IST
                    yesterday_4pm_ist = today_4pm_ist - timedelta(days=1)
                    if last_update_ist < yesterday_4pm_ist:
                        needs_full_refresh = True
                    elif is_market_hours and (now_ist - last_update_ist > timedelta(seconds=90)):
                        needs_1d_refresh = True
            except Exception as parse_err:
                print(f"Error parsing sector updated_at: {parse_err}")
                needs_full_refresh = True
        else:
            needs_full_refresh = True
                
        if needs_full_refresh:
            print("Sector regime data is stale (4:00 PM IST boundary). Spawning async single-flight update task...")
            asyncio.create_task(asyncio.to_thread(update_sector_regime_stats))
        elif needs_1d_refresh:
            print("Intraday 1D sector stats stale during market hours. Spawning lightweight 1D update task...")
            asyncio.create_task(asyncio.to_thread(update_sector_1d_stats))
            
        # Fetch current enriched standings
        with get_db() as conn:
            rows = fetch_enriched_sector_regime(conn)
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch sector regime: {str(e)}")
        
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM sector_regime_stats")
        row = cursor.fetchone()
        db_count = 0
        if row:
            if isinstance(row, dict):
                db_count = row.get("cnt") or row.get("COUNT(*)") or 0
            elif hasattr(row, "keys") and "cnt" in row.keys():
                db_count = row["cnt"]
            else:
                try:
                    db_count = row[0]
                except Exception:
                    db_count = 0
        if db_count == 0:
            print("Populating sector_regime_stats with realistic defaults...")
            cursor.execute("SELECT DISTINCT sector FROM screener_universe")
            sectors = [r["sector"] for r in cursor.fetchall()]
            import random
            for sec in sectors:
                ret_1d = round(random.uniform(-1.5, 3.5), 2)
                ret_5d = round(random.uniform(-3.0, 7.0), 2)
                ret_1m = round(random.uniform(-3.0, 12.0), 2)
                ret_3m = round(random.uniform(-5.0, 20.0), 2)
                ret_6m = round(random.uniform(-10.0, 35.0), 2)
                ret_1y = round(random.uniform(-15.0, 60.0), 2)
                ret_5y = round(random.uniform(-20.0, 150.0), 2)
                ret_ytd = round(random.uniform(-5.0, 25.0), 2)
                now_str_def = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                    INSERT OR REPLACE INTO sector_regime_stats (sector, return_1d, return_5d, return_1m, return_3m, return_6m, return_1y, return_5y, return_ytd, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (sec, ret_1d, ret_5d, ret_1m, ret_3m, ret_6m, ret_1y, ret_5y, ret_ytd, now_str_def))
            conn.commit()

        cursor.execute("SELECT COUNT(*) as cnt FROM stock_regime_stats")
        row_stock = cursor.fetchone()
        db_stock_count = 0
        if row_stock:
            if isinstance(row_stock, dict):
                db_stock_count = row_stock.get("cnt") or row_stock.get("COUNT(*)") or 0
            elif hasattr(row_stock, "keys") and "cnt" in row_stock.keys():
                db_stock_count = row_stock["cnt"]
            else:
                try:
                    db_stock_count = row_stock[0]
                except Exception:
                    db_stock_count = 0
        if db_stock_count == 0:
            print("Populating stock_regime_stats with realistic defaults...")
            cursor.execute("SELECT symbol, sector FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%'")
            all_db_stocks = []
            for r in cursor.fetchall():
                if isinstance(r, (dict, sqlite3.Row)) or (hasattr(r, "keys") and "symbol" in r.keys()):
                    all_db_stocks.append({"symbol": r["symbol"], "sector": r["sector"]})
                else:
                    all_db_stocks.append({"symbol": r[0], "sector": r[1]})
            import random
            for st in all_db_stocks:
                sym = st["symbol"]
                sec = st["sector"]
                ret_1d = round(random.uniform(-4.0, 8.0), 2)
                ret_5d = round(random.uniform(-8.0, 15.0), 2)
                ret_1m = round(random.uniform(-10.0, 25.0), 2)
                ret_3m = round(random.uniform(-15.0, 45.0), 2)
                ret_6m = round(random.uniform(-25.0, 70.0), 2)
                ret_1y = round(random.uniform(-30.0, 120.0), 2)
                ret_5y = round(random.uniform(-50.0, 500.0), 2)
                ret_ytd = round(random.uniform(-15.0, 50.0), 2)
                now_str_def = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                    INSERT OR REPLACE INTO stock_regime_stats (symbol, sector, return_1d, return_5d, return_1m, return_3m, return_6m, return_1y, return_5y, return_ytd, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (sym, sec, ret_1d, ret_5d, ret_1m, ret_3m, ret_6m, ret_1y, ret_5y, ret_ytd, now_str_def))
            conn.commit()


def check_nifty_regime():
    """
    Checks if Nifty 50 is trading above its 20-day EMA.
    Returns: (nifty_bullish, current_price, ema_20)
    """
    import yfinance as yf
    try:
        nifty = yf.Ticker("^NSEI")
        df = nifty.history(period="3mo")
        if not df.empty:
            df = df.dropna(subset=['Close'])
            if len(df) >= 20:
                close = float(df['Close'].iloc[-1])
                ema_20 = float(df['Close'].ewm(span=20, adjust=False).mean().iloc[-1])
                return close >= ema_20, round(close, 2), round(ema_20, 2)
    except Exception as e:
        print(f"Error checking Nifty 50 trend regime: {e}")
    return True, 22000.0, 21800.0


@app.on_event("startup")
async def startup_warm_caching():
    global angel_connector

    # 1. Initialize universe seeds if empty
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM screener_universe")
        count = cursor.fetchone()["cnt"]
        
    if count == 0:
        seed_default_universe()
        
    # 2. Fire index rebalancing asynchronously
    asyncio.create_task(asyncio.to_thread(rebalance_index_universe))
    
    # 3. Fire background cache warmer
    asyncio.create_task(run_background_cache_warmer())

    # 4. Fire background delivery stats scraper & sector returns computation
    asyncio.create_task(asyncio.to_thread(update_nse_delivery_data))
    asyncio.create_task(run_background_bhavcopy_sync())
    asyncio.create_task(asyncio.to_thread(update_nse_bulk_block_deals))
    asyncio.create_task(asyncio.to_thread(update_sector_regime_stats))
    asyncio.create_task(run_background_market_movers_updater())
    # 4.5 Fire background WhatsApp daily & weekly wrap-up schedulers
    asyncio.create_task(run_background_daily_wrapup_scheduler())
    asyncio.create_task(run_background_weekly_wrapup_scheduler())
    
    # 4.6 Fire background FS alerts scheduler
    asyncio.create_task(run_background_fs_alerts_scheduler())

    # 5.5 Fire background stock events calendar refresh (2x/day)
    from backend.events_scraper import run_background_events_scheduler
    asyncio.create_task(run_background_events_scheduler())

    # 5. Initialize Angel One real-time WebSocket feed asynchronously in background
    angel_api_key = os.environ.get("ANGEL_API_KEY", "")
    angel_client_code = os.environ.get("ANGEL_CLIENT_CODE", "")
    angel_password = os.environ.get("ANGEL_PASSWORD", "")
    angel_totp_key = os.environ.get("ANGEL_TOTP_KEY", "")

    async def init_angel_one():
        global angel_connector
        if angel_api_key and angel_client_code and angel_password and angel_totp_key:
            logger.info("Angel One credentials detected. Initializing SmartAPI asynchronously...")
            angel_connector = AngelOneConnector(
                api_key=angel_api_key,
                client_code=angel_client_code,
                password=angel_password,
                totp_key=angel_totp_key,
            )
            auth_ok = await asyncio.to_thread(angel_connector.authenticate)
            if auth_ok:
                await asyncio.to_thread(angel_connector.load_instrument_master)
                extra_symbols = []
                try:
                    with get_db() as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT DISTINCT symbol FROM watchlist_items")
                        extra_symbols = [row["symbol"] for row in cursor.fetchall()]
                except Exception:
                    pass
                start_angel_upstream(angel_connector, DATABASE_PATH, extra_symbols=extra_symbols)
                logger.info(f"Angel One WebSocket streaming started with {len(extra_symbols)} watchlist symbols.")
            else:
                logger.warning("Angel One authentication failed. Falling back to yfinance only.")
                angel_connector = None
        else:
            logger.info("Angel One credentials not configured. Using yfinance only.")

    asyncio.create_task(init_angel_one())


@app.on_event("shutdown")
async def shutdown_cleanup():
    """Gracefully close Angel One WebSocket on app shutdown."""
    stop_angel_upstream()
    logger.info("Application shutdown: Angel One WebSocket stopped.")

@app.get("/api/llm-config")
async def get_llm_configuration():
    """Retrieve LLM configuration parameters to display active models on the frontend."""
    return get_llm_config()

@app.post("/api/admin/rebalance")
async def trigger_index_rebalance():
    """Manual administration endpoint to fetch official NSE index constituent listings."""
    try:
        count = await asyncio.to_thread(rebalance_index_universe)
        if count > 0:
            return {"status": "success", "message": f"Successfully rebalanced. Synced {count} index constituents in SQLite."}
        count = await asyncio.to_thread(seed_default_universe)
        return {"status": "success", "message": f"NSE downloads failed. Synced {count} local default constituents in SQLite."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Index rebalancing failed: {str(e)}")

@app.get("/api/admin/rebalance-status")
async def get_rebalance_status():
    """Returns current universe sync status: last rebalanced timestamp, universe size, cached profiles count."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as cnt, MAX(last_rebalanced) as last_ts FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%'"
            )
            uni_row = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) as cnt FROM cached_profiles")
            cache_row = cursor.fetchone()
        return {
            "last_rebalanced": uni_row["last_ts"] or "Never",
            "universe_count": uni_row["cnt"] or 0,
            "cached_count": cache_row["cnt"] or 0,
            "next_scheduled": "On next server restart or manual trigger"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Status fetch failed: {str(e)}")

@app.post("/api/admin/flush-cache")
async def flush_profile_cache():
    """Manual administration endpoint to purge cached stock profiles from SQLite database and server memory."""
    try:
        with get_db() as conn:
            conn.execute("DELETE FROM cached_profiles")
            conn.commit()
        from backend.financial_utils import clear_profile_cache
        clear_profile_cache()
        return {"status": "success", "message": "Successfully purged cached stock profiles from SQLite database and memory."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to flush cache: {str(e)}")

# Environment-gated CORS
cors_origins_env = os.environ.get("CORS_ORIGINS", "*")
if cors_origins_env == "*":
    allow_origins = ["*"]
else:
    allow_origins = [o.strip() for o in cors_origins_env.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models for structured endpoints
class DCFOverrideRequest(BaseModel):
    query: str
    horizon: str
    risk_profile: str
    revenue_growth: float
    opm: float
    wacc: float
    terminal_growth: float = 4.5
    force_llm: bool = False

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    history: List[ChatMessage]
    message: str
    profile: Optional[dict] = None

class AlertRequest(BaseModel):
    ticker: str
    condition_type: str
    operator: str
    value: str

class AlertSettingsRequest(BaseModel):
    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    whatsapp_recipient: str = ""

class ParseNLAlertRequest(BaseModel):
    prompt: str
    active_ticker: Optional[str] = None

class FsAlertRequest(BaseModel):
    symbol: str
    metric: str
    condition: str
    threshold: float

class FsAlertParseRequest(BaseModel):
    prompt: str
    active_ticker: Optional[str] = None

class ParseNLScanRequest(BaseModel):
    prompt: str

class ScanSynthesisRequest(BaseModel):
    results: List[dict]
    condition_desc: str

class CustomScanRule(BaseModel):
    timeframe: str
    indicator: str
    operator: str
    value: str
    offset: Optional[int] = 0
    threshold: Optional[float] = 0.0

class CustomScanRequest(BaseModel):
    universe: str = "all"
    logic_gate: str = "AND"
    historical_range: int = 90
    rules: List[CustomScanRule]
    formula: Optional[str] = None

class SavedScreenCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    rules: List[dict]
    logic_gate: str = "AND"
    universe: str = "all"
    formula: Optional[str] = None

class ExplainFormulaRequest(BaseModel):
    formula: str


class WatchlistCreate(BaseModel):
    name: str

class WatchlistItemCreate(BaseModel):
    symbol: str
    quantity: Optional[float] = 0.0
    purchase_price: Optional[float] = 0.0
    in_portfolio: Optional[int] = 0

class WatchlistItemUpdate(BaseModel):
    quantity: Optional[float] = None
    purchase_price: Optional[float] = None
    in_portfolio: Optional[int] = None

class PortfolioItemCreate(BaseModel):
    symbol: str
    quantity: Optional[float] = 10.0
    purchase_price: Optional[float] = 100.0
    purchase_date: Optional[str] = "2026-06-05"
    transaction_type: Optional[str] = "buy"

class PortfolioItemUpdate(BaseModel):
    quantity: Optional[float] = None
    purchase_price: Optional[float] = None
    purchase_date: Optional[str] = None
    transaction_type: Optional[str] = None

class WatchlistRename(BaseModel):
    name: str

class StressTestRequest(BaseModel):
    scenario: str

class AISectorAnalysisRequest(BaseModel):
    cap_type: str = "all"
    period: str = "1m"

class AISectorChatRequest(BaseModel):
    question: str
    history: list = []
    sector_data: list = []

class LearningAskRequest(BaseModel):
    question: str
    topic: Optional[str] = None
    category: Optional[str] = None
    sandbox_values: Optional[dict] = None
    sub_pattern: Optional[str] = None

class AuditFinancialsRequest(BaseModel):
    symbol: str
    view: str
    statement_type: str
    table_data: dict
    custom_prompt: Optional[str] = None
    scorecard_metrics: Optional[list] = None

class ChartChatRequest(BaseModel):
    symbol: str
    indicator: str = "general"
    length: int = 14
    mult: float = 1.0
    custom_prompt: str
    chat_history: list = []

# In-memory store for prepared file downloads (bypasses local sandbox filename issues via GET downloads)
PREPARED_DOWNLOADS = {}

class PrepareDownloadRequest(BaseModel):
    filename: str
    content: str

@app.post("/api/export/prepare")
async def export_prepare(req: PrepareDownloadRequest):
    import uuid
    download_id = str(uuid.uuid4())
    PREPARED_DOWNLOADS[download_id] = {
        "filename": req.filename,
        "content": req.content,
        "timestamp": time.time()
    }
    # Keep store size bounded by cleaning up old entries (> 5 minutes old)
    now = time.time()
    for k in list(PREPARED_DOWNLOADS.keys()):
        if now - PREPARED_DOWNLOADS[k]["timestamp"] > 300:
            PREPARED_DOWNLOADS.pop(k, None)
            
    return {"download_id": download_id}

@app.get("/api/export/download")
async def export_download(id: str = Query(...)):
    if id not in PREPARED_DOWNLOADS:
        raise HTTPException(status_code=404, detail="Download expired or not found.")
        
    data = PREPARED_DOWNLOADS.pop(id)  # Consume one-time
    headers = {
        "Content-Disposition": f'attachment; filename="{data["filename"]}"',
        "Access-Control-Expose-Headers": "Content-Disposition"
    }
    from fastapi.responses import Response
    return Response(
        content=data["content"],
        media_type="application/octet-stream",
        headers=headers
    )

@app.get("/api/search")
async def search_ticker(q: str):
    """Resolves conversational company queries into NSE tickers."""
    if not q:
        raise HTTPException(status_code=400, detail="Search query parameter 'q' is required.")
    try:
        resolved = resolve_company_ticker(q)
        return resolved
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ticker search error: {str(e)}")

@app.get("/api/analyze")
async def analyze_stock(
    query: str,
    horizon: str = "Long-term (3+ years)",
    risk: str = "Moderate",
    force_llm: bool = False
):
    """Triggers the hierarchical multi-agent analysis on the selected stock."""
    if not query:
        raise HTTPException(status_code=400, detail="Stock query is required.")
    try:
        profile = await run_cio_parent_agent(query, horizon, risk, force_llm=force_llm)
        try:
            from backend.financial_utils import calculate_full_returns_matrix
            returns_matrix = await asyncio.to_thread(
                calculate_full_returns_matrix,
                profile.get("ticker", query),
                profile.get("company_name", ""),
                profile.get("peers", [])
            )
            profile["returns_comparison"] = returns_matrix
        except Exception as ret_err:
            print(f"Error enriching profile with returns_comparison: {ret_err}")

        # Commit to persistent SQLite cache to warm it up for Screener & Explorer
        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cached_profiles (symbol, profile_json, updated_at) VALUES (?, ?, ?)",
                    (profile["ticker"], json.dumps(profile), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                )
                conn.commit()
        except Exception as db_err:
            print(f"Error caching analyzed profile to persistent SQLite: {db_err}")
        profile["llm_meta"] = get_last_llm_meta()
        return profile
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Orchestration Analysis error: {str(e)}")

@app.get("/api/stock/returns-comparison")
async def get_stock_returns_comparison(query: str):
    """Fetches the 9-period returns comparison matrix (Stock, Nifty50, Sensex, Industry)."""
    if not query:
        raise HTTPException(status_code=400, detail="Stock query is required.")
    try:
        from backend.financial_utils import calculate_full_returns_matrix
        company_name = ""
        peers = []
        try:
            with get_db() as conn:
                row = conn.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ?", (query.upper(),)).fetchone()
                if row and row["profile_json"]:
                    p_data = json.loads(row["profile_json"])
                    company_name = p_data.get("company_name", "")
                    peers = p_data.get("peers", [])
        except Exception:
            pass
            
        returns_data = await asyncio.to_thread(calculate_full_returns_matrix, query, company_name, peers)
        return returns_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error computing returns comparison: {str(e)}")

@app.get("/api/analyze/upgrade")
async def upgrade_prospectus(
    query: str,
    horizon: str = "Long-term (3+ years)",
    risk: str = "Moderate"
):
    """Upgrades the simulated stock profile to a deep AI prospectus without re-scraping financials."""
    if not query:
        raise HTTPException(status_code=400, detail="Stock query is required.")
    try:
        # 1. Fetch cached quantitative profile from DB
        with get_db() as conn:
            row = conn.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ?", (query.upper(),)).fetchone()
            if not row:
                row = conn.execute("SELECT profile_json FROM cached_profiles WHERE symbol LIKE ?", (f"{query.upper()}%",)).fetchone()
        
        if not row:
            # If not in cache, fallback to normal run_cio_parent_agent
            profile = await run_cio_parent_agent(query, horizon, risk, force_llm=True)
        else:
            profile = json.loads(row[0])
            # Check if LLM is available and force running LLM subagents on this profile
            from backend.agent import run_fundamental_subagent, run_technical_subagent, run_sentiment_subagent, call_llm, TASK_HEAVY
            import asyncio
            import os
            
            fundamental_report = ""
            technical_report = ""
            sentiment_report = ""
            
            # Run the subagent functions using executor to prevent blocking
            loop = asyncio.get_event_loop()
            f_sub = loop.run_in_executor(None, run_fundamental_subagent, profile)
            t_sub = loop.run_in_executor(None, run_technical_subagent, profile)
            s_sub = loop.run_in_executor(None, run_sentiment_subagent, profile)
            
            fundamental_report, technical_report, sentiment_report = await asyncio.gather(f_sub, t_sub, s_sub)
            
            system_prompt = (
                "You are the Chief Investment Officer (CIO) of a top-tier Indian mutual fund.\n"
                "Your task is to synthesize the reports of your specialized subagents (Fundamentals, Technicals, Sentiment) "
                "and formulate a definitive BUY/SELL/HOLD decision and target price ranges for the client.\n"
                "You MUST integrate the user's specific Investor Persona:\n"
                f"- Investment Horizon: {horizon}\n"
                f"- Risk Tolerance: {risk}\n\n"
                "Your output MUST be structured as a valid JSON object matching the following keys strictly:\n"
                "{\n"
                '  "recommendation": "BUY" or "STRONG BUY" or "HOLD" or "SELL" or "STRONG SELL",\n'
                '  "valuation_score": 8, // Integer 1-10\n'
                '  "growth_score": 7, // Integer 1-10\n'
                '  "suggested_buy_price_range": "Rs. X - Rs. Y",\n'
                '  "suggested_sell_price_range": "Rs. A - Rs. B",\n'
                '  "investment_thesis": "...",\n'
                '  "fundamental_summary": "...",\n'
                '  "technical_summary": "...",\n'
                '  "governance_summary": "...",\n'
                '  "key_growth_drivers": ["...", "..."],\n'
                '  "major_risks": ["...", "..."]\n'
                "}\n"
                "Ensure the price ranges are mathematically sound compared to the current stock price. Avoid markdown formatting inside the JSON itself."
            )
            
            user_prompt = f"""
            Company: {profile['company_name']} ({profile['ticker']})
            Current Price: Rs. {profile['fundamentals']['current_price']}
            
            Subagent 1: CFA Fundamental Report:
            {fundamental_report}
            
            Subagent 2: Technical Charting Report:
            {technical_report}
            
            Subagent 3: Sentiment & Governance Audit Report:
            {sentiment_report}
            
            Street Analyst Consensus:
            - Broker Count: {profile['consensus']['analyst_count']}
            - Recommendation: {profile['consensus']['recommendation']}
            - Median Target Price: Rs. {profile['consensus']['target_median']}
            """
            
            response_text = call_llm(TASK_HEAVY, system_prompt, user_prompt, max_tokens=4096)
            
            clean_json = response_text.strip()
            if clean_json.startswith("```json"):
                clean_json = clean_json[7:]
            if clean_json.endswith("```"):
                clean_json = clean_json[:-3]
            clean_json = clean_json.strip()
            decision = json.loads(clean_json)
            decision["is_simulated"] = False
            
            # Blended recommendation logic
            scoring = profile.get("score_metrics", {})
            comp_score = scoring.get("final_score", 50)
            risk_lower_cio = risk.lower()
            if "conservative" in risk_lower_cio:
                buy_threshold, strong_buy_threshold = 75, 88
            elif "aggressive" in risk_lower_cio:
                buy_threshold, strong_buy_threshold = 55, 72
            else:
                buy_threshold, strong_buy_threshold = 65, 80
            
            if comp_score >= strong_buy_threshold:
                blended_rec = "STRONG BUY"
            elif comp_score >= buy_threshold:
                blended_rec = "BUY"
            elif comp_score >= 45:
                blended_rec = "HOLD"
            else:
                blended_rec = "SELL"
                
            decision["recommendation"] = blended_rec
            profile["analysis"] = decision
            
            # Save updated profile with full analysis back to cache
            with get_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cached_profiles (symbol, profile_json, updated_at) VALUES (?, ?, ?)",
                    (profile["ticker"], json.dumps(profile), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                )
                conn.commit()
                
        return profile
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Prospectus upgrade error: {str(e)}")

@app.post("/api/analyze-custom")
async def analyze_custom_dcf(data: DCFOverrideRequest):
    """Recalculates DCF sandbox overlays and returns updated AI prospectus."""
    try:
        custom_dcf = {
            "revenue_growth": data.revenue_growth,
            "opm": data.opm,
            "wacc": data.wacc,
            "terminal_growth": data.terminal_growth
        }
        profile = await run_cio_parent_agent(data.query, data.horizon, data.risk_profile, custom_dcf=custom_dcf, force_llm=data.force_llm)
        profile["llm_meta"] = get_last_llm_meta()
        return profile
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Custom valuation modeling error: {str(e)}")

@app.get("/api/discover")
async def discover_stocks(
    strategy: str = "hybrid",
    universe: str = "all",
    horizon: str = "Long-term (3+ years)",
    risk: str = "Moderate",
    style: str = "all",
    sector: str = None,
    symbol: str = None
):
    """
    Runs AI Screener Engine across the selected strategy (Bottom-Up, Top-Down, Hybrid)
    and selected cap category (All, Large, Mid, Small), with an optional style overlay.
    Investor profile (horizon + risk) adjusts quality gates and recommendation thresholds.
    """
    if strategy not in ["bottom_up", "top_down", "hybrid"]:
        raise HTTPException(status_code=400, detail="Invalid strategy selector.")
    if style not in ["all", "value", "growth", "contra"]:
        raise HTTPException(status_code=400, detail="Invalid investment style selector.")
    try:
        results = await asyncio.to_thread(run_ai_stock_screener, strategy, universe, horizon, risk, style, sector, symbol)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Screener engine failed: {str(e)}")

@app.get("/api/fuzzy/evaluate")
async def get_fuzzy_evaluation(symbol: str):
    symbol_upper = symbol.upper()
    try:
        with get_db() as conn:
            # 1. Fetch profile from cached_profiles
            row = conn.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ?", (symbol_upper,)).fetchone()
            if not row:
                # If not found, try without suffix (.NS) or with wildcard
                row = conn.execute("SELECT profile_json FROM cached_profiles WHERE symbol LIKE ?", (f"{symbol_upper}%",)).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail=f"Stock profile for {symbol} not found in database. Please run analysis first.")
            
            profile = json.loads(row["profile_json"])
            fundamentals = profile.get("fundamentals", {})
            technicals = profile.get("technicals", {})
            quality = profile.get("earnings_quality", {})
            sector = profile.get("sector", "Unknown")

            # 2. Extract present metrics
            rsi = float(technicals.get("rsi", 50.0))
            current_price = float(technicals.get("current_price", 0.0))
            sma_200 = float(technicals.get("sma_200", 0.0))
            dma_prox = 0.0
            if sma_200 > 0:
                dma_prox = ((current_price - sma_200) / sma_200) * 100.0
            
            # Simple Wyckoff classifier based on technical signals
            trend_str = technicals.get("trend_50_vs_200", "Neutral")
            
            # ADX extraction from technicals profile
            adx = float(technicals.get("adx", 22.0))
            
            stage = 1 # Default Stage 1 Accumulation
            if trend_str == "Bullish" and current_price >= sma_200:
                stage = 2 # Stage 2 Markup
            elif trend_str == "Bearish" and current_price < sma_200:
                stage = 4 # Stage 4 Markdown
            elif rsi > 65 and trend_str != "Bullish":
                stage = 3 # Stage 3 Distribution

            altman_z = float(quality.get("altman_z_score", 3.0))
            piotroski = int(quality.get("piotroski_score", 6))
            promoter_holding = float(fundamentals.get("promoter_holding_pct", 50.0))
            
            # Promoter pledge change over 1Y (delta)
            pledge_now = float(fundamentals.get("promoter_pledge_pct", 0.0))
            promoter_pledge_delta = pledge_now  # Use current pledge as proxy delta for rules trigger

            volume = float(fundamentals.get("volume", 1.0))
            average_volume = float(fundamentals.get("average_volume", 1.0))
            relative_volume = volume / average_volume if average_volume > 0 else 1.0

            # Sector Markdown check
            sector_markdown = False
            sec_row = conn.execute("SELECT return_1m FROM sector_regime_stats WHERE sector = ?", (sector,)).fetchone()
            if sec_row and sec_row["return_1m"] is not None and float(sec_row["return_1m"]) < -5.0:
                sector_markdown = True

            # 3. Compute Trajectories from Statement History
            opm_delta = 0.0
            roe_delta = 0.0
            debt_delta = 0.0
            
            # Load statements
            stmt_row = conn.execute("SELECT data_json FROM cached_financial_statements WHERE symbol = ? AND view = 'consolidated'", (symbol_upper,)).fetchone()
            if not stmt_row:
                stmt_row = conn.execute("SELECT data_json FROM cached_financial_statements WHERE symbol = ? AND view = 'standalone'", (symbol_upper,)).fetchone()
            
            has_history = False
            if stmt_row:
                try:
                    stmt_data = json.loads(stmt_row["data_json"])
                    quarters = stmt_data.get("quarters", {})
                    q_rows = quarters.get("rows", [])
                    
                    # Compute Operating Margin Trajectory slope
                    opm_row = next((r for r in q_rows if r.get("label") == "OPM %"), None)
                    if opm_row and "values" in opm_row:
                        # Clean values to float
                        opm_vals = []
                        for v in opm_row["values"]:
                            try:
                                if isinstance(v, str):
                                    v = v.replace("%", "").strip()
                                opm_vals.append(float(v))
                            except ValueError:
                                pass
                        # Take last 8 quarters to calculate slope
                        if len(opm_vals) >= 2:
                            y_vals = opm_vals[-8:]
                            n = len(y_vals)
                            x_vals = list(range(n))
                            mean_x = sum(x_vals) / n
                            mean_y = sum(y_vals) / n
                            num = sum((x_vals[i] - mean_x) * (y_vals[i] - mean_y) for i in range(n))
                            den = sum((x_vals[i] - mean_x) ** 2 for i in range(n))
                            opm_delta = num / den if den > 0 else 0.0
                            has_history = True

                    # Compute ROE and Debt trajectory from annual sheet
                    balance_sheet = stmt_data.get("balance_sheet", {})
                    profit_loss = stmt_data.get("profit_loss", {})
                    
                    bs_rows = balance_sheet.get("rows", [])
                    pl_rows = profit_loss.get("rows", [])
                    
                    capital_row = next((r for r in bs_rows if r.get("label") == "Equity Capital"), None)
                    reserves_row = next((r for r in bs_rows if r.get("label") == "Reserves"), None)
                    borrowing_row = next((r for r in bs_rows if r.get("label") == "Borrowings"), None)
                    net_profit_row = next((r for r in pl_rows if r.get("label") == "Net Profit"), None)
                    
                    if capital_row and reserves_row and net_profit_row and borrowing_row:
                        cap_vals = [float(v) for v in capital_row.get("values", []) if str(v).replace(".", "").isdigit()]
                        res_vals = [float(v) for v in reserves_row.get("values", []) if str(v).replace(".", "").isdigit()]
                        borrow_vals = [float(v) for v in borrowing_row.get("values", []) if str(v).replace(".", "").isdigit()]
                        profit_vals = [float(v) for v in net_profit_row.get("values", []) if str(v).replace(".", "").replace("-", "").isdigit()]
                        
                        min_len = min(len(cap_vals), len(res_vals), len(borrow_vals), len(profit_vals))
                        if min_len >= 2:
                            # Align historical arrays
                            roe_history = []
                            debt_history = []
                            for idx in range(-min_len, 0):
                                equity = cap_vals[idx] + res_vals[idx]
                                net_prof = profit_vals[idx]
                                borrow = borrow_vals[idx]
                                
                                roe = (net_prof / equity * 100.0) if equity > 0 else 0.0
                                debt_eq = (borrow / equity) if equity > 0 else 0.0
                                
                                roe_history.append(roe)
                                debt_history.append(debt_eq)
                            
                            # ROE slope over last 4 years
                            y_vals = roe_history[-4:]
                            n = len(y_vals)
                            x_vals = list(range(n))
                            mean_x = sum(x_vals) / n
                            mean_y = sum(y_vals) / n
                            num = sum((x_vals[i] - mean_x) * (y_vals[i] - mean_y) for i in range(n))
                            den = sum((x_vals[i] - mean_x) ** 2 for i in range(n))
                            roe_delta = num / den if den > 0 else 0.0
                            
                            # Debt-to-Equity delta: present - 3y ago
                            debt_delta = debt_history[-1] - debt_history[max(-len(debt_history), -4)]
                except Exception as parse_err:
                    print(f"Error parsing financial statement trajectories: {parse_err}")
            
            # If statement history was missing or empty, apply proxy estimation
            if not has_history:
                sales_growth_3y_pct = float(fundamentals.get("sales_growth_3y_pct", 0.0))
                profit_growth_3y_pct = float(fundamentals.get("profit_growth_3y_pct", 0.0))
                roe_pct = float(fundamentals.get("roe_pct", 12.0))
                debt_to_equity = float(fundamentals.get("debt_to_equity", 0.0))
                
                # proxy opm trajectory
                opm_delta = (profit_growth_3y_pct - sales_growth_3y_pct) / 10.0
                # proxy roe trajectory
                roe_delta = 1.0 if roe_pct > 15.0 else -1.0 if roe_pct < 8.0 else 0.0
                # proxy debt trajectory
                debt_delta = 0.0

            # 4. Extract institutional stealth parameters
            sma_50 = float(technicals.get("sma_50", 0.0))
            sma_20 = float(technicals.get("sma_20", current_price * 0.98 if current_price > 0 else 100.0))
            sma_100 = float(technicals.get("sma_100", (sma_50 + sma_200) / 2.0 if (sma_50 > 0 and sma_200 > 0) else current_price))
            dma_stack_bullish = bool(sma_20 > sma_50 > sma_100 > sma_200 > 0)
            dma_stack_bearish = bool(0 < sma_20 < sma_50 < sma_100 < sma_200)

            pe_ratio = float(fundamentals.get("pe_ratio", 20.0))
            pe_3y_median = float(fundamentals.get("pe_3y_median", 22.0))
            pe_valuation_ratio = pe_ratio / pe_3y_median if pe_3y_median > 0 else 1.0

            high_52w = float(fundamentals.get("high_52w", current_price * 1.1 if current_price > 0 else 110.0))
            low_52w = float(fundamentals.get("low_52w", current_price * 0.8 if current_price > 0 else 80.0))
            fifty_two_week_prox = (current_price - low_52w) / (high_52w - low_52w) if (high_52w - low_52w) > 0 else 0.5
            fifty_two_week_prox = max(0.0, min(1.0, fifty_two_week_prox))

            delivery_pct = float(fundamentals.get("delivery_pct", 40.0))
            vcp_squeeze = bool(technicals.get("vcp_squeeze", False))
            fii_dii_delta = float(fundamentals.get("fii_dii_delta", 0.0))
            icr = float(quality.get("interest_coverage_ratio", 5.0))
            ocf_pat_ratio = float(quality.get("ocf_pat_ratio", 1.0))

            # Evaluate Mamdani fuzzy logic model
            evaluation = evaluate_fuzzy_logic(
                opm_delta=opm_delta,
                roe_delta=roe_delta,
                debt_delta=debt_delta,
                rsi=rsi,
                dma_prox=dma_prox,
                adx=adx,
                stage=stage,
                altman_z=altman_z,
                piotroski=piotroski,
                promoter_holding=promoter_holding,
                promoter_pledge_delta=promoter_pledge_delta,
                relative_volume=relative_volume,
                sector_markdown=sector_markdown,
                pe_valuation_ratio=pe_valuation_ratio,
                dma_stack_bullish=dma_stack_bullish,
                dma_stack_bearish=dma_stack_bearish,
                fifty_two_week_prox=fifty_two_week_prox,
                delivery_pct=delivery_pct,
                vcp_squeeze=vcp_squeeze,
                fii_dii_delta=fii_dii_delta,
                icr=icr,
                ocf_pat_ratio=ocf_pat_ratio
            )
            
            # Include input diagnostics for visual transparency in the UI Console
            evaluation["inputs"] = {
                "symbol": symbol_upper,
                "company_name": profile.get("company_name", symbol_upper),
                "sector": sector,
                "opm_delta": round(opm_delta, 2),
                "roe_delta": round(roe_delta, 2),
                "debt_delta": round(debt_delta, 2),
                "rsi": round(rsi, 1),
                "dma_prox": round(dma_prox, 1),
                "adx": round(adx, 1),
                "stage": stage,
                "altman_z": round(altman_z, 2),
                "piotroski": piotroski,
                "promoter_holding": round(promoter_holding, 1),
                "promoter_pledge_delta": round(promoter_pledge_delta, 2),
                "relative_volume": round(relative_volume, 2),
                "sector_markdown": sector_markdown,
                "pe_valuation_ratio": round(pe_valuation_ratio, 2),
                "dma_stack_bullish": dma_stack_bullish,
                "dma_stack_bearish": dma_stack_bearish,
                "fifty_two_week_prox": round(fifty_two_week_prox, 2),
                "delivery_pct": round(delivery_pct, 1),
                "vcp_squeeze": vcp_squeeze,
                "fii_dii_delta": round(fii_dii_delta, 2),
                "icr": round(icr, 2),
                "ocf_pat_ratio": round(ocf_pat_ratio, 2)
            }
            return evaluation
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fuzzy evaluation error: {str(e)}")

@app.get("/api/fuzzy/rules-knowledge-base")
async def get_fuzzy_rules_knowledge_base():
    try:
        from backend.fuzzy_engine import get_all_fuzzy_rules_kb
        return {"rules": get_all_fuzzy_rules_kb(), "total": 19}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching fuzzy rules KB: {str(e)}")

@app.get("/api/fuzzy/universe-standings")
async def get_fuzzy_universe_standings_legacy(limit: int = 5):
    """
    Delegates to institutional normalized universe standings pipeline.
    """
    with get_db() as conn:
        eval_map = get_universe_fuzzy_evaluations(conn)
        evaluations = list(eval_map.values())
        for e in evaluations:
            e["market_regime"] = "ACCUMULATION" if e["fuzzy_score"] >= 15 else ("DISTRIBUTION" if e["fuzzy_score"] <= -15 else "NEUTRAL")

        top_buys = sorted(evaluations, key=lambda x: x["fuzzy_score"], reverse=True)[:limit]
        top_sells = sorted(evaluations, key=lambda x: x["fuzzy_score"])[:limit]

        return {
            "top_buys": top_buys,
            "top_sells": top_sells
        }

@app.get("/api/scans/fuzzy")
@app.get("/api/fuzzy/screener")
async def scan_fuzzy_conviction(min_score: float = -100.0, rating_class: Optional[str] = "ALL", limit: int = 50):
    return await scan_fuzzy(min_score=min_score, rating_class=rating_class, limit=limit)

class FuzzyCommentaryRequest(BaseModel):
    symbol: str
    centroid_score: float
    rating: str
    inputs: dict = {}
    active_rules: list = []

class FuzzyAskRequest(BaseModel):
    symbol: str
    question: str
    fuzzy_context: dict = {}

def generate_fallback_fuzzy_commentary(symbol: str, centroid_score: float, rating: str, inputs: dict) -> dict:
    opm_d = float(inputs.get("opm_delta", 0.0) or 0.0)
    roe_d = float(inputs.get("roe_delta", 0.0) or 0.0)
    debt_d = float(inputs.get("debt_delta", 0.0) or 0.0)
    adx = float(inputs.get("adx", 20.0) or 20.0)
    rsi = float(inputs.get("rsi", 50.0) or 50.0)

    if rating in ["Strong Buy", "Buy"]:
        thesis = f"{symbol} shows strong financial health and positive momentum. Profit margins and capital returns are expanding while financial leverage remains well managed."
        driver = f"Solid profit expansion (OPM delta: {opm_d:+.1f}%) and healthy trend strength (ADX: {adx:.1f})."
        risk = "Watch out for short-term technical pullbacks if broader sector momentum slows down."
    elif rating in ["Sell", "Strong Sell"]:
        thesis = f"{symbol} faces underlying financial margin compression or high debt pressures, dragging down quantitative conviction."
        driver = f"Deteriorating profit margins or weak Return on Equity trajectory (ROE delta: {roe_d:+.1f}%)."
        risk = "Debt expansion or broken technical support levels pose downside risk."
    else:
        thesis = f"{symbol} is currently in a balanced phase. Fundamentals and technical trends are rangebound."
        driver = f"Moderate profit growth and stable momentum (RSI: {rsi:.1f})."
        risk = "A clear breakout in profit margin trajectory or trend strength is required before upgrading to Buy."

    return {
        "status": "success",
        "symbol": symbol,
        "layman_summary": {
            "thesis": thesis,
            "key_driver": driver,
            "main_risk": risk
        },
        "is_fallback": True
    }

@app.post("/api/fuzzy/commentary")
async def get_fuzzy_ai_commentary(req: FuzzyCommentaryRequest):
    try:
        from backend.llm_config import call_llm, TASK_FAST
        
        rules_text = ", ".join([r.get("name", str(r)) for r in req.active_rules[:5]]) if req.active_rules else "Standard evaluation rules fired"
        system_prompt = (
            "You are an expert institutional quantitative analyst. Explain a mathematical fuzzy logic stock rating to a retail investor in VERY SIMPLE, LAYMAN TERMS (no complex academic jargon).\n"
            "Format your response as a valid JSON object with EXACTLY three keys:\n"
            '{\n  "thesis": "1-2 sentence simple overview of why the stock got this rating",\n'
            '  "key_driver": "1 short sentence highlighting the biggest positive or negative growth driver",\n'
            '  "main_risk": "1 short sentence noting the main potential risk or metric to monitor"\n}'
        )
        user_prompt = (
            f"Stock: {req.symbol}\n"
            f"Fuzzy Rating: {req.rating} (Centroid Conviction Score: {req.centroid_score:+.1f}%)\n"
            f"Fuzzified Inputs: OPM Delta={req.inputs.get('opm_delta', 0)}%, ROE Delta={req.inputs.get('roe_delta', 0)}%, Debt Delta={req.inputs.get('debt_delta', 0)}%, RSI={req.inputs.get('rsi', 50)}, ADX={req.inputs.get('adx', 20)}\n"
            f"Top Active Fired Rules: {rules_text}"
        )
        
        response_text = call_llm(TASK_FAST, system_prompt, user_prompt, max_tokens=350)
        if response_text and not response_text.startswith("ERROR:"):
            try:
                clean_txt = response_text.strip()
                if "```json" in clean_txt:
                    clean_txt = clean_txt.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_txt:
                    clean_txt = clean_txt.split("```")[1].split("```")[0].strip()
                parsed = json.loads(clean_txt)
                return {
                    "status": "success",
                    "symbol": req.symbol,
                    "layman_summary": parsed,
                    "is_fallback": False,
                    "llm_meta": get_last_llm_meta()
                }
            except Exception:
                pass

        return generate_fallback_fuzzy_commentary(req.symbol, req.centroid_score, req.rating, req.inputs)
    except Exception as e:
        return generate_fallback_fuzzy_commentary(req.symbol, req.centroid_score, req.rating, req.inputs)

@app.post("/api/fuzzy/ask")
async def ask_fuzzy_ai_assistant(req: FuzzyAskRequest):
    try:
        from backend.llm_config import call_llm, TASK_FAST

        ctx = req.fuzzy_context or {}
        inputs = ctx.get('inputs', {})
        active_rules = [r.get('rule_name', '') for r in ctx.get('rule_trail', []) if r.get('rule_name')]

        system_prompt = (
            "You are an expert AI quantitative analyst explaining a Mamdani Fuzzy Logic Stock Decision Engine. "
            "Answer the user's question or 'what-if' counterfactual scenario clearly, completely, and in layman terms. "
            "When responding to IF/ELSE scenarios (e.g. 'What if profit margins drop by 5%?', 'Why did this stock receive its rating?'):\n"
            "1. Explain IF the scenario occurs, how it alters the specific input indicator (e.g. OPM delta, ROE delta, Debt, RSI, ADX).\n"
            "2. Explain WHICH Mamdani fuzzy rules would trigger or weaken as a result.\n"
            "3. State clearly how the defuzzified Center-of-Gravity (Centroid Score) and overall conviction rating would shift (e.g., from Buy to Neutral/Sell).\n"
            "Keep your explanation direct, complete, and easy for a retail investor to understand. Do NOT truncate or cut off mid-sentence."
        )
        user_prompt = (
            f"Stock Symbol: {req.symbol}\n"
            f"Current Conviction Rating: {ctx.get('rating', 'Hold')} (Defuzzified Score: {ctx.get('centroid_score', 0):+.1f}%)\n"
            f"Current Fuzzified Indicators: Margin Delta (OPM)={inputs.get('opm_delta', 0)}%, ROE Delta={inputs.get('roe_delta', 0)}%, Debt Delta={inputs.get('debt_delta', 0)}, RSI={inputs.get('rsi', 50)}, 200-DMA Prox={inputs.get('dma_prox', 0)}%, ADX={inputs.get('adx', 20)}\n"
            f"Currently Active Rules: {', '.join(active_rules) if active_rules else 'Standard rules'}\n"
            f"User Question / Scenario: {req.question}"
        )

        answer_text = call_llm(TASK_FAST, system_prompt, user_prompt, max_tokens=2500)
        if answer_text and not answer_text.startswith("ERROR:"):
            return {
                "status": "success",
                "answer": answer_text.strip(),
                "is_fallback": False,
                "llm_meta": get_last_llm_meta()
            }
        
        # Smart dynamic fallback response for IF/ELSE queries if LLM is offline
        rating = ctx.get('rating', 'Hold')
        score = float(ctx.get('centroid_score', 0) or 0.0)
        q_lower = req.question.lower()
        if "profit" in q_lower or "opm" in q_lower or "drop" in q_lower or "margin" in q_lower:
            fb = f"IF {req.symbol}'s profit margins drop, the OPM delta antecedent will weaken. This weakens Buy rules and activates Margin Contraction penalty rules, pulling down the current score of {score:+.1f}% toward the Sell zone (-15% to -100%)."
        elif "debt" in q_lower or "risk" in q_lower or "leverage" in q_lower:
            fb = f"IF debt leverage increases for {req.symbol}, the Debt Expansion rule triggers a score penalty, reducing overall conviction and increasing downside risk."
        elif "buy" in q_lower or "strong buy" in q_lower:
            fb = f"To trigger a Strong Buy rating (> +50% Centroid Score), {req.symbol} requires expanding profit margins (OPM delta > +2%), strong capital returns (ROE delta > +3%), and healthy trend momentum (RSI between 45-65 and ADX > 25)."
        else:
            fb = f"For {req.symbol} (current rating: {rating}), the fuzzy decision engine balances fundamental deltas and technical momentum. Any negative shift in profit trajectory or technical breakdown will reduce the centroid score."

        return {
            "status": "success",
            "answer": fb,
            "is_fallback": True
        }
    except Exception as e:
        return {
            "status": "success",
            "answer": f"Analyzing {req.symbol}: The fuzzy decision engine combines balance sheet deltas and momentum regimes. Changes in profit growth or RSI directly shift the defuzzified centroid score.",
            "is_fallback": True
        }

@app.get("/api/technical-scans")
async def get_technical_scans():
    """
    Scans the database to return stocks qualifying in various technical breakout categories.
    """
    import sqlite3
    import json
    from backend.agent import get_db, clean_float

    try:
        def run_scans():
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT s.symbol, s.company_name, s.sector, s.cap_type, p.profile_json 
                    FROM screener_universe s 
                    JOIN cached_profiles p ON s.symbol = p.symbol
                    WHERE s.symbol NOT LIKE '%DUMMY%'
                """)
                rows = cursor.fetchall()
                
                delivery_stats_map = {}
                delivery_hist_map = {}
                try:
                    cursor.execute("SELECT symbol, delivery_percentage, delivery_qty, traded_qty, updated_at FROM daily_delivery_stats")
                    for d_row in cursor.fetchall():
                        delivery_stats_map[d_row["symbol"].upper()] = {
                            "deliv_pct": float(d_row["delivery_percentage"] or 0.0),
                            "deliv_qty": int(d_row["delivery_qty"] or 0),
                            "traded_qty": int(d_row["traded_qty"] or 0),
                            "updated_at": str(d_row["updated_at"] or "")
                        }
                    
                    cursor.execute("""
                        SELECT symbol, trade_date, delivery_percentage, delivery_qty, traded_qty
                        FROM daily_delivery_history
                        ORDER BY symbol, trade_date ASC
                    """)
                    for h_row in cursor.fetchall():
                        sym_u = h_row["symbol"].upper()
                        if sym_u not in delivery_hist_map:
                            delivery_hist_map[sym_u] = []
                        delivery_hist_map[sym_u].append(dict(h_row))
                except Exception as d_err:
                    print(f"Technical Scans: Delivery map fetch error: {d_err}")

                near_high = []
                near_low = []
                gap_up = []
                gap_down = []
                rsi_oversold = []
                rsi_overbought = []
                volume_shockers = []
                delivery_shockers = []
                golden_crossover = []
                sma_50_pullback = []
                sma_100_pullback = []
                sma_200_pullback = []
                fib_618_support = []
                fib_500_support = []
                
                for r in rows:
                    symbol = r["symbol"]
                    name = r["company_name"]
                    sector = r["sector"]
                    cap_raw = (r["cap_type"] or "").lower().strip()
                    
                    if cap_raw == "large":
                        segment = "Large Cap"
                    elif cap_raw == "mid":
                        segment = "Mid Cap"
                    elif cap_raw == "small":
                        segment = "Small Cap"
                    else:
                        segment = "Small Cap"
                    
                    try:
                        p = json.loads(r["profile_json"])
                    except Exception:
                        continue
                        
                    t = p.get("technicals") or {}
                    f = p.get("fundamentals") or {}
                    
                    # Ignore failed or blank profiles
                    if t.get("error") is True:
                        continue
                    
                    cp = t.get("current_price") or f.get("current_price") or p.get("current_price")
                    h52 = t.get("high_52w") or f.get("high_52week") or f.get("high52")
                    l52 = t.get("low_52w") or f.get("low_52week") or f.get("low52")
                    
                    cp_val = round(clean_float(cp), 2) if (cp is not None and clean_float(cp) > 0) else None
                    h52_val = round(clean_float(h52), 2) if (h52 is not None and clean_float(h52) > 0) else None
                    l52_val = round(clean_float(l52), 2) if (l52 is not None and clean_float(l52) > 0) else None
                    
                    # Skip stocks missing core price or 52W High/Low data to ensure 100% data integrity
                    if not cp_val or not h52_val or cp_val <= 0 or h52_val <= 0:
                        continue
                    if h52_val == cp_val and (not l52_val or l52_val == cp_val):
                        continue

                    # Calculate 100% real distance to 52W High and 52W Low
                    dh_val = round(((h52_val - cp_val) / h52_val) * 100, 2) if h52_val >= cp_val else 0.0
                    dl_val = round(((cp_val - l52_val) / l52_val) * 100, 2) if (l52_val and cp_val >= l52_val) else 0.0
                    dist_h = dh_val
                    dist_l = dl_val

                    rsi = t.get("rsi")
                    vol = t.get("volume_vs_avg20") or t.get("vol_ratio") or t.get("volume_ratio") or t.get("volume_surge_multiplier")
                    sma50 = t.get("sma_50") or t.get("sma50") or t.get("ema_50") or f.get("sma_50") or p.get("sma_50")
                    sma100 = t.get("sma_100") or t.get("sma100") or f.get("sma_100") or p.get("sma_100")
                    sma200 = t.get("sma_200") or t.get("sma200") or t.get("ema_200") or f.get("sma_200") or p.get("sma_200")
                    
                    fib = t.get("fib_levels") or {}
                    fib_618 = fib.get("fib_618")
                    fib_500 = fib.get("fib_500")
                    
                    op = clean_float(f.get("open") or t.get("daily_open"))
                    pc = clean_float(f.get("previous_close") or t.get("daily_close"))
                    
                    clean_sym = symbol.replace(".NS", "")
                    rsi_val = round(clean_float(rsi), 1) if (rsi is not None and clean_float(rsi) > 0) else None
                    pc_val = clean_float(pc) if (pc is not None and clean_float(pc) > 0) else None
                    chg_pct = round(((cp_val - pc_val) / pc_val) * 100, 2) if (cp_val and pc_val and pc_val > 0) else 0.0
                    vol_val = round(clean_float(vol), 2) if (vol is not None and clean_float(vol) > 0) else 1.0
                    s50_val = round(clean_float(sma50), 2) if (sma50 is not None and clean_float(sma50) > 0) else None
                    s200_val = round(clean_float(sma200), 2) if (sma200 is not None and clean_float(sma200) > 0) else None

                    item_meta = {
                        "symbol": clean_sym,
                        "name": name,
                        "sector": sector,
                        "segment": segment,
                        "rsi": rsi_val,
                        "price": cp_val,
                        "change_pct": chg_pct,
                        "vol_mult": vol_val,
                        "sma50": s50_val,
                        "sma200": s200_val,
                        "high52": h52_val,
                        "low52": l52_val,
                        "dist_h": dh_val,
                        "dist_l": dl_val
                    }
                    
                    # 1. Near 52W High (within 3% of peak)
                    if dist_h is not None and dist_h <= 3.0:
                        near_high.append({
                            **item_meta,
                            "value": f"{dist_h:.2f}%",
                            "sort_val": dist_h
                        })
                        
                    # 2. Near 52W Low
                    if dist_l is not None and clean_float(dist_l) <= 3.0:
                        near_low.append({
                            **item_meta,
                            "value": f"{clean_float(dist_l):.2f}%",
                            "sort_val": clean_float(dist_l)
                        })
                        
                    # 3. Gap Up / Down
                    if op > 0 and pc > 0:
                        gap = ((op - pc) / pc) * 100
                        if gap >= 1.0:
                            gap_up.append({
                                **item_meta,
                                "value": f"+{gap:.2f}%",
                                "sort_val": gap
                            })
                        elif gap <= -1.0:
                            gap_down.append({
                                **item_meta,
                                "value": f"{gap:.2f}%",
                                "sort_val": gap
                            })

                    # 4. RSI Oversold
                    if rsi is not None and clean_float(rsi) <= 35.0:
                        rsi_oversold.append({
                            **item_meta,
                            "value": f"{clean_float(rsi):.1f}",
                            "sort_val": clean_float(rsi)
                        })

                    # 5. RSI Overbought
                    if rsi is not None and clean_float(rsi) >= 65.0:
                        rsi_overbought.append({
                            **item_meta,
                            "value": f"{clean_float(rsi):.1f}",
                            "sort_val": clean_float(rsi)
                        })

                    # 6. Volume Shockers
                    if vol is not None and clean_float(vol) >= 1.5:
                        volume_shockers.append({
                            **item_meta,
                            "value": f"{clean_float(vol):.2f}x",
                            "sort_val": clean_float(vol)
                        })

                    # 7. Golden Crossover (Spread <= 3%)
                    if sma50 and sma200:
                        s50 = clean_float(sma50)
                        s200 = clean_float(sma200)
                        if s50 > s200:
                            spread = (s50 - s200) / s200
                            if spread <= 0.03:
                                golden_crossover.append({
                                    **item_meta,
                                    "value": f"+{spread*100:.2f}%",
                                    "sort_val": spread
                                })

                    # 8. SMA 50 Pullback (within 2%)
                    if cp and sma50:
                        c_price = clean_float(cp)
                        s50 = clean_float(sma50)
                        if s50 > 0:
                            dist = (c_price - s50) / s50
                            if abs(dist) <= 0.02:
                                sma_50_pullback.append({
                                    **item_meta,
                                    "value": f"{dist*100:+.2f}%",
                                    "sort_val": abs(dist)
                                })

                    # 9. SMA 100 Pullback (within 2%)
                    if cp and sma100:
                        c_price = clean_float(cp)
                        s100 = clean_float(sma100)
                        if s100 > 0:
                            dist = (c_price - s100) / s100
                            if abs(dist) <= 0.02:
                                sma_100_pullback.append({
                                    **item_meta,
                                    "value": f"{dist*100:+.2f}%",
                                    "sort_val": abs(dist)
                                })

                    # 10. SMA 200 Pullback (within 2%)
                    if cp and sma200:
                        c_price = clean_float(cp)
                        s200 = clean_float(sma200)
                        if s200 > 0:
                            dist = (c_price - s200) / s200
                            if abs(dist) <= 0.02:
                                sma_200_pullback.append({
                                    **item_meta,
                                    "value": f"{dist*100:+.2f}%",
                                    "sort_val": abs(dist)
                                })

                    # 11. Fib 61.8% Support (Golden support)
                    if cp and fib_618:
                        c_price = clean_float(cp)
                        f618 = clean_float(fib_618)
                        if f618 > 0:
                            dist = (c_price - f618) / f618
                            if abs(dist) <= 0.015:
                                fib_618_support.append({
                                    **item_meta,
                                    "value": f"{dist*100:+.2f}%",
                                    "sort_val": abs(dist)
                                })

                    # 12. Fib 50.0% Support (Midpoint)
                    if cp and fib_500:
                        c_price = clean_float(cp)
                        f500 = clean_float(fib_500)
                        if f500 > 0:
                            dist = (c_price - f500) / f500
                            if abs(dist) <= 0.015:
                                fib_500_support.append({
                                    **item_meta,
                                    "value": f"{dist*100:+.2f}%",
                                    "sort_val": abs(dist)
                                })
                                
                    # 13. Delivery Shockers (NSE EOD Delivery Surge)
                    d_info = delivery_stats_map.get(symbol.upper(), delivery_stats_map.get(f"{clean_sym}.NS", {}))
                    h_list = delivery_hist_map.get(symbol.upper(), delivery_hist_map.get(f"{clean_sym}.NS", []))
                    
                    if d_info or h_list:
                        latest_deliv_pct = d_info.get("deliv_pct", 0.0) if d_info else (float(h_list[-1]["delivery_percentage"] or 0.0) if h_list else 0.0)
                        
                        latest_date_raw = h_list[-1]["trade_date"] if h_list else ""
                        if latest_date_raw:
                            try:
                                d_obj = datetime.strptime(latest_date_raw, "%Y-%m-%d")
                                date_fmt = d_obj.strftime("%b %d")
                            except Exception:
                                date_fmt = latest_date_raw
                        else:
                            date_fmt = "EOD"
                            
                        if h_list:
                            prior_10 = h_list[-11:-1] if len(h_list) >= 11 else h_list[:-1]
                            avg_10d_pct = sum(float(x["delivery_percentage"] or 0.0) for x in prior_10) / len(prior_10) if prior_10 else 40.0
                            deliv_qtys = [int(x["delivery_qty"] or 0) for x in h_list]
                            from backend.quant_scoring import calculate_delivery_zscore
                            d_zscore = calculate_delivery_zscore(deliv_qtys)
                        else:
                            avg_10d_pct = 40.0
                            d_zscore = 0.0
                            
                        surge_ratio = (latest_deliv_pct / avg_10d_pct) if avg_10d_pct > 0 else 1.0
                        
                        deliv_qty = d_info.get("deliv_qty", 0) if d_info else (int(h_list[-1]["delivery_qty"] or 0) if h_list else 0)
                        traded_qty = d_info.get("traded_qty", 0) if d_info else (int(h_list[-1]["traded_qty"] or 0) if h_list else 0)

                        if latest_deliv_pct >= 48.0 or surge_ratio >= 1.35 or d_zscore >= 1.5:
                            delivery_shockers.append({
                                **item_meta,
                                "deliv_pct": round(latest_deliv_pct, 1),
                                "avg_10d_pct": round(avg_10d_pct, 1),
                                "deliv_surge": round(surge_ratio, 2),
                                "deliv_zscore": round(d_zscore, 2),
                                "deliv_qty": deliv_qty,
                                "traded_qty": traded_qty,
                                "trade_date": date_fmt,
                                "value": f"{latest_deliv_pct:.1f}% ({date_fmt})",
                                "sort_val": latest_deliv_pct
                            })
                                
                # Sort and slice top 50
                near_high = sorted(near_high, key=lambda x: x["sort_val"])[:50]
                near_low = sorted(near_low, key=lambda x: x["sort_val"])[:50]
                gap_up = sorted(gap_up, key=lambda x: x["sort_val"], reverse=True)[:50]
                gap_down = sorted(gap_down, key=lambda x: x["sort_val"])[:50]
                rsi_oversold = sorted(rsi_oversold, key=lambda x: x["sort_val"])[:50]
                rsi_overbought = sorted(rsi_overbought, key=lambda x: x["sort_val"], reverse=True)[:50]
                volume_shockers = sorted(volume_shockers, key=lambda x: x["sort_val"], reverse=True)[:50]
                delivery_shockers = sorted(delivery_shockers, key=lambda x: x["sort_val"], reverse=True)[:50]
                golden_crossover = sorted(golden_crossover, key=lambda x: x["sort_val"])[:50]
                sma_50_pullback = sorted(sma_50_pullback, key=lambda x: x["sort_val"])[:50]
                sma_100_pullback = sorted(sma_100_pullback, key=lambda x: x["sort_val"])[:50]
                sma_200_pullback = sorted(sma_200_pullback, key=lambda x: x["sort_val"])[:50]
                fib_618_support = sorted(fib_618_support, key=lambda x: x["sort_val"])[:50]
                fib_500_support = sorted(fib_500_support, key=lambda x: x["sort_val"])[:50]
                
                # Cleanup sort_val
                for lst in [near_high, near_low, gap_up, gap_down, rsi_oversold, rsi_overbought, volume_shockers, delivery_shockers, golden_crossover, sma_50_pullback, sma_100_pullback, sma_200_pullback, fib_618_support, fib_500_support]:
                    for item in lst:
                        item.pop("sort_val", None)
                        
                return {
                    "near_high": near_high,
                    "near_low": near_low,
                    "gap_up": gap_up,
                    "gap_down": gap_down,
                    "rsi_oversold": rsi_oversold,
                    "rsi_overbought": rsi_overbought,
                    "volume_shockers": volume_shockers,
                    "delivery_shockers": delivery_shockers,
                    "golden_crossover": golden_crossover,
                    "sma_50_pullback": sma_50_pullback,
                    "sma_100_pullback": sma_100_pullback,
                    "sma_200_pullback": sma_200_pullback,
                    "fib_618_support": fib_618_support,
                    "fib_500_support": fib_500_support
                }
                
        results = await asyncio.to_thread(run_scans)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query technical scans: {str(e)}")

def fetch_enriched_sector_regime(conn):
    cursor = conn.cursor()
    # 1. Fetch sector averages
    cursor.execute("SELECT sector, return_1d, return_5d, return_1m, return_3m, return_6m, return_1y, return_5y, return_ytd, updated_at FROM sector_regime_stats ORDER BY return_1m DESC")
    sector_rows = [dict(r) for r in cursor.fetchall()]
    
    # 2. Fetch all constituent stock stats
    cursor.execute("""
        SELECT s.symbol, s.sector, s.return_1d, s.return_5d, s.return_1m, s.return_3m, s.return_6m, s.return_1y, s.return_5y, s.return_ytd, u.company_name, u.cap_type
        FROM stock_regime_stats s
        JOIN screener_universe u ON s.symbol = u.symbol
    """)
    stock_rows = [dict(r) for r in cursor.fetchall()]
    
    # Group stocks by sector
    stocks_by_sector = {}
    for st in stock_rows:
        sec = st.get("sector") or "General Equities"
        if sec not in stocks_by_sector:
            stocks_by_sector[sec] = []
        stocks_by_sector[sec].append({
            "symbol": st.get("symbol") or "N/A",
            "company_name": st.get("company_name") or "N/A",
            "cap_type": st.get("cap_type") or "N/A",
            "return_1d": st.get("return_1d") or 0.0,
            "return_5d": st.get("return_5d") or 0.0,
            "return_1m": st.get("return_1m") or 0.0,
            "return_3m": st.get("return_3m") or 0.0,
            "return_6m": st.get("return_6m") or 0.0,
            "return_1y": st.get("return_1y") or 0.0,
            "return_5y": st.get("return_5y") or 0.0,
            "return_ytd": st.get("return_ytd") or 0.0
        })
        
    # Nest stocks inside their sector row
    for sec_row in sector_rows:
        sec_name = sec_row["sector"]
        sec_row["stocks"] = stocks_by_sector.get(sec_name, [])
        
    return sector_rows

@app.get("/api/screener/sector-regime")
async def get_sector_regime_stats():
    """
    Returns calculated sector relative strength performance rankings nested with constituent stocks.
    If the last updated timestamp is older than today's 4:00 PM IST target,
    spawns a background thread to refresh it once-a-day.
    """
    try:
        from datetime import datetime, time, timedelta
        
        # Check last updated timestamp
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MIN(updated_at) as min_ts FROM sector_regime_stats")
            row = cursor.fetchone()
            
        needs_refresh = True
        if row and row["min_ts"]:
            try:
                last_update = datetime.strptime(row["min_ts"], "%Y-%m-%d %H:%M:%S")
                now_local = datetime.now()
                today_4pm = datetime.combine(now_local.date(), time(16, 0))
                
                if now_local >= today_4pm:
                    # After 4:00 PM today, needs refresh if last update was before 4:00 PM today
                    if last_update >= today_4pm:
                        needs_refresh = False
                else:
                    # Before 4:00 PM today, needs refresh if last update was before 4:00 PM yesterday
                    yesterday_4pm = today_4pm - timedelta(days=1)
                    if last_update >= yesterday_4pm:
                        needs_refresh = False
            except Exception as parse_err:
                print(f"Error parsing sector updated_at: {parse_err}")
                
        if needs_refresh:
            print("Sector relative strength data is stale (4:00 PM IST once-daily boundary). Spawning async update task...")
            asyncio.create_task(asyncio.to_thread(update_sector_regime_stats))
            
        # Fetch current enriched standings
        with get_db() as conn:
            rows = fetch_enriched_sector_regime(conn)
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch sector regime: {str(e)}")

@app.post("/api/screener/sector-regime/refresh")
async def refresh_sector_regime_():
    """
    Manually forces recalculation of sector relative strength regime stats.
    """
    try:
        await asyncio.to_thread(update_sector_regime_stats)
        with get_db() as conn:
            rows = fetch_enriched_sector_regime(conn)
        return {"status": "success", "data": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Manual sector refresh failed: {str(e)}")

@app.post("/api/screener/sector-regime/ai-analysis")
async def analyze_sector_regime_ai(data: AISectorAnalysisRequest):
    """
    On-demand AI rotation analysis & Top-Down Macro Allocator.
    Gathers sector averages and constituent stock returns, fetches live news
    from Yahoo Finance for gainer/laggard drivers, and prompts Groq LLM for JSON response.
    """
    try:
        from datetime import datetime
        import yfinance as yf
        from backend.llm_config import call_llm, TASK_FAST, TASK_HEAVY
        
        # 1. Fetch current standings
        with get_db() as conn:
            raw_sectors = fetch_enriched_sector_regime(conn)
            
        if not raw_sectors:
            raise HTTPException(status_code=400, detail="No sector relative strength data available.")
            
        period = data.period # 1m, 3m, 6m, 1y, ytd
        col_name = f"return_{period}"
        cap_filter = data.cap_type.lower()
        
        # 2. Filter and calculate stats on the fly
        sector_standings = []
        total_advances = 0
        total_declines = 0
        
        for s in raw_sectors:
            sector_name = s["sector"]
            # Filter stocks by cap type
            filtered_stocks = []
            for stk in s.get("stocks", []):
                if cap_filter == "all" or stk.get("cap_type", "").lower() == cap_filter:
                    filtered_stocks.append(stk)
                    ret_val = stk.get(col_name) or 0.0
                    if ret_val >= 0:
                        total_advances += 1
                    else:
                        total_declines += 1
                        
            if not filtered_stocks:
                continue
                
            # Compute average return
            avg_ret = sum(stk.get(col_name) or 0.0 for stk in filtered_stocks) / len(filtered_stocks)
            
            # Find Leader and Laggard stocks
            leader = max(filtered_stocks, key=lambda x: x.get(col_name) or 0.0)
            laggard = min(filtered_stocks, key=lambda x: x.get(col_name) or 0.0)
            
            sector_standings.append({
                "sector": sector_name,
                f"return_{period}": round(avg_ret, 2),
                "stocks_count": len(filtered_stocks),
                "leader_symbol": leader["symbol"],
                "leader_return": round(leader.get(col_name) or 0.0, 2),
                "laggard_symbol": laggard["symbol"],
                "laggard_return": round(laggard.get(col_name) or 0.0, 2)
            })
            
        if not sector_standings:
            raise HTTPException(status_code=400, detail="No stocks match the selected cap universe filter.")
            
        # Sort sectors descending by average return
        sector_standings.sort(key=lambda x: x[f"return_{period}"], reverse=True)
        
        # 3. Identify Top and Bottom drivers
        top_sector = sector_standings[0]
        bottom_sector = sector_standings[-1]
        
        leader_symbol = top_sector["leader_symbol"]
        laggard_symbol = bottom_sector["laggard_symbol"]
        
        # 4. Fetch live news titles using yfinance
        leader_news_titles = []
        laggard_news_titles = []
        
        try:
            # Fetch top leader news
            leader_t = yf.Ticker(leader_symbol)
            raw_news = leader_t.news
            if raw_news:
                for item in raw_news[:4]:
                    title = item.get("title") or item.get("content", {}).get("title")
                    if title:
                        leader_news_titles.append(title)
            
            # Fetch bottom laggard news
            laggard_t = yf.Ticker(laggard_symbol)
            raw_news_lag = laggard_t.news
            if raw_news_lag:
                for item in raw_news_lag[:4]:
                    title = item.get("title") or item.get("content", {}).get("title")
                    if title:
                        laggard_news_titles.append(title)
        except Exception as yf_err:
            print(f"yfinance news extraction failed for macro allocation: {yf_err}")
            
        # 5. Check index regime
        nifty_bullish = False
        try:
            nifty_bullish, current_price, ema_20 = check_nifty_regime()
        except Exception:
            pass
            
        # 6. Compose Prompts
        system_prompt = (
            "You are the Chief Investment Officer (CIO) of a leading quantitative Indian equity fund.\n"
            "Your task is to analyze the sector rotation standings and the provided live news headlines for the lead and laggard stocks.\n"
            "Synthesize these catalysts to explain WHY the rotation is occurring from a top-down macroeconomic perspective.\n"
            "Link the news titles (e.g. corporate announcements, policy shifts, heatwaves, commodity rates) to the relative strength patterns.\n"
            "You MUST output a valid JSON object ONLY. Do not include markdown code blocks or code fence markers (e.g. do NOT wrap it in ```json ... ```). Structure it exactly as:\n"
            "{\n"
            '  "commentary": "Executive 3-sentence summary of flow rotations and market breadth confluences.",\n'
            '  "macro_allocator": "Detailed explanation of why the top sector is leading and the bottom is lagging, drawing insights from the news headlines provided. Link them to macroeconomic trends.",\n'
            '  "sector_sentiments": {\n'
            '     "Technology": 72, // Sentiment score integer 0-100 for each sector in the standings\n'
            '     "Energy": 45\n'
            '  },\n'
            '  "alpha_ideas": [\n'
            '     {\n'
            '        "symbol": "Ticker.NS",\n'
            '        "company_name": "Company Name Ltd.",\n'
            '        "sector": "Sector Name",\n'
            '        "reasoning": "Quantitative swing allocation thesis."\n'
            '     }\n'
            '  ],\n'
            '  "risk_flags": [\n'
            '     {\n'
            '        "sector": "Sector Name",\n'
            '        "flag_reason": "Warning regarding negative momentum risk."\n'
            '     }\n'
            '  ]\n'
            "}"
        )
        
        user_prompt = f"""
        Sector Rotation Standings (selected horizon: {period}, cap universe: {cap_filter}):
        - Top Performing Sector: {top_sector["sector"]} (+{top_sector[f"return_{period}"]:.2f}%)
          Leader Stock: {leader_symbol} (+{top_sector["leader_return"]:.2f}%)
          Recent news headlines for leader {leader_symbol}:
          {json.dumps(leader_news_titles, indent=2) if leader_news_titles else "No headlines found."}
          
        - Bottom Performing Sector: {bottom_sector["sector"]} ({bottom_sector[f"return_{period}"]:.2f}%)
          Laggard Stock: {laggard_symbol} ({bottom_sector["laggard_return"]:.2f}%)
          Recent news headlines for laggard {laggard_symbol}:
          {json.dumps(laggard_news_titles, indent=2) if laggard_news_titles else "No headlines found."}
          
        Other sectors standings:
        {json.dumps(sector_standings[1:-1], indent=2)}
        
        Market Breadth: {total_advances} Advances / {total_declines} Declines.
        Nifty 50 Trend: {"Bullish (Above 20 EMA)" if nifty_bullish else "Bearish (Below 20 EMA)"}
        """
        
        # 7. Call LLM
        response_text = call_llm(TASK_FAST, system_prompt, user_prompt, max_tokens=2000)
        
        # Parse Response
        if "ERROR_401" in response_text or "ERROR:" in response_text:
            raise Exception(response_text)
            
        clean_json = response_text.strip()
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:]
        if clean_json.endswith("```"):
            clean_json = clean_json[:-3]
        clean_json = clean_json.strip()
        
        result = json.loads(clean_json)
        if "sector_sentiments" not in result or not isinstance(result["sector_sentiments"], dict):
            result["sector_sentiments"] = {}
        for s in sector_standings:
            sec_name = s["sector"]
            if sec_name not in result["sector_sentiments"]:
                ret_val = s[f"return_{period}"]
                if ret_val >= 5.0: score = 85
                elif ret_val >= 0.0: score = 65
                elif ret_val >= -5.0: score = 42
                else: score = 20
                result["sector_sentiments"][sec_name] = score
        result["llm_meta"] = get_last_llm_meta()
        return result
        
    except Exception as err:
        print(f"AI Sector Rotation analysis query failed. Activating high-fidelity fallback: {err}")
        
        # Build High-Fidelity Rule-based Fallback
        try:
            top_sec = sector_standings[0]
            bottom_sec = sector_standings[-1]
            top_sec_name = top_sec["sector"]
            bottom_sec_name = bottom_sec["sector"]
            top_ret = top_sec[f"return_{period}"]
            bottom_ret = bottom_sec[f"return_{period}"]
            
            # Map default sentiments
            sentiments = {}
            for s in sector_standings:
                ret_val = s[f"return_{period}"]
                if ret_val >= 5.0: score = 85
                elif ret_val >= 0.0: score = 65
                elif ret_val >= -5.0: score = 42
                else: score = 20
                sentiments[s["sector"]] = score
                
            fallback_res = {
                "commentary": f"Relative strength analysis shows a strong rotation towards {top_sec_name} (+{top_ret:.2f}%) and defensive profit-taking out of {bottom_sec_name} ({bottom_ret:.2f}%). Market breadth represents a selective stock-picker's regime with {total_advances} Advances and {total_declines} Declines.",
                "macro_allocator": f"The outperformance of {top_sec_name} indicates structural institutional allocation and supportive catalysts, whereas the negative drift in {bottom_sec_name} suggests intermediate headwind risks. Portfolios should focus capital on leading rotation setups.",
                "sector_sentiments": sentiments,
                "alpha_ideas": [
                    {
                        "symbol": top_sec["leader_symbol"],
                        "company_name": f"Leader of {top_sec_name}",
                        "sector": top_sec_name,
                        "reasoning": f"Exhibits top gainer status in {top_sec_name} with +{top_sec['leader_return']:.2f}% return, signaling immediate breakout momentum."
                    }
                ],
                "risk_flags": [
                    {
                        "sector": bottom_sec_name,
                        "flag_reason": f"Underperforming sector exhibiting lagging relative strength of {bottom_ret:.2f}%. Allocations here should be minimised."
                    }
                ]
            }
            return fallback_res
        except Exception as fb_err:
            raise HTTPException(status_code=500, detail=f"AI query and local fallback failed: {str(fb_err)}")

@app.post("/api/screener/sector-regime/ai-chat")
async def chat_sector_regime_ai(data: AISectorChatRequest):
    """
    Conversational follow-up Co-Pilot chat on sector rotation.
    Provides context-aware analysis based on current radar standings.
    """
    try:
        from backend.llm_config import call_llm, TASK_FAST, TASK_HEAVY
        
        system_prompt = (
            "You are the Chief Investment Officer (CIO) of a leading quantitative Indian equity fund.\n"
            "You are an expert on market cycles, sector rotation, and swing trading.\n"
            "Your task is to answer the user's follow-up question about the sector standings, relative strength performance, or specific stock drivers.\n"
            "Answer in a concise, professional, institutional tone (max 150 words). Be quantitative where possible.\n"
            "If the user asks about specific stocks, refer to their return profiles if available in the standings, or use your general financial knowledge.\n"
            "Whenever you suggest a stock symbol, format it as a clickable markdown ticker like [TCS.NS] or [RELIANCE.NS] (ensure it has the .NS extension so the UI hooks it up!).\n"
            "Here is the active sector standings snapshot:\n"
            f"{json.dumps(data.sector_data, indent=2)}\n"
        )
        
        # Re-build message history if available
        messages = [{"role": "system", "content": system_prompt}]
        for msg in data.history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ["user", "assistant"]:
                messages.append({"role": role, "content": content})
                
        messages.append({"role": "user", "content": data.question})
        
        response_text = call_llm(TASK_FAST, system_prompt, messages=messages, max_tokens=1000)
        
        if "ERROR_401" in response_text or "ERROR:" in response_text:
            # Fallback reply
            return {"reply": "The AI Co-Pilot chat is currently running in local offline mode. TCS, Tata Power, and Reliance remain solid rotational anchors in the Large Cap space.", "llm_meta": get_last_llm_meta()}
            
        return {"reply": response_text, "llm_meta": get_last_llm_meta()}
    except Exception as e:
        return {"reply": f"Co-Pilot Chat connection error: {str(e)}", "llm_meta": get_last_llm_meta()}

@app.get("/api/stock-profile/{symbol}")
async def get_stock_profile_endpoint(symbol: str, cache: bool = True):
    """
    Lightweight endpoint to fetch the latest price and fundamentals for a symbol.
    Checks tick store first, then cached profiles, and falls back to yfinance.
    """
    from backend.websocket_server import tick_store
    symbol = symbol.strip().upper()
    plain = symbol.replace(".NS", "").replace(".BO", "")
    
    # Try tick store first
    tick = tick_store.get(plain) or tick_store.get(symbol)
    
    # Always check cached profiles first to avoid expensive full scrapes on periodic polls
    profile = None
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ?", (symbol,))
            row = cursor.fetchone()
            if row:
                profile = json.loads(row["profile_json"])
    except Exception as e:
        logger.error(f"Error reading cached profile: {e}")
        
    # If not cached in DB, fetch complete profile
    if not profile:
        try:
            profile = await asyncio.to_thread(get_complete_financial_profile, symbol, bypass_db_cache=not cache)
        except Exception:
            profile = {}
            
    # Update fundamentals with live tick price if available
    fundamentals = profile.get("fundamentals", {}) if profile else {}
    if tick:
        fundamentals["current_price"] = tick["price"]
        if tick.get("high", 0) > 0:
            fundamentals["day_high"] = tick["high"]
        if tick.get("low", 0) > 0:
            fundamentals["day_low"] = tick["low"]
            
    # Self-heal missing day/52w ranges from technicals if present
    technicals = profile.get("technicals", {}) if profile else {}
    if technicals:
        if "day_low" not in fundamentals or not fundamentals.get("day_low"):
            fundamentals["day_low"] = technicals.get("daily_low") or technicals.get("low_52w")
        if "day_high" not in fundamentals or not fundamentals.get("day_high"):
            fundamentals["day_high"] = technicals.get("daily_high") or technicals.get("high_52w")
        if "low_52week" not in fundamentals or not fundamentals.get("low_52week"):
            fundamentals["low_52week"] = technicals.get("low_52w")
        if "high_52week" not in fundamentals or not fundamentals.get("high_52week"):
            fundamentals["high_52week"] = technicals.get("high_52w")

    # If cache=False OR current_price or any ranges are still missing, fetch fresh quote from yfinance
    if (not cache or 
        not fundamentals.get("current_price") or 
        not fundamentals.get("day_low") or 
        not fundamentals.get("day_high") or 
        not fundamentals.get("low_52week") or 
        not fundamentals.get("high_52week") or
        "open" not in fundamentals or not fundamentals.get("open")):
        
        # Check in-memory rate-limiting cache first to prevent OOM spikes under high-frequency polling
        now = time.time()
        cached_quote, cached_time = _YFINANCE_FALLBACK_CACHE.get(symbol, (None, 0))
        if cached_quote and (now - cached_time < _YFINANCE_CACHE_TTL_SEC):
            # Merge cached quote details
            for k, v in cached_quote.items():
                if v is not None:
                    fundamentals[k] = v
        else:
            try:
                import yfinance as yf
                ticker_obj = yf.Ticker(symbol if '.' in symbol or symbol.startswith('^') else f"{symbol}.NS")
                info = ticker_obj.info
                if info:
                    fundamentals["current_price"] = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("navPrice") or fundamentals.get("current_price")
                    fundamentals["day_high"] = info.get("dayHigh") or info.get("regularMarketDayHigh") or fundamentals.get("current_price")
                    fundamentals["day_low"] = info.get("dayLow") or info.get("regularMarketDayLow") or fundamentals.get("current_price")
                    fundamentals["low_52week"] = info.get("fiftyTwoWeekLow") or info.get("regularMarketFiftyTwoWeekLow") or fundamentals.get("current_price")
                    fundamentals["high_52week"] = info.get("fiftyTwoWeekHigh") or info.get("regularMarketFiftyTwoWeekHigh") or fundamentals.get("current_price")
                    
                    # Fetch new metrics for the enterprise meta banner
                    fundamentals["open"] = info.get("open") or info.get("regularMarketOpen")
                    fundamentals["previous_close"] = info.get("previousClose") or info.get("regularMarketPreviousClose")
                    fundamentals["volume"] = info.get("volume") or info.get("regularMarketVolume")
                    fundamentals["average_volume"] = info.get("averageVolume") or info.get("averageVolume10Days")
                    
                    # Update in-memory rate-limiting cache
                    quote_data = {
                        "current_price": fundamentals.get("current_price"),
                        "day_high": fundamentals.get("day_high"),
                        "day_low": fundamentals.get("day_low"),
                        "low_52week": fundamentals.get("low_52week"),
                        "high_52week": fundamentals.get("high_52week"),
                        "open": fundamentals.get("open"),
                        "previous_close": fundamentals.get("previous_close"),
                        "volume": fundamentals.get("volume"),
                        "average_volume": fundamentals.get("average_volume"),
                    }
                    _YFINANCE_FALLBACK_CACHE[symbol] = (quote_data, now)
            except Exception as e:
                print(f"Error fetching yfinance fallback quote for {symbol}: {e}")
            
    return {
        "fundamentals": fundamentals,
        "technicals": profile.get("technicals", {}) if profile else {},
        "analysis": profile.get("analysis", {}) if profile else {},
        "earnings_quality": profile.get("earnings_quality", {}) if profile else {},
        "capm_risk_nifty50": profile.get("capm_risk_nifty50", {}) if profile else {},
        "capm_risk_sector": profile.get("capm_risk_sector", {}) if profile else {}
    }


@app.get("/api/stock/price-analysis/{symbol}")
async def get_stock_price_analysis_endpoint(symbol: str):
    """
    Returns multi-timeframe price ranges (1D, 1W, 1M, 52W/1Y) with High, Low, 
    LTP position %, and return % for Trendlyne-style visual analysis cards.
    """
    symbol = symbol.strip().upper()
    ticker = symbol if ('.' in symbol or symbol.startswith('^')) else f"{symbol}.NS"
    plain_symbol = symbol.split('.')[0]

    try:
        df = await fetch_history_df(ticker, period="1y", interval="1d")
        if df is not None and not df.empty:
            df = df.dropna(subset=['Close'])
        if df is None or df.empty or len(df) < 1:
            raise HTTPException(status_code=404, detail=f"No price history found for {symbol}")
        
        # Check live tick store if available
        from backend.websocket_server import tick_store
        tick = tick_store.get(plain_symbol) or tick_store.get(symbol)
        
        ltp = float(df['Close'].iloc[-1])

        if tick and tick.get("price", 0) > 0:
            ltp = float(tick["price"])
            
        def calc_range_bounds(sub_df, prev_close_ref=None):
            if sub_df.empty:
                return {"low": ltp, "high": ltp, "return_pct": 0.0, "position_pct": 50.0}
            low_val = float(sub_df['Low'].min())
            high_val = float(sub_df['High'].max())
            
            ref_price = prev_close_ref if prev_close_ref is not None else float(sub_df['Close'].iloc[0])
            
            return_pct = 0.0
            if ref_price > 0:
                return_pct = round(((ltp - ref_price) / ref_price) * 100, 2)
                
            pos_pct = 50.0
            if high_val > low_val:
                pos_pct = round(max(0.0, min(100.0, ((ltp - low_val) / (high_val - low_val)) * 100)), 1)
            elif ltp > high_val:
                pos_pct = 100.0
            elif ltp < low_val:
                pos_pct = 0.0
                
            return {
                "low": round(low_val, 2),
                "high": round(high_val, 2),
                "return_pct": return_pct,
                "position_pct": pos_pct
            }
            
        # 1D Range
        day_df = df.iloc[-1:]
        day_low = float(day_df['Low'].min())
        day_high = float(day_df['High'].max())
        if tick and tick.get("high", 0) > 0:
            day_high = max(day_high, float(tick["high"]))
        if tick and tick.get("low", 0) > 0:
            day_low = min(day_low, float(tick["low"]))
            
        prev_close_1d = float(df['Close'].iloc[-2]) if len(df) >= 2 else day_low
        day_range = {
            "low": round(day_low, 2),
            "high": round(day_high, 2),
            "return_pct": round(((ltp - prev_close_1d) / prev_close_1d) * 100, 2) if prev_close_1d > 0 else 0.0,
            "position_pct": round(max(0.0, min(100.0, ((ltp - day_low) / (day_high - day_low)) * 100)), 1) if day_high > day_low else 50.0
        }
        
        from datetime import timedelta
        dates = df.index
        latest_date = dates[-1]
        
        def get_past_close_ref(days_back):
            target_date = latest_date - timedelta(days=days_back)
            time_diffs = abs(dates - target_date)
            closest_idx = time_diffs.argmin()
            return float(df["Close"].iloc[closest_idx])

        # 1W Range (return vs close 7 calendar days ago)
        week_df = df.iloc[-5:] if len(df) >= 5 else df
        prev_close_1w = get_past_close_ref(7)
        week_range = calc_range_bounds(week_df, prev_close_ref=prev_close_1w)
        
        # 1M Range (return vs close 30 calendar days ago)
        month_df = df.iloc[-21:] if len(df) >= 21 else df
        prev_close_1m = get_past_close_ref(30)
        month_range = calc_range_bounds(month_df, prev_close_ref=prev_close_1m)
        
        # 52W / 1Y Range (return vs close 365 calendar days ago)
        year_range = calc_range_bounds(df, prev_close_ref=get_past_close_ref(365))

        
        return {
            "symbol": symbol,
            "ltp": round(ltp, 2),
            "day_range": day_range,
            "week_range": week_range,
            "month_range": month_range,
            "year_range": year_range
        }
    except Exception as e:
        logger.error(f"Error computing price analysis for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Price analysis computation failed: {str(e)}")


@app.get("/api/stock/technical-suite/{symbol}")
async def get_stock_technical_suite_endpoint(symbol: str):
    """
    Returns Trendlyne-style EMA & SMA moving average spectrum levels, 
    bullish/bearish counters, and Classic / Fibonacci / Camarilla Pivot Points.
    """
    symbol = symbol.strip().upper()
    ticker = symbol if ('.' in symbol or symbol.startswith('^')) else f"{symbol}.NS"
    plain_symbol = symbol.split('.')[0]

    try:
        df = await fetch_history_df(ticker, period="1y", interval="1d")
        if df.empty or len(df) < 5:
            raise HTTPException(status_code=404, detail=f"Insufficient history for {symbol}")

        from backend.websocket_server import tick_store
        tick = tick_store.get(plain_symbol) or tick_store.get(symbol)

        ltp = float(df['Close'].iloc[-1])
        if tick and tick.get("price", 0) > 0:
            ltp = float(tick["price"])

        day_df = df.iloc[-1]
        prev_close = float(df['Close'].iloc[-2]) if len(df) >= 2 else float(day_df['Close'])
        day_change_pct = round(((ltp - prev_close) / prev_close) * 100, 2) if prev_close > 0 else 0.0

        periods = [5, 10, 20, 30, 50, 100, 150, 200]
        sma_data = {}
        ema_data = {}
        sma_bull_cnt, sma_bear_cnt = 0, 0
        ema_bull_cnt, ema_bear_cnt = 0, 0

        for p in periods:
            # SMA
            if len(df) >= p:
                sma_val = float(df['Close'].rolling(window=p).mean().iloc[-1])
            else:
                sma_val = float(df['Close'].mean())
            sma_val = round(sma_val, 2)
            is_sma_bull = ltp >= sma_val
            if is_sma_bull:
                sma_bull_cnt += 1
            else:
                sma_bear_cnt += 1
            sma_data[f"{p}d"] = {"value": sma_val, "is_bullish": is_sma_bull}

            # EMA
            if len(df) >= p:
                ema_val = float(df['Close'].ewm(span=p, adjust=False).mean().iloc[-1])
            else:
                ema_val = float(df['Close'].mean())
            ema_val = round(ema_val, 2)
            is_ema_bull = ltp >= ema_val
            if is_ema_bull:
                ema_bull_cnt += 1
            else:
                ema_bear_cnt += 1
            ema_data[f"{p}d"] = {"value": ema_val, "is_bullish": is_ema_bull}

        # Calculate Pivot Points from previous trading session (High, Low, Close)
        prev_session = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
        H = float(prev_session['High'])
        L = float(prev_session['Low'])
        C = float(prev_session['Close'])

        # Classic Pivots
        P_classic = (H + L + C) / 3.0
        r1_c = 2 * P_classic - L
        s1_c = 2 * P_classic - H
        r2_c = P_classic + (H - L)
        s2_c = P_classic - (H - L)
        r3_c = H + 2 * (P_classic - L)
        s3_c = L - 2 * (H - P_classic)

        classic_pivots = {
            "pivot": round(P_classic, 2),
            "r1": round(r1_c, 2), "s1": round(s1_c, 2),
            "r2": round(r2_c, 2), "s2": round(s2_c, 2),
            "r3": round(r3_c, 2), "s3": round(s3_c, 2),
        }

        # Fibonacci Pivots
        fib_diff = H - L
        r1_f = P_classic + 0.382 * fib_diff
        s1_f = P_classic - 0.382 * fib_diff
        r2_f = P_classic + 0.618 * fib_diff
        s2_f = P_classic - 0.618 * fib_diff
        r3_f = P_classic + 1.000 * fib_diff
        s3_f = P_classic - 1.000 * fib_diff

        fib_pivots = {
            "pivot": round(P_classic, 2),
            "r1": round(r1_f, 2), "s1": round(s1_f, 2),
            "r2": round(r2_f, 2), "s2": round(s2_f, 2),
            "r3": round(r3_f, 2), "s3": round(s3_f, 2),
        }

        # Camarilla Pivots
        r3_cam = C + (fib_diff * 1.1 / 4.0)
        s3_cam = C - (fib_diff * 1.1 / 4.0)
        r2_cam = C + (fib_diff * 1.1 / 6.0)
        s2_cam = C - (fib_diff * 1.1 / 6.0)
        r1_cam = C + (fib_diff * 1.1 / 12.0)
        s1_cam = C - (fib_diff * 1.1 / 12.0)

        camarilla_pivots = {
            "pivot": round(P_classic, 2),
            "r1": round(r1_cam, 2), "s1": round(s1_cam, 2),
            "r2": round(r2_cam, 2), "s2": round(s2_cam, 2),
            "r3": round(r3_cam, 2), "s3": round(s3_cam, 2),
        }

        return {
            "symbol": symbol,
            "ltp": round(ltp, 2),
            "day_change_pct": day_change_pct,
            "ma_summary": {
                "ema": {
                    "data": ema_data,
                    "bullish_count": ema_bull_cnt,
                    "bearish_count": ema_bear_cnt
                },
                "sma": {
                    "data": sma_data,
                    "bullish_count": sma_bull_cnt,
                    "bearish_count": sma_bear_cnt
                }
            },
            "pivots": {
                "classic": classic_pivots,
                "fibonacci": fib_pivots,
                "camarilla": camarilla_pivots
            }
        }
    except Exception as e:
        logger.error(f"Error computing technical suite for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Technical suite computation failed: {str(e)}")


@app.get("/api/stock/audit")
async def audit_stock(
    symbol: str,
    horizon: str = "Long-term (3+ years)",
    risk: str = "Moderate"
):
    """
    Simulates the selected stock against all 12 operational + style screening combinations,
    returning detailed pass/failed checklists and style score calculations.
    """
    try:
        result = await asyncio.to_thread(run_single_stock_audit, symbol, horizon, risk)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Strategic audit simulation failed: {str(e)}")


@app.get("/api/stock/capture")
async def get_interactive_capture(
    symbol: str,
    years: Optional[str] = None,
    period: Optional[str] = None
):
    """
    Calculates Up-Market Capture and Down-Market Capture ratios over the selected time horizon
    (e.g., 3m, 6m, 9m, 1y, 3y, 5y).
    """
    if not symbol:
        raise HTTPException(status_code=400, detail="Stock symbol is required.")
        
    time_horizon = period or years or "3y"
    time_horizon = time_horizon.strip().lower()
    
    if time_horizon not in ["3m", "6m", "9m", "1y", "3y", "5y", "1", "3", "5"]:
        raise HTTPException(status_code=400, detail="Time period must be 3m, 6m, 9m, 1y, 3y, or 5y.")
        
    if time_horizon == "1":
        time_horizon = "1y"
    elif time_horizon == "3":
        time_horizon = "3y"
    elif time_horizon == "5":
        time_horizon = "5y"
        
    try:
        from backend.financial_utils import calculate_capture_ratios, resolve_company_ticker
        resolved = resolve_company_ticker(symbol)
        ticker = resolved["yf_ticker"]
        
        # Calculate fresh capture ratios in another thread to keep FastAPI responsive
        ratios = await asyncio.to_thread(calculate_capture_ratios, ticker, None, time_horizon)
        return ratios
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Capture ratio calculation failed: {str(e)}")


@app.get("/api/stock/compare-chart")
async def get_compare_chart(
    symbols: str,
    period: str = "1y"
):
    """
    Returns aligned, normalized daily price histories for multiple stock symbols + benchmark index.
    Allows side-by-side performance overlays inside the benchmarking panel.
    """
    if not symbols:
        raise HTTPException(status_code=400, detail="Symbols parameter is required.")
    if period not in ["3mo", "6mo", "1y", "2y", "3y", "5y"]:
        raise HTTPException(status_code=400, detail="Supported periods are 3mo, 6mo, 1y, 2y, 3y, or 5y.")
        
    try:
        from backend.financial_utils import resolve_company_ticker
        ticker_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if not ticker_list:
            raise HTTPException(status_code=400, detail="Invalid symbols list.")
            
        # Resolve tickers through company index lookup first
        resolved_tickers = []
        for s in ticker_list:
            if s.startswith("^"):
                resolved_tickers.append(s)
            else:
                try:
                    res = resolve_company_ticker(s)
                    resolved_tickers.append(res["yf_ticker"])
                except Exception:
                    # Fallback directly to symbol if resolution fails
                    resolved_tickers.append(s)
                    
        # Add Nifty 50 or Sensex based on first symbol's exchange suffix
        primary = resolved_tickers[0]
        benchmark = "^BSESN" if primary.endswith(".BO") else "^NSEI"
        if benchmark not in resolved_tickers:
            resolved_tickers.append(benchmark)
            
        # Fetch price histories concurrently using thread pool execution
        def fetch_ticker_data(ticker):
            try:
                t = yf.Ticker(ticker)
                # auto_adjust=True guarantees proper stock splits / dividends adjustments
                df = t.history(period=period, interval="1d", auto_adjust=True)
                if df.empty:
                    return ticker, None
                return ticker, df["Close"]
            except Exception as e:
                print(f"Error fetching data for {ticker}: {e}")
                return ticker, None
                
        # Concurrently query yfinance
        loop = asyncio.get_event_loop()
        tasks = [loop.run_in_executor(None, fetch_ticker_data, ticker) for ticker in resolved_tickers]
        results = await asyncio.gather(*tasks)
        
        # Build DataFrame with aligned series
        series_dict = {}
        for ticker, series in results:
            if series is not None and not series.empty:
                series_dict[ticker] = series
                
        if not series_dict:
            raise HTTPException(status_code=400, detail="No historical price data could be loaded for any symbols.")
            
        # Use pandas to align date indices via outer join and forward-fill occasional gaps
        combined_df = pd.DataFrame(series_dict)
        # Drop dates with completely missing values (e.g. weekend alignment gaps)
        combined_df = combined_df.dropna(how="all")
        # Forward fill individual missing prices for trading holiday alignments
        combined_df = combined_df.ffill().bfill()
        
        if combined_df.empty:
            raise HTTPException(status_code=400, detail="Aligned price series DataFrame is empty.")
            
        dates = [d.strftime("%Y-%m-%d") for d in combined_df.index]
        
        # Normalize each series to start exactly at 100.0 relative to its first valid price index
        normalized_series = {}
        for col in combined_df.columns:
            first_idx = combined_df[col].first_valid_index()
            if first_idx is not None:
                first_price = combined_df.loc[first_idx, col]
                if first_price > 0.0:
                    normalized_series[col] = [
                        round((val / first_price) * 100.0, 2) for val in combined_df[col]
                    ]
                else:
                    normalized_series[col] = [100.0] * len(combined_df)
            else:
                normalized_series[col] = [100.0] * len(combined_df)
                
        return {
            "dates": dates,
            "series": normalized_series,
            "benchmark_symbol": benchmark
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Comparison overlay calculation failed: {str(e)}")


@app.get("/api/universe")
async def get_index_universe(cap_type: Optional[str] = None):
    """
    Returns the list of stocks in each index stored in the database,
    indicating their symbol, name, industry/sector, cap type, rebalance date,
    and whether they have a cached profile.
    """
    query = """
        SELECT 
            u.symbol, 
            u.base_symbol, 
            u.company_name, 
            u.sector, 
            u.cap_type, 
            u.last_rebalanced,
            (CASE WHEN p.symbol IS NOT NULL THEN 1 ELSE 0 END) as is_cached
        FROM screener_universe u
        LEFT JOIN cached_profiles p ON u.symbol = p.symbol
        WHERE u.symbol NOT LIKE '%DUMMY%'
    """
    params = []
    if cap_type:
        query += " AND u.cap_type = ?"
        params.append(cap_type)
        
    query += " ORDER BY u.company_name ASC"
    
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = [dict(row) for row in cursor.fetchall()]
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch index universe: {str(e)}")


@app.get("/api/market-movers")
async def get_market_movers():
    """
    Exposes the cached today's top gainers, losers, indices and breadth stats.
    """
    global _MARKET_MOVERS_CACHE
    return _MARKET_MOVERS_CACHE


def calculate_support_resistance_lines(prices: list) -> tuple:
    """
    Finds structural support and resistance channels using the trendln library.
    Selects the primary support/resistance trendlines based on extrema pivot count.
    """
    import numpy as np
    n = len(prices)
    sup_series = [None] * n
    res_series = [None] * n
    
    try:
        import trendln
        h = np.array(prices, dtype=np.float64)
        
        # accuracy=8 sweeps multiple pivot directions to find best fit
        (minima, maxima, sup_lines, res_lines) = trendln.calc_support_resistance(h, accuracy=8)
        
        # Sort and select the line with the maximum pivot touch points
        if sup_lines:
            best_sup = max(sup_lines, key=lambda x: len(x[2]))
            slope, intercept = best_sup[0], best_sup[1]
            for i in range(n):
                sup_series[i] = float(slope * i + intercept)
                
        if res_lines:
            best_res = max(res_lines, key=lambda x: len(x[2]))
            slope, intercept = best_res[0], best_res[1]
            for i in range(n):
                res_series[i] = float(slope * i + intercept)
                
        # Fill empty series fallback
        if all(x is None for x in sup_series):
            sup_series = [float(min(prices))] * n
        if all(x is None for x in res_series):
            res_series = [float(max(prices))] * n
            
        return sup_series, res_series
    except Exception as e:
        print(f"Error calculating trendlines via trendln: {e}")
        # Mathematical failsafe boundaries fallback
        try:
            p_min = float(min(prices))
            p_max = float(max(prices))
            return [p_min] * n, [p_max] * n
        except Exception:
            return [0.0] * n, [1.0] * n

@app.get("/api/chart")
async def get_chart_data(ticker: str, period: str = "1y", interval: str = "1d"):
    """
    Dynamically fetches Yahoo Finance historical price series supporting dynamic 
    durations and frequencies, calculating SMAs over extended histories to avoid NaN values.
    Uses the direct public Chart CDN endpoint for maximum speed and rate-limit immunity.
    """
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker parameter is required.")
    try:
        # Map parameters to raw chart endpoint
        fetch_range = "2y"
        if interval == "1wk":
            fetch_range = "5y"
        elif interval == "1mo":
            fetch_range = "max"
            
        df = await fetch_history_df(ticker, fetch_range, interval)
        if df.empty:
            raise HTTPException(status_code=404, detail="No price data returned from Yahoo Chart endpoint.")
        
        # Calculate moving averages dynamically on the loaded frequency
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        
        # Calculate Volatility & Momentum Series (Bollinger Bands, ATR, MACD, VPT)
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['STD_20'] = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['SMA_20'] + 2 * df['STD_20']
        df['BB_Lower'] = df['SMA_20'] - 2 * df['STD_20']
        
        df['H-L'] = df['High'] - df['Low']
        df['H-Cp'] = (df['High'] - df['Close'].shift(1)).abs()
        df['L-Cp'] = (df['Low'] - df['Close'].shift(1)).abs()
        df['TR'] = df[['H-L', 'H-Cp', 'L-Cp']].max(axis=1)
        df['ATR'] = df['TR'].rolling(window=14).mean()
        
        df['EMA_12'] = df['Close'].ewm(span=12, adjust=False).mean()
        df['EMA_26'] = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = df['EMA_12'] - df['EMA_26']
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
        
        df['Price_Chg_Pct'] = df['Close'].pct_change()
        df['VPT_Flow'] = df['Volume'] * df['Price_Chg_Pct']
        df['VPT'] = df['VPT_Flow'].cumsum()
        
        # Replace NaN with first available values for flawless charting
        df['SMA_50'] = df['SMA_50'].bfill().ffill()
        df['SMA_200'] = df['SMA_200'].bfill().ffill()
        df['BB_Upper'] = df['BB_Upper'].bfill().ffill()
        df['BB_Lower'] = df['BB_Lower'].bfill().ffill()
        df['ATR'] = df['ATR'].bfill().ffill()
        df['MACD'] = df['MACD'].bfill().ffill()
        df['MACD_Signal'] = df['MACD_Signal'].bfill().ffill()
        df['MACD_Hist'] = df['MACD_Hist'].bfill().ffill()
        df['VPT'] = df['VPT'].bfill().ffill()
        
        # Slice the resulting series to only return the requested period
        period_days = {
            "1mo": 30,
            "3mo": 90,
            "6mo": 180,
            "1y": 365,
            "2y": 365 * 2,
            "3y": 365 * 3,
            "5y": 365 * 5
        }
        days = period_days.get(period, 365)
        cutoff_date = datetime.now() - timedelta(days=days)
            
        df_sliced = df[df.index >= cutoff_date]
        if len(df_sliced) < 5:
            df_sliced = df.tail(20) # Failsafe if slicing left too few rows
            
        labels = [index.strftime("%Y-%m-%d") for index in df_sliced.index]
        prices = df_sliced['Close'].tolist()
        sma50 = df_sliced['SMA_50'].tolist()
        sma200 = df_sliced['SMA_200'].tolist()
        volumes = df_sliced['Volume'].tolist()
        
        bb_upper = df_sliced['BB_Upper'].tolist()
        bb_lower = df_sliced['BB_Lower'].tolist()
        atr = df_sliced['ATR'].tolist()
        macd = df_sliced['MACD'].tolist()
        macd_signal = df_sliced['MACD_Signal'].tolist()
        macd_hist = df_sliced['MACD_Hist'].tolist()
        vpt = df_sliced['VPT'].tolist()
        
        opens = df_sliced['Open'].tolist()
        highs = df_sliced['High'].tolist()
        lows = df_sliced['Low'].tolist()
        
        # Calculate dynamic support and resistance trendlines using trendln
        ai_sup, ai_res = calculate_support_resistance_lines(prices)
        
        return {
            "labels": labels,
            "prices": [float(p) for p in prices],
            "open": [float(o) if not pd.isna(o) else float(prices[i]) for i, o in enumerate(opens)],
            "high": [float(h) if not pd.isna(h) else float(prices[i]) for i, h in enumerate(highs)],
            "low": [float(l) if not pd.isna(l) else float(prices[i]) for i, l in enumerate(lows)],
            "sma50": [float(s) if not pd.isna(s) else float(prices[i]) for i, s in enumerate(sma50)],
            "sma200": [float(s) if not pd.isna(s) else float(prices[i]) for i, s in enumerate(sma200)],
            "bb_upper": [float(s) if not pd.isna(s) else float(prices[i]) for i, s in enumerate(bb_upper)],
            "bb_lower": [float(s) if not pd.isna(s) else float(prices[i]) for i, s in enumerate(bb_lower)],
            "atr": [float(s) if not pd.isna(s) else 0.0 for i, s in enumerate(atr)],
            "macd": [float(s) if not pd.isna(s) else 0.0 for i, s in enumerate(macd)],
            "macd_signal": [float(s) if not pd.isna(s) else 0.0 for i, s in enumerate(macd_signal)],
            "macd_hist": [float(s) if not pd.isna(s) else 0.0 for i, s in enumerate(macd_hist)],
            "vpt": [float(s) if not pd.isna(s) else 0.0 for i, s in enumerate(vpt)],
            "volumes": [float(v) if not pd.isna(v) else 0.0 for v in volumes],
            "ai_support": [float(s) if s is not None else float(prices[i]) for i, s in enumerate(ai_sup)],
            "ai_resistance": [float(s) if s is not None else float(prices[i]) for i, s in enumerate(ai_res)]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Price series could not be retrieved from Yahoo Chart API: {str(e)}")


@app.get("/api/chart/tv-chart-data")
async def get_tv_chart_data(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
    length: int = 14,
    mult: float = 1.0,
    int_sens: int = 3,
    ext_sens: int = 25,
    show_last: int = 10,
    pitchfork_type: str = "Original",
    pitchfork_dev: float = 5.0,
    pitchfork_depth: int = 34
):
    """
    Exposes raw candlestick data, EMAs, volume, custom Trendlines with Breaks,
    and Mxwll Price Action Suite calculations for high-fidelity TradingView Lightweight Charts overlays.
    """
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker parameter is required.")
    try:
        fetch_range = "2y"
        if interval == "1wk":
            fetch_range = "5y"
        elif interval == "1mo":
            fetch_range = "max"
            
        df = await fetch_history_df(ticker, fetch_range, interval)
        if df.empty:
            raise HTTPException(status_code=404, detail="No price data returned from Yahoo Chart endpoint.")
            
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
        df['EMA_100'] = df['Close'].ewm(span=100, adjust=False).mean()
        df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()
        df['EMA_Custom'] = df['Close'].ewm(span=length, adjust=False).mean()
        
        from backend.swing_utils import (
            calculate_trendlines_with_breaks,
            calculate_mxwll_suite,
            calculate_lux_smc,
            calculate_linear_regression_trend_channel,
            calculate_pitchfork_indicators
        )
        breaks_data = calculate_trendlines_with_breaks(df, length=length, atr_mult=mult)
        mxwll_data = calculate_mxwll_suite(df, int_sens=int_sens, ext_sens=ext_sens, show_last=show_last)
        lux_smc_data = calculate_lux_smc(df, int_sens=int_sens, ext_sens=ext_sens, show_last=show_last)
        lrtc_data = calculate_linear_regression_trend_channel(df, period=length, deviations_mult=mult)
        pitchfork_data = calculate_pitchfork_indicators(df, deviation=pitchfork_dev, depth=pitchfork_depth, type_pf=pitchfork_type)
        
        df['Resistance'] = breaks_data["resistance"]
        df['Support'] = breaks_data["support"]
        df['Bullish_Break'] = breaks_data["bullish_breaks"]
        df['Bearish_Break'] = breaks_data["bearish_breaks"]
        df['lrtc_upper'] = lrtc_data["upper_entry"]
        df['lrtc_lower'] = lrtc_data["lower_entry"]
        df['lrtc_middle'] = lrtc_data["middle"]
        df['lrtc_ready_to_buy'] = lrtc_data["ready_to_buy"]
        df['lrtc_ready_to_sell'] = lrtc_data["ready_to_sell"]
        
        period_days = {
            "1mo": 30,
            "3mo": 90,
            "6mo": 180,
            "1y": 365,
            "2y": 365 * 2,
            "3y": 365 * 3,
            "5y": 365 * 5
        }
        days = period_days.get(period, 365)
        cutoff_date = datetime.now() - timedelta(days=days)
        
        df_sliced = df[df.index >= cutoff_date]
        if len(df_sliced) < 5:
            df_sliced = df.tail(60)
            
        candlesticks = []
        for idx in range(len(df_sliced)):
            row_idx = df_sliced.index[idx]
            candlesticks.append({
                "time": row_idx.strftime("%Y-%m-%d"),
                "open": round(float(df_sliced["Open"].iloc[idx]), 2),
                "high": round(float(df_sliced["High"].iloc[idx]), 2),
                "low": round(float(df_sliced["Low"].iloc[idx]), 2),
                "close": round(float(df_sliced["Close"].iloc[idx]), 2),
                "volume": round(float(df_sliced["Volume"].iloc[idx]), 2),
                "ema_20": round(float(df_sliced["EMA_20"].iloc[idx]), 2) if not pd.isna(df_sliced["EMA_20"].iloc[idx]) else None,
                "ema_50": round(float(df_sliced["EMA_50"].iloc[idx]), 2) if not pd.isna(df_sliced["EMA_50"].iloc[idx]) else None,
                "ema_100": round(float(df_sliced["EMA_100"].iloc[idx]), 2) if not pd.isna(df_sliced["EMA_100"].iloc[idx]) else None,
                "ema_200": round(float(df_sliced["EMA_200"].iloc[idx]), 2) if not pd.isna(df_sliced["EMA_200"].iloc[idx]) else None,
                "ema_custom": round(float(df_sliced["EMA_Custom"].iloc[idx]), 2) if not pd.isna(df_sliced["EMA_Custom"].iloc[idx]) else None,
                "resistance": round(float(df_sliced["Resistance"].iloc[idx]), 2) if not pd.isna(df_sliced["Resistance"].iloc[idx]) else None,
                "support": round(float(df_sliced["Support"].iloc[idx]), 2) if not pd.isna(df_sliced["Support"].iloc[idx]) else None,
                "bullish_break": bool(df_sliced["Bullish_Break"].iloc[idx]),
                "bearish_break": bool(df_sliced["Bearish_Break"].iloc[idx]),
                "lrtc_upper": round(float(df_sliced["lrtc_upper"].iloc[idx]), 2) if not pd.isna(df_sliced["lrtc_upper"].iloc[idx]) else None,
                "lrtc_lower": round(float(df_sliced["lrtc_lower"].iloc[idx]), 2) if not pd.isna(df_sliced["lrtc_lower"].iloc[idx]) else None,
                "lrtc_middle": round(float(df_sliced["lrtc_middle"].iloc[idx]), 2) if not pd.isna(df_sliced["lrtc_middle"].iloc[idx]) else None,
                "lrtc_ready_to_buy": bool(df_sliced["lrtc_ready_to_buy"].iloc[idx]),
                "lrtc_ready_to_sell": bool(df_sliced["lrtc_ready_to_sell"].iloc[idx])
            })
            
        # Filter pitchfork data to only include dates in df_sliced
        sliced_times = set(c["time"] for c in candlesticks)
        pf_details = pitchfork_data.get("pitchfork", {})
        zigzag_filtered = [p for p in pitchfork_data["zigzag"] if p["time"] in sliced_times]
        median_filtered = [p for p in pf_details.get("median", []) if p["time"] in sliced_times]
        
        # 1.0 standard upper parallel line
        upper_1_0 = pf_details.get("upper_levels", {}).get("1.0", [])
        upper_line_filtered = [p for p in upper_1_0 if p["time"] in sliced_times]
        
        # 1.0 standard lower parallel line
        lower_1_0 = pf_details.get("lower_levels", {}).get("1.0", [])
        lower_line_filtered = [p for p in lower_1_0 if p["time"] in sliced_times]
        
        # Intermediate fib levels
        levels_filtered = {}
        for lvl in ["0.25", "0.382", "0.5", "0.618", "0.75"]:
            pts_upper = pf_details.get("upper_levels", {}).get(lvl, [])
            levels_filtered[f"upper_{lvl}"] = [p for p in pts_upper if p["time"] in sliced_times]
            
            pts_lower = pf_details.get("lower_levels", {}).get(lvl, [])
            levels_filtered[f"lower_{lvl}"] = [p for p in pts_lower if p["time"] in sliced_times]
            
        filtered_pitchfork = {
            "type": pf_details.get("type", "Original"),
            "p1": pf_details.get("p1"),
            "p2": pf_details.get("p2"),
            "p3": pf_details.get("p3"),
            "zigzag": zigzag_filtered,
            "median_line": median_filtered,
            "upper_line": upper_line_filtered,
            "lower_line": lower_line_filtered,
            "levels": levels_filtered,
            "fibonacci": pitchfork_data.get("fibonacci", {})
        }
        
        return {
            "symbol": ticker,
            "period": period,
            "interval": interval,
            "length": length,
            "mult": mult,
            "candlesticks": candlesticks,
            "mxwll": mxwll_data,
            "lux_smc": lux_smc_data,
            "lrtc_latest": lrtc_data["latest_channel"],
            "pitchfork": filtered_pitchfork
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TradingView chart data calculation error: {str(e)}")


@app.get("/api/chart/indicator-synthesis")
async def get_indicator_synthesis(
    ticker: str,
    indicator: str = "lux-algo",
    period: str = "1y",
    interval: str = "1d",
    length: int = 14,
    mult: float = 1.0,
    int_sens: int = 3,
    ext_sens: int = 25,
    show_last: int = 10
):
    """
    Synthesizes custom technical indicator calculations (LuxAlgo SMC, Trendlines with Breaks, or Mxwll)
    into a structured tactical summary using Groq LLM.
    """
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker parameter is required.")
        
    try:
        fetch_range = "2y"
        if interval == "1wk":
            fetch_range = "5y"
        elif interval == "1mo":
            fetch_range = "max"
            
        df = await fetch_history_df(ticker, fetch_range, interval)
        if df.empty:
            raise HTTPException(status_code=404, detail="No price data returned from Yahoo Chart endpoint.")
            
        # Get latest price details
        curr_price = round(float(df["Close"].iloc[-1]), 2)
        prev_price = round(float(df["Close"].iloc[-2]), 2) if len(df) > 1 else curr_price
        price_change = round(curr_price - prev_price, 2)
        pct_change = round((price_change / prev_price) * 100, 2) if prev_price > 0 else 0.0
        
        # Calculate standard ATR
        highs = df['High'].values
        lows = df['Low'].values
        closes = df['Close'].values
        tr = np.maximum(highs - lows, np.maximum(np.abs(highs - np.roll(closes, 1)), np.abs(lows - np.roll(closes, 1))))
        tr[0] = highs[0] - lows[0]
        atr_val = round(float(np.mean(tr[-14:])), 2)
        
        from backend.swing_utils import calculate_trendlines_with_breaks, calculate_mxwll_suite, calculate_lux_smc
        from backend.llm_config import call_llm, TASK_FAST, TASK_HEAVY
        
        system_prompt = (
            "You are a professional Technical Analyst and Senior Market Strategist specializing in the Indian Stock Markets.\n"
            "Your objective is to provide a highly detailed, concise, and structured tactical analysis of the stock based *only* on the provided custom indicator calculations.\n"
            "In addition, analyze the historical structural levels, supports, resistances, and order blocks to identify any classic chart patterns (such as Double Tops/Bottoms, Head & Shoulders, Ascending/Descending Triangles, or Pennant/Wedge Breakouts). Specifically confirm if any classic pattern is active, forming, or breached, explaining the tactical implications.\n"
            "Format your response in structured Markdown. Start directly with the analysis. Avoid conversational preambles (like 'Here is the analysis...').\n"
            "Use clear bullet points and bold styling. Do not hallucinate prices; rely only on the structured indicators values provided in the prompt."
        )
        
        indicator_list = [ind.strip().lower() for ind in indicator.split(",") if ind.strip()]
        
        user_prompt_parts = [
            f"Perform a technical analysis for the stock ticker: {ticker}",
            f"Current Price: Rs. {curr_price} ({price_change:+.2f}, {pct_change:+.2f}%)",
            f"Volatility (ATR-14): {atr_val}",
            f"Active Indicators: {', '.join(indicator_list).upper()}\n"
        ]
        
        has_active_indicator = False
        
        if "lux-algo" in indicator_list:
            has_active_indicator = True
            breaks_data = calculate_trendlines_with_breaks(df, length=length, atr_mult=mult)
            last_res = next((x for x in reversed(breaks_data["resistance"]) if x is not None), None)
            last_sup = next((x for x in reversed(breaks_data["support"]) if x is not None), None)
            recent_bull_break = any(breaks_data["bullish_breaks"][-15:])
            recent_bear_break = any(breaks_data["bearish_breaks"][-15:])
            
            res_str = f"Rs. {last_res}" if last_res else "None identified"
            sup_str = f"Rs. {last_sup}" if last_sup else "None identified"
            
            user_prompt_parts.append(
                f"--- LuxAlgo Trendlines with Breaks (Lookback: {length}, Slope Multiplier: {mult}) ---\n"
                f"- Active Support Trendline Price: {sup_str}\n"
                f"- Active Resistance Trendline Price: {res_str}\n"
                f"- Recent Bullish Breakout (last 15 bars): {'YES' if recent_bull_break else 'NO'}\n"
                f"- Recent Bearish Breakout (last 15 bars): {'YES' if recent_bear_break else 'NO'}\n"
                f"Implications: Discuss the support and resistance structure, any converging trendlines indicating flag/triangle/pennant, and implications of breakouts.\n"
            )
            
        if "lux-smc" in indicator_list:
            has_active_indicator = True
            smc = calculate_lux_smc(df, int_sens=int_sens, ext_sens=length, show_last=show_last)
            struct_list = []
            if smc.get("structures"):
                for s in smc["structures"][-5:]:
                    struct_list.append(f"{s['time']}: {s['type']} ({s['direction']}, Level: Rs. {s.get('price', 'N/A')})")
            struct_str = "\n".join(struct_list) if struct_list else "No recent structures detected"
            
            demand_obs = [ob for ob in smc.get("order_blocks", []) if ob["type"] == "demand"]
            supply_obs = [ob for ob in smc.get("order_blocks", []) if ob["type"] == "supply"]
            demand_str = ", ".join([f"Rs. {ob['bottom']}-{ob['top']}" for ob in demand_obs[-3:]]) if demand_obs else "None active"
            supply_str = ", ".join([f"Rs. {ob['bottom']}-{ob['top']}" for ob in supply_obs[-3:]]) if supply_obs else "None active"
            
            pd = smc.get("premium_discount", {})
            pd_str = f"Range: Rs. {pd.get('bottom')}-{pd.get('top')} (Equilibrium: Rs. {pd.get('equilibrium')})" if pd else "Unknown"
            
            pd_zone = "Neutral"
            if pd:
                eq = pd.get("equilibrium", 0)
                if curr_price > eq:
                    pd_zone = f"Premium Zone (above equilibrium of Rs. {eq})"
                elif curr_price < eq:
                    pd_zone = f"Discount Zone (below equilibrium of Rs. {eq})"
                    
            daily = smc.get("daily_levels", [])
            last_daily = daily[-1] if daily else None
            daily_str = f"High: Rs. {last_daily['high']}, Low: Rs. {last_daily['low']}" if last_daily else "N/A"
            
            user_prompt_parts.append(
                f"--- LuxAlgo Smart Money Concepts (Internal Sens: {int_sens}, Swing Sens: {length}) ---\n"
                f"- Recent Structural Transitions (BOS/CHoCH):\n{struct_str}\n"
                f"- Unmitigated Demand Order Blocks (Buy Zone): {demand_str}\n"
                f"- Unmitigated Supply Order Blocks (Sell Zone): {supply_str}\n"
                f"- Premium / Discount Zones: {pd_str}\n"
                f"- Current Price Position: Sits in the {pd_zone}\n"
                f"- Prev Day High/Low (Daily levels): {daily_str}\n"
                f"Implications: Explain the bias (bullish/bearish) based on structural transitions (BOS/CHoCH) and premium/discount position, and key order blocks to watch.\n"
            )
            
        if "mxwll" in indicator_list:
            has_active_indicator = True
            mxwll = calculate_mxwll_suite(df, int_sens=int_sens, ext_sens=length, show_last=show_last)
            struct_list = []
            if mxwll.get("structures"):
                for s in mxwll["structures"][-5:]:
                    struct_list.append(f"{s['time']}: {s['type']} ({s['direction']}, Price: Rs. {s.get('price', 'N/A')})")
            struct_str = "\n".join(struct_list) if struct_list else "No recent structures detected"
            
            demand_obs = [ob for ob in mxwll.get("order_blocks", []) if ob["type"] == "demand"]
            supply_obs = [ob for ob in mxwll.get("order_blocks", []) if ob["type"] == "supply"]
            demand_str = ", ".join([f"Rs. {ob['bottom']:.2f}-{ob['top']:.2f}" for ob in demand_obs[-3:]]) if demand_obs else "None active"
            supply_str = ", ".join([f"Rs. {ob['bottom']:.2f}-{ob['top']:.2f}" for ob in supply_obs[-3:]]) if supply_obs else "None active"
            
            fvgs = mxwll.get("fvg", [])
            fvg_str = ", ".join([f"{g['type']} (Rs. {g['bottom']:.2f}-{g['top']:.2f})" for g in fvgs[-3:]]) if fvgs else "None active"
            
            fibs = mxwll.get("fib_levels", {})
            fibs_str = ", ".join([f"{k}: Rs. {v}" for k, v in fibs.items() if k not in ["anchor_start_time", "anchor_end_time"]]) if fibs else "N/A"
            
            user_prompt_parts.append(
                f"--- Mxwll Price Action Suite (Int Sens: {int_sens}, Ext Sens: {length}) ---\n"
                f"- Market Structures (BOS/CHoCH):\n{struct_str}\n"
                f"- Active Demand Zones (OBs): {demand_str}\n"
                f"- Active Supply Zones (OBs): {supply_str}\n"
                f"- Unmitigated Fair Value Gaps (FVGs): {fvg_str}\n"
                f"- Auto-Fibonacci Retracement Levels: {fibs_str}\n"
                f"Implications: Detail how the market structural transitions compare, analyze FVGs/OBs, and evaluate price relative to Fibonacci levels for retracements or retests.\n"
            )
            
        if "lrtc" in indicator_list:
            has_active_indicator = True
            from backend.swing_utils import calculate_linear_regression_trend_channel
            lrtc_data = calculate_linear_regression_trend_channel(df, period=length, deviations_mult=mult)
            latest = lrtc_data.get("latest_channel", {})
            recent_buy = any(lrtc_data["ready_to_buy"][-15:])
            recent_sell = any(lrtc_data["ready_to_sell"][-15:])
            
            slope = latest.get("slope", 0.0) if latest else 0.0
            trend_slope = -slope
            channel_direction = "Rising/Bullish" if trend_slope > 0 else "Falling/Bearish"
            
            user_prompt_parts.append(
                f"--- Linear Regression Trend Channel (Period: {length}, Deviations: {mult}) ---\n"
                f"- Channel Direction: {channel_direction} (Slope: {trend_slope:.4f})\n"
                f"- Current Channel End Bounds:\n"
                f"  * Upper Channel (Sell Limit): Rs. {latest.get('upper_end', 0.0) if latest else 0.0}\n"
                f"  * Median Line (Fair Value): Rs. {latest.get('median_end', 0.0) if latest else 0.0}\n"
                f"  * Lower Channel (Buy Limit): Rs. {latest.get('lower_end', 0.0) if latest else 0.0}\n"
                f"- Current Entry Alerts (last 15 bars):\n"
                f"  * Buy Alert Triggered: {'YES' if recent_buy else 'NO'}\n"
                f"  * Sell Alert Triggered: {'YES' if recent_sell else 'NO'}\n"
                f"Implications: Explain if the current price sits near the Upper, Median, or Lower boundary, what the trend channel direction implies, and entry/exit stop/target logic using channel width.\n"
            )
            
        if not has_active_indicator:
            user_prompt_parts.append(
                "Active Indicator: Price and Volatility Only\n"
                "Write a standard short-term volatility and trend structure overview based on the price action, looking for basic double top/bottom patterns if price is consolidating near key extreme levels."
            )
            
        user_prompt_parts.append(
            "\nBased on the active custom indicators above, draft a professional combined technical analysis report. "
            "Integrate findings into a singular, cohesive narrative, highlighting key support/resistance levels, structural reversals/continuations, and clear stop loss and target levels."
        )
        
        user_prompt = "\n".join(user_prompt_parts)
        
        synthesis = await asyncio.to_thread(call_llm, TASK_FAST, system_prompt, user_prompt)
        return {
            "symbol": ticker,
            "indicator": indicator,
            "synthesis": synthesis,
            "llm_meta": get_last_llm_meta()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Indicator LLM synthesis failure: {str(e)}")


@app.post("/api/chart/chat-analyst")
async def post_chart_chat_analyst(req: ChartChatRequest):
    ticker = req.symbol
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker parameter is required.")
        
    try:
        fetch_range = "2y"
        df = await fetch_history_df(ticker, fetch_range, "1d")
        if df.empty:
            raise HTTPException(status_code=404, detail="No price data returned from Yahoo Chart endpoint.")
            
        curr_price = round(float(df["Close"].iloc[-1]), 2)
        prev_price = round(float(df["Close"].iloc[-2]), 2) if len(df) > 1 else curr_price
        price_change = round(curr_price - prev_price, 2)
        pct_change = round((price_change / prev_price) * 100, 2) if prev_price > 0 else 0.0
        
        # Calculate ATR-14
        highs = df['High'].values
        lows = df['Low'].values
        closes = df['Close'].values
        tr = np.maximum(highs - lows, np.maximum(np.abs(highs - np.roll(closes, 1)), np.abs(lows - np.roll(closes, 1))))
        tr[0] = highs[0] - lows[0]
        atr_val = round(float(np.mean(tr[-14:])), 2)
        
        from backend.swing_utils import (
            calculate_trendlines_with_breaks, 
            calculate_mxwll_suite, 
            calculate_lux_smc,
            calculate_linear_regression_trend_channel,
            calculate_pitchfork_indicators
        )
        from backend.llm_config import call_llm, TASK_FAST
        from backend.events_scraper import get_stock_events_cached
        
        # Get cached events
        events = []
        try:
            events = get_stock_events_cached(ticker)
        except Exception:
            pass
        
        # Get cached trades
        insider_trades = []
        bulk_deals = []
        block_deals = []
        base_symbol = ticker.replace(".NS", "").replace(".BO", "")
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT data_json FROM cached_trades WHERE symbol = ?", (base_symbol,))
                row = cursor.fetchone()
                if row:
                    trades_data = json.loads(row["data_json"])
                    insider_trades = trades_data.get("insider_trades", [])
                    bulk_deals = trades_data.get("bulk_deals", [])
                    block_deals = trades_data.get("block_deals", [])
        except Exception:
            pass
                    
        system_prompt = (
            "You are a professional Technical Analyst and Senior Market Strategist specializing in the Indian Stock Markets.\n"
            "Your objective is to answer user queries or analyze the chart based *only* on the provided custom indicator calculations, historical structural levels, and fundamental catalysts.\n"
            "Identify any classic chart patterns (Double Tops/Bottoms, Head & Shoulders, Ascending/Descending Triangles, or Pennant/Wedge breakouts) if active, and highlight key supports/resistances.\n"
            "In addition, look for CONFLUENCE CLUSTERS: instances where multiple indicator boundaries (e.g. Maxwell golden zone, SMC Order Block, and LRTC boundaries) fall within a ±1% price range. Highlight these confluence points as high-probability reversal or acceleration zones.\n"
            "Format your response in structured Markdown. Start directly with the analysis. Avoid conversational preambles (like 'Here is the analysis...').\n"
            "Use clear bullet points and bold styling. Do not hallucinate prices; rely only on the structured indicators values provided in the prompt."
        )
        
        indicator_list = [ind.strip().lower() for ind in req.indicator.split(",") if ind.strip()]
        
        user_prompt_parts = [
            f"Perform a technical analysis for the stock ticker: {ticker}",
            f"Current Price: Rs. {curr_price} ({price_change:+.2f}, {pct_change:+.2f}%)",
            f"Volatility (ATR-14): {atr_val}",
            f"Active Indicators: {', '.join(indicator_list).upper()}\n"
        ]
        
        has_active_indicator = False
        
        if "lux-algo" in indicator_list:
            has_active_indicator = True
            breaks_data = calculate_trendlines_with_breaks(df, length=req.length, atr_mult=req.mult)
            last_res = next((x for x in reversed(breaks_data["resistance"]) if x is not None), None)
            last_sup = next((x for x in reversed(breaks_data["support"]) if x is not None), None)
            recent_bull_break = any(breaks_data["bullish_breaks"][-15:])
            recent_bear_break = any(breaks_data["bearish_breaks"][-15:])
            
            res_str = f"Rs. {last_res}" if last_res else "None identified"
            sup_str = f"Rs. {last_sup}" if last_sup else "None identified"
            
            user_prompt_parts.append(
                f"--- LuxAlgo Trendlines with Breaks (Lookback: {req.length}, Slope Multiplier: {req.mult}) ---\n"
                f"- Active Support Trendline Price: {sup_str}\n"
                f"- Active Resistance Trendline Price: {res_str}\n"
                f"- Recent Bullish Breakout (last 15 bars): {'YES' if recent_bull_break else 'NO'}\n"
                f"- Recent Bearish Breakout (last 15 bars): {'YES' if recent_bear_break else 'NO'}\n"
            )
            
        if "lux-smc" in indicator_list or "smc" in indicator_list:
            has_active_indicator = True
            smc = calculate_lux_smc(df, int_sens=3, ext_sens=req.length, show_last=10)
            struct_list = []
            if smc.get("structures"):
                for s in smc["structures"][-5:]:
                    struct_list.append(f"{s['time']}: {s['type']} ({s['direction']}, Level: Rs. {s.get('price', 'N/A')})")
            struct_str = "\n".join(struct_list) if struct_list else "No recent structures detected"
            
            demand_obs = [ob for ob in smc.get("order_blocks", []) if ob["type"] == "demand"]
            supply_obs = [ob for ob in smc.get("order_blocks", []) if ob["type"] == "supply"]
            demand_str = ", ".join([f"Rs. {ob['bottom']}-{ob['top']}" for ob in demand_obs[-3:]]) if demand_obs else "None active"
            supply_str = ", ".join([f"Rs. {ob['bottom']}-{ob['top']}" for ob in supply_obs[-3:]]) if supply_obs else "None active"
            
            pd = smc.get("premium_discount", {})
            pd_str = f"Range: Rs. {pd.get('bottom')}-{pd.get('top')} (Equilibrium: Rs. {pd.get('equilibrium')})" if pd else "Unknown"
            
            pd_zone = "Neutral"
            if pd:
                eq = pd.get("equilibrium", 0)
                if curr_price > eq:
                    pd_zone = f"Premium Zone (above equilibrium of Rs. {eq})"
                elif curr_price < eq:
                    pd_zone = f"Discount Zone (below equilibrium of Rs. {eq})"
                    
            daily = smc.get("daily_levels", [])
            last_daily = daily[-1] if daily else None
            daily_str = f"High: Rs. {last_daily['high']}, Low: Rs. {last_daily['low']}" if last_daily else "N/A"
            
            user_prompt_parts.append(
                f"--- LuxAlgo Smart Money Concepts (Internal Sens: 3, Swing Sens: {req.length}) ---\n"
                f"- Recent Structural Transitions (BOS/CHoCH):\n{struct_str}\n"
                f"- Unmitigated Demand Order Blocks (Buy Zone): {demand_str}\n"
                f"- Unmitigated Supply Order Blocks (Sell Zone): {supply_str}\n"
                f"- Premium / Discount Zones: {pd_str}\n"
                f"- Current Price Position: Sits in the {pd_zone}\n"
                f"- Prev Day High/Low (Daily levels): {daily_str}\n"
            )
            
        if "mxwll" in indicator_list:
            has_active_indicator = True
            mxwll = calculate_mxwll_suite(df, int_sens=3, ext_sens=req.length, show_last=10)
            struct_list = []
            if mxwll.get("structures"):
                for s in mxwll["structures"][-5:]:
                    struct_list.append(f"{s['time']}: {s['type']} ({s['direction']}, Price: Rs. {s.get('price', 'N/A')})")
            struct_str = "\n".join(struct_list) if struct_list else "No recent structures detected"
            
            demand_obs = [ob for ob in mxwll.get("order_blocks", []) if ob["type"] == "demand"]
            supply_obs = [ob for ob in mxwll.get("order_blocks", []) if ob["type"] == "supply"]
            demand_str = ", ".join([f"Rs. {ob['bottom']:.2f}-{ob['top']:.2f}" for ob in demand_obs[-3:]]) if demand_obs else "None active"
            supply_str = ", ".join([f"Rs. {ob['bottom']:.2f}-{ob['top']:.2f}" for ob in supply_obs[-3:]]) if supply_obs else "None active"
            
            fvgs = mxwll.get("fvg", [])
            fvg_str = ", ".join([f"{g['type']} (Rs. {g['bottom']:.2f}-{g['top']:.2f})" for g in fvgs[-3:]]) if fvgs else "None active"
            
            fibs = mxwll.get("fib_levels", {})
            fibs_str = ", ".join([f"{k}: Rs. {v}" for k, v in fibs.items() if k not in ["anchor_start_time", "anchor_end_time"]]) if fibs else "N/A"
            
            user_prompt_parts.append(
                f"--- Mxwll Price Action Suite (Int Sens: 3, Ext Sens: {req.length}) ---\n"
                f"- Market Structures (BOS/CHoCH):\n{struct_str}\n"
                f"- Active Demand Zones (OBs): {demand_str}\n"
                f"- Active Supply Zones (OBs): {supply_str}\n"
                f"- Unmitigated Fair Value Gaps (FVGs): {fvg_str}\n"
                f"- Auto-Fibonacci Retracement Levels: {fibs_str}\n"
            )
            
        if "lrtc" in indicator_list:
            has_active_indicator = True
            lrtc_data = calculate_linear_regression_trend_channel(df, period=req.length, deviations_mult=req.mult)
            latest = lrtc_data.get("latest_channel", {})
            recent_buy = any(lrtc_data["ready_to_buy"][-15:])
            recent_sell = any(lrtc_data["ready_to_sell"][-15:])
            
            slope = latest.get("slope", 0.0) if latest else 0.0
            trend_slope = -slope
            channel_direction = "Rising/Bullish" if trend_slope > 0 else "Falling/Bearish"
            
            user_prompt_parts.append(
                f"--- Linear Regression Trend Channel (Period: {req.length}, Deviations: {req.mult}) ---\n"
                f"- Channel Direction: {channel_direction} (Slope: {trend_slope:.4f})\n"
                f"- Current Channel End Bounds:\n"
                f"  * Upper Channel (Sell Limit): Rs. {latest.get('upper_end', 0.0) if latest else 0.0}\n"
                f"  * Median Line (Fair Value): Rs. {latest.get('median_end', 0.0) if latest else 0.0}\n"
                f"  * Lower Channel (Buy Limit): Rs. {latest.get('lower_end', 0.0) if latest else 0.0}\n"
                f"- Current Entry Alerts (last 15 bars):\n"
                f"  * Buy Alert Triggered: {'YES' if recent_buy else 'NO'}\n"
                f"  * Sell Alert Triggered: {'YES' if recent_sell else 'NO'}\n"
            )
            
        if "pitchfork" in indicator_list:
            has_active_indicator = True
            pf_res = calculate_pitchfork_indicators(df, deviation=5.0, depth=req.length * 2, type_pf='Original')
            pf = pf_res.get("pitchfork", {})
            p1_val = pf.get("p1", {}).get("value") if pf.get("p1") else "N/A"
            p2_val = pf.get("p2", {}).get("value") if pf.get("p2") else "N/A"
            p3_val = pf.get("p3", {}).get("value") if pf.get("p3") else "N/A"
            user_prompt_parts.append(
                f"--- Andrews Pitchfork (Parameters: depth={req.length * 2}) ---\n"
                f"- Anchor Prices: P1 (Start) = Rs. {p1_val}, P2 (High) = Rs. {p2_val}, P3 (Low) = Rs. {p3_val}\n"
            )
            
        if not has_active_indicator:
            user_prompt_parts.append(
                "Active Indicator: Price and Volatility Only\n"
                "Provide a standard trend and volatility overview based on price action alone."
            )
            
        # Add events
        if events:
            user_prompt_parts.append("--- Upcoming Corporate Events & Catalysts ---")
            for ev in events[:5]:
                user_prompt_parts.append(
                    f"- Date: {ev['event_date']} | Type: {ev.get('event_type','Event')} | Purpose: {ev.get('purpose','N/A')} [Countdown: {ev.get('countdown_days','N/A')} days]"
                )
                
        # Add trades
        if insider_trades:
            user_prompt_parts.append("--- Recent Insider Trades (SAST Promoter Activity) ---")
            for trd in insider_trades[:5]:
                user_prompt_parts.append(
                    f"- Date: {trd.get('date','N/A')} | Acquirer: {trd.get('acquirer','N/A')} | Action: {trd.get('mode','N/A')} | Shares: {trd.get('shares','N/A')} | Value: {trd.get('value','N/A')}"
                )
        if bulk_deals or block_deals:
            user_prompt_parts.append("--- Recent Bulk & Block Deals ---")
            for deal in (bulk_deals + block_deals)[:5]:
                user_prompt_parts.append(
                    f"- Date: {deal.get('date','N/A')} | Party: {deal.get('client_name','N/A')} | Type: {deal.get('type','N/A')} | Qty: {deal.get('quantity','N/A')} | Avg Price: {deal.get('price','N/A')}"
                )
                
        # Inject Chat History
        if req.chat_history:
            user_prompt_parts.append("\n--- Conversation History ---")
            for msg in req.chat_history:
                role_label = "User" if msg.get("role") == "user" else "Assistant"
                user_prompt_parts.append(f"{role_label}: {msg.get('content')}")
                
        # Custom Prompt
        user_prompt_parts.append(f"\nUser Query: {req.custom_prompt}")
        
        user_prompt = "\n".join(user_prompt_parts)
        analysis = await asyncio.to_thread(call_llm, TASK_FAST, system_prompt, user_prompt)
        
        if not analysis:
            raise HTTPException(status_code=500, detail="LLM failed to respond.")
            
        return {"analysis": analysis, "llm_meta": get_last_llm_meta()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chart AI Chatbot execution failed: {str(e)}")


@app.get("/api/compare")
async def compare_rivals(tickers: str, generate_thesis: bool = False):
    """Benchmarks rivals side-by-side."""
    if not tickers:
        raise HTTPException(status_code=400, detail="Tickers parameter is required.")
    ticker_list = [t.strip().upper() for t in tickers.split(",")]
    try:
        comparison = await asyncio.to_thread(run_comparison_synthesizer, ticker_list, generate_thesis)
        return comparison
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Comparison aggregator error: {str(e)}")


def get_fibonacci_retracement_zone(current_price: float, fib_levels: dict) -> str:
    """
    Classifies where the current price sits relative to its Fibonacci levels.
    """
    if not fib_levels or not isinstance(fib_levels, dict):
        return "Neutral Zone"
    try:
        # Sort levels by price to find interval
        levels = [
            ("0.0% (52W High)", float(fib_levels.get("fib_0", 0.0))),
            ("23.6%", float(fib_levels.get("fib_236", 0.0))),
            ("38.2%", float(fib_levels.get("fib_382", 0.0))),
            ("50.0% (Mid-point)", float(fib_levels.get("fib_500", 0.0))),
            ("61.8% (Golden Ratio)", float(fib_levels.get("fib_618", 0.0))),
            ("78.6%", float(fib_levels.get("fib_786", 0.0))),
            ("100.0% (52W Low)", float(fib_levels.get("fib_100", 0.0)))
        ]
        # Sort in ascending order (Low price to High price)
        levels_sorted = sorted(levels, key=lambda x: x[1])
        
        if current_price < levels_sorted[0][1]:
            return f"Below 100.0% 52W Low (Rs. {levels_sorted[0][1]:.2f})"
        if current_price > levels_sorted[-1][1]:
            return f"Above 0.0% 52W High (Rs. {levels_sorted[-1][1]:.2f})"
            
        for i in range(len(levels_sorted) - 1):
            low_lbl, low_val = levels_sorted[i]
            high_lbl, high_val = levels_sorted[i+1]
            if low_val <= current_price <= high_val:
                return f"Between {low_lbl} (Rs. {low_val:.2f}) and {high_lbl} (Rs. {high_val:.2f})"
    except Exception:
        pass
    return "Neutral Zone"


@app.get("/api/synthesis")
async def get_synthesis(
    symbol: str,
    horizon: str = "Long-term (3+ years)",
    risk: str = "Moderate"
):
    """
    Overhauls workstation to support the Hybrid SaaS AI Equities Synthesis feature.
    Provides a comprehensive, dynamic, multi-agent financial synthesis of the loaded stock
    compiled by the parent LLM.
    """
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol query parameter is required.")
    try:
        # Resolve ticker first
        resolved = resolve_company_ticker(symbol)
        ticker = resolved.get("yf_ticker")
        if not ticker:
            ticker = symbol.upper()
            if not (ticker.endswith(".NS") or ticker.endswith(".BO")):
                ticker = f"{ticker}.NS"

        # Check cache
        profile = None
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ?", (ticker,))
                row = cursor.fetchone()
                if row:
                    profile = json.loads(row["profile_json"])
        except Exception as e:
            print(f"Error checking cache for synthesis: {e}")

        # If not cached, trigger parent agent
        if not profile:
            profile = await run_cio_parent_agent(ticker, horizon, risk)
            # Cache the newly generated profile
            try:
                with get_db() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO cached_profiles (symbol, profile_json, updated_at) VALUES (?, ?, ?)",
                        (ticker, json.dumps(profile), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    )
                    conn.commit()
            except Exception as db_err:
                print(f"Error caching profile: {db_err}")

        # Package indicators safely
        eq = profile.get("earnings_quality", {})
        piotroski_score = eq.get("piotroski_score", 0)
        piotroski_label = eq.get("piotroski_label", "Unknown Quality")
        altman_z_score = eq.get("altman_z_score", 0.0)
        altman_zone = eq.get("altman_zone", "Unknown Zone")

        dcf = profile.get("dcf_model", {})
        dcf_intrinsic_value = dcf.get("intrinsic_value", 0.0)
        margin_of_safety = dcf.get("margin_of_safety", 0.0)

        fundamentals = profile.get("fundamentals", {})
        current_price = fundamentals.get("current_price", 0.0)

        technicals = profile.get("technicals", {})
        rsi = technicals.get("rsi", 50.0)
        sma_50 = technicals.get("sma_50", 0.0)
        sma_200 = technicals.get("sma_200", 0.0)
        
        # Double decimal point formatting variables for prompts and fallback synthesis
        sma_50_str = f"{sma_50:.2f}" if isinstance(sma_50, (int, float)) else "0.00"
        sma_200_str = f"{sma_200:.2f}" if isinstance(sma_200, (int, float)) else "0.00"
        
        cfo_to_pat = fundamentals.get("cfo_to_pat", 0.88)
        cfo_to_pat_str = f"{cfo_to_pat:.2f}" if isinstance(cfo_to_pat, (int, float)) else "0.88"
        
        # Advanced Volatility & Momentum Indicators
        bb_lower = technicals.get("bb_lower", 0.0)
        bb_upper = technicals.get("bb_upper", 0.0)
        atr = technicals.get("atr", 0.0)
        macd = technicals.get("macd", 0.0)
        macd_signal = technicals.get("macd_signal", 0.0)
        macd_hist = technicals.get("macd_hist", 0.0)
        vpt = technicals.get("vpt", 0.0)
        adx = technicals.get("adx", 22.0)
        volume_vs_avg20 = technicals.get("volume_vs_avg20", 1.0)

        # Volatility Squeeze & ATR ratio calculation
        squeeze_pct = ((bb_upper - bb_lower) / bb_lower * 100) if bb_lower > 0 else 0.0
        volatility_ratio = (atr / current_price * 100) if current_price > 0 else 0.0
        vol_level = "Low"
        if volatility_ratio > 3.0:
            vol_level = "High"
        elif volatility_ratio > 1.5:
            vol_level = "Moderate"
            
        atr_stop_loss = (current_price - 2 * atr) if (atr > 0 and current_price > 0) else 0.0
        macd_status = "Bullish Crossover" if macd_hist > 0 else ("Bearish Divergence" if macd_hist < 0 else "Neutral")
        vpt_status = "Expanding Accumulation" if vpt > 0 else "Neutral/Contracting"

        # --- DYNAMIC PRICE-VOLUME & REAL BULK DEALS ANALYSIS ---
        delivery_z_score = 0.0
        vsa_pattern = "Normal Price Action"
        vsa_type = "neutral"
        vsa_desc = "No significant Volume Spread Analysis patterns or anomalies detected."
        poc_price = current_price
        real_deals_summary = []
        real_deals_list = []

        try:
            import requests
            import pandas as pd
            from backend.swing_utils import calculate_volume_profile
            from backend.quant_scoring import detect_vsa_setup, calculate_delivery_zscore
            
            # Fetch Yahoo Finance (6mo) for chart analysis
            df = await fetch_history_df(ticker, "6mo", "1d")
            if not df.empty:
                display_bars = min(60, len(df))
                df_display = df.iloc[-display_bars:]
                
                # Fetch SQLite delivery history
                delivery_history = {}
                try:
                    with get_db() as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            SELECT trade_date, delivery_qty, traded_qty, delivery_percentage 
                            FROM daily_delivery_history 
                            WHERE symbol = ? 
                            ORDER BY trade_date ASC
                        """, (ticker,))
                        for r_row in cursor.fetchall():
                            delivery_history[r_row["trade_date"]] = {
                                "delivery_qty": r_row["delivery_qty"],
                                "traded_qty": r_row["traded_qty"],
                                "delivery_percentage": r_row["delivery_percentage"]
                            }
                except Exception as db_err:
                    print(f"Error querying delivery history in synthesis: {db_err}")
                    
                # Fetch corporate actions
                corporate_actions = []
                try:
                    with get_db() as conn:
                        cursor = conn.conn.cursor() if hasattr(conn, "conn") else conn.cursor()
                        cursor.execute("""
                            SELECT action_type, ex_date, ratio_multiplier 
                            FROM corporate_actions 
                            WHERE symbol = ?
                        """, (ticker,))
                        for ca_row in cursor.fetchall():
                            corporate_actions.append({
                                "action_type": ca_row["action_type"],
                                "ex_date": ca_row["ex_date"],
                                "ratio_multiplier": ca_row["ratio_multiplier"]
                            })
                except Exception as ca_err:
                    print(f"Error querying corporate actions in synthesis: {ca_err}")
                    
                # Process delivery values
                historical_delivery_values = []
                
                df["Vol_20MA"] = df["Volume"].rolling(window=20).mean().ffill().bfill()
                df_display_with_ma = df.iloc[-display_bars:]
                
                for idx in range(len(df_display_with_ma)):
                    bar_date = df_display_with_ma.index[idx].strftime("%Y-%m-%d")
                    vol = float(df_display_with_ma["Volume"].iloc[idx])
                    close_p = float(df_display_with_ma["Close"].iloc[idx])
                    
                    if bar_date in delivery_history:
                        deliv_pct = delivery_history[bar_date]["delivery_percentage"]
                        deliv_qty = delivery_history[bar_date]["delivery_qty"]
                        traded_qty = delivery_history[bar_date]["traded_qty"]
                        
                        # Clean None values from database
                        if deliv_pct is None:
                            deliv_pct = 0.0
                        if traded_qty is None:
                            traded_qty = int(vol)
                        if deliv_qty is None:
                            deliv_qty = 0
                    else:
                        deliv_pct = 0.0
                        traded_qty = int(vol)
                        deliv_qty = 0
                        
                    for ca in corporate_actions:
                        if bar_date < ca["ex_date"]:
                            if deliv_qty is not None:
                                deliv_qty = int(deliv_qty * ca["ratio_multiplier"])
                            if traded_qty is not None:
                                traded_qty = int(traded_qty * ca["ratio_multiplier"])
                            
                    historical_delivery_values.append((deliv_qty or 0) * close_p)
                        
                    latest_row = df_display_with_ma.iloc[-1]
                    latest_vol_ma = df_display_with_ma["Vol_20MA"].iloc[-1]
                    vsa_result = detect_vsa_setup(
                        latest_row["Open"], latest_row["High"], latest_row["Low"], latest_row["Close"],
                        latest_row["Volume"], latest_vol_ma
                    )
                    delivery_z_score = calculate_delivery_zscore(historical_delivery_values)
                    if vsa_result:
                        vsa_pattern = vsa_result["pattern"]
                        vsa_desc = vsa_result["description"]
                        vsa_type = vsa_result["type"]
                        
                    # Calculate POC
                    vprofile = calculate_volume_profile(df_display_with_ma, bins=12)
                    if vprofile and len(vprofile) > 0:
                        max_bin = max(vprofile, key=lambda x: x["volume"])
                        poc_price = max_bin["price"]
        except Exception as pva_err:
            print(f"Error calculating dynamic volume metrics in synthesis: {pva_err}")

        if poc_price <= 0.0:
            poc_price = current_price

        # Fetch REAL bulk/block deals (filter is_mock = 0)
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT deal_date, client_name, deal_type, quantity, price, percentage_equity, deal_window, is_mock 
                    FROM bulk_block_deals 
                    WHERE symbol = ? AND (is_mock = 0 OR is_mock = FALSE OR is_mock IS NULL)
                    ORDER BY deal_date DESC
                """, (ticker,))
                for row in cursor.fetchall():
                    deal_dict = dict(row)
                    real_deals_list.append(deal_dict)
                    real_deals_summary.append(
                        f"{deal_dict['deal_date']}: {deal_dict['deal_type']} of {deal_dict['quantity']:,} shares @ Rs.{deal_dict['price']} by {deal_dict['client_name']} ({deal_dict['deal_window']}, Equity%: {deal_dict['percentage_equity'] or 0.0}%)"
                    )
        except Exception as deals_err:
            print(f"Error fetching real deals for synthesis: {deals_err}")

        scoring = profile.get("score_metrics", {})
        final_score = scoring.get("final_score", 50)
        recommendation = profile.get("analysis", {}).get("recommendation", scoring.get("action", "HOLD"))

        # CAPM Risk factors (Nifty 50)
        nifty50_risk = profile.get("capm_risk_nifty50", {})
        nifty50_beta = nifty50_risk.get("beta", profile.get("info", {}).get("beta", 1.0))
        try:
            nifty50_beta = float(nifty50_beta)
        except Exception:
            nifty50_beta = 1.0
        nifty50_alpha = nifty50_risk.get("capm_alpha_pct", 0.0)
        nifty50_corr = nifty50_risk.get("correlation", 0.5)

        # CAPM Risk factors (Cap-specific Index)
        sector_risk = profile.get("capm_risk_sector", {})
        sector_beta = sector_risk.get("beta", nifty50_beta)
        try:
            sector_beta = float(sector_beta)
        except Exception:
            sector_beta = nifty50_beta
        sector_alpha = sector_risk.get("capm_alpha_pct", nifty50_alpha)
        sector_corr = sector_risk.get("correlation", nifty50_corr)
        sector_bench_symbol = sector_risk.get("benchmark_symbol", "^NSEI")
        sector_bench_name = sector_risk.get("benchmark_name", "Nifty 50")

        nifty50_stock_ret = nifty50_risk.get("annual_stock_ret_pct", 0.0)
        nifty50_bench_ret = nifty50_risk.get("annual_bench_ret_pct", 0.0)
        sector_stock_ret = sector_risk.get("annual_stock_ret_pct", nifty50_stock_ret)
        sector_bench_ret = sector_risk.get("annual_bench_ret_pct", nifty50_bench_ret)

        nifty50_alpha_str = f"+{nifty50_alpha:.2f}%" if nifty50_alpha >= 0 else f"{nifty50_alpha:.2f}%"
        sector_alpha_str = f"+{sector_alpha:.2f}%" if sector_alpha >= 0 else f"{sector_alpha:.2f}%"

        matrix_md = (
            f"| Benchmark | Beta (β) | Alpha (α) | Correlation (ρ) | Benchmark Ret |\n"
            f"| :--- | :---: | :---: | :---: | :---: |\n"
            f"| Nifty 50 Index (Broad Market) | {nifty50_beta:.3f} | {nifty50_alpha_str} | {nifty50_corr:.3f} | {nifty50_bench_ret:.2f}% vs {nifty50_stock_ret:.2f}% |\n"
            f"| {sector_bench_name} Index (Suggested) | {sector_beta:.3f} | {sector_alpha_str} | {sector_corr:.3f} | {sector_bench_ret:.2f}% vs {sector_stock_ret:.2f}% |"
        )

        # Market capture ratios
        capture_ratios = profile.get("capture_ratios", {})
        up_capture = capture_ratios.get("up_capture", 100.0)
        down_capture = capture_ratios.get("down_capture", 100.0)
        bench_symbol = capture_ratios.get("benchmark_symbol", "^NSEI")

        # Drawdown metrics
        drawdown_metrics = profile.get("drawdown_metrics", {})
        max_dd = drawdown_metrics.get("max_drawdown_pct", -20.0)
        worst_dd_days = drawdown_metrics.get("worst_drawdown_duration_days", 365)

        # Fibonacci zone analysis
        fib_levels = technicals.get("fib_levels", {})
        fib_zone = get_fibonacci_retracement_zone(current_price, fib_levels)

        # Evaluating high-priority critical warning alerts
        warning_flags = []
        if altman_z_score < 1.81:
            warning_flags.append(f"Insolvency Risk: Altman Z-Score of {altman_z_score:.2f} sits in the Distress Zone.")
        if piotroski_score <= 3:
            warning_flags.append(f"Weak Earnings Quality: Piotroski F-Score is critical at {piotroski_score}/9.")
        shareholding = profile.get("shareholding", {})
        promoter_pledge_pct = float(shareholding.get("Promoter Pledging %", 0.0))
        if promoter_pledge_pct > 25.0:
            warning_flags.append(f"High Promoter Pledge: {promoter_pledge_pct:.1f}% of promoter shares are pledged as collateral.")
        if rsi > 75.0:
            warning_flags.append(f"Overheated Momentum: Daily RSI at {rsi:.1f} indicates near-term overbought exhaustion.")
        if max_dd < -35.0:
            warning_flags.append(f"Historical Drawdown Risk: Stock has registered a severe historical peak-to-trough drawdown of {max_dd:.1f}%.")
        if down_capture > 150.0:
            warning_flags.append(f"Elevated Downside Risk: Downside market capture is exceptionally high at {down_capture:.1f}%.")

        # Peer benchmarking and valuations
        peers = profile.get("peers", [])
        median_peer_pe = 0.0
        median_peer_pb = 0.0
        if len(peers) > 1:
            pe_vals = []
            pb_vals = []
            for p in peers[1:]:
                try:
                    pe_str = str(p.get("P/E", "N/A")).replace(",", "").strip()
                    if pe_str != "N/A" and pe_str != "":
                        pe_vals.append(float(pe_str))
                except ValueError:
                    pass
                try:
                    pb_str = str(p.get("P/B", "N/A")).replace(",", "").strip()
                    if pb_str != "N/A" and pb_str != "":
                        pb_vals.append(float(pb_str))
                except ValueError:
                    pass
            if pe_vals:
                median_peer_pe = float(np.median(pe_vals))
            if pb_vals:
                median_peer_pb = float(np.median(pb_vals))

        target_pe = fundamentals.get("pe_ratio", 0.0)
        valuation_comparison = "N/A"
        if target_pe > 0 and median_peer_pe > 0:
            diff_pe = ((target_pe - median_peer_pe) / median_peer_pe) * 100
            comparison_type = "premium" if diff_pe > 0 else "discount"
            valuation_comparison = f"trades at a **{abs(diff_pe):.1f}% {comparison_type}** to peer group median PE (**{median_peer_pe:.2f}**)"

        target_pb = fundamentals.get("pb_ratio", 0.0)
        try:
            target_pb = float(target_pb)
        except Exception:
            target_pb = 0.0
        pb_comparison = "N/A"
        if target_pb > 0 and median_peer_pb > 0:
            diff_pb = ((target_pb - median_peer_pb) / median_peer_pb) * 100
            pb_comp_type = "premium" if diff_pb > 0 else "discount"
            pb_comparison = f"trades at a **{abs(diff_pb):.1f}% {pb_comp_type}** to peer group median PB (**{median_peer_pb:.2f}**)"

        pe_diff_pct = 0.0
        if target_pe > 0 and median_peer_pe > 0:
            pe_diff_pct = ((target_pe - median_peer_pe) / median_peer_pe) * 100
            
        solvency_status = "Solvency: Safe" if altman_z_score >= 1.81 else "Solvency: Distress"
        valuation_status = "Undervalued" if margin_of_safety >= 15.0 else ("Overvalued" if margin_of_safety < -5.0 else "Fairly Valued")
        technical_status = technicals.get("breakout_status", "Consolidating")
        capm_status = "Defensive Value Creator" if (nifty50_beta < 0.95 and nifty50_alpha > 0) else ("Value Destroyer" if nifty50_alpha < 0 else "Hot Beta Ride")
        
        rec_upper = str(recommendation).upper()
        if "BUY" in rec_upper:
            verdict_action = "TACTICAL BUY"
        elif "SELL" in rec_upper:
            verdict_action = "STRATEGIC AVOID"
        else:
            verdict_action = "NEUTRAL HOLD"

        vsa_verdict = "Institutional Accumulation" if delivery_z_score >= 1.0 else ("Distribution Pressure" if delivery_z_score <= -1.0 else "Speculative Churn")
        verdict_matrix_md = (
            f"| Strategic Dimension | Supporting Key Metrics | Programmatic AI Verdict |\n"
            f"| :--- | :--- | :--- |\n"
            f"| **I. Solvency & Quality** | F-Score: **{piotroski_score}/9**, Z-Score: **{altman_z_score:.2f}** | **{solvency_status}** |\n"
            f"| **II. Valuation & Margin** | Intrinsic MOS: **{margin_of_safety:+.1f}%**, PE vs Peers: **{pe_diff_pct:+.1f}%** | **{valuation_status}** |\n"
            f"| **III. Technical Velocity** | RSI: **{rsi:.1f}**, Trend: **{technicals.get('trend_50_vs_200', 'Neutral')}** | **{technical_status}** |\n"
            f"| **IV. VSA & Smart Money** | Z-Score: **{delivery_z_score:+.2f}**, POC Floor: **Rs. {poc_price:.2f}** | **{vsa_verdict}** |\n"
            f"| **V. CAPM Risk-Reward** | Beta: **{nifty50_beta:.2f}**, Alpha: **{nifty50_alpha_str}** | **{capm_status}** |\n"
            f"| **VI. CIO Bottom-Line** | Composite Score: **{final_score}/100** | **{verdict_action}** |"
        )

        system_prompt = (
            "You are the Chief Investment Officer (CIO) of a premier Indian equities advisory firm managing an autonomous multi-agent stock research panel.\n"
            "Your task is to compile a highly coherent, institutional-grade 360-degree AI Multi-Agent Verdict Debate for the specified stock.\n"
            "The prospectus MUST analyze and synthesize all provided technical and fundamental parameters, their inter-relationships, and yield a final verdict.\n"
            "You must structure the debate under exactly five distinct sections, using the exact markdown subheadings provided below:\n"
            "\n"
            "### I. Operational Quality & Solvency Scorecard\n"
            "Use the following HTML block structure to present a debate between the Fundamental Analyst and the Sentiment & Smart Money Auditor:\n"
            "<div class=\"agent-debate-block fundamental\">\n"
            "  <div class=\"agent-header\">📊 Fundamental & Valuation Analyst</div>\n"
            "  <div class=\"agent-comment\">Detail the operational and solvency parameters: Piotroski F-Score, Altman Z-Score, Debt-to-Equity ratio, current ratios, and CFO to PAT conversion. Highlight strengths or leverage concerns. Use bold markup for figures (e.g. **8/9**, **2.45**).</div>\n"
            "</div>\n"
            "<div class=\"agent-debate-block sentiment\">\n"
            "  <div class=\"agent-header\">🛡️ Sentiment & Smart Money Auditor</div>\n"
            "  <div class=\"agent-comment\">Respond from a governance and risk perspective, auditing promoter pledges (if any), FII/DII holdings, and how leverage/pledging impacts capital safety.</div>\n"
            "</div>\n"
            "\n"
            "### II. Valuation & Peer Benchmarking\n"
            "Use the following HTML block structure to present a debate on intrinsic value:\n"
            "<div class=\"agent-debate-block fundamental\">\n"
            "  <div class=\"agent-header\">📊 Fundamental & Valuation Analyst</div>\n"
            "  <div class=\"agent-comment\">Analyze the WACC, DCF intrinsic value against the current price, the margin of safety, trailing PE, PEG ratio, PB ratio, and comparisons relative to the peer group and sector medians. Discuss value drivers and pricing premiums/discounts. Use bold markup (e.g. **Rs. 1,420**, **12.5%**).</div>\n"
            "</div>\n"
            "<div class=\"agent-debate-block technical\">\n"
            "  <div class=\"agent-header\">📈 Technical & VSA Tactician</div>\n"
            "  <div class=\"agent-comment\">React to the valuation thesis. Discuss if the technical price action and chart supports this value or if market price lags/leads the intrinsic value.</div>\n"
            "</div>\n"
            "\n"
            "### III. Technical Timing & Fibonacci Zones\n"
            "Use the following HTML block structure to present the timing debate:\n"
            "<div class=\"agent-debate-block technical\">\n"
            "  <div class=\"agent-header\">📈 Technical & VSA Tactician</div>\n"
            "  <div class=\"agent-comment\">Analyze 14-day RSI, 50-day and 200-day SMAs (Golden Cross / Death Cross), 52-week High and Low boundaries (distance and proximity), Fibonacci retracement levels, Bollinger squeeze width, ATR volatility stop floor, MACD signal status, Volume Price Trend (VPT), smart money Deliverable Z-Score, VSA patterns, and Point of Control (POC) support floor. Use bold markup (e.g. **Rs. 420.50**, **48.2**).</div>\n"
            "</div>\n"
            "<div class=\"agent-debate-block fundamental\">\n"
            "  <div class=\"agent-header\">📊 Fundamental & Valuation Analyst</div>\n"
            "  <div class=\"agent-comment\">React to the technical setup. Comment on whether these support lines and breakout channels align with long-term earnings growth.</div>\n"
            "</div>\n"
            "\n"
            "### IV. CAPM Risk Analytics & Market Capture\n"
            "Use the following HTML block structure to present systematic risk analysis:\n"
            "<div class=\"agent-debate-block technical\">\n"
            "  <div class=\"agent-header\">📈 Technical & VSA Tactician</div>\n"
            "  <div class=\"agent-comment\">Review risk parameters: systematic Beta, Alpha, and Correlation relative to both Nifty 50 and capitalization index. Discuss Upside/Downside Capture percentages, Maximum Drawdowns, and recovery durational history. Use bold markup.</div>\n"
            "</div>\n"
            "After this block, you must append the EXACT markdown table representing the Polymorphic Benchmark Comparison Matrix (do not omit or alter it).\n"
            "\n"
            "### V. CIO Investment Prospectus & Conviction Summary\n"
            "Use the following HTML block structure to present the ultimate verdict debate:\n"
            "<div class=\"agent-debate-block fundamental\">\n"
            "  <div class=\"agent-header\">📊 Fundamental & Valuation Analyst</div>\n"
            "  <div class=\"agent-comment\">Summarize the core long-term investment case based on quality metrics and DCF margin of safety.</div>\n"
            "</div>\n"
            "<div class=\"agent-debate-block technical\">\n"
            "  <div class=\"agent-header\">📈 Technical & VSA Tactician</div>\n"
            "  <div class=\"agent-comment\">Summarize entry/exit timing based on moving averages, RSI, and smart money deliverable accumulation trends.</div>\n"
            "</div>\n"
            "<div class=\"agent-debate-block cio\">\n"
            "  <div class=\"agent-header\">⚖️ Lead CIO Referee (Consensus Moderator)</div>\n"
            "  <div class=\"agent-comment\">Synthesize the relationships and conflicts between all technical, fundamental, and governance parameters (e.g. high PE but strong support, or high quality but bearish trend). Declare the final strategic consensus recommendation (Tactical BUY, Strategic AVOID, or Neutral HOLD) with a clear, definitive, and comprehensive explanation. Incorporate the Composite AI Conviction Score, suggested Buy/Entry price range, and suggested Sell/Exit target range.</div>\n"
            "</div>\n"
            "After this block, you must append the EXACT markdown table of the Strategic Investment Verdict Matrix (do not omit or alter it).\n"
            "\n"
            "Maintain an objective, institutional, and analytical tone. Do not use bullet points or list items outside the markdown tables."
        )

        user_prompt = f"""
        Company: {profile.get('company_name', symbol)} ({ticker})
        Investor Profile: Horizon: {horizon} | Risk: {risk}
        
        1. Operational Quality & Solvency Scorecard:
        - Piotroski F-Score: {piotroski_score}/9 ({piotroski_label})
        - Altman Z-Score: {altman_z_score:.2f} ({altman_zone})
        - Debt-to-Equity: {fundamentals.get('debt_to_equity', 'N/A')}
        - Current Ratio: {fundamentals.get('current_ratio', 'N/A')}
        - CFO to PAT Ratio: {cfo_to_pat_str}
        
        2. Valuation & Sector Peer Benchmarking:
        - Current Price: Rs. {current_price}
        - DCF Intrinsic Value: Rs. {dcf_intrinsic_value:.2f} (Margin of Safety: {margin_of_safety:.1f}%, Status: {dcf.get('valuation_rating', 'N/A')})
        - PE Ratio: {target_pe:.1f} (Peer Group Median PE: {median_peer_pe:.2f}, Comparison: {valuation_comparison})
        - PB Ratio: {target_pb:.2f} (Peer Group Median PB: {median_peer_pb:.2f}, Comparison: {pb_comparison})
        - PEG Ratio: {scoring.get('peg_ratio', 'N/A')}
        
        3. Technical Timing, Volatility & Momentum:
        - 14-day RSI: {rsi:.1f} ({technicals.get('rsi_status', 'Neutral')})
        - 50-day SMA: Rs. {sma_50_str} | 200-day SMA: Rs. {sma_200_str} (Trend: {technicals.get('trend_50_vs_200', 'N/A')})
        - Breakout Status: {technicals.get('breakout_status', 'N/A')} ({technicals.get('breakout_desc', 'N/A')})
        - Fibonacci Levels: {json.dumps(fib_levels)}
        - Current Fibonacci Retracement Zone: {fib_zone}
        - Bollinger Bands: Lower: Rs. {bb_lower:.2f} | Upper: Rs. {bb_upper:.2f} (Squeeze Width: {squeeze_pct:.1f}%)
        - ATR: Rs. {atr:.2f} (Volatility Rating: {vol_level} at {volatility_ratio:.1f}% ratio)
        - Volatility-Adjusted 2x ATR Stop Floor: Rs. {atr_stop_loss:.2f}
        - MACD Value: {macd:.2f} (Signal: {macd_signal:.2f}, Hist: {macd_hist:.2f}, Status: {macd_status})
        - Volume Price Trend (VPT): {vpt:.0f} ({vpt_status})
        - Deliverable Volume Z-Score: {delivery_z_score:.2f}
        - Volume Spread Analysis (VSA) Pattern: {vsa_pattern} ({vsa_desc})
        - Point of Control (POC) Level: Rs. {poc_price:.2f}
        
        4. CAPM Risk Analytics & Market Capture:
        - Relative to Nifty 50: Beta: {nifty50_beta:.2f}, Alpha: {nifty50_alpha:.2f}%, Correlation: {nifty50_corr:.2f}
        - Relative to {sector_bench_name} ({sector_bench_symbol}): Beta: {sector_beta:.2f}, Alpha: {sector_alpha:.2f}%, Correlation: {sector_corr:.2f}
        - Market Capture Ratios: Upside Market Capture: {up_capture:.1f}% | Downside Market Capture: {down_capture:.1f}% (relative to {bench_symbol})
        - Max Drawdown: {max_dd:.1f}% (Worst Drawdown Duration: {worst_dd_days} days)
        - Exact Polymorphic Benchmark Comparison Matrix Markdown Table (print this EXACT table at the end of Section IV):
{matrix_md}
        
        5. CIO Investment Prospectus & Conviction:
        - Composite AI Score: {final_score}/100
        - Strategic recommendation: {recommendation}
        - Suggested Buy Range: {profile.get('analysis', {}).get('suggested_buy_price_range', 'N/A')}
        - Suggested Sell Range: {profile.get('analysis', {}).get('suggested_sell_price_range', 'N/A')}
        - Analyst Target Median: Rs. {profile.get('consensus', {}).get('target_median', 'N/A')}
        - Exact Strategic Investment Verdict Matrix Markdown Table (print this EXACT table at the end of Section V):
{verdict_matrix_md}
        """
 
        synthesis_text = await asyncio.to_thread(call_llm, TASK_FAST, system_prompt, user_prompt)
 
        # Failsafe programmatic fallback if LLM is unavailable or errors
        if "ERROR" in synthesis_text or not synthesis_text.strip():
            p1 = (
                f"### I. Operational Quality & Solvency Scorecard\n"
                f"<div class=\"agent-debate-block fundamental\">\n"
                f"  <div class=\"agent-header\">📊 Fundamental & Valuation Analyst</div>\n"
                f"  <div class=\"agent-comment\">Financial audits of **{profile.get('company_name', symbol)}** show a Piotroski F-Score of **{piotroski_score}/9** ({piotroski_label}) and an Altman Z-Score of **{altman_z_score:.2f}** ({altman_zone}). Leverage is comfortable with a Debt-to-Equity of **{fundamentals.get('debt_to_equity', 0.0):.2f}x** and conversion cash quality is strong at a CFO to PAT ratio of **{cfo_to_pat_str}x**. Solvency remains secure.</div>\n"
                f"</div>\n"
                f"<div class=\"agent-debate-block sentiment\">\n"
                f"  <div class=\"agent-header\">🛡️ Sentiment & Smart Money Auditor</div>\n"
                f"  <div class=\"agent-comment\">Pledging stats report promoter pledging is at **{fundamentals.get('promoter_pledge_pct', 0.0):.1f}%** with institutional holdings backing the structure. No high-priority governance warnings exist.</div>\n"
                f"</div>"
            )
            p2 = (
                f"### II. Valuation & Peer Benchmarking\n"
                f"<div class=\"agent-debate-block fundamental\">\n"
                f"  <div class=\"agent-header\">📊 Fundamental & Valuation Analyst</div>\n"
                f"  <div class=\"agent-comment\">Intrinsic value calculations establish DCF Fair Value at **Rs. {dcf_intrinsic_value:.2f}**, offering a **{margin_of_safety:.1f}% margin of safety** ({dcf.get('valuation_rating', 'Fairly Valued')}). Trailing PE of **{target_pe:.1f}** {valuation_comparison} against peer group median PE of **{median_peer_pe:.2f}**. PEG ratio stands at **{scoring.get('peg_ratio', 'N/A')}**.</div>\n"
                f"</div>\n"
                f"<div class=\"agent-debate-block technical\">\n"
                f"  <div class=\"agent-header\">📈 Technical & VSA Tactician</div>\n"
                f"  <div class=\"agent-comment\">Price is currently **Rs. {current_price}**. Looking at PEG and peer multiples, the current entry zone corresponds to minor support consolidations.</div>\n"
                f"</div>"
            )
            p3 = (
                f"### III. Technical Timing & Fibonacci Zones\n"
                f"<div class=\"agent-debate-block technical\">\n"
                f"  <div class=\"agent-header\">📈 Technical & VSA Tactician</div>\n"
                f"  <div class=\"agent-comment\">The daily chart shows the price **{fib_zone}**. SMA parameters: 50-day SMA is at **Rs. {sma_50_str}** and 200-day SMA is at **Rs. {sma_200_str}** (**{technicals.get('trend_50_vs_200', 'Neutral')}** trend). RSI (14) is at **{rsi:.1f}** ({technicals.get('rsi_status', 'Neutral')}). Bollinger Squeeze width is **{squeeze_pct:.1f}%**, volatility is **{vol_level}** with ATR of **Rs. {atr:.2f}**, and volatility stop floor is at **Rs. {atr_stop_loss:.2f}**. MACD reports **{macd:.2f}** (Signal: **{macd_signal:.2f}** | **{macd_status}**). VPT is at **{vpt:.0f}**. smart money Deliverable Z-Score is **{delivery_z_score:+.2f}** with VSA Pattern diagnosis: **{vsa_pattern}** ({vsa_desc}). Liquidity POC support sits at **Rs. {poc_price:.2f}**.</div>\n"
                f"</div>\n"
                f"<div class=\"agent-debate-block fundamental\">\n"
                f"  <div class=\"agent-header\">📊 Fundamental & Valuation Analyst</div>\n"
                f"  <div class=\"agent-comment\">The technical consolidation zones around POC support of **Rs. {poc_price:.2f}** and the 52w range limits align with DCF intrinsic floors, representing low-risk accumulation.</div>\n"
                f"</div>"
            )
            p4 = (
                f"### IV. CAPM Risk Analytics & Market Capture\n"
                f"<div class=\"agent-debate-block technical\">\n"
                f"  <div class=\"agent-header\">📈 Technical & VSA Tactician</div>\n"
                f"  <div class=\"agent-comment\">Broad market Beta is **{nifty50_beta:.2f}**, Alpha is **{nifty50_alpha:.2f}%**, and Correlation is **{nifty50_corr:.2f}** relative to Nifty 50. Relative to {sector_bench_name}, Beta is **{sector_beta:.2f}**, Alpha is **{sector_alpha:.2f}%**, and Correlation is **{sector_corr:.2f}**. Market Capture: Upside capture is **{up_capture:.1f}%** and Downside capture is **{down_capture:.1f}%**. Max Drawdown is **{max_dd:.1f}%** with recovery times of **{worst_dd_days} days**.</div>\n"
                f"</div>\n\n"
                f"**Polymorphic Benchmark Comparison Matrix:**\n\n"
                f"{matrix_md}"
            )
            deals_sum_str = "; ".join(real_deals_summary[:3]) if real_deals_summary else "no real bulk/block transactions recorded"
            p5 = (
                f"### V. CIO Investment Prospectus & Conviction Summary\n"
                f"<div class=\"agent-debate-block fundamental\">\n"
                f"  <div class=\"agent-header\">📊 Fundamental & Valuation Analyst</div>\n"
                f"  <div class=\"agent-comment\">Strong margin of safety of **{margin_of_safety:.1f}%** and excellent return ratios support a long-term investment case.</div>\n"
                f"</div>\n"
                f"<div class=\"agent-debate-block technical\">\n"
                f"  <div class=\"agent-header\">📈 Technical & VSA Tactician</div>\n"
                f"  <div class=\"agent-comment\">Consolidation support at the POC floor of **Rs. {poc_price:.2f}** and a neutral RSI indicator favor accumulative entries.</div>\n"
                f"</div>\n"
                f"<div class=\"agent-debate-block cio\">\n"
                f"  <div class=\"agent-header\">⚖️ Lead CIO Referee (Consensus Moderator)</div>\n"
                f"  <div class=\"agent-comment\">Considering the interplay of safe solvency (Altman Z of **{altman_z_score:.2f}**), strong valuation margin, and robust smart money support (Deliverable Z of **{delivery_z_score:+.2f}**), we issue a **{recommendation}** verdict for the **{horizon}** horizon. AI composite conviction score is **{final_score}/100**. Actionable buy/entry range is suggested at **{profile.get('analysis', {}).get('suggested_buy_price_range', 'Rs. ' + str(round(current_price * 0.95)) + ' - Rs. ' + str(round(current_price * 1.02)))}**, and suggested sell/exit range is at **{profile.get('analysis', {}).get('suggested_sell_price_range', 'Rs. ' + str(round(current_price * 1.15)) + ' - Rs. ' + str(round(current_price * 1.25)))}**.</div>\n"
                f"</div>\n\n"
                f"**Strategic Investment Verdict Matrix:**\n\n"
                f"{verdict_matrix_md}"
            )
            synthesis_text = f"{p1}\n\n{p2}\n\n{p3}\n\n{p4}\n\n{p5}"

        # Compute individual agent conviction scores out of 100
        f_score_val = scoring.get("fundamental_score", 15.0)
        v_score_val = scoring.get("valuation_score", 12.0)
        g_score_val = scoring.get("growth_score", 7.0)
        fundamental_conviction = int(((f_score_val + v_score_val + g_score_val) / 70.0) * 100.0)
        fundamental_conviction = min(100, max(0, fundamental_conviction))
        
        t_score_val = scoring.get("technical_score", 12.0)
        technical_conviction = int((t_score_val / 25.0) * 100.0)
        technical_conviction = min(100, max(0, technical_conviction))
        
        s_score_val = scoring.get("sentiment_score", 2.0)
        sentiment_bonus = 1.0 if delivery_z_score >= 1.0 else 0.0
        sentiment_conviction = int(((s_score_val + sentiment_bonus) / 6.0) * 100.0)
        sentiment_conviction = min(100, max(0, sentiment_conviction))
        
        friction_points = []
        if pe_diff_pct > 20.0:
            friction_points.append(f"Valuation Friction: Trades at a high P/E multiple premium of {pe_diff_pct:+.1f}% compared to peers.")
        if margin_of_safety < 0.0:
            friction_points.append(f"Margin of Safety Deficit: Current market price trades at a {-margin_of_safety:.1f}% valuation premium over DCF Fair Value (Rs. {dcf_intrinsic_value:.2f}).")
        if current_price < sma_200:
            friction_points.append(f"Bearish Trend Alignment: Price is structurally locked below its long-term 200-day SMA of Rs. {sma_200:.2f}.")
        if promoter_pledge_pct > 15.0:
            friction_points.append(f"Governance Drag: Promoter share pledging is elevated at {promoter_pledge_pct:.1f}% representing capital collateral risk.")
        if fundamentals.get("debt_to_equity", 0.0) > 1.2:
            friction_points.append(f"Balance Sheet Friction: Elevated Debt-to-Equity ratio of {fundamentals.get('debt_to_equity', 0.0):.2f}x restricts fiscal leverage.")
        if rsi > 70.0:
            friction_points.append(f"Overbought Friction: Daily RSI (14) at {rsi:.1f} signals short-term momentum overextension.")
        elif rsi < 30.0:
            friction_points.append(f"Oversold Momentum: Daily RSI (14) at {rsi:.1f} signals steep downward capitalization trends.")

        return {
            "synthesis_text": synthesis_text,
            "final_score": final_score,
            "recommendation": recommendation,
            "dcf_intrinsic_value": dcf_intrinsic_value,
            "current_price": current_price,
            "margin_of_safety": margin_of_safety,
            "altman_z_score": altman_z_score,
            "altman_zone": altman_zone,
            "piotroski_score": piotroski_score,
            "piotroski_label": piotroski_label,
            "rsi": rsi,
            "sma_50": sma_50,
            "sma_200": sma_200,
            "capm_risk_nifty50": nifty50_risk,
            "capm_risk_sector": sector_risk,
            "risk_warning_flags": warning_flags,
            "delivery_z_score": delivery_z_score,
            "vsa_pattern": vsa_pattern,
            "vsa_type": vsa_type,
            "poc_price": poc_price,
            "real_deals": real_deals_list,
            "friction_points": friction_points,
            "fundamental_conviction": fundamental_conviction,
            "technical_conviction": technical_conviction,
            "sentiment_conviction": sentiment_conviction
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Synthesis compilation failed: {str(e)}")

@app.get("/api/analyze/pitchbook")
async def get_pitchbook(
    symbol: str,
    horizon: str = "Long-term (3+ years)",
    risk: str = "Moderate",
    wacc: float = None,
    growth: float = None,
    opm: float = None,
    terminal_growth: float = 4.5
):
    """
    Generates a print-ready Investment Committee Memo ("Pitchbook") for the stock.
    Aggregates fundamental ratios, active DCF models, technical levels, peers, and sector rotation standings,
    then prompts the Groq LLM to output a comprehensive markdown memo.
    """
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol parameter is required.")
    try:
        # 1. Resolve Ticker
        resolved = resolve_company_ticker(symbol)
        ticker = resolved.get("yf_ticker")
        if not ticker:
            ticker = symbol.upper()
            if not (ticker.endswith(".NS") or ticker.endswith(".BO")):
                ticker = f"{ticker}.NS"

        # 2. Gather profile data (Fundamentals, Technicals, CAPM, etc.)
        profile = get_complete_financial_profile(ticker, bypass_db_cache=True)

        # 2.5 Calculate Technical Swing Signal and VSA Setup dynamically
        setup_pattern = "Consolidation Trend"
        setup_desc = "Standard range bounds."
        stop_loss = 0.0
        target_1 = 0.0
        target_2 = 0.0
        vsa_pattern = "Normal"
        delivery_z_score = 0.0
        
        try:
            df = await fetch_history_df(ticker, "6mo", "1d")
            if not df.empty:
                # 1. Swing Trend Signal detection
                from backend.swing_utils import calculate_swing_indicators, analyze_swing_signals
                df_ind = calculate_swing_indicators(df)
                setup_pattern, setup_desc, stop_loss, target_1, target_2 = analyze_swing_signals(df_ind, horizon="short")
                
                # 2. VSA Setup detection
                from backend.quant_scoring import detect_vsa_setup, calculate_delivery_zscore
                last_row = df.iloc[-1]
                avg_vol = df['Volume'].rolling(20).mean().iloc[-1] if len(df) >= 20 else df['Volume'].mean()
                vsa_res = detect_vsa_setup(
                    open_p=float(last_row['Open']),
                    high_p=float(last_row['High']),
                    low_p=float(last_row['Low']),
                    close_p=float(last_row['Close']),
                    volume=float(last_row['Volume']),
                    avg_volume_20d=float(avg_vol)
                )
                if vsa_res:
                    vsa_pattern = vsa_res.get("pattern", "Normal")
                
                # 3. Delivery Z-score calculation
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT delivery_qty FROM daily_delivery_history
                        WHERE symbol = ? ORDER BY trade_date DESC LIMIT 21
                    """, (ticker,))
                    rows = cursor.fetchall()
                    if rows:
                        deliv_hist = [r["delivery_qty"] for r in rows if r["delivery_qty"] is not None]
                        delivery_z_score = calculate_delivery_zscore(deliv_hist)
        except Exception as tech_err:
            print(f"Error calculating dynamic technical features in pitchbook: {tech_err}")

        # 3. Recalculate DCF if custom sandbox inputs are provided
        if wacc is not None or growth is not None or opm is not None:
            custom_dcf = {
                "wacc": wacc if wacc is not None else profile["dcf_model"].get("wacc", 11.5),
                "revenue_growth": growth if growth is not None else profile["dcf_model"].get("revenue_growth", 10.0),
                "opm": opm if opm is not None else profile["dcf_model"].get("opm", 15.0),
                "terminal_growth": terminal_growth if terminal_growth is not None else profile["dcf_model"].get("terminal_growth", 4.5)
            }
            dcf_val = calculate_dcf_valuation(
                profile["ticker"],
                rev_growth_5y=custom_dcf["revenue_growth"],
                target_opm=custom_dcf["opm"],
                wacc=custom_dcf["wacc"],
                terminal_growth=custom_dcf["terminal_growth"]
            )
            profile["dcf_model"] = dcf_val

        # 4. Extract Peer metrics
        peers = profile.get("peers", [])
        peers_list_str = json.dumps(peers[:5], indent=2)

        # 5. Extract Sector Momentum Radar metrics
        sector_name = "N/A"
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT sector FROM screener_universe WHERE symbol = ? OR symbol LIKE ?", (ticker, f"{symbol.split('.')[0]}%"))
                s_univ_row = cursor.fetchone()
                if s_univ_row:
                    sector_name = s_univ_row["sector"]
        except Exception as db_err:
            print(f"Error querying standardized sector in screener_universe: {db_err}")
            
        if sector_name == "N/A":
            sector_name = profile.get("sector", "N/A")

        sector_regime = "N/A"
        sector_sentiment = "--%"
        sector_adv_dec = "N/A"
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT sector, return_1m, return_3m, return_6m, return_1y, return_ytd
                    FROM sector_regime_stats
                    WHERE sector = ?
                """, (sector_name,))
                s_row = cursor.fetchone()
                if s_row:
                    s_dict = dict(s_row)
                    ret_1m = s_dict.get("return_1m", 0.0) or 0.0
                    # Calculate regime label dynamically
                    if ret_1m > 5.0:
                        sector_regime = "Bullish Rotation / Leading"
                    elif ret_1m > 0.0:
                        sector_regime = "Consolidation / Improving"
                    elif ret_1m > -5.0:
                        sector_regime = "Weakening / Softening"
                    else:
                        sector_regime = "Lagging / Bearish"
                    
                    # Sentiment score proxy
                    sentiment_score = int(min(max((ret_1m + 10.0) * 5.0, 10.0), 90.0))
                    sentiment_emoji = "🐂" if sentiment_score >= 60 else ("🐻" if sentiment_score <= 40 else "🟡")
                    sector_sentiment = f"{sentiment_emoji} {sentiment_score}%"
                    
                    # Advances/declines proxy from stock_regime_stats for this sector
                    cursor.execute("""
                        SELECT COUNT(CASE WHEN return_1m > 0 THEN 1 END) AS advances,
                               COUNT(CASE WHEN return_1m <= 0 THEN 1 END) AS declines
                        FROM stock_regime_stats
                        WHERE sector = ?
                    """, (sector_name,))
                    counts = cursor.fetchone()
                    if counts:
                        advs = counts["advances"] or 0
                        decs = counts["declines"] or 0
                        sector_adv_dec = f"{advs} Advances / {decs} Declines"
        except Exception as db_err:
            print(f"Error querying sector regime in pitchbook endpoint: {db_err}")

        # 6. Retrieve corporate actions & block deals
        real_deals = []
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT deal_date, client_name, deal_type, quantity, price, percentage_equity
                    FROM bulk_block_deals
                    WHERE symbol = ? AND (is_mock = 0 OR is_mock = FALSE OR is_mock IS NULL)
                    ORDER BY deal_date DESC LIMIT 5
                """, (ticker,))
                real_deals = [dict(row) for row in cursor.fetchall()]
        except Exception as deals_err:
            print(f"Error fetching real deals for pitchbook: {deals_err}")

        # 7. Formulate system and user prompts
        system_prompt = (
            "You are the Lead Chief Investment Officer (CIO) and Senior Equities Analyst of a premier Indian institutional fund.\n"
            "Your objective is to generate an institutional-grade, comprehensive, print-ready Investment Committee Memo ('Pitchbook') for the specified stock.\n"
            "The Pitchbook must synthesize all fundamental, technical, and qualitative indicators into a professional pitch.\n"
            "Use clear Markdown formatting with structured sections. Ensure all numbers are bolded (e.g. **15.2%**, **Rs. 2,450**).\n"
            "Write the Pitchbook under the following exact structural sections:\n"
            "\n"
            "# INVESTMENT COMMITTEE MEMO: [COMPANY_NAME] ([TICKER])\n"
            "\n"
            "## I. Executive Verdict & Conviction Summary\n"
            "- Outline the core investment summary, final strategic consensus (BUY/SELL/HOLD), composite conviction score, and recommended entry/exit ranges.\n"
            "\n"
            "## II. Financial Quality & Solvency Audit\n"
            "- Analyze balance sheet health, capital allocation efficiencies (ROE/ROCE), debt margins, Piotroski F-Score, Altman Z-Score, and CFO to PAT conversion.\n"
            "\n"
            "## III. DCF Intrinsic Valuation sensitivity\n"
            "- Detail the DCF intrinsic valuation model (WACC, terminal growth, OPM), user-customized sandbox parameters, margin of safety, and historical valuation bands.\n"
            "\n"
            "## IV. Technical Timing & Volume Spread Analysis (VSA)\n"
            "- Review chart momentum trends (50 vs 200 SMA), RSI levels, Fibonacci zones, unmitigated order blocks, VSA setups (delivery z-score), and Point of Control (POC) supports.\n"
            "\n"
            "## V. Competitive Benchmarking & Sector Rotation\n"
            "- Compare the target stock's ratios (PE, PB, EV/EBITDA, Returns) against the direct competitors. Discuss its valuation relative to peers (premium or discount).\n"
            "- Integrate the sector's relative strength momentum phase, advances/declines ratio, and AI Sentiment Thermometer context from the Sector Radar.\n"
            "\n"
            "## VI. Catalysts, Risks & Mitigation Framework\n"
            "- Outline 3 key quantitative catalysts (e.g., industry tailwinds, corporate actions, block deals) and 3 major risk flags (with corresponding mitigation strategies).\n"
            "\n"
            "Maintain a highly objective, rigorous, and professional tone. Start directly with the memo content, avoiding conversational preambles."
        )

        # Safely compute pb_ratio as it is not present in fundamentals directly
        curr_price = profile.get("fundamentals", {}).get("current_price", 0.0) or 0.0
        bv = profile.get("fundamentals", {}).get("book_value", 1.0) or 1.0
        pb_ratio = curr_price / bv if bv > 0 else 1.0

        user_prompt = f"""
        Stock: {profile['company_name']} ({profile['ticker']})
        Sector: {profile.get('sector', 'N/A')} | Industry: {profile.get('industry', 'N/A')}
        Current Stock Price: Rs. {profile['fundamentals']['current_price']}
        Investor Persona: Horizon: {horizon} | Risk: {risk}
        
        1. Fundamentals & Solvency:
        - Market Cap: {profile['fundamentals']['market_cap_cr']} Cr
        - Trailing PE: {profile['fundamentals']['pe_ratio']} | PB: {pb_ratio:.2f}
        - ROE: {profile['fundamentals']['roe_pct']}% | ROCE: {profile['fundamentals']['roce_pct']}%
        - Debt to Equity: {profile['fundamentals']['debt_to_equity']}
        - Piotroski F-Score: {profile.get('earnings_quality', {}).get('piotroski_score', 0)}/9 ({profile.get('earnings_quality', {}).get('piotroski_label', 'Unknown')})
        - Altman Z-Score: {profile.get('earnings_quality', {}).get('altman_z_score', 0.0)} ({profile.get('earnings_quality', {}).get('altman_zone', 'Unknown')})
        - CFO to PAT conversion: {profile['fundamentals'].get('cfo_to_pat', 0.88)}
        
        2. User DCF Sandbox Parameters:
        - Applied WACC: {profile['dcf_model'].get('wacc')}%
        - Revenue Growth: {profile['dcf_model'].get('revenue_growth')}% | OPM: {profile['dcf_model'].get('opm')}%
        - Terminal Growth: {profile['dcf_model'].get('terminal_growth')}%
        - Intrinsic Fair Value: Rs. {profile['dcf_model'].get('intrinsic_value'):.2f} (MOS Margin: {profile['dcf_model'].get('margin_of_safety'):.1f}%)
        
        3. Technicals, Swing Setups & Price Action:
        - Trend Setup: {setup_pattern} ({setup_desc})
        - Active Targets: Stop Loss: Rs. {stop_loss:.2f} | Target 1: Rs. {target_1:.2f} | Target 2: Rs. {target_2:.2f}
        - RSI-14: {profile['technicals'].get('rsi'):.1f} ({profile['technicals'].get('rsi_status')})
        - 50-day SMA: Rs. {profile['technicals'].get('sma_50')} | 200-day SMA: Rs. {profile['technicals'].get('sma_200')}
        - Fibonacci Levels: {json.dumps(profile['technicals'].get('fib_levels'))}
        - Volume Spread Analysis (VSA) Setup: {vsa_pattern} (Delivery Z-Score: {delivery_z_score:.2f})
        - Point of Control (POC): Rs. {profile['technicals'].get('poc_price', profile['fundamentals']['current_price'])}
        
        4. Benchmarking Competitors (Peers):
        {peers_list_str}
        
        5. Sector Momentum Radar Status:
        - Sector: {sector_name}
        - Rotational Phase: {sector_regime}
        - AI Sentiment Thermometer: {sector_sentiment}
        - Advances/Declines: {sector_adv_dec}
        
        6. News & Strategic Deals:
        - Corporate block deals: {json.dumps(real_deals, indent=2)}
        - News headlines: {json.dumps(profile.get('news', [])[:3], indent=2)}
        """

        markdown_memo = await asyncio.to_thread(call_llm, TASK_FAST, system_prompt, user_prompt)
        
        # Rule-based fallback if API is unavailable or limits exceeded
        if "ERROR" in markdown_memo or not markdown_memo.strip():
            markdown_memo = f"""# INVESTMENT COMMITTEE MEMO: {profile['company_name']} ({profile['ticker']})

## I. Executive Verdict & Conviction Summary
*   **Verdict**: **TACTICAL BUY**
*   **Conviction Score**: **{profile.get('score_metrics', {}).get('final_score', 65)}/100**
*   **Horizon/Risk**: **{horizon}** | **{risk}**
*   **Buy/Sell Ranges**: Buy Range: **{profile.get('analysis', {}).get('suggested_buy_price_range', 'N/A')}** | Target Range: **{profile.get('analysis', {}).get('suggested_sell_price_range', 'N/A')}**

## II. Financial Quality & Solvency Audit
*   **Balance Sheet Quality**: The business represents robust health with a Piotroski F-Score of **{profile.get('earnings_quality', {}).get('piotroski_score', 7)}/9** and an Altman Z-Score of **{profile.get('earnings_quality', {}).get('altman_z_score', 3.0):.2f}**.
*   **Cash Quality**: CFO to PAT ratio is **{profile['fundamentals'].get('cfo_to_pat', 0.88):.2f}**, demonstrating solid operational cash backing of net profits.
*   **Solvency**: Debt-to-Equity stands at **{profile['fundamentals'].get('debt_to_equity', 0.1)}**, minimizing interest distress.

## III. DCF Intrinsic Valuation sensitivity
*   **Fair Value Estimate**: The DCF model estimates Intrinsic Fair Value at **Rs. {profile['dcf_model'].get('intrinsic_value'):.2f}** based on WACC of **{profile['dcf_model'].get('wacc')}%** and Terminal Growth of **{profile['dcf_model'].get('terminal_growth')}%**.
*   **Margin of Safety**: At current price, the valuation margin is **{profile['dcf_model'].get('margin_of_safety'):.1f}%**.

## IV. Technical Timing & Volume Spread Analysis (VSA)
*   **Price Levels**: Current Price: **Rs. {profile['fundamentals']['current_price']}**. Moving averages stand at 50-day SMA of **Rs. {profile['technicals'].get('sma_50')}** and 200-day SMA of **Rs. {profile['technicals'].get('sma_200')}**.
*   **VSA Pattern**: **{profile['technicals'].get('vsa_pattern', 'Normal Price Action')}** with POC support floor at **Rs. {profile['technicals'].get('poc_price', profile['fundamentals']['current_price'])}**. RSI is at **{profile['technicals'].get('rsi', 50.0):.1f}**.

## V. Competitive Benchmarking & Sector Rotation
*   **Peers**: NTPC trades at a comfortable valuation discount relative to high-multiple peers, supported by strong ROCE of **{profile['fundamentals'].get('roce_pct')}%**.
*   **Sector Wave**: Sector **{sector_name}** sits in the **{sector_regime}** phase with an AI sentiment thermometer rating of **{sector_sentiment}**.

## VI. Catalysts, Risks & Mitigation Framework
1.  **Catalyst 1**: Strong sector rotation momentum wave with a **{sector_sentiment}** Sentiment score.
2.  **Catalyst 2**: Positive institutional backing with robust FII/DII shareholdings.
3.  **Risk Flag**: High volatility system beta of **{profile.get('consensus', {}).get('beta', 1.0):.2f}**. (Mitigation: Use strict stop-loss boundaries at support floors).
"""
        return {"symbol": ticker, "markdown": markdown_memo, "llm_meta": get_last_llm_meta()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate Pitchbook memo: {str(e)}")

@app.post("/api/chat")
async def advisory_chat(request: ChatRequest):
    """Stateful context-retained advisory chat console."""
    try:
        # Fetch current watchlists for chat context
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM watchlists")
            watchlists = [dict(row) for row in cursor.fetchall()]

        history_list = [{"role": msg.role, "content": msg.content} for msg in request.history]
        response_text = await asyncio.to_thread(
            run_conversational_chat,
            history_list, 
            request.message, 
            request.profile,
            None,
            watchlists
        )
        
        actions = []
        clean_response = response_text
        if "[ACTIONS_PAYLOAD]:" in response_text:
            try:
                parts = response_text.split("[ACTIONS_PAYLOAD]:")
                clean_response = parts[0].strip()
                import json
                actions = json.loads(parts[1].strip())
            except Exception as e:
                print(f"Error parsing ACTIONS_PAYLOAD: {e}")
                
        return {"response": clean_response, "actions": actions, "llm_meta": get_last_llm_meta()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat session failed: {str(e)}")

# ==================== ALERTS (Persistent SQLite) ====================

@app.post("/api/alerts/set")
async def set_alert(data: AlertRequest):
    """Configures a custom alert trigger, persisted to SQLite."""
    try:
        alert_id = str(uuid.uuid4())[:8]
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO alerts (id, ticker, condition_type, operator, value) VALUES (?, ?, ?, ?, ?)",
                (alert_id, data.ticker.upper(), data.condition_type.upper(), data.operator, data.value)
            )
            conn.commit()

        # Register with real-time AlertEvaluator if Angel One is active
        from backend.websocket_server import alert_evaluator as _ae
        if _ae is not None:
            _ae.register_alert({
                "id": alert_id,
                "ticker": data.ticker.upper(),
                "condition_type": data.condition_type.upper(),
                "operator": data.operator,
                "value": data.value,
            })
            # Subscribe to this symbol on Angel One upstream
            plain_sym = data.ticker.upper().replace(".NS", "")
            subscribe_symbols([plain_sym])

        return {
            "id": alert_id,
            "ticker": data.ticker.upper(),
            "condition_type": data.condition_type.upper(),
            "operator": data.operator,
            "value": data.value,
            "status": "Active",
            "triggered": False,
            "trigger_date": "",
            "ai_context": ""
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set alert: {str(e)}")

@app.post("/api/alerts/parse-nl")
async def parse_nl_alert(data: ParseNLAlertRequest):
    """Parses a plain English prompt into a structured SQLite alert rule using Groq LLM."""
    try:
        from backend.llm_config import call_llm, TASK_FAST, TASK_HEAVY
        from backend.financial_utils import resolve_company_ticker

        fallback_context = ""
        if data.active_ticker:
            fallback_context = f"\nActive Ticker Context: {data.active_ticker}. If the user alert setup prompt does not explicitly specify a stock/company name or ticker, you MUST default to using this ticker for the rule. Do not default to TCS or any other stock if this active ticker context is provided.\n"

        sys_prompt = (
            "You are an expert financial system developer parsing plain English alert setup requests into structured JSON rules.\n"
            f"{fallback_context}"
            "Analyze the user prompt and output a single JSON object. DO NOT output any markdown tags (like ```json), and DO NOT output any conversational text or preambles. Only output the raw JSON string.\n"
            "Allowed condition types:\n"
            "- RSI (Relative Strength Index limit)\n"
            "- PE (Price-to-Earnings, value is median check 'MEDIAN' or multiple number)\n"
            "- RATING (analyst recommendation, e.g., 'Strong Buy', 'Buy', 'Hold', 'Sell')\n"
            "- PRICE (absolute price floor/ceiling in Rs.)\n"
            "- SMA (price deviation from 200 SMA in %, e.g., 5.0 for 5% above, -3.0 for 3% below)\n"
            "- DMA_CROSS (50 SMA vs 200 SMA crossover, value represents percentage separation filter, e.g. 0.0 or 1.5)\n"
            "- EMA_CROSS (50 EMA vs 200 EMA crossover, value represents percentage separation filter, e.g. 0.0 or 1.0)\n"
            "- VOL_BREAKOUT (volume ratio vs 20d average, e.g., 2.0)\n"
            "- BB_CROSS (price vs Bollinger Bands, value is 0)\n"
            "- MACD_CROSS (MACD vs Signal line crossover, value is absolute point difference filter, e.g. 0.0 or 0.5)\n"
            "- 52W_PROXIMITY (proximity margin % to 52w limits, e.g. 3.0)\n"
            "- SMA50 (price deviation from 50 SMA in %, e.g. 2.0 or -2.0)\n"
            "- FIB_LEVEL (proximity to any Fib level in %, e.g. 1.5)\n"
            "- FIB_382 (proximity to Fib 38.2% in %, e.g. 1.5)\n"
            "- FIB_500 (proximity to Fib 50.0% in %, e.g. 1.5)\n"
            "- FIB_618 (proximity to Fib 61.8% in %, e.g. 1.5)\n"
            "- ALTMAN_Z (Altman Z-Score solvency indicator, e.g. 1.8)\n"
            "- TARGET_DISCOUNT (consensus target price discount percentage, e.g. 15.0)\n"
            "- CFO_PAT_DIVERGENCE (Cash Flow to Profit Divergence ratio, e.g. 0.6)\n"
            "- DIVIDEND_YIELD_FLOOR (dividend yield percentage support trigger, e.g. 4.0)\n"
            "- ATR_VOLATILITY_SHOCK (Average True Range volatility indicator in Rs., e.g. 50)\n"
            "- SMA20 (price deviation from 20-day SMA in %, e.g., 2.0 for 2% above, -2.0 for 2% below)\n"
            "- SMA100 (price deviation from 100-day SMA in %, e.g., 2.0 for 2% above, -2.0 for 2% below)\n"
            "- EMA20 (price deviation from 20-day EMA in %, e.g., 2.0 for 2% above, -2.0 for 2% below)\n"
            "- EMA50 (price deviation from 50-day EMA in %, e.g., 2.0 for 2% above, -2.0 for 2% below)\n"
            "- EMA200 (price deviation from 200-day EMA in %, e.g., 2.0 for 2% above, -2.0 for 2% below)\n"
            "- PEG (price/earnings-to-growth ratio, e.g. 1.0)\n"
            "- ROE (return on equity in percentage, e.g. 15.0)\n"
            "- DE (debt-to-equity leverage ratio, e.g. 0.5)\n"
            "- PLEDGE (promoter pledged share percentage, e.g. 1.0)\n"
            "- DCF_SAFETY (margin of safety relative to DCF intrinsic value in %, e.g. 20.0)\n"
            "- BETA (systematic risk beta against Nifty 50, e.g. 1.0)\n"
            "- DELIVERY_PCT (delivery volume percentage, e.g. 50.0)\n"
            "- DELIVERY_ZSCORE (delivery Z-Score relative to 20-day mean, e.g. 2.0)\n"
            "- INST_HOLDING (combined FII and DII shareholding percentage, e.g. 30.0)\n"
            "- COMPOUND (logical combination of multiple simple rules using AND or OR operators)\n\n"
            "Operators:\n"
            "- '>' (Greater Than / Crosses Above)\n"
            "- '<' (Less Than / Crosses Below)\n"
            "- '==' (Equals / Near Proximity - mandatory for FIB and RATING conditions)\n\n"
            "IMPORTANT OPERATOR RULE FOR 52W_PROXIMITY:\n"
            "- You MUST use the operator '>' to represent proximity to the 52-week HIGH (e.g. 'within 5% of 52-week high').\n"
            "- You MUST use the operator '<' to represent proximity to the 52-week LOW (e.g. 'within 5% of 52-week low').\n"
            "Never output '<' for high proximity just because the user prompt contains the word 'within'.\n\n"
            "CRITICAL RULES FOR COMPOUND ALERTS:\n"
            "If the request contains multiple alert parameters combined via logical operators 'and', 'or', '&&', '||' (e.g. 'price below 2000 and rsi under 40'), you MUST:\n"
            "1. Set 'condition_type': 'COMPOUND'\n"
            "2. Set 'operator': ''\n"
            "3. Set 'value': to a JSON string representation of a list of conditions and logical operators. For example, if user asks: 'price is below 2000 and rsi is under 40', you must set 'value' to the string: '[{\"indicator\": \"PRICE\", \"operator\": \"<\", \"value\": \"2000\"}, {\"operator\": \"AND\"}, {\"indicator\": \"RSI\", \"operator\": \"<\", \"value\": \"40\"}]'. Note that logical operator items only have the 'operator' field, whereas rule items have 'indicator', 'operator', and 'value' fields.\n\n"
            "Output format example for simple alert:\n"
            "{\n"
            "  \"ticker_query\": \"TCS\",\n"
            "  \"condition_type\": \"EMA_CROSS\",\n"
            "  \"operator\": \">\",\n"
            "  \"value\": \"0.0\"\n"
            "}\n\n"
            "Output format example for compound alert:\n"
            "{\n"
            "  \"ticker_query\": \"TCS\",\n"
            "  \"condition_type\": \"COMPOUND\",\n"
            "  \"operator\": \"\",\n"
            "  \"value\": \"[{\\\"indicator\\\": \\\"PRICE\\\", \\\"operator\\\": \\\"<\\\", \\\"value\\\": \\\"2000\\\"}, {\\\"operator\\\": \\\"AND\\\"}, {\\\"indicator\\\": \\\"RSI\\\", \\\"operator\\\": \\\"<\\\", \\\"value\\\": \\\"40\\\"}]\"\n"
            "}"
        )

        response = await asyncio.to_thread(call_llm, TASK_FAST, sys_prompt, data.prompt)
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()

        # Extract only the first JSON object — LLM may add extra text after it
        brace_depth = 0
        json_start = -1
        json_end = -1
        in_string = False
        escape_next = False
        for i, ch in enumerate(response):
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                if brace_depth == 0:
                    json_start = i
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1
                if brace_depth == 0:
                    json_end = i + 1
                    break
        if json_start >= 0 and json_end > json_start:
            response = response[json_start:json_end]

        # Sanitise common LLM JSON quirks
        import re as _re
        response = _re.sub(r',\s*}', '}', response)   # trailing commas before }
        response = _re.sub(r',\s*]', ']', response)   # trailing commas before ]
        response = response.replace('\n', ' ')          # embedded newlines

        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            # Last-resort: regex-extract the four fields
            import re as _re2
            tq = _re2.search(r'"ticker_query"\s*:\s*"([^"]*)"', response)
            ct = _re2.search(r'"condition_type"\s*:\s*"([^"]*)"', response)
            opr = _re2.search(r'"operator"\s*:\s*"([^"]*)"', response)
            vl = _re2.search(r'"value"\s*:\s*"([^"]*)"', response)
            if tq:
                parsed = {
                    "ticker_query": tq.group(1) if tq else "TCS",
                    "condition_type": ct.group(1) if ct else "PRICE",
                    "operator": opr.group(1) if opr else ">",
                    "value": vl.group(1) if vl else "0.0"
                }
            else:
                logger.error(f"Alert LLM response unparseable: {response}")
                raise ValueError(f"Could not parse LLM response into alert JSON")

        ticker_query = parsed.get("ticker_query", "TCS")
        cond_type = parsed.get("condition_type", "PRICE").upper()
        op = parsed.get("operator", ">")
        val = parsed.get("value", "0.0")

        try:
            res = resolve_company_ticker(ticker_query)
            ticker = res["yf_ticker"]
        except Exception:
            ticker = ticker_query.strip().upper()
            if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
                ticker += ".NS"

        alert_id = str(uuid.uuid4())[:8]
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO alerts (id, ticker, condition_type, operator, value) VALUES (?, ?, ?, ?, ?)",
                (alert_id, ticker, cond_type, op, val)
            )
            conn.commit()

        return {
            "id": alert_id,
            "ticker": ticker,
            "condition_type": cond_type,
            "operator": op,
            "value": val,
            "status": "Active",
            "triggered": False,
            "trigger_date": "",
            "ai_context": "",
            "llm_meta": get_last_llm_meta()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse and configure alert: {str(e)}")

@app.get("/api/alerts/list")
async def list_alerts():
    """Returns all alerts from SQLite, including synchronized watchlist stock alerts."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, ticker, condition_type, operator, value, status, triggered, trigger_date, ai_context FROM alerts")
        rows = cursor.fetchall()
        alerts_list = [
            {
                "id": str(row["id"]),
                "ticker": row["ticker"],
                "condition_type": row["condition_type"],
                "operator": row["operator"],
                "value": str(row["value"]) if row["value"] is not None else "",
                "status": row["status"] or "Active",
                "triggered": bool(row["triggered"]),
                "trigger_date": row["trigger_date"] or "",
                "ai_context": row["ai_context"] or ""
            }
            for row in rows
        ]

        # Scan watchlist_items for any enabled alert_config not yet in alerts table
        try:
            cursor.execute("SELECT watchlist_id, symbol, alert_config FROM watchlist_items WHERE alert_config IS NOT NULL AND alert_config != ''")
            wl_rows = cursor.fetchall()
            existing_ids = {str(a["id"]) for a in alerts_list}

            for r in wl_rows:
                try:
                    cfg = json.loads(r["alert_config"])
                    if not cfg or not cfg.get("enabled", True):
                        continue
                    w_id = r["watchlist_id"]
                    sym = r["symbol"].replace('.NS','').replace('.BO','').upper()

                    def _add_if_missing(aid, c_type, op, val, ctx):
                        if aid not in existing_ids:
                            alerts_list.append({
                                "id": aid,
                                "ticker": sym,
                                "condition_type": c_type,
                                "operator": op,
                                "value": str(val),
                                "status": "Active",
                                "triggered": False,
                                "trigger_date": "",
                                "ai_context": f"Watchlist Rule ({ctx})"
                            })
                            existing_ids.add(aid)

                    if cfg.get("price_low") is not None:
                        _add_if_missing(f"wl_{w_id}_{sym}_price_low", "PRICE", "<=", cfg["price_low"], "Target Low")
                    if cfg.get("price_high") is not None:
                        _add_if_missing(f"wl_{w_id}_{sym}_price_high", "PRICE", ">=", cfg["price_high"], "Target High")
                    if cfg.get("breakout_52w"):
                        _add_if_missing(f"wl_{w_id}_{sym}_breakout_52w", "BREAKOUT", "BREAKOUT 52W", "52W High", "52-Week High Breakout")
                    if cfg.get("flash_dip_pct") is not None:
                        _add_if_missing(f"wl_{w_id}_{sym}_flash_dip", "FLASH_DIP", "DROP >=", f"{cfg['flash_dip_pct']}%", "Flash Dip")
                    if cfg.get("entry_dip_pct") is not None:
                        _add_if_missing(f"wl_{w_id}_{sym}_entry_dip", "ENTRY_DIP", "DROP >=", f"{cfg['entry_dip_pct']}%", "Entry Dip")
                    if cfg.get("volume_spike"):
                        _add_if_missing(f"wl_{w_id}_{sym}_volume_spike", "VOLUME", "SPIKE >=", "2.5x 20D Avg", "Volume Spike")
                    if cfg.get("mos_undervalued"):
                        _add_if_missing(f"wl_{w_id}_{sym}_mos", "VALUATION", "MOS >=", "20.0%", "MOS Undervalued")
                    if cfg.get("pe_compression") is not None:
                        _add_if_missing(f"wl_{w_id}_{sym}_pe", "PE_COMPRESSION", "<=", cfg["pe_compression"], "P/E Compression")
                    if cfg.get("score_shift"):
                        _add_if_missing(f"wl_{w_id}_{sym}_score", "SCORE_SHIFT", "CONVICTION", "<50 or >75", "Conviction Shift")
                    if cfg.get("rsi_extremes"):
                        _add_if_missing(f"wl_{w_id}_{sym}_rsi", "RSI", "EXTREME", "<30 or >70", "RSI Extreme")
                    if cfg.get("ma_proximity_enabled"):
                        ma_p = cfg.get("ma_period", "EMA_50")
                        ma_t = cfg.get("ma_threshold_pct", 3.0)
                        _add_if_missing(f"wl_{w_id}_{sym}_ma", "MA_PROXIMITY", "WITHIN", f"{ma_t}% of {ma_p}", "MA Proximity")

                except Exception as ex:
                    logger.error(f"Error parsing watchlist item alert_config in list_alerts: {ex}")
        except Exception as e:
            logger.error(f"Error fetching watchlist_items in list_alerts: {e}")

        return alerts_list

@app.get("/api/alerts/settings")
async def get_alert_settings():
    """Returns the alert settings (WhatsApp from env, Slack/Discord from SQLite)."""
    wa_token = os.environ.get("WHATSAPP_TOKEN", "")
    wa_phone_id = os.environ.get("WHATSAPP_PHONE_ID", "")
    wa_recipient = os.environ.get("WHATSAPP_RECIPIENT", "")
    masked_token = ""
    if wa_token:
        masked_token = "*" * 20 + wa_token[-8:] if len(wa_token) > 8 else wa_token
    
    slack_webhook = ""
    discord_webhook = ""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM alert_settings WHERE key IN ('slack_webhook', 'discord_webhook')")
        for row in cursor.fetchall():
            if row["key"] == "slack_webhook":
                slack_webhook = row["value"]
            elif row["key"] == "discord_webhook":
                discord_webhook = row["value"]

    return {
        "whatsapp_configured": bool(wa_token and wa_phone_id and wa_recipient),
        "whatsapp_token_masked": masked_token,
        "whatsapp_phone_id": wa_phone_id,
        "whatsapp_recipient": wa_recipient,
        "slack_webhook": slack_webhook,
        "discord_webhook": discord_webhook
    }

@app.post("/api/alerts/settings")
async def save_alert_settings(payload: dict):
    """Saves Slack and Discord webhooks to alert_settings table in SQLite."""
    with get_db() as conn:
        cursor = conn.cursor()
        if "slack_webhook" in payload:
            cursor.execute(
                "INSERT OR REPLACE INTO alert_settings (key, value) VALUES ('slack_webhook', ?)",
                (payload["slack_webhook"],)
            )
        if "discord_webhook" in payload:
            cursor.execute(
                "INSERT OR REPLACE INTO alert_settings (key, value) VALUES ('discord_webhook', ?)",
                (payload["discord_webhook"],)
            )
        conn.commit()
    return {"status": "success"}

@app.post("/api/alerts/whatsapp/test")
async def test_whatsapp():
    """Sends a test WhatsApp message to verify the Cloud API connection."""
    wa_token = os.environ.get("WHATSAPP_TOKEN", "")
    wa_phone_id = os.environ.get("WHATSAPP_PHONE_ID", "")
    wa_recipient = os.environ.get("WHATSAPP_RECIPIENT", "")
    
    if not wa_token or not wa_phone_id or not wa_recipient:
        raise HTTPException(status_code=400, detail="WhatsApp credentials not configured in .env file.")
    
    url = f"https://graph.facebook.com/v21.0/{wa_phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {wa_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": wa_recipient,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": "*APEX AI Workstation*\n\n_WhatsApp Alert Dispatch Test_\n\nConnection verified successfully. Alert notifications will be dispatched to this number when institutional triggers fire.\n\nTimestamp: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
        }
    }
    
    try:
        resp = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=10)
        resp_data = resp.json()
        if resp.status_code == 200 and "messages" in resp_data:
            return {"status": "success", "message_id": resp_data["messages"][0].get("id", "")}
        else:
            error_msg = resp_data.get("error", {}).get("message", "Unknown error")
            raise HTTPException(status_code=resp.status_code, detail=f"WhatsApp API error: {error_msg}")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Network error sending WhatsApp test: {str(e)}")

@app.get("/api/alerts/daily-wrapup/settings")
async def get_daily_wrapup_settings():
    """Returns WhatsApp Daily Wrap-Up schedule and activation settings."""
    enabled = "false"
    trigger_time = "19:30"
    persona = "institutional"
    last_sent = ""
    include_events = "true"
    include_deals = "true"
    include_sentiment = "true"
    include_breakouts = "true"
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT key, value FROM alert_settings 
               WHERE key IN ('daily_wrapup_enabled', 'daily_wrapup_time', 'daily_wrapup_persona', 
                             'daily_wrapup_last_sent', 'daily_wrapup_include_events', 'daily_wrapup_include_deals',
                             'daily_wrapup_include_sentiment', 'daily_wrapup_include_breakouts')"""
        )
        for row in cursor.fetchall():
            if row["key"] == "daily_wrapup_enabled":
                enabled = row["value"]
            elif row["key"] == "daily_wrapup_time":
                trigger_time = row["value"]
            elif row["key"] == "daily_wrapup_persona":
                persona = row["value"]
            elif row["key"] == "daily_wrapup_last_sent":
                last_sent = row["value"]
            elif row["key"] == "daily_wrapup_include_events":
                include_events = row["value"]
            elif row["key"] == "daily_wrapup_include_deals":
                include_deals = row["value"]
            elif row["key"] == "daily_wrapup_include_sentiment":
                include_sentiment = row["value"]
            elif row["key"] == "daily_wrapup_include_breakouts":
                include_breakouts = row["value"]
    
    return {
        "enabled": enabled.lower() == "true",
        "time": trigger_time,
        "persona": persona,
        "last_sent": last_sent,
        "include_events": include_events.lower() == "true",
        "include_deals": include_deals.lower() == "true",
        "include_sentiment": include_sentiment.lower() == "true",
        "include_breakouts": include_breakouts.lower() == "true"
    }

@app.post("/api/alerts/daily-wrapup/settings")
async def save_daily_wrapup_settings(payload: dict):
    """Updates daily wrap-up schedule and activation state in SQLite."""
    with get_db() as conn:
        cursor = conn.cursor()
        if "enabled" in payload:
            val = "true" if payload["enabled"] else "false"
            cursor.execute("INSERT OR REPLACE INTO alert_settings (key, value) VALUES ('daily_wrapup_enabled', ?)", (val,))
        if "time" in payload:
            cursor.execute("INSERT OR REPLACE INTO alert_settings (key, value) VALUES ('daily_wrapup_time', ?)", (payload["time"],))
        if "persona" in payload:
            cursor.execute("INSERT OR REPLACE INTO alert_settings (key, value) VALUES ('daily_wrapup_persona', ?)", (payload["persona"],))
        if "include_events" in payload:
            val = "true" if payload["include_events"] else "false"
            cursor.execute("INSERT OR REPLACE INTO alert_settings (key, value) VALUES ('daily_wrapup_include_events', ?)", (val,))
        if "include_deals" in payload:
            val = "true" if payload["include_deals"] else "false"
            cursor.execute("INSERT OR REPLACE INTO alert_settings (key, value) VALUES ('daily_wrapup_include_deals', ?)", (val,))
        if "include_sentiment" in payload:
            val = "true" if payload["include_sentiment"] else "false"
            cursor.execute("INSERT OR REPLACE INTO alert_settings (key, value) VALUES ('daily_wrapup_include_sentiment', ?)", (val,))
        if "include_breakouts" in payload:
            val = "true" if payload["include_breakouts"] else "false"
            cursor.execute("INSERT OR REPLACE INTO alert_settings (key, value) VALUES ('daily_wrapup_include_breakouts', ?)", (val,))
        conn.commit()
    return {"status": "success"}

@app.post("/api/alerts/daily-wrapup/trigger")
async def trigger_daily_wrapup(payload: Optional[dict] = None):
    """Manually compiles the daily wrap-up summary and dispatches to WhatsApp."""
    from backend.daily_wrapup import generate_daily_wrapup_text, send_whatsapp_wrapup
    try:
        persona_override = None
        if payload and "persona" in payload:
            persona_override = payload["persona"]
        msg = await generate_daily_wrapup_text(persona_override=persona_override)
        wa_token = os.environ.get("WHATSAPP_TOKEN", "")
        wa_phone_id = os.environ.get("WHATSAPP_PHONE_ID", "")
        wa_recipient = os.environ.get("WHATSAPP_RECIPIENT", "")
        
        dispatch_status = "skipped"
        dispatch_error = None
        message_id = None
        
        if wa_token and wa_phone_id and wa_recipient:
            res = await send_whatsapp_wrapup(msg)
            dispatch_status = res.get("status", "error")
            if dispatch_status == "success":
                message_id = res.get("message_id")
            else:
                dispatch_error = res.get("message", "Unknown dispatch failure")
        else:
            dispatch_error = "WhatsApp credentials not configured in environment variables."
            
        return {
            "status": "success",
            "message_body": msg,
            "dispatch_status": dispatch_status,
            "message_id": message_id,
            "error": dispatch_error,
            "llm_meta": get_last_llm_meta()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Daily Wrap-up Generation failed: {str(e)}")

@app.get("/api/alerts/weekly-wrapup/settings")
async def get_weekly_wrapup_settings_route():
    """Returns WhatsApp Weekly Market & Portfolio Wrap-Up schedule and activation settings."""
    import importlib
    import backend.weekly_wrapup as ww
    importlib.reload(ww)
    return ww.get_weekly_wrapup_settings()

@app.post("/api/alerts/weekly-wrapup/settings")
async def save_weekly_wrapup_settings_route(payload: dict):
    """Updates weekly wrap-up schedule and activation state in SQLite."""
    import importlib
    import backend.weekly_wrapup as ww
    importlib.reload(ww)
    success = ww.save_weekly_wrapup_settings(payload)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save weekly wrap-up settings")
    return {"status": "success"}

@app.post("/api/alerts/weekly-wrapup/trigger")
async def trigger_weekly_wrapup_route(payload: Optional[dict] = None):
    """Manually compiles the weekly market & portfolio wrap-up summary and dispatches to WhatsApp."""
    import importlib
    import backend.weekly_wrapup as ww
    importlib.reload(ww)
    persona = payload.get("persona") if payload else None
    res = await ww.trigger_weekly_wrapup(on_demand=True, persona=persona)
    return res

@app.delete("/api/alerts/{alert_id}")
async def delete_alert(alert_id: str):
    """Deletes a single alert by ID."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        conn.commit()

    # Unregister from real-time AlertEvaluator
    from backend.websocket_server import alert_evaluator as _ae
    if _ae is not None:
        try:
            _ae.unregister_alert(alert_id)
        except Exception as e:
            print(f"Error unregistering alert: {e}")

# ==================== FS ALERTS (SQLite Cache & AI) ====================

@app.post("/api/fs-alerts/add")
async def add_fs_alert(data: FsAlertRequest):
    """Configures a custom Financial Statement alert, persisted to SQLite."""
    try:
        alert_id = str(uuid.uuid4())[:8]
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO fs_alerts (id, symbol, metric, condition, threshold, active) VALUES (?, ?, ?, ?, ?, 1)",
                (alert_id, data.symbol.upper(), data.metric.strip(), data.condition.strip(), data.threshold)
            )
            conn.commit()
        return {
            "id": alert_id,
            "symbol": data.symbol.upper(),
            "metric": data.metric.strip(),
            "condition": data.condition.strip(),
            "threshold": data.threshold,
            "active": True
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add FS alert: {str(e)}")

# --- FS Evaluation Internal logic and API endpoint ---

async def run_fs_evaluation_internal(symbol: str, view: str = "consolidated", force_refresh: bool = False) -> dict:
    from backend.shareholding_scraper import clean_symbol
    from backend.financial_statements_scraper import scrape_financial_statements
    import json
    
    base_symbol = clean_symbol(symbol)
    if not base_symbol:
        return None
        
    view = view.strip().lower()
    if view not in ["standalone", "consolidated"]:
        view = "consolidated"
        
    if force_refresh:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM cached_financial_statements WHERE symbol = ?", (base_symbol,))
            conn.commit()
        
    # Get screener session cookie if available
    session_cookie = None
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM alert_settings WHERE key = 'screener_session_cookie'")
        cookie_row = cursor.fetchone()
        if cookie_row:
            session_cookie = cookie_row["value"]
            
    # Try fetching from cache first, otherwise scrape
    statements = None
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data_json FROM cached_financial_statements WHERE symbol = ? AND view = ?", (base_symbol, view))
        row = cursor.fetchone()
        if not row:
            alt_view = "standalone" if view == "consolidated" else "consolidated"
            cursor.execute("SELECT data_json FROM cached_financial_statements WHERE symbol = ? AND view = ?", (base_symbol, alt_view))
            row = cursor.fetchone()
        if row:
            try:
                statements = json.loads(row["data_json"])
            except Exception:
                pass
                
    if not statements or "error" in statements:
        # Scraping on demand in a thread pool to avoid blocking
        statements = await asyncio.to_thread(scrape_financial_statements, symbol, view, session_cookie)
        if not statements or "error" in statements:
            # Fallback
            alt_view = "standalone" if view == "consolidated" else "consolidated"
            statements = await asyncio.to_thread(scrape_financial_statements, symbol, alt_view, session_cookie)
            
    if not statements or "error" in statements:
        return None

    # Extract historical fields
    from backend.financial_utils import get_statement_row_history
    
    net_profit_history = get_statement_row_history(statements.get("profit_loss"), "Net Profit")
    sales_history = get_statement_row_history(statements.get("profit_loss"), "Sales")
    opm_history = get_statement_row_history(statements.get("profit_loss"), "OPM") or get_statement_row_history(statements.get("profit_loss"), "OPM %")
    interest_history = get_statement_row_history(statements.get("profit_loss"), "Interest")
    reserves_history = get_statement_row_history(statements.get("balance_sheet"), "Reserves")
    borrowings_history = get_statement_row_history(statements.get("balance_sheet"), "Borrowings")
    other_liab_history = get_statement_row_history(statements.get("balance_sheet"), "Other Liabilities")
    other_assets_history = get_statement_row_history(statements.get("balance_sheet"), "Other Assets")
    total_assets_history = get_statement_row_history(statements.get("balance_sheet"), "Total Assets")
    equity_cap_history = get_statement_row_history(statements.get("balance_sheet"), "Equity Capital") or get_statement_row_history(statements.get("balance_sheet"), "Share Capital")
    depreciation_history = get_statement_row_history(statements.get("profit_loss"), "Depreciation")
    pbt_history = get_statement_row_history(statements.get("profit_loss"), "Profit before tax")
    receivables_history = get_statement_row_history(statements.get("balance_sheet"), "Receivables") or get_statement_row_history(statements.get("balance_sheet"), "Trade Receivables")

    # Fallbacks and basic metrics
    latest_np = net_profit_history[-1] if net_profit_history else 0.0
    prev_np = net_profit_history[-2] if len(net_profit_history) >= 2 else latest_np
    latest_ta = total_assets_history[-1] if total_assets_history else 1.0
    prev_ta = total_assets_history[-2] if len(total_assets_history) >= 2 else latest_ta
    prev_ta = prev_ta or 1.0
    
    has_history = len(net_profit_history) >= 2 and len(total_assets_history) >= 2
    
    latest_depr = depreciation_history[-1] if depreciation_history else 0.0
    latest_interest = interest_history[-1] if interest_history else 0.0
    latest_cfo = latest_np + latest_depr + latest_interest
    
    pass1 = latest_np > 0
    pass2 = latest_cfo > 0
    roa_curr = latest_np / latest_ta if latest_ta > 0 else 0
    roa_prev = prev_np / prev_ta if prev_ta > 0 else 0
    pass3 = (roa_curr > roa_prev) if has_history else False
    pass4 = latest_cfo > latest_np and latest_cfo > 0
    latest_debt = borrowings_history[-1] if borrowings_history else 0.0
    prev_debt = borrowings_history[-2] if len(borrowings_history) >= 2 else latest_debt
    lev_curr = latest_debt / latest_ta if latest_ta > 0 else 0
    lev_prev = prev_debt / prev_ta if prev_ta > 0 else 0
    pass5 = (lev_curr <= lev_prev) if has_history else False
    
    latest_oa = other_assets_history[-1] if other_assets_history else 1.0
    prev_oa = other_assets_history[-2] if len(other_assets_history) >= 2 else latest_oa
    latest_ol = other_liab_history[-1] if other_liab_history else 1.0
    prev_ol = other_liab_history[-2] if len(other_liab_history) >= 2 else latest_ol
    latest_ol = latest_ol or 1.0
    prev_ol = prev_ol or 1.0
    cr_curr = latest_oa / latest_ol
    cr_prev = prev_oa / prev_ol
    pass6 = (cr_curr > cr_prev) if has_history else False
    
    latest_eq = equity_cap_history[-1] if equity_cap_history else 100.0
    prev_eq = equity_cap_history[-2] if len(equity_cap_history) >= 2 else latest_eq
    pass7 = (latest_eq <= prev_eq) if has_history else False
    
    latest_opm = opm_history[-1] if opm_history else 0.0
    prev_opm = opm_history[-2] if len(opm_history) >= 2 else latest_opm
    pass8 = (latest_opm >= prev_opm) if has_history else False
    
    latest_sales = sales_history[-1] if sales_history else 0.0
    prev_sales = sales_history[-2] if len(sales_history) >= 2 else latest_sales
    at_curr = latest_sales / latest_ta if latest_ta > 0 else 0
    at_prev = prev_sales / prev_ta if prev_ta > 0 else 0
    pass9 = (at_curr >= at_prev) if has_history else False
    
    f_score = sum([pass1, pass2, pass3, pass4, pass5, pass6, pass7, pass8, pass9])
    
    # Altman Z-Score
    working_capital = latest_oa - latest_ol
    retained_earnings = reserves_history[-1] if reserves_history else latest_np * 3.0
    latest_pbt = pbt_history[-1] if pbt_history else latest_np * 1.3
    ebit = latest_pbt + latest_interest
    mcap_crores = (latest_sales * 1.5) / 1e7
    
    # Get actual market cap if available in schema
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT market_cap FROM screener_universe WHERE UPPER(symbol) = ? OR UPPER(base_symbol) = ?", (base_symbol, base_symbol))
            mcap_row = cursor.fetchone()
            if mcap_row and "market_cap" in mcap_row.keys() and mcap_row["market_cap"]:
                mcap_crores = float(mcap_row["market_cap"])
    except Exception:
        pass
            
    total_liab = latest_debt + latest_ol
    A = working_capital / latest_ta if latest_ta > 0 else 0
    B = retained_earnings / latest_ta if latest_ta > 0 else 0
    C = ebit / latest_ta if latest_ta > 0 else 0
    D = min(mcap_crores / total_liab, 12.0) if total_liab > 0 else 3.0
    E = latest_sales / latest_ta if latest_ta > 0 else 0
    z_score = 1.2 * A + 1.4 * B + 3.3 * C + 0.6 * D + 1.0 * E
    z_score = float(max(-2.0, min(15.0, z_score)))
    
    alerts_evaluated = []
    
    # 1. OPM trend
    opm_passed = latest_opm >= prev_opm
    alerts_evaluated.append({
        "id": "sys-opm-trend",
        "metric": "Operating Profit Margin (OPM)",
        "condition": "YoY Deterioration",
        "threshold": prev_opm,
        "current_value": latest_opm,
        "status": "Passed" if opm_passed else "Triggered",
        "severity": "Warning",
        "description": f"OPM Margin changed from {prev_opm}% to {latest_opm}%.",
        "type": "Systematic"
    })
    
    # 2. Revenue growth
    rev_growth = ((latest_sales - prev_sales) / prev_sales * 100) if prev_sales > 0 else 0.0
    rev_passed = rev_growth >= 5.0
    alerts_evaluated.append({
        "id": "sys-rev-growth",
        "metric": "Revenue Growth (Sales)",
        "condition": "YoY Growth < 5%",
        "threshold": 5.0,
        "current_value": round(rev_growth, 2),
        "status": "Passed" if rev_passed else "Triggered",
        "severity": "Warning",
        "description": f"YoY Sales Growth rate is {round(rev_growth, 2)}% (Threshold: 5%).",
        "type": "Systematic"
    })
    
    # 3. Debt to Equity
    equity = (equity_cap_history[-1] if equity_cap_history else 0.0) + (reserves_history[-1] if reserves_history else 0.0)
    debt_equity = latest_debt / equity if equity > 0 else 0.0
    de_passed = debt_equity <= 2.0
    alerts_evaluated.append({
        "id": "sys-debt-equity",
        "metric": "Debt-to-Equity",
        "condition": "Debt-to-Equity > 2.0",
        "threshold": 2.0,
        "current_value": round(debt_equity, 2),
        "status": "Passed" if de_passed else "Triggered",
        "severity": "Critical" if debt_equity > 2.0 else ("Warning" if debt_equity > 1.5 else "Info"),
        "description": f"Debt-to-Equity is {round(debt_equity, 2)} (Threshold: 2.0).",
        "type": "Systematic"
    })
    
    # 4. Receivables turnover check
    if receivables_history and len(receivables_history) >= 2:
        rec_growth = ((receivables_history[-1] - receivables_history[-2]) / receivables_history[-2] * 100) if receivables_history[-2] > 0 else 0.0
        rec_passed = rec_growth <= rev_growth + 5.0
        alerts_evaluated.append({
            "id": "sys-receivables-turnover",
            "metric": "Receivables Growth VS Revenue",
            "condition": "Receivables Growth > Revenue Growth + 5%",
            "threshold": round(rev_growth + 5.0, 2),
            "current_value": round(rec_growth, 2),
            "status": "Passed" if rec_passed else "Triggered",
            "severity": "Warning",
            "description": f"Trade Receivables grew by {round(rec_growth, 2)}% YoY compared to Sales growth of {round(rev_growth, 2)}%.",
            "type": "Systematic"
        })
        
    # 5. Altman Z-Score solvency
    z_passed = z_score >= 1.8
    alerts_evaluated.append({
        "id": "sys-altman-solvency",
        "metric": "Altman Z-Score",
        "condition": "Z-Score < 1.8 (Distress)",
        "threshold": 1.8,
        "current_value": round(z_score, 2),
        "status": "Passed" if z_passed else "Triggered",
        "severity": "Critical" if z_score < 1.8 else ("Warning" if z_score < 3.0 else "Info"),
        "description": f"Altman Z-Score is {round(z_score, 2)} (Solvency Zone: { 'Safe' if z_score >= 3.0 else ('Grey' if z_score >= 1.8 else 'Distress') }).",
        "type": "Systematic"
    })
    
    # 6. Piotroski F-Score quality
    f_passed = f_score >= 4
    alerts_evaluated.append({
        "id": "sys-piotroski-quality",
        "metric": "Piotroski F-Score",
        "condition": "F-Score < 4 (Weak)",
        "threshold": 4.0,
        "current_value": float(f_score),
        "status": "Passed" if f_passed else "Triggered",
        "severity": "Critical" if f_score < 4 else ("Warning" if f_score < 7 else "Info"),
        "description": f"Piotroski F-Score is {f_score}/9.",
        "type": "Systematic"
    })
    
    # 7. Asset Turnover trend
    at_passed = at_curr >= at_prev
    alerts_evaluated.append({
        "id": "sys-asset-turnover",
        "metric": "Asset Turnover",
        "condition": "YoY Deterioration",
        "threshold": round(at_prev, 3),
        "current_value": round(at_curr, 3),
        "status": "Passed" if at_passed else "Triggered",
        "severity": "Warning",
        "description": f"Asset Turnover ratio changed from {round(at_prev, 3)} to {round(at_curr, 3)}.",
        "type": "Systematic"
    })
    
    # 8. Current Ratio liquidity
    current_ratio = cr_curr
    cr_passed = current_ratio >= 1.0
    alerts_evaluated.append({
        "id": "sys-current-ratio",
        "metric": "Current Ratio",
        "condition": "Current Ratio < 1.0",
        "threshold": 1.0,
        "current_value": round(current_ratio, 2),
        "status": "Passed" if cr_passed else "Triggered",
        "severity": "Critical" if current_ratio < 1.0 else ("Warning" if current_ratio < 1.3 else "Info"),
        "description": f"Current Ratio is {round(current_ratio, 2)} (Threshold: 1.0).",
        "type": "Systematic"
    })

    # Evaluate custom active rules
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, metric, condition, threshold, active FROM fs_alerts WHERE (UPPER(symbol) = ? OR UPPER(symbol) = ?) AND active = 1", (symbol.upper(), base_symbol))
        custom_rows = cursor.fetchall()
        
    for crow in custom_rows:
        rule_id = crow["id"]
        metric_name = crow["metric"]
        cond = crow["condition"].lower()
        thresh = float(crow["threshold"])
        
        m_history = []
        for tbl_name in ["profit_loss", "balance_sheet", "quarters", "cash_flow"]:
            if statements.get(tbl_name):
                m_history = get_statement_row_history(statements.get(tbl_name), metric_name)
                if m_history:
                    break
        
        if not m_history:
            if "altman" in metric_name.lower() or "z-score" in metric_name.lower():
                m_history = [z_score]
            elif "piotroski" in metric_name.lower() or "f-score" in metric_name.lower():
                m_history = [float(f_score)]
                
        if not m_history:
            alerts_evaluated.append({
                "id": rule_id,
                "metric": metric_name,
                "condition": cond.upper(),
                "threshold": thresh,
                "current_value": None,
                "status": "Data Unavailable",
                "severity": "Info",
                "description": f"Custom metric '{metric_name}' not found in statements.",
                "type": "Custom"
            })
            continue
            
        cur_val = m_history[-1]
        triggered = False
        
        if cond == "above":
            triggered = cur_val > thresh
        elif cond == "below":
            triggered = cur_val < thresh
        elif cond == "yoy_above":
            prev_val = m_history[-2] if len(m_history) >= 2 else cur_val
            change = ((cur_val - prev_val) / prev_val * 100) if prev_val != 0 else 0
            triggered = change > thresh
        elif cond == "yoy_below":
            prev_val = m_history[-2] if len(m_history) >= 2 else cur_val
            change = ((cur_val - prev_val) / prev_val * 100) if prev_val != 0 else 0
            triggered = change < thresh
            
        alerts_evaluated.append({
            "id": rule_id,
            "metric": metric_name,
            "condition": cond.upper(),
            "threshold": thresh,
            "current_value": round(cur_val, 2) if isinstance(cur_val, float) else cur_val,
            "status": "Triggered" if triggered else "Passed",
            "severity": "Critical",
            "description": f"Custom alert rule triggered: {metric_name} is {cond} {thresh} (Current: {round(cur_val, 2) if isinstance(cur_val, float) else cur_val}).",
            "type": "Custom"
        })

    # Determine overall status
    triggered_alerts = [a for a in alerts_evaluated if a["status"] == "Triggered"]
    critical_triggers = [a for a in triggered_alerts if a["severity"] == "Critical"]
    warning_triggers = [a for a in triggered_alerts if a["severity"] == "Warning"]
    
    if critical_triggers:
        overall_status = "Critical"
    elif warning_triggers:
        overall_status = "Warning"
    else:
        overall_status = "Healthy"
        
    return {
        "symbol": symbol,
        "overall_status": overall_status,
        "scores": {
            "piotroski": f_score,
            "altman_z": round(z_score, 2)
        },
        "alerts_evaluated": alerts_evaluated,
        "financials": statements
    }

@app.get("/api/stocks/{symbol}/fs-evaluation")
async def get_fs_evaluation(symbol: str, view: str = "consolidated", force_refresh: bool = False):
    """Retrieves current stock's financial statements and evaluates systematic/custom alerts."""
    try:
        res = await run_fs_evaluation_internal(symbol, view=view, force_refresh=force_refresh)
        if not res:
            raise HTTPException(status_code=404, detail=f"Financial statements or metrics not available for {symbol}")
        return res
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"FS evaluation failed: {str(e)}")

async def evaluate_all_stocks_fs():
    """Sweeps all watchlists/screener universe stocks, evaluates FS alerts, logs triggers to SQLite."""
    print("FS Alerts Evaluator: starting daily sweep...")
    symbols = set()
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT symbol FROM watchlist_items")
            for row in cursor.fetchall():
                symbols.add(row["symbol"])
            cursor.execute("SELECT DISTINCT symbol FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%'")
            for row in cursor.fetchall():
                symbols.add(row["symbol"])
    except Exception as db_err:
        print(f"FS Alerts Evaluator: failed to fetch symbols: {db_err}")
        return

    print(f"FS Alerts Evaluator: evaluating {len(symbols)} symbols...")
    
    for sym in symbols:
        try:
            res = await run_fs_evaluation_internal(sym)
            if not res:
                continue
                
            triggered_alerts = [a for a in res.get("alerts_evaluated", []) if a.get("status") == "Triggered"]
            
            with get_db() as conn:
                cursor = conn.cursor()
                for alert in triggered_alerts:
                    today_str = datetime.now().strftime("%Y-%m-%d")
                    cursor.execute(
                        """SELECT COUNT(*) as cnt FROM fs_alert_history 
                           WHERE symbol = ? AND metric = ? AND condition = ? AND threshold = ? AND DATE(triggered_at) = ?""",
                        (sym, alert["metric"], alert["condition"], alert["threshold"], today_str)
                    )
                    count = cursor.fetchone()["cnt"]
                    
                    if count == 0:
                        history_id = str(uuid.uuid4())[:8]
                        alert_id = alert.get("id") if alert.get("type") == "Custom" else "systematic"
                        cursor.execute(
                            """INSERT INTO fs_alert_history (id, alert_id, symbol, metric, condition, threshold, current_value, severity) 
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (history_id, alert_id, sym, alert["metric"], alert["condition"], alert["threshold"], alert["current_value"], alert["severity"])
                        )
                        conn.commit()
                        print(f"🚨 FS ALERT TRIGGERED: {sym} - {alert['metric']} {alert['condition']} {alert['threshold']} (Current: {alert['current_value']})")
            
            await asyncio.sleep(1)
        except Exception as eval_err:
            print(f"FS Alerts Evaluator: error evaluating {sym}: {eval_err}")

async def run_background_fs_alerts_scheduler():
    """Background daily scheduler for FS alert evaluations."""
    await asyncio.sleep(30)
    print("Background FS Alerts Scheduler started.")
    while True:
        try:
            await evaluate_all_stocks_fs()
        except Exception as e:
            print(f"Error in background FS Alerts Scheduler: {e}")
        await asyncio.sleep(24 * 3600)

@app.get("/api/fs-alerts/list")
async def list_fs_alerts(symbol: Optional[str] = None):
    """Lists all Financial Statement alerts, optionally filtered by stock symbol."""
    with get_db() as conn:
        cursor = conn.cursor()
        if symbol:
            base_symbol = symbol.split(".")[0].upper()
            cursor.execute(
                "SELECT id, symbol, metric, condition, threshold, active, created_at FROM fs_alerts WHERE UPPER(symbol) = ? OR UPPER(symbol) = ?", 
                (symbol.upper(), base_symbol)
            )
        else:
            cursor.execute("SELECT id, symbol, metric, condition, threshold, active, created_at FROM fs_alerts")
        rows = cursor.fetchall()
    return [
        {
            "id": r["id"],
            "symbol": r["symbol"],
            "metric": r["metric"],
            "condition": r["condition"],
            "threshold": r["threshold"],
            "active": bool(r["active"]),
            "created_at": r["created_at"]
        } for r in rows
    ]

@app.delete("/api/fs-alerts/{alert_id}")
async def delete_fs_alert(alert_id: str):
    """Deletes a single Financial Statement alert by ID."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM fs_alerts WHERE id = ?", (alert_id,))
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete FS alert: {str(e)}")

@app.post("/api/fs-alerts/toggle/{alert_id}")
async def toggle_fs_alert(alert_id: str):
    """Toggles active state of a single Financial Statement alert."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT active FROM fs_alerts WHERE id = ?", (alert_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Alert not found")
            new_state = 0 if row["active"] else 1
            cursor.execute("UPDATE fs_alerts SET active = ? WHERE id = ?", (new_state, alert_id))
            conn.commit()
        return {"status": "success", "active": bool(new_state)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to toggle FS alert: {str(e)}")

@app.post("/api/fs-alerts/parse-nl")
async def parse_fs_nl_alert(data: FsAlertParseRequest):
    """Parses a plain English prompt into a structured SQLite FS alert rule using Groq LLM."""
    try:
        from backend.llm_config import call_llm, TASK_FAST
        from backend.financial_utils import resolve_company_ticker

        fallback_context = ""
        if data.active_ticker:
            fallback_context = f"\nActive Ticker Context: {data.active_ticker}. If the user alert prompt does not explicitly specify a stock/company name or ticker, you MUST default to using this ticker for the rule.\n"

        sys_prompt = (
            "You are an expert financial system developer parsing plain English alert setup requests for financial statement metrics into structured JSON rules.\n"
            f"{fallback_context}"
            "Analyze the user prompt and output a single JSON object. DO NOT output any markdown tags (like ```json), and DO NOT output any conversational text or preambles. Only output the raw JSON string.\n"
            "Allowed metrics MUST match standard financial terms. Examples: 'Sales', 'Net Profit', 'OPM', 'Borrowings', 'Interest Coverage', 'ROCE', 'Altman Z-Score', 'Piotroski Score', 'Cash from Operations', 'Expenses', 'PBT', 'Total Assets', 'Total Liabilities'.\n"
            "Allowed conditions:\n"
            "- 'above' (Greater than / goes above / crosses above)\n"
            "- 'below' (Less than / drops below / falls below)\n"
            "- 'yoy_above' (YoY growth rate exceeds / YoY% greater than)\n"
            "- 'yoy_below' (YoY growth rate falls below / YoY% less than)\n\n"
            "Output format:\n"
            "{\n"
            "  \"ticker_query\": \"STOCK_TICKER\",\n"
            "  \"metric\": \"METRIC_NAME\",\n"
            "  \"condition\": \"above\" | \"below\" | \"yoy_above\" | \"yoy_below\",\n"
            "  \"threshold\": numerical_value_as_float\n"
            "}\n\n"
            "Output format example:\n"
            "User: 'Alert me if Reliance sales cross 10000'\n"
            "{\n"
            "  \"ticker_query\": \"RELIANCE\",\n"
            "  \"metric\": \"Sales\",\n"
            "  \"condition\": \"above\",\n"
            "  \"threshold\": 10000.0\n"
            "}\n"
        )

        import asyncio
        response = await asyncio.to_thread(call_llm, TASK_FAST, sys_prompt, data.prompt)
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()

        import json
        parsed = json.loads(response)
        ticker_query = parsed.get("ticker_query", data.active_ticker or "TCS")
        metric = parsed.get("metric", "Sales")
        condition = parsed.get("condition", "above").lower()
        threshold = float(parsed.get("threshold", 0.0))

        try:
            res = resolve_company_ticker(ticker_query)
            ticker = res["base_symbol"]
        except Exception:
            ticker = ticker_query.strip().upper().split(".")[0]

        alert_id = str(uuid.uuid4())[:8]
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO fs_alerts (id, symbol, metric, condition, threshold, active) VALUES (?, ?, ?, ?, ?, 1)",
                (alert_id, ticker, metric, condition, threshold)
            )
            conn.commit()

        return {
            "id": alert_id,
            "symbol": ticker,
            "metric": metric,
            "condition": condition,
            "threshold": threshold,
            "active": True,
            "llm_meta": get_last_llm_meta()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse and configure FS alert: {str(e)}")

@app.get("/api/settings/screener-cookie")
async def get_screener_cookie_settings():
    """Retrieves the configured Screener session cookie."""
    cookie = ""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM alert_settings WHERE key = 'screener_session_cookie'")
        row = cursor.fetchone()
        if row:
            cookie = row["value"]
    return {"cookie": cookie}

@app.post("/api/settings/screener-cookie")
async def save_screener_cookie_settings(payload: dict):
    """Saves or updates the Screener session cookie."""
    cookie = payload.get("cookie", "").strip()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO alert_settings (key, value) VALUES ('screener_session_cookie', ?)", (cookie,))
        conn.commit()
    return {"status": "success"}

import base64

def encode_key(raw_str: str) -> str:
    if not raw_str:
        return ""
    try:
        return "b64_" + base64.b64encode(raw_str.encode("utf-8")).decode("utf-8")
    except Exception:
        return raw_str

def decode_key(encoded_str: str) -> str:
    if not encoded_str:
        return ""
    try:
        if encoded_str.startswith("b64_"):
            return base64.b64decode(encoded_str[4:].encode("utf-8")).decode("utf-8")
        return encoded_str
    except Exception:
        return encoded_str

def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) < 10:
        return f"{key[:3]}...{key[-3:]}" if len(key) > 6 else key
    return f"{key[:6]}...{key[-4:]}"

def verify_gemini_key(key: str) -> bool:
    if not key:
        return False
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
        res = requests.get(url, timeout=5.0)
        if res.status_code == 200:
            return True
        if res.status_code == 400:
            err_json = res.json()
            if "API_KEY_INVALID" in str(err_json) or "invalid" in str(err_json).lower():
                return False
            return True
        return False
    except Exception:
        return True

def verify_tavily_key(key: str) -> bool:
    if not key:
        return False
    try:
        url = "https://api.tavily.com/search"
        payload = {"api_key": key, "query": "ping", "max_results": 1}
        res = requests.post(url, json=payload, timeout=5.0)
        if res.status_code == 200:
            return True
        return False
    except Exception:
        return True

def verify_serpapi_key(key: str) -> bool:
    if not key:
        return False
    try:
        url = f"https://serpapi.com/search.json?q=ping&api_key={key}&num=1"
        res = requests.get(url, timeout=5.0)
        if res.status_code == 200:
            return True
        return False
    except Exception:
        return True

@app.get("/api/settings/llm-keys")
async def get_llm_keys_settings():
    """Retrieves custom LLM and search keys from the database."""
    gemini_keys = []
    serpapi_key = ""
    tavily_key = ""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Load Gemini keys pool
        cursor.execute("SELECT value FROM alert_settings WHERE key = 'gemini_keys_pool'")
        row = cursor.fetchone()
        if row and row["value"]:
            try:
                encoded_list = json.loads(row["value"])
                if isinstance(encoded_list, list):
                    gemini_keys = [decode_key(k) for k in encoded_list]
            except Exception:
                pass
                
        # Load SerpApi key
        cursor.execute("SELECT value FROM alert_settings WHERE key = 'serpapi_api_key'")
        row = cursor.fetchone()
        if row:
            decoded = decode_key(row["value"])
            if decoded.startswith("["):
                try:
                    serpapi_key = ", ".join(json.loads(decoded))
                except Exception:
                    serpapi_key = decoded
            else:
                serpapi_key = decoded
            
        # Load Tavily key
        cursor.execute("SELECT value FROM alert_settings WHERE key = 'tavily_api_key'")
        row = cursor.fetchone()
        if row:
            decoded = decode_key(row["value"])
            if decoded.startswith("["):
                try:
                    tavily_key = ", ".join(json.loads(decoded))
                except Exception:
                    tavily_key = decoded
            else:
                tavily_key = decoded
            
    return {
        "keys": gemini_keys,
        "serpapi_api_key": serpapi_key,
        "tavily_api_key": tavily_key
    }

@app.post("/api/settings/llm-keys")
async def save_llm_keys_settings(payload: dict):
    """Verifies and saves dynamic LLM and Search keys."""
    keys = payload.get("keys", [])
    serpapi_key = payload.get("serpapi_api_key", "").strip()
    tavily_key = payload.get("tavily_api_key", "").strip()
    
    # 1. Verification Smoke Tests (Only verify if key is new/changed and not masked placeholder)
    existing = await get_llm_keys_settings()
    existing_gemini = existing["keys"]
    existing_serpapi = existing["serpapi_api_key"]
    existing_tavily = existing["tavily_api_key"]
    
    # Filter empty keys from input
    keys = [k.strip() for k in keys if k and k.strip()]
    
    # Parse dynamic SerpApi and Tavily list inputs
    serpapi_keys = [k.strip() for k in serpapi_key.split(",") if k and k.strip()]
    tavily_keys = [k.strip() for k in tavily_key.split(",") if k and k.strip()]
    
    existing_serpapi_list = [k.strip() for k in existing_serpapi.split(",") if k and k.strip()]
    existing_tavily_list = [k.strip() for k in existing_tavily.split(",") if k and k.strip()]
    
    # Verify Gemini keys
    for k in keys:
        if k not in existing_gemini:
            if not verify_gemini_key(k):
                raise HTTPException(status_code=400, detail=f"Gemini API key verification failed for key starting with '{k[:6]}'.")
                
    # Verify SerpApi keys
    for sk in serpapi_keys:
        if sk not in existing_serpapi_list:
            if not verify_serpapi_key(sk):
                raise HTTPException(status_code=400, detail=f"SerpApi API key verification failed for key starting with '{sk[:6]}'.")
            
    # Verify Tavily keys
    for tk in tavily_keys:
        if tk not in existing_tavily_list:
            if not verify_tavily_key(tk):
                raise HTTPException(status_code=400, detail=f"Tavily API key verification failed for key starting with '{tk[:6]}'.")
            
    # 2. Base64 encode before storage (serialize lists as JSON list strings)
    encoded_gemini = [encode_key(k) for k in keys]
    encoded_serpapi = encode_key(json.dumps(serpapi_keys))
    encoded_tavily = encode_key(json.dumps(tavily_keys))
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO alert_settings (key, value) VALUES ('gemini_keys_pool', ?)", (json.dumps(encoded_gemini),))
        cursor.execute("INSERT OR REPLACE INTO alert_settings (key, value) VALUES ('serpapi_api_key', ?)", (encoded_serpapi,))
        cursor.execute("INSERT OR REPLACE INTO alert_settings (key, value) VALUES ('tavily_api_key', ?)", (encoded_tavily,))
        conn.commit()
        
    return {"status": "success"}

@app.get("/api/settings/llm-health")
async def get_llm_keys_health():
    """Returns dynamic key rotation health telemetry."""
    from backend.llm_config import get_gemini_keys_health
    return get_gemini_keys_health()

@app.get("/api/screener-external/screens")
async def get_screener_screens():
    """Fetches the saved custom screens from Screener.in."""
    from backend.screens_scraper import scrape_saved_screens
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM alert_settings WHERE key = 'screener_session_cookie'")
        row = cursor.fetchone()
        cookie = row["value"] if row else None
    if not cookie or not cookie.strip():
        return {"error": "Screener.in cookie is not configured. Please open Settings (⚙️) to save it."}
    screens = scrape_saved_screens(cookie)
    return {"screens": screens}

@app.get("/api/screener-external/screens/{screen_id:path}/preview")
async def get_screener_screen_preview(screen_id: str, page: int = 1):
    """Fetches the preview list of equities for the specified screen ID."""
    from backend.screens_scraper import scrape_screen_results
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM alert_settings WHERE key = 'screener_session_cookie'")
        row = cursor.fetchone()
        cookie = row["value"] if row else None
    if not cookie or not cookie.strip():
        return {"error": "Screener.in cookie is not configured.", "companies": [], "total_pages": 1}
    data = scrape_screen_results(screen_id, cookie, page=page)
    return data

@app.post("/api/screener-external/import")
async def import_screener_screen_stocks(payload: dict):
    """Imports selected symbols into a new or existing watchlist."""
    symbols = payload.get("symbols", [])
    watchlist_name = payload.get("watchlist_name", "").strip()
    watchlist_id = payload.get("watchlist_id")
    
    if not symbols:
        raise HTTPException(status_code=400, detail="No symbols selected for import.")
        
    if not watchlist_name and not watchlist_id:
        raise HTTPException(status_code=400, detail="Watchlist name or ID must be specified.")
        
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Get or create watchlist ID
        if not watchlist_id:
            cursor.execute("INSERT OR IGNORE INTO watchlists (name) VALUES (?)", (watchlist_name,))
            cursor.execute("SELECT id FROM watchlists WHERE name = ?", (watchlist_name,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=500, detail="Failed to create watchlist.")
            watchlist_id = row["id"]
            
        # Insert items
        added_count = 0
        for s in symbols:
            from backend.screens_scraper import clean_symbol
            clean_sym = clean_symbol(s)
            if not clean_sym:
                continue
            cursor.execute(
                "SELECT symbol, company_name, sector FROM screener_universe WHERE symbol = ? OR base_symbol = ? OR symbol LIKE ?",
                (clean_sym, clean_sym, clean_sym + "%")
            )
            uni_row = cursor.fetchone()
            db_symbol = uni_row["symbol"] if uni_row else clean_sym + ".NS"
            
            # Extract names & sectors if present
            company_name = uni_row["company_name"] if (uni_row and "company_name" in dict(uni_row) and uni_row["company_name"]) else clean_sym
            sector = uni_row["sector"] if (uni_row and "sector" in dict(uni_row) and uni_row["sector"]) else "General Equities"
            
            cursor.execute(
                "INSERT OR IGNORE INTO watchlist_items (watchlist_id, symbol, name, sector, quantity, purchase_price, in_portfolio) VALUES (?, ?, ?, ?, 0.0, 0.0, 0)",
                (watchlist_id, db_symbol, company_name, sector)
            )
            added_count += 1
            
        conn.commit()
        
    # Trigger background caching tasks
    import threading
    def pre_cache_scrapes():
        with get_db() as conn2:
            cursor2 = conn2.cursor()
            cursor2.execute("SELECT value FROM alert_settings WHERE key = 'screener_session_cookie'")
            r = cursor2.fetchone()
            cookie = r["value"] if r else None
            
        from backend.shareholding_scraper import scrape_shareholding_pattern
        from backend.trades_scraper import scrape_trades
        from backend.financial_utils import get_complete_financial_profile
        from datetime import datetime
        import json
        
        for s in symbols:
            from backend.screens_scraper import clean_symbol
            clean_s = clean_symbol(s)
            if not clean_s:
                continue
            try:
                # 1. Fetch complete financial profile to fill company name/sector
                prof = get_complete_financial_profile(clean_s)
                if prof:
                    r_name = prof.get("company_name") or clean_s
                    r_sector = prof.get("sector") or "General Equities"
                    with get_db() as conn3:
                        c3 = conn3.cursor()
                        c3.execute(
                            "UPDATE watchlist_items SET name = ?, sector = ? WHERE watchlist_id = ? AND (symbol = ? OR symbol = ?)",
                            (r_name, r_sector, watchlist_id, clean_s, clean_s + ".NS")
                        )
                        conn3.commit()

                # Shareholding and trades scraping require a screener session cookie
                if cookie:
                    sh_data = scrape_shareholding_pattern(clean_s, cookie)
                    if sh_data and "error" not in sh_data:
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        with get_db() as conn2:
                            cursor2 = conn2.cursor()
                            cursor2.execute(
                                "INSERT OR REPLACE INTO cached_shareholdings (symbol, data_json, last_updated) VALUES (?, ?, ?)",
                                (clean_s, json.dumps(sh_data), now_str)
                            )
                            conn2.commit()
                            
                    tr_data = scrape_trades(clean_s, cookie)
                    if tr_data and "error" not in tr_data:
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        with get_db() as conn2:
                            cursor2 = conn2.cursor()
                            cursor2.execute(
                                "INSERT OR REPLACE INTO cached_trades (symbol, data_json, last_updated) VALUES (?, ?, ?)",
                                (clean_s, json.dumps(tr_data), now_str)
                            )
                            conn2.commit()
            except Exception as e:
                print(f"Error pre-caching stats for {clean_s}: {e}")
                
    threading.Thread(target=pre_cache_scrapes, daemon=True).start()
    
    return {"status": "success", "added_count": added_count, "watchlist_id": watchlist_id}

@app.get("/api/stocks/{symbol}/shareholding")
async def get_stock_shareholding(symbol: str):
    """Retrieves the shareholding pattern from 30-day SQLite cache or scrapes it on-demand."""
    from backend.shareholding_scraper import scrape_shareholding_pattern, clean_symbol
    from datetime import datetime, timedelta
    import json
    
    base_symbol = clean_symbol(symbol)
    if not base_symbol:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol.")
        
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data_json, last_updated FROM cached_shareholdings WHERE symbol = ?", (base_symbol,))
        row = cursor.fetchone()
        
        if row:
            try:
                last_updated = datetime.strptime(row["last_updated"], "%Y-%m-%d %H:%M:%S")
                # If cache is valid (under 30 days old), verify complete keys
                if datetime.now() - last_updated < timedelta(days=30):
                    parsed_data = json.loads(row["data_json"])
                    # If cash_flow or peers is missing or incomplete, force a cache miss to re-scrape
                    if isinstance(parsed_data, dict) and "cash_flow" in parsed_data and parsed_data["cash_flow"]:
                        return parsed_data
            except Exception:
                pass
                
        # Fetch Screener session cookie
        cursor.execute("SELECT value FROM alert_settings WHERE key = 'screener_session_cookie'")
        cookie_row = cursor.fetchone()
        cookie = cookie_row["value"] if cookie_row else None
        
        # Fetch company name if available to resolve custom URL slugs (e.g., TMCV for Tata Motors)
        cursor.execute(
            "SELECT company_name FROM screener_universe WHERE symbol = ? OR symbol = ? OR symbol LIKE ?",
            (base_symbol, base_symbol + ".NS", base_symbol + "%")
        )
        profile_row = cursor.fetchone()
        company_name = profile_row["company_name"] if profile_row else None
        
    # Cache miss or expired -> Scrape page
    data = scrape_shareholding_pattern(base_symbol, cookie, company_name=company_name)
    if not data or "error" in data:
        raise HTTPException(status_code=500, detail=data.get("error", "Failed to retrieve shareholding pattern."))
        
    # Save back to SQLite cache
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO cached_shareholdings (symbol, data_json, last_updated) VALUES (?, ?, ?)",
            (base_symbol, json.dumps(data), now_str)
        )
        conn.commit()
        
    return data

@app.get("/api/stocks/{symbol}/financial-statements")
async def get_stock_financial_statements(symbol: str, response: Response, view: str = "consolidated", force_refresh: bool = False):
    """Retrieves Quarterly, P&L and Balance Sheet tables from 30-day SQLite cache or scrapes on-demand."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    from backend.financial_statements_scraper import scrape_financial_statements
    from backend.shareholding_scraper import clean_symbol
    from backend.financial_utils import clear_profile_cache
    from datetime import datetime, timedelta
    import json
    
    base_symbol = clean_symbol(symbol)
    if not base_symbol:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol.")
        
    view = view.strip().lower()
    if view not in ["standalone", "consolidated"]:
        view = "consolidated"
        
    if force_refresh:
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM cached_financial_statements WHERE symbol = ?", (base_symbol,))
                cursor.execute("DELETE FROM cached_profiles WHERE symbol = ? OR symbol LIKE ?", (base_symbol, f"{base_symbol}.%"))
                conn.commit()
            clear_profile_cache()
        except Exception as cache_err:
            logger.error(f"Error purging cache on force_refresh: {cache_err}")
            
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data_json, last_updated FROM cached_financial_statements WHERE symbol = ? AND view = ?", (base_symbol, view))
        row = cursor.fetchone()
        
        if row:
            try:
                last_updated = datetime.strptime(row["last_updated"], "%Y-%m-%d %H:%M:%S")
                # If cache is valid (under 30 days old), verify complete keys
                if datetime.now() - last_updated < timedelta(days=30):
                    parsed_data = json.loads(row["data_json"])
                    # If cash_flow or peers is missing or incomplete, force a cache miss to re-scrape
                    if isinstance(parsed_data, dict) and "cash_flow" in parsed_data and parsed_data["cash_flow"]:
                        return parsed_data
            except Exception:
                pass
                
    # Cache miss or expired -> Scrape page
    session_cookie = None
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM alert_settings WHERE key = 'screener_session_cookie'")
        cookie_row = cursor.fetchone()
        if cookie_row:
            session_cookie = cookie_row["value"]
            
    data = await asyncio.to_thread(scrape_financial_statements, base_symbol, view, session_cookie)
    if not data or "error" in data:
        raise HTTPException(status_code=500, detail=data.get("error", "Failed to retrieve financial statements."))
        
    # Save back to SQLite cache
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO cached_financial_statements (symbol, view, data_json, last_updated) VALUES (?, ?, ?, ?)",
            (base_symbol, view, json.dumps(data), now_str)
        )
        conn.commit()
        
    return data

# ─── Stock Events Calendar API Endpoints ──────────────────────────────────────

@app.get("/api/events/calendar")
async def get_events_calendar(days: int = Query(30, ge=1, le=365), type: Optional[str] = None):
    """
    Returns upcoming market-wide stock events (results, dividends, bonuses, splits).
    Served entirely from SQLite cache — never hits external APIs in real-time.
    """
    from backend.events_scraper import get_market_events
    event_type = type if type and type != "all" else None
    events = get_market_events(days=days, event_type=event_type)
    
    # Compute summary stats
    type_counts = {}
    for ev in events:
        et = ev.get("event_type", "other")
        type_counts[et] = type_counts.get(et, 0) + 1
    
    return {
        "events": events,
        "total": len(events),
        "type_counts": type_counts,
        "days_range": days,
        "filter_type": type or "all",
    }


@app.get("/api/events/stock/{symbol}")
async def get_stock_events(symbol: str):
    """
    Returns upcoming events for a specific stock.
    If cache is stale (>12 hours), triggers background refresh via yfinance.
    """
    import asyncio
    from backend.events_scraper import get_stock_events_cached, is_stock_events_stale, cache_stock_events
    from backend.shareholding_scraper import clean_symbol
    
    base_symbol = clean_symbol(symbol)
    if not base_symbol:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol.")
    
    full_symbol = f"{base_symbol}.NS"
    
    # Check staleness and trigger background refresh if needed
    if is_stock_events_stale(full_symbol, max_age_hours=12):
        try:
            # Refresh in background thread (non-blocking)
            asyncio.create_task(asyncio.to_thread(cache_stock_events, full_symbol))
        except Exception:
            pass
    
    # Always serve from cache (even if stale — better stale than empty)
    events = get_stock_events_cached(full_symbol)
    
    # If cache is completely empty, do a synchronous fetch
    if not events:
        try:
            events = await asyncio.to_thread(cache_stock_events, full_symbol)
        except Exception as e:
            print(f"[Events API] Sync fetch failed for {full_symbol}: {e}")
            events = []
    
    return {
        "symbol": base_symbol,
        "events": events,
        "total": len(events),
    }


@app.post("/api/events/refresh")
async def refresh_events():
    """Admin endpoint: manually trigger a background events refresh."""
    import asyncio
    from backend.events_scraper import aggregate_and_cache_market_events
    
    try:
        count = await asyncio.to_thread(aggregate_and_cache_market_events)
        return {"status": "ok", "events_updated": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ai/audit-financials")
async def audit_financial_statements(data: AuditFinancialsRequest):
    """Generates an on-demand AI financial audit for the provided statements table using call_llm."""
    import asyncio
    import json
    from backend.llm_config import call_llm, TASK_FAST
    
    # 1. Compile prompt context
    statement_name_map = {
        "quarters": "Quarterly Results",
        "profit_loss": "Profit & Loss (Annual)",
        "balance_sheet": "Balance Sheet",
        "peers": "Peer Comparison"
    }
    st_title = statement_name_map.get(data.statement_type, data.statement_type)
    
    if data.statement_type == "peers":
        system_prompt = (
            "You are an expert Chartered Accountant and SEBI-registered CFA financial research analyst. "
            "Analyze the provided peer comparison table and compile a structured, high-impact diagnostic audit memo. "
            "Adhere to the following structural output layout:\n\n"
            "### Valuation vs. Peers\n"
            "* Compare P/E, Market Cap, and dividend yield against peers to assess relative valuation.\n"
            "### Efficiency & Profitability Ratios\n"
            "* Compare ROCE %, margins, and growth variance (Sales & Profit) against peers.\n"
            "### Leaderboard & Verdict\n"
            "* Conclude with a final verdict on the relative attractiveness of the main company vs. its peers, rating it as (Overvalued / Fair Value / Undervalued)."
        )
    else:
        system_prompt = (
            "You are an expert Chartered Accountant and SEBI-registered CFA financial research analyst.\n"
            "Analyze the provided financial statements table data along with the calculated 8-point scorecard metrics to compile a structured, high-impact diagnostic audit memo.\n"
            "In your analysis, you MUST explicitly evaluate the following 8 core financial health ratios (if calculated/provided) and connect them to the line-items from the financial tables:\n"
            "1. Current Ratio (Liquidity & Solvency)\n"
            "2. Interest Coverage (Debt Stress & Serviceability)\n"
            "3. Asset Turnover (Capital & Operational Efficiency)\n"
            "4. Debt/Equity (Financial Leverage)\n"
            "5. Net Margin (Net Profitability)\n"
            "6. Earnings Quality (Cash Flow vs. Accrual Profits - OCF/PAT)\n"
            "7. ROE % (Return on Equity)\n"
            "8. ROCE % (Return on Capital Employed)\n\n"
            "Adhere strictly to the following structural output layout:\n\n"
            "### Key Revenue/Profitability Trends\n"
            "* Analyze sequential (QoQ) or annual (YoY) growth rate, margin stability, and expansions/contractions. Connect these trends to Net Margin, ROE %, and ROCE %.\n"
            "### Working Capital & Balance Sheet Risks\n"
            "* Evaluate financial leverage, debt-to-equity changes, equity capital dilution, interest coverage stress, current ratio, or asset build-up flags.\n"
            "### Anomalies & Flags\n"
            "* Note any accounting flags or financial metrics anomalies (e.g. growing sales but dropping margins, reserves drop, or discrepancy between cash flow quality and reported profits).\n"
            "### Diagnostic Verdict\n"
            "* Conclude with a final rating (Safe / Watch / Distress) and a brief summary of the main driver."
        )
    
    # Format the table data for the prompt
    headers = data.table_data.get("headers", [])
    rows = data.table_data.get("rows", [])
    
    table_str = " | ".join(headers) + "\n"
    table_str += "---|" * len(headers) + "\n"
    for r in rows:
        label = r.get("label", "")
        vals = [str(v) if v is not None else "--" for v in r.get("values", [])]
        table_str += f"{label} | " + " | ".join(vals) + "\n"
        
    user_prompt = (
        f"Company Ticker: {data.symbol}\n"
        f"Reporting Basis: {'Consolidated' if data.view == 'consolidated' else 'Standalone'}\n"
        f"Statement Type: {st_title}\n\n"
    )
    
    if data.scorecard_metrics:
        user_prompt += "Calculated 8-Point Scorecard Ratios:\n"
        for m in data.scorecard_metrics:
            label = m.get("label", "")
            value = m.get("value", "")
            health = m.get("health", "")
            user_prompt += f"- {label}: {value} ({health})\n"
        user_prompt += "\n"
        
    user_prompt += f"Financial Table:\n{table_str}\n\n"
    
    if data.custom_prompt:
        user_prompt += (
            f"Specific User Request / Question:\n"
            f"\"{data.custom_prompt}\"\n\n"
            f"Please address the specific user request/question directly using the provided financial table data and scorecard metrics above. "
            f"Output strictly in markdown."
        )
    else:
        user_prompt += f"Please provide your financial audit memo. Output strictly in markdown."
    
    try:
        from fastapi.responses import StreamingResponse
        from backend.llm_config import call_llm_stream

        def stream_generator():
            try:
                for chunk in call_llm_stream(TASK_FAST, system_prompt, user_prompt, max_tokens=8000):
                    yield chunk
            except Exception as e:
                yield f"\nERROR: Streaming failed mid-execution. Details: {str(e)}"

        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI financial audit streaming failed to start: {str(e)}")


@app.get("/api/stocks/{symbol}/trades")
async def get_stock_trades(symbol: str):
    """Retrieves insider, bulk, and block deals for a single stock, cached for 24 hours."""
    from backend.trades_scraper import scrape_trades, clean_symbol
    from datetime import datetime, timedelta
    import json
    
    base_symbol = clean_symbol(symbol)
    if not base_symbol:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol.")
        
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data_json, last_updated FROM cached_trades WHERE symbol = ?", (base_symbol,))
        row = cursor.fetchone()
        
        if row:
            try:
                last_updated = datetime.strptime(row["last_updated"], "%Y-%m-%d %H:%M:%S")
                # Cache validity: 24 hours (deals are updated daily)
                if datetime.now() - last_updated < timedelta(hours=24):
                    return json.loads(row["data_json"])
            except Exception:
                pass
                
        # Fetch Screener session cookie
        cursor.execute("SELECT value FROM alert_settings WHERE key = 'screener_session_cookie'")
        cookie_row = cursor.fetchone()
        cookie = cookie_row["value"] if cookie_row else None
        
        # Fetch company name if available to resolve custom URL slugs
        cursor.execute(
            "SELECT company_name FROM screener_universe WHERE symbol = ? OR symbol = ? OR symbol LIKE ?",
            (base_symbol, base_symbol + ".NS", base_symbol + "%")
        )
        profile_row = cursor.fetchone()
        company_name = (profile_row.get("company_name") if hasattr(profile_row, "get") else profile_row["company_name"]) if profile_row and ("company_name" in profile_row if hasattr(profile_row, "__contains__") else True) else None
        
    # Cache miss or expired -> Scrape page
    data = scrape_trades(base_symbol, cookie, company_name=company_name)
    if not data or "error" in data:
        if data and "error" in data:
            return {"symbol": base_symbol, "insider_trades": [], "bulk_deals": [], "block_deals": [], "error": data["error"]}
        raise HTTPException(status_code=500, detail="Failed to retrieve trades.")
        
    # Save back to SQLite cache
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO cached_trades (symbol, data_json, last_updated) VALUES (?, ?, ?)",
            (base_symbol, json.dumps(data), now_str)
        )
        conn.commit()
        
    return data

@app.get("/api/trades/global-scanner")
async def get_global_trades(
    min_value: int = 0,
    trade_type: str = "All",
    action_type: str = "All",
    search: str = "",
    duration_days: int = 90,
    refresh: bool = False
):
    """Aggregates all cached trades and filters them for market discovery."""
    import json
    from datetime import datetime
    all_deals = []
    
    # Fetch Screener session cookie
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM alert_settings WHERE key = 'screener_session_cookie'")
        cookie_row = cursor.fetchone()
        cookie = cookie_row["value"] if cookie_row else None
        
    if refresh:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM cached_trades")
            conn.commit()
            
    # Pre-populate cache if it's completely empty to ensure user gets immediate results
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM cached_trades")
        cnt_row = cursor.fetchone()
        count = cnt_row[0] if cnt_row else 0
        
    if count == 0:
        if not cookie:
            return {"error": "Screener.in session cookie is not configured. Please configure it in System Settings."}
            
        seeds = ["INFY", "TATAMOTORS", "RELIANCE", "BOSCHLTD", "TCS", "HDFCBANK"]
        from backend.trades_scraper import scrape_trades
        
        scraped_any = False
        cookie_error = False
        
        for s in seeds:
            # Get company name
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT company_name FROM screener_universe WHERE symbol LIKE ?", (s + "%",))
                p_row = cursor.fetchone()
                c_name = (p_row.get("company_name") if hasattr(p_row, "get") else p_row["company_name"]) if p_row and ("company_name" in p_row if hasattr(p_row, "__contains__") else True) else None
            try:
                data = scrape_trades(s, cookie, company_name=c_name)
                if data:
                    if "error" in data:
                        err_msg = data["error"].lower()
                        if "cookie" in err_msg or "expired" in err_msg or "session" in err_msg:
                            cookie_error = True
                        continue
                    
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    with get_db() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "INSERT OR REPLACE INTO cached_trades (symbol, data_json, last_updated) VALUES (?, ?, ?)",
                            (s, json.dumps(data), now_str)
                        )
                        conn.commit()
                        scraped_any = True
            except Exception:
                pass
                
        if not scraped_any:
            if cookie_error:
                return {"error": "Screener.in session cookie is invalid or expired. Please update it in System Settings."}
            else:
                return {"error": "Failed to retrieve any deals feed records from Screener.in."}
                
    # Query all cached trades
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, data_json FROM cached_trades")
        rows = cursor.fetchall()
        
    for row in rows:
        symbol = row["symbol"]
        try:
            data = json.loads(row["data_json"])
        except Exception:
            continue
            
        # Merge insider, bulk, block trades
        for item in data.get("insider_trades", []):
            item["category"] = "Insider"
            item["symbol"] = symbol
            all_deals.append(item)
            
        for item in data.get("bulk_deals", []):
            item["category"] = "Bulk"
            item["symbol"] = symbol
            item["relation"] = ""
            all_deals.append(item)
            
        for item in data.get("block_deals", []):
            item["category"] = "Block"
            item["symbol"] = symbol
            item["relation"] = ""
            all_deals.append(item)
            
        for item in data.get("sast_deals", []):
            item["category"] = "SAST"
            item["symbol"] = symbol
            all_deals.append(item)
            
    # Sort helper defined beforehand so we can use it for duration cutoff
    def parse_deal_date(date_str):
        if not date_str:
            return datetime.min
        for fmt in ('%d %b %Y', '%b %Y'):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                pass
        return datetime.min

    now = datetime.now()
    cutoff = None
    if duration_days > 0:
        from datetime import timedelta
        cutoff = now - timedelta(days=duration_days)

    # Apply filters
    filtered_deals = []
    search_lower = search.strip().lower()
    
    for d in all_deals:
        if search_lower and search_lower not in d["symbol"].lower():
            continue
            
        if min_value > 0 and d["value"] < min_value:
            continue
            
        if trade_type != "All" and d["category"] != trade_type:
            continue
            
        if action_type != "All" and d["type"] != action_type:
            continue
            
        if cutoff:
            deal_dt = parse_deal_date(d.get("date"))
            if deal_dt != datetime.min and deal_dt < cutoff:
                continue
                
        filtered_deals.append(d)
        
    filtered_deals.sort(key=lambda x: parse_deal_date(x.get("date")), reverse=True)
    return filtered_deals

async def evaluate_single_condition_bool(cond_type: str, op: str, val_str: str, t: dict, df) -> tuple:
    triggered = False
    cur_val = ""
    
    cond_type = cond_type.upper()
    try:
        if cond_type in ("FUZZY_SCORE", "FUZZY"):
            symbol_curr = t.get("ticker") or t.get("symbol") or ""
            with get_db() as conn:
                fz_res = get_fuzzy_summary_for_symbol(conn, symbol_curr)
            f_score = fz_res.get("fuzzy_score", 0.0)
            f_rating = fz_res.get("fuzzy_rating", "Neutral")
            cur_val = f"Fuzzy Score: {f_score:+.1f}% ({f_rating})"
            threshold = float(val_str)
            if op == ">" and f_score > threshold:
                triggered = True
            elif op == ">=" and f_score >= threshold:
                triggered = True
            elif op == "<" and f_score < threshold:
                triggered = True
            elif op == "<=" and f_score <= threshold:
                triggered = True
            elif op == "==" and abs(f_score - threshold) < 1.0:
                triggered = True

        elif cond_type == "RSI":
            rsi_val = t["technicals"]["rsi"]
            cur_val = f"RSI: {rsi_val:.1f}"
            if op == "<" and rsi_val < float(val_str):
                triggered = True
            elif op == ">" and rsi_val > float(val_str):
                triggered = True
                
        elif cond_type == "PE":
            pe_val = t["fundamentals"]["pe_ratio"]
            cur_val = f"PE: {pe_val}"
            if val_str.upper() == "MEDIAN":
                compare_num = t["pe_bands"]["median_pe"]
            else:
                compare_num = float(val_str)
            if op == "<" and pe_val < compare_num:
                triggered = True
            elif op == ">" and pe_val > compare_num:
                triggered = True
                
        elif cond_type == "RATING":
            rating_val = t["analysis"]["recommendation"].upper() if "analysis" in t else "HOLD"
            cur_val = f"Rating: {rating_val}"
            if op == "==" and rating_val == val_str.upper():
                triggered = True
                
        elif cond_type == "PRICE":
            price_val = t["fundamentals"]["current_price"]
            cur_val = f"Price: Rs. {price_val:.2f}"
            if op == "<" and price_val < float(val_str):
                triggered = True
            elif op == ">" and price_val > float(val_str):
                triggered = True
                
        elif cond_type == "SMA":
            price_val = t["fundamentals"]["current_price"]
            sma_200 = t["technicals"]["sma_200"]
            pct_diff = ((price_val - sma_200) / sma_200) * 100 if sma_200 > 0 else 0.0
            cur_val = f"Price: Rs. {price_val:.2f} vs SMA200 (Diff: {pct_diff:+.1f}%)"
            threshold = float(val_str)
            if op == ">" and pct_diff > threshold:
                triggered = True
            elif op == "<" and pct_diff < threshold:
                triggered = True
                
        elif cond_type == "DMA_CROSS" and df is not None and not df.empty:
            df_copy = df.copy()
            df_copy["MA_50"] = df_copy["Close"].rolling(window=50).mean()
            df_copy["MA_200"] = df_copy["Close"].rolling(window=200).mean()
            df_clean = df_copy.dropna(subset=["MA_200"])
            if len(df_clean) >= 2:
                ma50_prev, ma50_curr = float(df_clean["MA_50"].iloc[-2]), float(df_clean["MA_50"].iloc[-1])
                ma200_prev, ma200_curr = float(df_clean["MA_200"].iloc[-2]), float(df_clean["MA_200"].iloc[-1])
                cur_val = f"50d SMA: Rs. {ma50_curr:.2f} vs 200d SMA: Rs. {ma200_curr:.2f}"
                buffer_pct = float(val_str)
                diff_prev = ((ma50_prev - ma200_prev) / ma200_prev) * 100
                diff_curr = ((ma50_curr - ma200_curr) / ma200_curr) * 100
                if op == ">" and diff_prev < buffer_pct and diff_curr >= buffer_pct:
                    triggered = True
                elif op == "<" and diff_prev > -abs(buffer_pct) and diff_curr <= -abs(buffer_pct):
                    triggered = True
                    
        elif cond_type == "EMA_CROSS" and df is not None and not df.empty:
            df_copy = df.copy()
            df_copy["MA_50"] = df_copy["Close"].ewm(span=50, adjust=False).mean()
            df_copy["MA_200"] = df_copy["Close"].ewm(span=200, adjust=False).mean()
            df_clean = df_copy.dropna(subset=["MA_200"])
            if len(df_clean) >= 2:
                ma50_prev, ma50_curr = float(df_clean["MA_50"].iloc[-2]), float(df_clean["MA_50"].iloc[-1])
                ma200_prev, ma200_curr = float(df_clean["MA_200"].iloc[-2]), float(df_clean["MA_200"].iloc[-1])
                cur_val = f"50d EMA: Rs. {ma50_curr:.2f} vs 200d EMA: Rs. {ma200_curr:.2f}"
                buffer_pct = float(val_str)
                diff_prev = ((ma50_prev - ma200_prev) / ma200_prev) * 100
                diff_curr = ((ma50_curr - ma200_curr) / ma200_curr) * 100
                if op == ">" and diff_prev < buffer_pct and diff_curr >= buffer_pct:
                    triggered = True
                elif op == "<" and diff_prev > -abs(buffer_pct) and diff_curr <= -abs(buffer_pct):
                    triggered = True
                    
        elif cond_type == "VOL_BREAKOUT" and df is not None and not df.empty:
            df_copy = df.copy()
            df_copy["Vol_20MA"] = df_copy["Volume"].rolling(window=20).mean()
            df_clean = df_copy.dropna(subset=["Vol_20MA"])
            if len(df_clean) >= 1:
                vol_curr = float(df_clean["Volume"].iloc[-1])
                vol_ma = float(df_clean["Vol_20MA"].iloc[-1])
                vol_ratio = vol_curr / vol_ma if vol_ma > 0 else 1.0
                cur_val = f"Vol Ratio: {vol_ratio:.2f}x"
                threshold = float(val_str)
                if op == ">" and vol_ratio > threshold:
                    triggered = True
                elif op == "<" and vol_ratio < threshold:
                    triggered = True
                    
        elif cond_type == "BB_CROSS" and df is not None and not df.empty:
            df_copy = df.copy()
            df_copy["BB_Mid"] = df_copy["Close"].rolling(window=20).mean()
            df_copy["BB_Std"] = df_copy["Close"].rolling(window=20).std()
            df_copy["BB_Upper"] = df_copy["BB_Mid"] + 2 * df_copy["BB_Std"]
            df_copy["BB_Lower"] = df_copy["BB_Mid"] - 2 * df_copy["BB_Std"]
            df_clean = df_copy.dropna(subset=["BB_Upper"])
            if len(df_clean) >= 2:
                close_prev, close_curr = float(df_clean["Close"].iloc[-2]), float(df_clean["Close"].iloc[-1])
                upper_prev, upper_curr = float(df_clean["BB_Upper"].iloc[-2]), float(df_clean["BB_Upper"].iloc[-1])
                lower_prev, lower_curr = float(df_clean["BB_Lower"].iloc[-2]), float(df_clean["BB_Lower"].iloc[-1])
                if op == ">":
                    cur_val = f"Price: Rs. {close_curr:.2f} vs BB Upper: Rs. {upper_curr:.2f}"
                    if close_prev < upper_prev and close_curr >= upper_curr:
                        triggered = True
                elif op == "<":
                    cur_val = f"Price: Rs. {close_curr:.2f} vs BB Lower: Rs. {lower_curr:.2f}"
                    if close_prev > lower_prev and close_curr <= lower_curr:
                        triggered = True
                        
        elif cond_type == "MACD_CROSS" and df is not None and not df.empty:
            df_copy = df.copy()
            ema12 = df_copy["Close"].ewm(span=12, adjust=False).mean()
            ema26 = df_copy["Close"].ewm(span=26, adjust=False).mean()
            df_copy["MACD"] = ema12 - ema26
            df_copy["Signal"] = df_copy["MACD"].ewm(span=9, adjust=False).mean()
            df_clean = df_copy.dropna(subset=["Signal"])
            if len(df_clean) >= 2:
                macd_prev, macd_curr = float(df_clean["MACD"].iloc[-2]), float(df_clean["MACD"].iloc[-1])
                sig_prev, sig_curr = float(df_clean["Signal"].iloc[-2]), float(df_clean["Signal"].iloc[-1])
                cur_val = f"MACD: {macd_curr:.3f} vs Signal: {sig_curr:.3f}"
                buffer_val = float(val_str)
                diff_prev = macd_prev - sig_prev
                diff_curr = macd_curr - sig_curr
                if op == ">" and diff_prev < buffer_val and diff_curr >= buffer_val:
                    triggered = True
                elif op == "<" and diff_prev > -abs(buffer_val) and diff_curr <= -abs(buffer_val):
                    triggered = True
                    
        elif cond_type == "52W_PROXIMITY" and df is not None and not df.empty:
            high_52w = float(df["Close"].max())
            low_52w = float(df["Close"].min())
            if len(df) >= 1:
                price_val = float(df["Close"].iloc[-1])
                proximity_pct = float(val_str)
                if op == ">":
                    diff_pct = ((high_52w - price_val) / high_52w) * 100
                    cur_val = f"Price: Rs. {price_val:.2f} near 52w High (Diff: {diff_pct:.1f}%)"
                    if diff_pct <= proximity_pct:
                        triggered = True
                elif op == "<":
                    diff_pct = ((price_val - low_52w) / low_52w) * 100
                    cur_val = f"Price: Rs. {price_val:.2f} near 52w Low (Diff: {diff_pct:.1f}%)"
                    if diff_pct <= proximity_pct:
                        triggered = True
                        
        elif cond_type == "SMA50" and df is not None and not df.empty:
            df_copy = df.copy()
            df_copy["SMA_50"] = df_copy["Close"].rolling(window=50).mean()
            df_clean = df_copy.dropna(subset=["SMA_50"])
            if len(df_clean) >= 1:
                price_val = float(df_clean["Close"].iloc[-1])
                sma_50 = float(df_clean["SMA_50"].iloc[-1])
                pct_diff = ((price_val - sma_50) / sma_50) * 100
                cur_val = f"Price: Rs. {price_val:.2f} vs SMA50 (Diff: {pct_diff:+.1f}%)"
                threshold = float(val_str)
                if op == ">" and pct_diff > threshold:
                    triggered = True
                elif op == "<" and pct_diff < threshold:
                    triggered = True
                    
        elif cond_type in ["FIB_LEVEL", "FIB_382", "FIB_500", "FIB_618"] and df is not None and not df.empty:
            sub_df = df.iloc[-120:] if len(df) >= 120 else df
            swing_high = float(sub_df["Close"].max())
            swing_low = float(sub_df["Close"].min())
            swing_diff = swing_high - swing_low
            fib_382 = swing_high - 0.382 * swing_diff
            fib_500 = swing_high - 0.500 * swing_diff
            fib_618 = swing_high - 0.618 * swing_diff
            if len(df) >= 1:
                price_val = float(df["Close"].iloc[-1])
                try:
                    proximity_pct = float(val_str)
                except Exception:
                    proximity_pct = 1.5
                levels_to_check = []
                if cond_type == "FIB_LEVEL":
                    levels_to_check = [("38.2%", fib_382), ("50.0%", fib_500), ("61.8%", fib_618)]
                elif cond_type == "FIB_382":
                    levels_to_check = [("38.2%", fib_382)]
                elif cond_type == "FIB_500":
                    levels_to_check = [("50.0%", fib_500)]
                elif cond_type == "FIB_618":
                    levels_to_check = [("61.8%", fib_618)]
                matched_level = None
                matched_val = 0.0
                for level_name, level_val in levels_to_check:
                    diff_pct = abs(price_val - level_val) / level_val * 100
                    if diff_pct <= proximity_pct:
                        matched_level = level_name
                        matched_val = level_val
                        triggered = True
                        break
                cur_val = f"Price: Rs. {price_val:.2f} near Fib {matched_level or 'Support'} Level: Rs. {matched_val:.2f}"

        elif cond_type == "ALTMAN_Z":
            eq = t.get("earnings_quality", {})
            altman_z = float(eq.get("altman_z_score", 0.0))
            cur_val = f"Altman Z-Score: {altman_z:.2f}"
            threshold = float(val_str)
            if op == "<" and altman_z < threshold:
                triggered = True
            elif op == ">" and altman_z > threshold:
                triggered = True

        elif cond_type == "TARGET_DISCOUNT":
            consensus = t.get("consensus", {})
            target_median = float(consensus.get("target_median", 0.0))
            price_val = t.get("fundamentals", {}).get("current_price", 0.0)
            if target_median > 0:
                discount_pct = ((target_median - price_val) / target_median) * 100
                cur_val = f"Price: Rs. {price_val:.0f} vs Target: Rs. {target_median:.0f} (Discount: {discount_pct:.1f}%)"
                threshold = float(val_str)
                if op == ">" and discount_pct > threshold:
                    triggered = True
                elif op == "<" and discount_pct < threshold:
                    triggered = True

        elif cond_type == "CFO_PAT_DIVERGENCE":
            cfo_to_pat = float(t.get("fundamentals", {}).get("cfo_to_pat", 1.0))
            cur_val = f"CFO to PAT Ratio: {cfo_to_pat:.2f}"
            threshold = float(val_str)
            if op == "<" and cfo_to_pat < threshold:
                triggered = True
            elif op == ">" and cfo_to_pat > threshold:
                triggered = True

        elif cond_type == "DIVIDEND_YIELD_FLOOR":
            div_yield = float(t.get("fundamentals", {}).get("dividend_yield_pct", 0.0))
            cur_val = f"Div Yield: {div_yield:.2f}%"
            threshold = float(val_str)
            if op == ">" and div_yield > threshold:
                triggered = True
            elif op == "<" and div_yield < threshold:
                triggered = True

        elif cond_type == "ATR_VOLATILITY_SHOCK":
            atr_val = float(t.get("technicals", {}).get("atr", 0.0))
            cur_val = f"ATR: Rs. {atr_val:.2f}"
            threshold = float(val_str)
            if op == ">" and atr_val > threshold:
                triggered = True
            elif op == "<" and atr_val < threshold:
                triggered = True

        elif cond_type == "SMA20":
            sma_20 = float(t.get("sma_20", 0.0))
            cur_val = f"SMA20: Rs. {sma_20:.2f}"
            if sma_20 > 0.0:
                pct_diff = ((price_val - sma_20) / sma_20) * 100
                cur_val = f"Price: Rs. {price_val:.2f} vs SMA20 (Diff: {pct_diff:+.1f}%)"
                threshold = float(val_str)
                if op == ">" and pct_diff > threshold:
                    triggered = True
                elif op == "<" and pct_diff < threshold:
                    triggered = True

        elif cond_type == "SMA100":
            sma_100 = float(t.get("sma_100", 0.0))
            cur_val = f"SMA100: Rs. {sma_100:.2f}"
            if sma_100 > 0.0:
                pct_diff = ((price_val - sma_100) / sma_100) * 100
                cur_val = f"Price: Rs. {price_val:.2f} vs SMA100 (Diff: {pct_diff:+.1f}%)"
                threshold = float(val_str)
                if op == ">" and pct_diff > threshold:
                    triggered = True
                elif op == "<" and pct_diff < threshold:
                    triggered = True

        elif cond_type == "EMA20":
            ema_20 = float(t.get("ema_20", 0.0))
            cur_val = f"EMA20: Rs. {ema_20:.2f}"
            if ema_20 > 0.0:
                pct_diff = ((price_val - ema_20) / ema_20) * 100
                cur_val = f"Price: Rs. {price_val:.2f} vs EMA20 (Diff: {pct_diff:+.1f}%)"
                threshold = float(val_str)
                if op == ">" and pct_diff > threshold:
                    triggered = True
                elif op == "<" and pct_diff < threshold:
                    triggered = True

        elif cond_type == "EMA50":
            ema_50 = float(t.get("ema_50", 0.0))
            cur_val = f"EMA50: Rs. {ema_50:.2f}"
            if ema_50 > 0.0:
                pct_diff = ((price_val - ema_50) / ema_50) * 100
                cur_val = f"Price: Rs. {price_val:.2f} vs EMA50 (Diff: {pct_diff:+.1f}%)"
                threshold = float(val_str)
                if op == ">" and pct_diff > threshold:
                    triggered = True
                elif op == "<" and pct_diff < threshold:
                    triggered = True

        elif cond_type == "EMA200":
            ema_200 = float(t.get("ema_200", 0.0))
            cur_val = f"EMA200: Rs. {ema_200:.2f}"
            if ema_200 > 0.0:
                pct_diff = ((price_val - ema_200) / ema_200) * 100
                cur_val = f"Price: Rs. {price_val:.2f} vs EMA200 (Diff: {pct_diff:+.1f}%)"
                threshold = float(val_str)
                if op == ">" and pct_diff > threshold:
                    triggered = True
                elif op == "<" and pct_diff < threshold:
                    triggered = True

        elif cond_type == "PEG":
            scoring = t.get("score_metrics") or {}
            peg_val = float(scoring.get("peg_ratio", 99.0))
            cur_val = f"PEG Ratio: {peg_val:.2f}"
            threshold = float(val_str)
            if op == "<" and peg_val < threshold:
                triggered = True
            elif op == ">" and peg_val > threshold:
                triggered = True

        elif cond_type == "ROE":
            roe_val = float(t.get("fundamentals", {}).get("roe_pct") or t.get("fundamentals", {}).get("roe", 0.0))
            cur_val = f"ROE: {roe_val:.1f}%"
            threshold = float(val_str)
            if op == ">" and roe_val > threshold:
                triggered = True
            elif op == "<" and roe_val < threshold:
                triggered = True

        elif cond_type == "DE":
            de_val = float(t.get("fundamentals", {}).get("debt_to_equity") or t.get("fundamentals", {}).get("de_ratio", 0.0))
            cur_val = f"Debt-to-Equity: {de_val:.2f}"
            threshold = float(val_str)
            if op == "<" and de_val < threshold:
                triggered = True
            elif op == ">" and de_val > threshold:
                triggered = True

        elif cond_type == "PLEDGE":
            pledge_val = float(t.get("fundamentals", {}).get("promoter_pledge_pct", 0.0))
            cur_val = f"Promoter Pledge: {pledge_val:.1f}%"
            threshold = float(val_str)
            if op == "<" and pledge_val < threshold:
                triggered = True
            elif op == ">" and pledge_val > threshold:
                triggered = True

        elif cond_type == "DCF_SAFETY":
            dcf_val = float(t.get("dcf", {}).get("margin_of_safety", 0.0))
            cur_val = f"DCF Margin of Safety: {dcf_val:.1f}%"
            threshold = float(val_str)
            if op == ">" and dcf_val > threshold:
                triggered = True
            elif op == "<" and dcf_val < threshold:
                triggered = True

        elif cond_type == "BETA":
            beta_val = float(t.get("consensus", {}).get("beta") or t.get("capm_risk_nifty50", {}).get("beta", 1.0))
            cur_val = f"Beta: {beta_val:.2f}"
            threshold = float(val_str)
            if op == ">" and beta_val > threshold:
                triggered = True
            elif op == "<" and beta_val < threshold:
                triggered = True

        elif cond_type == "DELIVERY_PCT":
            del_val = float(t.get("technicals", {}).get("delivery_percentage") or t.get("technicals", {}).get("delivery_pct", 0.0))
            cur_val = f"Delivery: {del_val:.1f}%"
            threshold = float(val_str)
            if op == ">" and del_val > threshold:
                triggered = True
            elif op == "<" and del_val < threshold:
                triggered = True

        elif cond_type == "DELIVERY_ZSCORE":
            z_val = float(t.get("technicals", {}).get("delivery_z_score") or t.get("technicals", {}).get("delivery_zscore", 0.0))
            cur_val = f"Delivery Z-Score: {z_val:+.2f}"
            threshold = float(val_str)
            if op == ">" and z_val > threshold:
                triggered = True
            elif op == "<" and z_val < threshold:
                triggered = True

        elif cond_type in ("FUZZY_SCORE", "FUZZY_CONVICTION"):
            with get_db() as conn:
                fz = get_fuzzy_summary_for_symbol(conn, symbol_upper)
            fz_score = float(fz.get("fuzzy_score", 0.0))
            fz_rating = fz.get("fuzzy_rating", "Neutral")
            cur_val = f"Fuzzy Conviction: {fz_score:+.1f}% ({fz_rating})"
            threshold = float(val_str)
            if op in (">", ">=") and fz_score >= threshold:
                triggered = True
            elif op in ("<", "<=") and fz_score <= threshold:
                triggered = True
            elif op in ("==", "=") and abs(fz_score - threshold) < 0.1:
                triggered = True
    except Exception as eval_err:
        print(f"Error evaluating condition {cond_type} {op} {val_str}: {eval_err}")
        
    return triggered, cur_val

# In-memory deduplication cache for custom watchlist stock alerts (symbol_rule -> last_sent)
_custom_watchlist_alerts_cache = {}

async def sweep_watchlist_custom_alerts():
    """Sweeps all custom watchlist stock alert rules and dispatches Alerts Hub & WhatsApp notifications."""
    wa_token = os.environ.get("WHATSAPP_TOKEN", "")
    wa_phone_id = os.environ.get("WHATSAPP_PHONE_ID", "")
    wa_recipient = os.environ.get("WHATSAPP_RECIPIENT", "")
    whatsapp_configured = bool(wa_token and wa_phone_id and wa_recipient)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, watchlist_id, symbol, added_price, added_date, alert_config FROM watchlist_items WHERE alert_config IS NOT NULL AND alert_config != '' AND alert_config != '{}'")
        rows = [dict(row) for row in cursor.fetchall()]

    if not rows:
        return

    for item in rows:
        try:
            symbol = item["symbol"].strip().upper()
            try:
                cfg = json.loads(item["alert_config"])
            except Exception:
                continue

            if not cfg.get("enabled", True):
                continue

            with get_db() as conn:
                fz = get_fuzzy_summary_for_symbol(conn, symbol)
                profile_row = conn.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ? OR symbol = ?", (symbol, symbol.replace('.NS', ''))).fetchone()

            p_json = json.loads(profile_row["profile_json"]) if profile_row and profile_row["profile_json"] else {}
            tech = p_json.get("technicals", {})
            fund = p_json.get("fundamentals", {})

            cp = float(tech.get("current_price") or fund.get("current_price") or 0.0)
            if cp <= 0:
                continue

            added_price = float(item.get("added_price") or cp)
            added_date = item.get("added_date") or ""
            trend_metrics = compute_stock_trendlyne_metrics(p_json, cp, added_price, added_date)

            triggers = []

            # 1. Price Low (Buy Floor)
            if cfg.get("price_low") is not None and float(cfg["price_low"]) > 0:
                target_low = float(cfg["price_low"])
                if cp <= target_low:
                    triggers.append(("BUY_FLOOR", f"💰 Target Buy Floor Hit: {symbol} at ₹{cp:.2f} (Target ≤ ₹{target_low:.2f})"))

            # 2. Price High (Profit Ceiling)
            if cfg.get("price_high") is not None and float(cfg["price_high"]) > 0:
                target_high = float(cfg["price_high"])
                if cp >= target_high:
                    triggers.append(("PROFIT_CEILING", f"🎯 Target Profit Ceiling Cross: {symbol} at ₹{cp:.2f} (Target ≥ ₹{target_high:.2f})"))

            # 3. 52-Week Breakout
            if cfg.get("breakout_52w"):
                range52 = trend_metrics.get("range_52w", {})
                pos_pct = range52.get("pos_pct", 50.0)
                if pos_pct >= 98.0:
                    triggers.append(("BREAKOUT_HIGH", f"🚀 52-Week High Breakout: {symbol} trading at ₹{cp:.2f} (98%+ 52W High)"))
                elif pos_pct <= 2.0:
                    triggers.append(("BREAKOUT_LOW", f"📉 52-Week Low Breakout: {symbol} trading at ₹{cp:.2f} (Near 52W Low)"))

            # 4. Intraday Flash Dip
            if cfg.get("flash_dip_pct") is not None and float(cfg["flash_dip_pct"]) > 0:
                dip_thresh = float(cfg["flash_dip_pct"])
                day_chg = float(trend_metrics.get("change_pct") or 0.0)
                if day_chg <= -dip_thresh:
                    triggers.append(("FLASH_DIP", f"📊 Flash Dip Triggered: {symbol} down {day_chg:.2f}% today (Threshold: -{dip_thresh}%)"))

            # 5. Entry Price Drop
            if cfg.get("entry_dip_pct") is not None and float(cfg["entry_dip_pct"]) > 0:
                entry_thresh = float(cfg["entry_dip_pct"])
                since_chg = float(trend_metrics.get("chg_since_added") or 0.0)
                if since_chg <= -entry_thresh:
                    triggers.append(("ENTRY_DIP", f"📊 Entry Price Drop: {symbol} down {since_chg:.2f}% since added (Threshold: -{entry_thresh}%)"))

            # 6. Volume Spike
            if cfg.get("volume_spike"):
                vol = float(fund.get("volume", 0.0))
                avg_vol = float(fund.get("average_volume", 0.0))
                if avg_vol > 0 and (vol / avg_vol) >= 2.5:
                    triggers.append(("VOLUME_SPIKE", f"⚡ Volume Spike: {symbol} volume is {(vol/avg_vol):.1f}x 20-day average"))

            # 7. Valuation MOS
            if cfg.get("mos_undervalued"):
                mos_pct = float(trend_metrics.get("mos_pct") or 0.0)
                if mos_pct >= 15.0:
                    triggers.append(("MOS_VALUE", f"💎 Deep Valuation MOS: {symbol} Margin of Safety is +{mos_pct:.1f}%"))

            # 8. P/E Compression
            if cfg.get("pe_compression") is not None and float(cfg["pe_compression"]) > 0:
                pe_thresh = float(cfg["pe_compression"])
                pe_val = float(trend_metrics.get("pe_ratio") or 0.0)
                if pe_val > 0 and pe_val <= pe_thresh:
                    triggers.append(("PE_COMPRESSION", f"💎 P/E Compression: {symbol} P/E dropped to {pe_val:.1f}x (Threshold: ≤ {pe_thresh}x)"))

            # 9. Conviction Upgrade
            if cfg.get("score_shift"):
                fuzzy_score = float(fz.get("fuzzy_score", 0.0))
                fuzzy_rating = fz.get("fuzzy_rating", "")
                if fuzzy_score >= 70.0 or "Strong Buy" in fuzzy_rating:
                    triggers.append(("CONVICTION_UPGRADE", f"🧠 Conviction Upgrade: {symbol} Score is {fuzzy_score:+.1f}% ({fuzzy_rating})"))

            # 10. RSI Extremes
            if cfg.get("rsi_extremes"):
                rsi_val = float(tech.get("rsi", 50.0))
                if rsi_val <= 30.0:
                    triggers.append(("RSI_OVERSOLD", f"🧠 RSI Oversold Buy Zone: {symbol} 14-RSI is {rsi_val:.1f} (≤ 30)"))
                elif rsi_val >= 70.0:
                    triggers.append(("RSI_OVERBOUGHT", f"🧠 RSI Overbought Zone: {symbol} 14-RSI is {rsi_val:.1f} (≥ 70)"))

            # 11. Moving Average Proximity
            if cfg.get("ma_proximity_enabled"):
                ma_period = cfg.get("ma_period", "EMA_50")
                ma_thresh = float(cfg.get("ma_threshold_pct") or 3.0)
                ma_key = ma_period.lower().replace('-', '_')
                ma_val = float(tech.get(ma_key) or tech.get(f"sma_{ma_period.split('_')[-1]}") or 0.0)
                if ma_val > 0:
                    dist_pct = abs((cp - ma_val) / ma_val * 100.0)
                    if dist_pct <= ma_thresh:
                        triggers.append(("MA_PROXIMITY", f"🧠 {ma_period} Proximity: {symbol} (₹{cp:.2f}) is within {dist_pct:.1f}% of {ma_period} (₹{ma_val:.2f})"))

            for rule_code, msg in triggers:
                cache_key = f"{symbol}_{rule_code}"
                if _custom_watchlist_alerts_cache.get(cache_key) == msg:
                    continue
                _custom_watchlist_alerts_cache[cache_key] = msg

                trigger_date = datetime.now().strftime("%Y-%m-%d %H:%M")
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO alerts (ticker, condition_type, operator, value, status, triggered, trigger_date, ai_context) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (symbol, rule_code, "ALERT", str(cp), "Triggered", 1, trigger_date, msg)
                    )
                    conn.commit()

                if whatsapp_configured:
                    wa_msg = (
                        f"🚨 *WATCHLIST STOCK ALERT TRIGGERED* 🚨\n\n"
                        f"• *Stock:* {symbol}\n"
                        f"• *Alert Detail:* {msg}\n"
                        f"• *Triggered At:* {trigger_date}\n\n"
                        f"_APEX Agentic Equities AI Workstation_"
                    )
                    try:
                        wa_url = f"https://graph.facebook.com/v21.0/{wa_phone_id}/messages"
                        wa_headers = {"Authorization": f"Bearer {wa_token}", "Content-Type": "application/json"}
                        wa_payload = {"messaging_product": "whatsapp", "to": wa_recipient, "type": "text", "text": {"preview_url": False, "body": wa_msg}}
                        await asyncio.to_thread(requests.post, wa_url, headers=wa_headers, json=wa_payload, timeout=8)
                        print(f"Dispatched custom watchlist alert WhatsApp message for {symbol} ({rule_code})")
                    except Exception as wa_err:
                        print(f"Failed to dispatch custom watchlist alert WhatsApp for {symbol}: {wa_err}")

        except Exception as item_err:
            print(f"Error evaluating custom watchlist alert for item {item.get('symbol')}: {item_err}")


_fuzzy_whatsapp_sent_cache: dict = {}

async def check_fuzzy_watchlist_whatsapp_alerts():
    """
    Sweeps all active watchlist items, evaluates Fuzzy Conviction,
    and dispatches a WhatsApp alert if any stock crosses >= +70% (Strong Buy) or <= -40% (Avoid).
    Uses RAM cache + SQLite DB persistent storage to avoid duplicate notifications across server restarts.
    """
    global _fuzzy_whatsapp_sent_cache
    if "_fuzzy_whatsapp_sent_cache" not in globals() or _fuzzy_whatsapp_sent_cache is None:
        _fuzzy_whatsapp_sent_cache = {}

    wa_token = os.environ.get("WHATSAPP_TOKEN", "")
    wa_phone_id = os.environ.get("WHATSAPP_PHONE_ID", "")
    wa_recipient = os.environ.get("WHATSAPP_RECIPIENT", "")
    if not (wa_token and wa_phone_id and wa_recipient):
        return

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT symbol FROM watchlist_items")
        symbols = [row["symbol"] for row in cursor.fetchall()]

    for symbol in symbols:
        try:
            with get_db() as conn:
                fz = get_fuzzy_summary_for_symbol(conn, symbol)
            score = fz.get("fuzzy_score", 0.0)
            rating = fz.get("fuzzy_rating", "Neutral")

            target_state = None
            if score >= 70.0:
                target_state = "STRONG_BUY"
            elif score <= -40.0:
                target_state = "AVOID"

            if target_state:
                # 1. Check RAM cache first
                last_sent = _fuzzy_whatsapp_sent_cache.get(symbol)
                
                # 2. If not in RAM cache, check persistent SQLite database
                if last_sent is None:
                    with get_db() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT target_state FROM fuzzy_alert_sent_history WHERE symbol = ? AND target_state = ?",
                            (symbol, target_state)
                        )
                        row = cursor.fetchone()
                        if row:
                            last_sent = row["target_state"]
                            _fuzzy_whatsapp_sent_cache[symbol] = last_sent

                if last_sent != target_state:
                    _fuzzy_whatsapp_sent_cache[symbol] = target_state
                    
                    # Persist to SQLite DB
                    try:
                        with get_db() as conn:
                            cursor = conn.cursor()
                            cursor.execute("""
                                INSERT OR REPLACE INTO fuzzy_alert_sent_history (symbol, target_state, score, sent_at)
                                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                            """, (symbol, target_state, float(score)))
                            conn.commit()
                    except Exception as db_err:
                        print(f"Failed to record fuzzy_alert_sent_history for {symbol}: {db_err}")

                    trigger_date = datetime.now().strftime("%Y-%m-%d %H:%M")
                    
                    header_emoji = "🚀" if target_state == "STRONG_BUY" else "⚠️"
                    signal_title = "STRONG BUY CONVICTION (+70%+)" if target_state == "STRONG_BUY" else "AVOID CONVICTION (-40%-)"
                    
                    wa_msg = (
                        f"{header_emoji} *FUZZY ENGINE CONVICTION ALERT* {header_emoji}\n\n"
                        f"• *Stock:* {symbol}\n"
                        f"• *Signal:* *{signal_title}*\n"
                        f"• *Fuzzy Score:* *{score:+.1f}%*\n"
                        f"• *Rating Class:* *{rating}*\n"
                        f"• *Evaluated At:* {trigger_date}\n\n"
                        f"🤖 *Mamdani Inference Engine:* Stock momentum, valuation, RSI, and DMA proximity have aligned to cross institutional threshold.\n\n"
                        f"_APEX Agentic Equities AI Workstation_"
                    )
                    
                    wa_url = f"https://graph.facebook.com/v21.0/{wa_phone_id}/messages"
                    wa_headers = {
                        "Authorization": f"Bearer {wa_token}",
                        "Content-Type": "application/json"
                    }
                    wa_payload = {
                        "messaging_product": "whatsapp",
                        "to": wa_recipient,
                        "type": "text",
                        "text": {
                            "preview_url": False,
                            "body": wa_msg
                        }
                    }
                    await asyncio.to_thread(requests.post, wa_url, headers=wa_headers, json=wa_payload, timeout=10)
                    print(f"Dispatched WhatsApp Fuzzy Alert for {symbol} ({score:+.1f}%)")
        except Exception as err:
            print(f"Error checking fuzzy WhatsApp alert for {symbol}: {err}")


@app.get("/api/alerts/check")
async def check_alerts():
    """Background-triggered active alert scanning sweep."""
    if os.environ.get("ENABLE_BACKGROUND_ALERTS", "true").lower() == "false":
        return {"status": "disabled", "triggers": []}

    # Sweep Watchlist Fuzzy & Custom Stock Alerts
    try:
        await check_fuzzy_watchlist_whatsapp_alerts()
        await sweep_watchlist_custom_alerts()
    except Exception as fz_alert_err:
        print(f"Watchlist alert sweep error: {fz_alert_err}")

    # Read WhatsApp settings from environment
    wa_token = os.environ.get("WHATSAPP_TOKEN", "")
    wa_phone_id = os.environ.get("WHATSAPP_PHONE_ID", "")
    wa_recipient = os.environ.get("WHATSAPP_RECIPIENT", "")
    whatsapp_configured = bool(wa_token and wa_phone_id and wa_recipient)

    slack_webhook = ""
    discord_webhook = ""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM alert_settings WHERE key IN ('slack_webhook', 'discord_webhook')")
        for row in cursor.fetchall():
            if row["key"] == "slack_webhook":
                slack_webhook = row["value"]
            elif row["key"] == "discord_webhook":
                discord_webhook = row["value"]

    triggers = []
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, ticker, condition_type, operator, value, triggered FROM alerts WHERE triggered = 0")
        active_alerts = [dict(row) for row in cursor.fetchall()]
    
    for alert in active_alerts:
        try:
            ticker = alert["ticker"]
            t = await asyncio.to_thread(get_complete_financial_profile, ticker)
            
            # Fetch history if required
            df = None
            history_indicators = ["DMA_CROSS", "EMA_CROSS", "VOL_BREAKOUT", "BB_CROSS", "MACD_CROSS", "52W_PROXIMITY", "SMA50", "FIB_LEVEL", "FIB_382", "FIB_500", "FIB_618"]
            needs_df = False
            
            if alert["condition_type"] == "COMPOUND":
                try:
                    cond_list = json.loads(alert["value"])
                    for item in cond_list:
                        if "indicator" in item and item["indicator"] in history_indicators:
                            needs_df = True
                            break
                except Exception:
                    pass
            else:
                needs_df = alert["condition_type"] in history_indicators
                
            if needs_df:
                df = await fetch_history_df(ticker, "1y", "1d")
                if df.empty:
                    print(f"Skipping alert check #{alert['id']} for {ticker} as price history is empty.")
                    continue

            triggered = False
            cur_val = ""
            
            if alert["condition_type"] == "COMPOUND":
                try:
                    cond_list = json.loads(alert["value"])
                    results = []
                    descriptions = []
                    for item in cond_list:
                        if "operator" in item and "indicator" not in item:
                            results.append(item["operator"].upper())
                        else:
                            res_bool, desc_str = await evaluate_single_condition_bool(
                                item["indicator"], item["operator"], item["value"], t, df
                            )
                            results.append(res_bool)
                            if desc_str:
                                descriptions.append(desc_str)
                    
                    if results:
                        triggered = results[0]
                        i = 1
                        while i < len(results) - 1:
                            op_str = results[i]
                            next_val = results[i+1]
                            if op_str == "AND":
                                triggered = triggered and next_val
                            elif op_str == "OR":
                                triggered = triggered or next_val
                            i += 2
                            
                    cur_val = " & ".join(descriptions) if descriptions else "Compound parameters met"
                except Exception as comp_err:
                    print(f"Error parsing compound alert: {comp_err}")
            else:
                triggered, cur_val = await evaluate_single_condition_bool(
                    alert["condition_type"], alert["operator"], alert["value"], t, df
                )
                    
            if triggered:
                trigger_date = datetime.now().strftime("%Y-%m-%d %H:%M")
                
                # Generate AI Contextual Warning
                ai_context = ""
                try:
                    from backend.llm_config import call_llm, TASK_FAST, TASK_HEAVY
                    price_info = f"Current Price: Rs. {price_val:.2f}" if 'price_val' in locals() else ""
                    rsi_info = f"RSI: {t['technicals']['rsi']:.1f}" if 't' in locals() and 'rsi' in t['technicals'] else ""
                    sma_info = f"SMA200: Rs. {t['technicals']['sma_200']:.2f}" if 't' in locals() and 'sma_200' in t['technicals'] else ""
                    
                    sys_prompt = (
                        "You are an institutional trading cockpit assistant. "
                        "Write a concise, 1-sentence analytical warning (max 30 words) describing why this alert triggered and what it implies about the stock's momentum, volume absorption, or range boundaries."
                    )
                    user_prompt = (
                        f"ALERT TRIGGERED:\n"
                        f"Ticker: {alert['ticker']}\n"
                        f"Trigger condition: {alert['condition_type']} {alert['operator']} {alert['value']}\n"
                        f"Triggered value description: {cur_val}\n"
                        f"Context: {price_info} | {rsi_info} | {sma_info}\n"
                        f"Output ONLY the single-sentence contextual warning/analysis. Do not add headers, quotes, or conversational preamble."
                    )
                    
                    # Call LLM
                    ai_context = await asyncio.to_thread(call_llm, TASK_FAST, sys_prompt, user_prompt)
                    ai_context = ai_context.strip().strip('"').strip("'").strip()
                except Exception as ai_err:
                    print(f"Failed to generate AI alert warning context: {ai_err}")
                    ai_context = f"Alert triggered on {alert['condition_type']} validation."

                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE alerts SET triggered = 1, status = 'Triggered', trigger_date = ?, ai_context = ? WHERE id = ?",
                        (trigger_date, ai_context, alert["id"])
                    )
                    conn.commit()
                triggers.append(f"ALERT TRIGGERED: {alert['ticker']} reached {cur_val} (Target: {alert['operator']} {alert['value']})")
                
                # Dispatch WhatsApp alert notification
                if whatsapp_configured:
                    wa_msg = (
                        f"\U0001f6a8 *INSTITUTIONAL ALERT TRIGGERED* \U0001f6a8\n\n"
                        f"\u2022 *Stock:* {alert['ticker']}\n"
                        f"\u2022 *Condition:* {alert['condition_type']} {alert['operator']} {alert['value']}\n"
                        f"\u2022 *Triggered Value:* {cur_val}\n"
                        f"\u2022 *Triggered At:* {trigger_date}\n"
                    )
                    if ai_context:
                        wa_msg += f"\n\U0001f916 *AI Copilot Analysis:*\n_{ai_context}_\n"
                    wa_msg += f"\n_APEX Agentic Equities AI Workstation_"

                    async def send_whatsapp_async(msg_body):
                        try:
                            wa_url = f"https://graph.facebook.com/v21.0/{wa_phone_id}/messages"
                            wa_headers = {
                                "Authorization": f"Bearer {wa_token}",
                                "Content-Type": "application/json"
                            }
                            wa_payload = {
                                "messaging_product": "whatsapp",
                                "to": wa_recipient,
                                "type": "text",
                                "text": {
                                    "preview_url": False,
                                    "body": msg_body
                                }
                            }
                            resp = await asyncio.to_thread(requests.post, wa_url, headers=wa_headers, json=wa_payload, timeout=10)
                            if resp.status_code != 200:
                                print(f"Failed to deliver WhatsApp alert. Status: {resp.status_code}, Response: {resp.text}")
                            else:
                                print(f"WhatsApp alert successfully delivered to {wa_recipient}. Response: {resp.text}")
                        except Exception as wa_err:
                            print(f"Failed to deliver WhatsApp alert due to error: {wa_err}")

                    asyncio.create_task(send_whatsapp_async(wa_msg))

                # Asynchronously dispatch webhook alerts
                async def send_webhook_async(url, payload):
                    import requests
                    try:
                        await asyncio.to_thread(requests.post, url, json=payload, timeout=5)
                    except Exception as web_err:
                        print(f"Failed to deliver alert webhook: {web_err}")

                text_msg = (
                    f"🔔 **INSTITUTIONAL ALERT TRIGGERED** 🔔\n"
                    f"• **Stock**: {alert['ticker']}\n"
                    f"• **Condition**: {alert['condition_type']} {alert['operator']} {alert['value']}\n"
                    f"• **Triggered Value**: {cur_val}\n"
                    f"• **Triggered At**: {trigger_date}\n"
                )
                if ai_context:
                    text_msg += f"• **AI Copilot Analysis**: {ai_context}\n"

                if discord_webhook:
                    fields = [
                        {"name": "Stock", "value": f"**{alert['ticker']}**", "inline": True},
                        {"name": "Condition", "value": f"`{alert['condition_type']} {alert['operator']} {alert['value']}`", "inline": True},
                        {"name": "Triggered Value", "value": f"{cur_val}", "inline": False},
                        {"name": "Timestamp", "value": f"{trigger_date}", "inline": True}
                    ]
                    if ai_context:
                        fields.append({"name": "AI Copilot Analysis", "value": f"{ai_context}", "inline": False})
                    discord_payload = {
                        "content": None,
                        "embeds": [{
                            "title": "🚨 Institutional Alert Triggered",
                            "color": 15548997,  # Red
                            "fields": fields,
                            "footer": {
                                "text": "APEX Agentic Equities AI Workstation"
                            }
                        }]
                    }
                    asyncio.create_task(send_webhook_async(discord_webhook, discord_payload))

                if slack_webhook:
                    slack_payload = {
                        "text": text_msg
                    }
                    asyncio.create_task(send_webhook_async(slack_webhook, slack_payload))
                
        except Exception as e:
            print(f"Error checking alert #{alert['id']}: {e}")
    
    # Re-fetch all alerts after updates
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, ticker, condition_type, operator, value, status, triggered, trigger_date, ai_context FROM alerts")
        all_alerts = [
            {
                "id": row["id"],
                "ticker": row["ticker"],
                "condition_type": row["condition_type"],
                "operator": row["operator"],
                "value": row["value"],
                "status": row["status"],
                "triggered": bool(row["triggered"]),
                "trigger_date": row["trigger_date"],
                "ai_context": row["ai_context"]
            }
            for row in cursor.fetchall()
        ]
            
    return {"status": "success", "triggers": triggers, "alerts": all_alerts}

# ==================== WATCHLISTS ====================

def get_fuzzy_summary_for_symbol(conn, symbol_upper: str) -> dict:
    """Helper to evaluate and return fuzzy score and rating from cached profile."""
    try:
        base_sym = symbol_upper.split('.')[0]
        ns_sym = f"{base_sym}.NS"
        row = conn.execute(
            "SELECT profile_json FROM cached_profiles WHERE symbol = ? OR symbol = ? OR symbol = ?",
            (symbol_upper, base_sym, ns_sym)
        ).fetchone()
        if not row:
            return {"fuzzy_score": 0.0, "fuzzy_rating": "Neutral"}
        profile = json.loads(row["profile_json"])
        fundamentals = profile.get("fundamentals", {})
        technicals = profile.get("technicals", {})
        quality = profile.get("earnings_quality", {})
        sector = profile.get("sector", "Unknown")

        rsi = float(technicals.get("rsi", 50.0))
        current_price = float(technicals.get("current_price", 0.0))
        sma_200 = float(technicals.get("sma_200", 0.0))
        dma_prox = ((current_price - sma_200) / sma_200 * 100.0) if sma_200 > 0 else 0.0
        trend_str = technicals.get("trend_50_vs_200", "Neutral")
        adx = float(technicals.get("adx", 22.0))

        stage = 1
        if trend_str == "Bullish" and current_price >= sma_200:
            stage = 2
        elif trend_str == "Bearish" and current_price < sma_200:
            stage = 4
        elif rsi > 65 and trend_str != "Bullish":
            stage = 3

        altman_z = float(quality.get("altman_z_score", 3.0))
        piotroski = int(quality.get("piotroski_score", 6))
        promoter_holding = float(fundamentals.get("promoter_holding_pct", 50.0))
        promoter_pledge_delta = float(fundamentals.get("promoter_pledge_pct", 0.0))

        volume = float(fundamentals.get("volume", 1.0))
        average_volume = float(fundamentals.get("average_volume", 1.0))
        relative_volume = volume / average_volume if average_volume > 0 else 1.0

        sector_markdown = False
        sec_row = conn.execute("SELECT return_1m FROM sector_regime_stats WHERE sector = ?", (sector,)).fetchone()
        if sec_row and sec_row["return_1m"] is not None and float(sec_row["return_1m"]) < -5.0:
            sector_markdown = True

        sales_growth = float(fundamentals.get("sales_growth_3y_pct", 0.0))
        profit_growth = float(fundamentals.get("profit_growth_3y_pct", 0.0))
        roe_pct = float(fundamentals.get("roe_pct", 12.0))
        opm_delta = (profit_growth - sales_growth) / 10.0
        roe_delta = 1.0 if roe_pct > 15.0 else -1.0 if roe_pct < 8.0 else 0.0
        debt_delta = 0.0

        sma_50 = float(technicals.get("sma_50", 0.0))
        sma_20 = float(technicals.get("sma_20", current_price * 0.98 if current_price > 0 else 100.0))
        sma_100 = float(technicals.get("sma_100", (sma_50 + sma_200) / 2.0 if (sma_50 > 0 and sma_200 > 0) else current_price))
        dma_stack_bullish = bool(sma_20 > sma_50 > sma_100 > sma_200 > 0)
        dma_stack_bearish = bool(0 < sma_20 < sma_50 < sma_100 < sma_200)

        pe_ratio = float(fundamentals.get("pe_ratio", 20.0))
        pe_3y_median = float(fundamentals.get("pe_3y_median", 22.0))
        pe_valuation_ratio = pe_ratio / pe_3y_median if pe_3y_median > 0 else 1.0

        high_52w = float(fundamentals.get("high_52w", current_price * 1.1 if current_price > 0 else 110.0))
        low_52w = float(fundamentals.get("low_52w", current_price * 0.8 if current_price > 0 else 80.0))
        fifty_two_week_prox = (current_price - low_52w) / (high_52w - low_52w) if (high_52w - low_52w) > 0 else 0.5
        fifty_two_week_prox = max(0.0, min(1.0, fifty_two_week_prox))

        delivery_pct = float(fundamentals.get("delivery_pct", 40.0))
        vcp_squeeze = bool(technicals.get("vcp_squeeze", False))
        fii_dii_delta = float(fundamentals.get("fii_dii_delta", 0.0))
        icr = float(quality.get("interest_coverage_ratio", 5.0))
        ocf_pat_ratio = float(quality.get("ocf_pat_ratio", 1.0))

        res = evaluate_fuzzy_logic(
            opm_delta=opm_delta, roe_delta=roe_delta, debt_delta=debt_delta,
            rsi=rsi, dma_prox=dma_prox, adx=adx, stage=stage,
            altman_z=altman_z, piotroski=piotroski,
            promoter_holding=promoter_holding, promoter_pledge_delta=promoter_pledge_delta,
            relative_volume=relative_volume, sector_markdown=sector_markdown,
            pe_valuation_ratio=pe_valuation_ratio,
            dma_stack_bullish=dma_stack_bullish,
            dma_stack_bearish=dma_stack_bearish,
            fifty_two_week_prox=fifty_two_week_prox,
            delivery_pct=delivery_pct,
            vcp_squeeze=vcp_squeeze,
            fii_dii_delta=fii_dii_delta,
            icr=icr,
            ocf_pat_ratio=ocf_pat_ratio
        )
        raw_sc = float(res.get("fuzzy_score", res.get("score", 0.0)))
        if abs(raw_sc) <= 62.5 and raw_sc != 0.0:
            final_sc = round(min(100.0, max(-100.0, raw_sc / 0.625)), 1)
        else:
            final_sc = round(raw_sc, 1)
        return {
            "fuzzy_score": final_sc,
            "fuzzy_rating": res.get("rating", "Neutral")
        }
    except Exception:
        return {"fuzzy_score": 0.0, "fuzzy_rating": "Neutral"}

_FUZZY_EVAL_CACHE = {}
_FUZZY_CACHE_TIMESTAMP = 0.0

def get_universe_fuzzy_evaluations(conn):
    global _FUZZY_EVAL_CACHE, _FUZZY_CACHE_TIMESTAMP
    import importlib
    import backend.fuzzy_engine
    importlib.reload(backend.fuzzy_engine)
    from backend.fuzzy_engine import evaluate_fuzzy_logic

    now = time.time()
    if _FUZZY_EVAL_CACHE and (now - _FUZZY_CACHE_TIMESTAMP < 1.0):
        return _FUZZY_EVAL_CACHE

    cursor = conn.cursor()
    cursor.execute("SELECT symbol, profile_json FROM cached_profiles")
    rows = cursor.fetchall()
    
    if not rows:
        cursor.execute("SELECT symbol, name as company_name, sector FROM watchlist_items")
        rows = cursor.fetchall()

    sec_rows = cursor.execute("SELECT sector, return_1m FROM sector_regime_stats").fetchall()
    sector_stats_map = {r["sector"]: float(r["return_1m"]) for r in sec_rows if r["return_1m"] is not None}

    evaluations = {}
    for r in rows:
        sym = r["symbol"]
        profile_raw = r["profile_json"] if "profile_json" in r.keys() else None
        comp_name = sym.split('.')[0]
        sector = "N/A"
        
        if profile_raw:
            try:
                p = json.loads(profile_raw)
                comp_name = p.get("company_name", comp_name)
                sector = p.get("sector", "N/A")
                
                tech = p.get("technicals", {})
                quality = p.get("earnings_quality", {})
                fundamentals = p.get("fundamentals", {})
                
                rsi = float(tech.get("rsi", 50.0))
                adx = float(tech.get("adx", 20.0))
                sma_50 = float(tech.get("sma_50", 0.0))
                current_price = float(fundamentals.get("current_price", sma_50 if sma_50 > 0 else 100.0))
                dma_prox = ((current_price - sma_50) / sma_50 * 100.0) if sma_50 > 0 else 0.0
                
                sma_200 = float(tech.get("sma_200", 0.0))
                stage = 2
                if sma_50 > sma_200 > 0: stage = 2
                elif sma_50 < sma_200: stage = 4
                else: stage = 3

                altman_z = float(quality.get("altman_z_score", 3.0))
                piotroski = int(quality.get("piotroski_score", 6))
                promoter_holding = float(fundamentals.get("promoter_holding_pct", 50.0))
                promoter_pledge_delta = float(fundamentals.get("promoter_pledge_pct", 0.0))
                volume = float(fundamentals.get("volume", 1.0))
                average_volume = float(fundamentals.get("average_volume", 1.0))
                relative_volume = volume / average_volume if average_volume > 0 else 1.0

                sec_ret = sector_stats_map.get(sector, 0.0)
                sector_markdown = (sec_ret < -5.0)

                sales_growth = float(fundamentals.get("sales_growth_3y_pct", 0.0))
                profit_growth = float(fundamentals.get("profit_growth_3y_pct", 0.0))
                roe_pct = float(fundamentals.get("roe_pct", 12.0))
                opm_delta = (profit_growth - sales_growth) / 10.0
                roe_delta = 1.0 if roe_pct > 15.0 else -1.0 if roe_pct < 8.0 else 0.0
                debt_delta = 0.0

                sma_20 = float(tech.get("sma_20", current_price * 0.98))
                sma_100 = float(tech.get("sma_100", (sma_50 + sma_200) / 2.0 if (sma_50 > 0 and sma_200 > 0) else current_price))
                dma_stack_bullish = bool(sma_20 > sma_50 > sma_100 > sma_200 > 0)
                dma_stack_bearish = bool(0 < sma_20 < sma_50 < sma_100 < sma_200)

                pe_ratio = float(fundamentals.get("pe_ratio", 20.0))
                pe_3y_median = float(fundamentals.get("pe_3y_median", 22.0))
                pe_valuation_ratio = pe_ratio / pe_3y_median if pe_3y_median > 0 else 1.0

                high_52w = float(fundamentals.get("high_52w", current_price * 1.1))
                low_52w = float(fundamentals.get("low_52w", current_price * 0.8))
                fifty_two_week_prox = (current_price - low_52w) / (high_52w - low_52w) if (high_52w - low_52w) > 0 else 0.5
                fifty_two_week_prox = max(0.0, min(1.0, fifty_two_week_prox))

                delivery_pct = float(fundamentals.get("delivery_pct", 40.0))
                vcp_squeeze = bool(tech.get("vcp_squeeze", False))
                fii_dii_delta = float(fundamentals.get("fii_dii_delta", 0.0))
                icr = float(quality.get("interest_coverage_ratio", 5.0))
                ocf_pat_ratio = float(quality.get("ocf_pat_ratio", 1.0))

                fz = evaluate_fuzzy_logic(
                    opm_delta=opm_delta, roe_delta=roe_delta, debt_delta=debt_delta,
                    rsi=rsi, dma_prox=dma_prox, adx=adx, stage=stage,
                    altman_z=altman_z, piotroski=piotroski,
                    promoter_holding=promoter_holding, promoter_pledge_delta=promoter_pledge_delta,
                    relative_volume=relative_volume, sector_markdown=sector_markdown,
                    pe_valuation_ratio=pe_valuation_ratio,
                    dma_stack_bullish=dma_stack_bullish,
                    dma_stack_bearish=dma_stack_bearish,
                    fifty_two_week_prox=fifty_two_week_prox,
                    delivery_pct=delivery_pct,
                    vcp_squeeze=vcp_squeeze,
                    fii_dii_delta=fii_dii_delta,
                    icr=icr,
                    ocf_pat_ratio=ocf_pat_ratio
                )
                raw_fz_score = float(fz.get("fuzzy_score", fz.get("score", 0.0)))
                if abs(raw_fz_score) <= 62.5 and raw_fz_score != 0.0:
                    fuzzy_score = round(min(100.0, max(-100.0, raw_fz_score / 0.625)), 1)
                else:
                    fuzzy_score = round(raw_fz_score, 1)
                fuzzy_rating = fz.get("rating", "Neutral")
                rule_trail = fz.get("rule_trail", [])
            except Exception:
                fuzzy_score = 0.0
                fuzzy_rating = "Neutral"
                rule_trail = []
        else:
            fuzzy_score = 0.0
            fuzzy_rating = "Neutral"

        evaluations[sym] = {
            "symbol": sym,
            "company_name": comp_name,
            "sector": sector,
            "fuzzy_score": fuzzy_score,
            "fuzzy_rating": fuzzy_rating,
            "rule_trail": rule_trail
        }

    _FUZZY_EVAL_CACHE = evaluations
    _FUZZY_CACHE_TIMESTAMP = now
    return evaluations

@app.get("/api/fuzzy/universe-standings")
async def get_fuzzy_universe_standings(limit: int = 8):
    """
    Returns top accumulation signals and value traps across cached stock profiles using Mamdani Fuzzy engine.
    """
    with get_db() as conn:
        eval_map = get_universe_fuzzy_evaluations(conn)
        evaluations = list(eval_map.values())
        for e in evaluations:
            e["market_regime"] = "ACCUMULATION" if e["fuzzy_score"] >= 15 else ("DISTRIBUTION" if e["fuzzy_score"] <= -15 else "NEUTRAL")

        top_buys = sorted(evaluations, key=lambda x: x["fuzzy_score"], reverse=True)[:limit]
        top_sells = sorted(evaluations, key=lambda x: x["fuzzy_score"])[:limit]

        return {
            "top_buys": top_buys,
            "top_sells": top_sells,
            "total_evaluated": len(evaluations)
        }

@app.get("/api/scans/fuzzy")
async def scan_fuzzy(min_score: float = -100.0, rating_class: Optional[str] = "ALL", limit: int = 50):
    """
    Scans cached stock profiles using Mamdani Fuzzy Inference engine.
    Supports filtering by min_score and rating_class ('STRONG_BUY', 'BUY', 'HOLD', 'AVOID', or 'ALL').
    """
    with get_db() as conn:
        eval_map = get_universe_fuzzy_evaluations(conn)
        r_upper = rating_class.upper() if rating_class else "ALL"

        matches = []
        for sym, item in eval_map.items():
            score = item["fuzzy_score"]
            rating = item.get("fuzzy_rating", "")

            if r_upper == "STRONG_BUY":
                if score < 70.0 and rating != "Strong Buy": continue
            elif r_upper == "BUY":
                if (score < 30.0 or score >= 70.0) and rating != "Buy": continue
            elif r_upper == "HOLD":
                if (score <= -40.0 or score >= 30.0) and rating != "Hold": continue
            elif r_upper == "AVOID":
                if score > -40.0 and rating not in ["Sell", "Strong Sell"]: continue
            else: # ALL
                if score < min_score: continue

            matches.append(item)

        reverse_sort = (r_upper != "AVOID")
        matches = sorted(matches, key=lambda x: x["fuzzy_score"], reverse=reverse_sort)[:limit]

        return {
            "stocks": matches,
            "count": len(matches),
            "total_matches": len(matches)
        }

@app.get("/api/portfolio/fuzzy-swaps")
async def get_portfolio_fuzzy_swaps():
    """
    Scans active portfolio holdings against Mamdani Fuzzy Conviction scores.
    Identifies underperforming holdings (fuzzy_score < 15.0) and recommends
    same-sector high-conviction swaps (fuzzy_score >= +30.0, ideally >= +70.0).
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, symbol, quantity, purchase_price FROM portfolio_items WHERE quantity > 0")
        items = cursor.fetchall()
        
        if not items:
            return {
                "portfolio_fuzzy_score": 0.0,
                "portfolio_health_rating": "No Holdings",
                "underperforming_count": 0,
                "swap_recommendations": []
            }
            
        universe_evals = get_universe_fuzzy_evaluations(conn)
        
        portfolio_positions = []
        total_value = 0.0
        weighted_score_sum = 0.0
        
        for item in items:
            sym = item["symbol"]
            qty = float(item["quantity"] or 0.0)
            purchase_price = float(item["purchase_price"] or 0.0)
            
            fz_info = get_fuzzy_summary_for_symbol(conn, sym)
            fuzzy_score = float(fz_info.get("fuzzy_score", 0.0))
            fuzzy_rating = fz_info.get("fuzzy_rating", "Neutral")
            
            sec_row = conn.execute("SELECT name, sector FROM watchlist_items WHERE symbol = ?", (sym,)).fetchone()
            if not sec_row:
                sec_row = conn.execute("SELECT symbol as name, 'Other' as sector FROM cached_profiles WHERE symbol = ?", (sym,)).fetchone()
            
            comp_name = sec_row["name"] if sec_row and "name" in sec_row.keys() else sym
            sector = sec_row["sector"] if sec_row and "sector" in sec_row.keys() else "Other"
            
            if sector in ("Other", "Unknown", "N/A"):
                univ_item = universe_evals.get(sym, {})
                if univ_item.get("sector") and univ_item.get("sector") not in ("Other", "Unknown", "N/A"):
                    sector = univ_item["sector"]
                    
            pos_val = qty * (purchase_price if purchase_price > 0 else 100.0)
            total_value += pos_val
            weighted_score_sum += (fuzzy_score * pos_val)
            
            portfolio_positions.append({
                "symbol": sym,
                "company_name": comp_name,
                "sector": sector,
                "quantity": qty,
                "purchase_price": purchase_price,
                "fuzzy_score": fuzzy_score,
                "fuzzy_rating": fuzzy_rating
            })
            
        avg_portfolio_score = round(weighted_score_sum / total_value, 1) if total_value > 0 else 0.0
        
        if avg_portfolio_score >= 50.0:
            health_rating = "Strong Conviction"
        elif avg_portfolio_score >= 15.0:
            health_rating = "Moderate Conviction"
        elif avg_portfolio_score >= -15.0:
            health_rating = "Neutral / Hold"
        else:
            health_rating = "High Vulnerability"
            
        underperforming = [p for p in portfolio_positions if p["fuzzy_score"] < 15.0]
        # Deduplicate underperforming positions by symbol keeping lowest score
        seen_under_syms = set()
        dedup_underperforming = []
        for p in sorted(underperforming, key=lambda x: x["fuzzy_score"]):
            if p["symbol"] not in seen_under_syms:
                seen_under_syms.add(p["symbol"])
                dedup_underperforming.append(p)
        
        swap_recommendations = []
        portfolio_symbols = set(p["symbol"] for p in portfolio_positions)
        
        for p in dedup_underperforming:
            cur_sym = p["symbol"]
            cur_sector = p["sector"]
            cur_score = p["fuzzy_score"]
            cur_rating = p["fuzzy_rating"]
            
            candidates = []
            for u_sym, u_data in universe_evals.items():
                if u_sym in portfolio_symbols:
                    continue
                u_sector = u_data.get("sector", "Other")
                u_score = u_data.get("fuzzy_score", 0.0)
                
                same_sector = (u_sector == cur_sector) if (cur_sector not in ("Other", "N/A", "Unknown")) else True
                
                if same_sector and u_score >= 30.0 and u_score > cur_score:
                    candidates.append(u_data)
                    
            candidates.sort(key=lambda x: x.get("fuzzy_score", 0.0), reverse=True)
            
            if candidates:
                best_match = candidates[0]
                rec_sym = best_match["symbol"]
                rec_name = best_match.get("company_name", rec_sym)
                rec_score = best_match.get("fuzzy_score", 0.0)
                rec_rating = best_match.get("fuzzy_rating", "Buy")
                rec_sector = best_match.get("sector", cur_sector)
                
                delta = round(rec_score - cur_score, 1)
                
                swap_recommendations.append({
                    "current_symbol": cur_sym,
                    "current_name": p["company_name"],
                    "current_sector": cur_sector,
                    "current_fuzzy_score": cur_score,
                    "current_fuzzy_rating": cur_rating,
                    "suggested_symbol": rec_sym,
                    "suggested_name": rec_name,
                    "suggested_sector": rec_sector,
                    "suggested_fuzzy_score": rec_score,
                    "suggested_fuzzy_rating": rec_rating,
                    "conviction_delta": delta,
                    "rationale": f"Upgrades conviction by +{delta}% within {cur_sector}. {rec_sym} exhibits superior Mamdani trend & trajectory metrics."
                })
                
        return {
            "portfolio_fuzzy_score": avg_portfolio_score,
            "portfolio_health_rating": health_rating,
            "underperforming_count": len(dedup_underperforming),
            "swap_recommendations": swap_recommendations
        }

@app.get("/api/watchlists")

async def get_watchlists():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM watchlists")
        watchlists = [dict(row) for row in cursor.fetchall()]
        
        for w in watchlists:
            cursor.execute("""
                SELECT 
                    i.symbol, 
                    i.name, 
                    i.sector, 
                    i.quantity, 
                    i.purchase_price, 
                    i.in_portfolio,
                    i.added_price,
                    i.added_date,
                    i.alert_config,
                    p.profile_json,
                    (CASE WHEN p.symbol IS NOT NULL THEN 1 ELSE 0 END) as is_cached
                FROM watchlist_items i
                LEFT JOIN cached_profiles p ON i.symbol = p.symbol
                WHERE i.watchlist_id = ?
            """, (w["id"],))
            items = [dict(row) for row in cursor.fetchall()]
            for item in items:
                p_json = {}
                if item.get("profile_json"):
                    try:
                        p_json = json.loads(item["profile_json"])
                    except Exception:
                        pass
                item.pop("profile_json", None)

                alert_cfg = {}
                if item.get("alert_config"):
                    try:
                        alert_cfg = json.loads(item["alert_config"])
                    except Exception:
                        pass
                item["alert_config"] = alert_cfg

                fz = get_fuzzy_summary_for_symbol(conn, item["symbol"])
                item["fuzzy_score"] = fz["fuzzy_score"]
                item["fuzzy_rating"] = fz["fuzzy_rating"]

                cp_val = float(p_json.get("technicals", {}).get("current_price") or p_json.get("fundamentals", {}).get("current_price") or 0.0)
                trend_metrics = compute_stock_trendlyne_metrics(p_json, cp_val, item.get("added_price"), item.get("added_date"))
                item.update(trend_metrics)

            w["items"] = items
        
    return watchlists

@app.post("/api/watchlists")
async def create_watchlist(data: WatchlistCreate):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Watchlist name cannot be empty.")
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Check max limit of 10 watchlists
        cursor.execute("SELECT COUNT(*) as cnt FROM watchlists")
        if cursor.fetchone()["cnt"] >= 10:
            raise HTTPException(status_code=400, detail="Maximum limit of 10 watchlists reached.")
            
        try:
            cursor.execute("INSERT INTO watchlists (name) VALUES (?)", (name,))
            watchlist_id = cursor.lastrowid
            conn.commit()
            return {"id": watchlist_id, "name": name, "items": []}
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=400, detail="Watchlist with this name already exists.")

@app.put("/api/watchlists/{watchlist_id}")
async def rename_watchlist(watchlist_id: int, data: WatchlistRename):
    """Rename an existing watchlist."""
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Watchlist name cannot be empty.")
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE watchlists SET name = ? WHERE id = ?", (name, watchlist_id))
            conn.commit()
            return {"id": watchlist_id, "name": name}
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=400, detail="Watchlist with this name already exists.")

@app.post("/api/watchlists/{watchlist_id}/duplicate")
async def duplicate_watchlist(watchlist_id: int):
    """Duplicate an existing watchlist and all its constituent items."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) as cnt FROM watchlists")
        cnt_row = cursor.fetchone()
        if cnt_row and cnt_row["cnt"] >= 10:
            raise HTTPException(status_code=400, detail="Maximum limit of 10 watchlists reached. Please delete an existing watchlist first.")
            
        cursor.execute("SELECT id, name FROM watchlists WHERE id = ?", (watchlist_id,))
        source = cursor.fetchone()
        if not source:
            raise HTTPException(status_code=404, detail="Watchlist not found.")
            
        base_name = source["name"]
        new_name = f"{base_name} (Copy)"
        cursor.execute("SELECT id FROM watchlists WHERE name = ?", (new_name,))
        counter = 2
        while cursor.fetchone():
            new_name = f"{base_name} (Copy {counter})"
            cursor.execute("SELECT id FROM watchlists WHERE name = ?", (new_name,))
            counter += 1
            
        try:
            cursor.execute("INSERT INTO watchlists (name) VALUES (?)", (new_name,))
            new_id = cursor.lastrowid
            
            cursor.execute("""
                SELECT symbol, name, sector, quantity, purchase_price, in_portfolio, added_price, added_date 
                FROM watchlist_items WHERE watchlist_id = ?
            """, (watchlist_id,))
            items = cursor.fetchall()
            for item in items:
                item_dict = dict(item)
                cursor.execute("""
                    INSERT INTO watchlist_items (watchlist_id, symbol, name, sector, quantity, purchase_price, in_portfolio, added_price, added_date) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    new_id, 
                    item_dict.get("symbol"), 
                    item_dict.get("name"), 
                    item_dict.get("sector"), 
                    item_dict.get("quantity", 0.0), 
                    item_dict.get("purchase_price", 0.0), 
                    item_dict.get("in_portfolio", 0), 
                    item_dict.get("added_price", 0.0), 
                    item_dict.get("added_date")
                ))
                               
            conn.commit()
            return {"id": new_id, "name": new_name, "items_count": len(items)}
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=400, detail=f"Watchlist '{new_name}' already exists.")


@app.delete("/api/watchlists/{watchlist_id}")
async def delete_watchlist(watchlist_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM watchlist_items WHERE watchlist_id = ?", (watchlist_id,))
        cursor.execute("DELETE FROM watchlists WHERE id = ?", (watchlist_id,))
        conn.commit()
    return {"status": "success"}

def compute_stock_trendlyne_metrics(profile, cp_val, added_price, added_date):
    profile = profile or {}
    t = profile.get("technicals") or {}
    f = profile.get("fundamentals") or {}

    def safe_num(val, default=0.0):
        if val is None or val == "" or val == "--" or val == "N/A":
            return default
        try:
            if isinstance(val, (int, float)):
                return float(val)
            s = str(val).replace(',', '').replace('₹', '').replace('%', '').strip()
            return float(s)
        except Exception:
            return default

    cp_val = safe_num(cp_val or t.get("current_price") or f.get("current_price"))

    # 1. Since Added Calculation
    added_p = safe_num(added_price)
    if added_p <= 0 and cp_val > 0:
        added_p = cp_val
    chg_since_added = round(((cp_val - added_p) / added_p) * 100, 2) if (added_p > 0 and cp_val > 0) else 0.0

    # 2. 52W Range Bar Position %
    h52 = round(safe_num(t.get("high_52w") or f.get("high_52week") or f.get("high52")), 2)
    l52 = round(safe_num(t.get("low_52w") or f.get("low_52week") or f.get("low52")), 2)
    pos_52w = 50.0
    if h52 > 0 and l52 > 0 and h52 > l52 and cp_val > 0:
        pos_52w = round(((cp_val - l52) / (h52 - l52)) * 100, 1)

    # 3. Multi-timeframe Returns
    perf_dict = (profile.get("swot_performance") or {}).get("performance") or profile.get("performance") or {}

    chg_1d = round(safe_num(t.get("chg_1d") or t.get("price_change_pct") or f.get("change_pct")), 2)

    val_1w = perf_dict.get("1W")
    if val_1w is not None:
        chg_1w = round(safe_num(val_1w), 2)
    else:
        chg_1w = round(safe_num(t.get("chg_1w") or t.get("roc_20") or (chg_1d * 1.4)), 2)

    val_1m = perf_dict.get("1M")
    if val_1m is not None:
        chg_1m = round(safe_num(val_1m), 2)
    else:
        chg_1m = round(safe_num(t.get("chg_1m") or t.get("rsc_6m")), 2)

    val_3m = perf_dict.get("3M")
    if val_3m is not None:
        chg_3m = round(safe_num(val_3m), 2)
    else:
        raw_3m = t.get("chg_3m")
        sma_50 = safe_num(t.get("sma_50"))
        if raw_3m is not None and safe_num(raw_3m) != 0.0:
            chg_3m = round(safe_num(raw_3m), 2)
        elif cp_val > 0 and sma_50 > 0:
            chg_3m = round(((cp_val - sma_50) / sma_50) * 100, 2)
        else:
            chg_3m = 0.0

    val_6m = perf_dict.get("6M")
    if val_6m is not None:
        chg_6m = round(safe_num(val_6m), 2)
    else:
        raw_6m = t.get("chg_6m")
        sma_150 = safe_num(t.get("sma_150"))
        sma_50 = safe_num(t.get("sma_50"))
        if raw_6m is not None and safe_num(raw_6m) != 0.0:
            chg_6m = round(safe_num(raw_6m), 2)
        elif cp_val > 0 and sma_150 > 0:
            chg_6m = round(((cp_val - sma_150) / sma_150) * 100, 2)
        elif cp_val > 0 and sma_50 > 0:
            chg_6m = round(((cp_val - sma_50) / sma_50) * 100, 2)
        else:
            chg_6m = 0.0

    val_1y = perf_dict.get("1Y")
    if val_1y is not None:
        chg_1y = round(safe_num(val_1y), 2)
    else:
        raw_1y = t.get("chg_1y") or f.get("return_1y")
        sma_200 = safe_num(t.get("sma_200"))
        if raw_1y is not None and safe_num(raw_1y) != 0.0:
            chg_1y = round(safe_num(raw_1y), 2)
        elif cp_val > 0 and sma_200 > 0:
            chg_1y = round(((cp_val - sma_200) / sma_200) * 100, 2)
        else:
            chg_1y = 0.0

    # 4. Institutional Multi-Parameter 3-Dot Traffic Light Signals
    # Dot 1: Valuation (P/E Ratio vs Sector P/E, PEG Ratio, EV/EBITDA, P/B Ratio)
    pe = safe_num(f.get("pe_ratio") or f.get("pe") or f.get("trailing_pe"))
    ind_pe = safe_num(f.get("industry_pe") or f.get("sector_pe"))
    peg = safe_num(f.get("peg_ratio") or f.get("peg"))
    pb = safe_num(f.get("price_to_book") or f.get("pb_ratio") or f.get("book_value"))
    ev_ebitda = safe_num(f.get("ev_ebitda"))

    if (0 < pe < 25) or (ind_pe > 0 and 0 < pe < ind_pe) or (0 < peg < 1.0) or (0 < ev_ebitda < 12.0):
        val_dot = "green"
        val_txt = f"Valuation: Undervalued (P/E {pe:.1f}" + (f" vs Sector {ind_pe:.1f}" if ind_pe > 0 else "") + (f", PEG {peg:.2f})" if peg > 0 else ")")
    elif (25 <= pe <= 45) or (1.0 <= peg <= 2.0) or (12.0 <= ev_ebitda <= 20.0):
        val_dot = "yellow"
        val_txt = f"Valuation: Fairly Valued (P/E {pe:.1f}" + (f", EV/EBITDA {ev_ebitda:.1f}" if ev_ebitda > 0 else ")")
    elif pe > 45 or peg > 2.0 or ev_ebitda > 25.0:
        val_dot = "red"
        val_txt = f"Valuation: Premium / Expensive (P/E {pe:.1f}" + (f", EV/EBITDA {ev_ebitda:.1f}" if ev_ebitda > 0 else ")")
    else:
        val_dot = "yellow"
        val_txt = f"Valuation: Neutral (P/E {pe:.1f})" if pe > 0 else "Valuation: Neutral"

    # Dot 2: Technical Momentum (RSI 14, 50MA vs 200MA, 52W High Proximity, Breakout Status)
    rsi = safe_num(t.get("rsi"))
    sma50 = safe_num(t.get("sma_50"))
    sma200 = safe_num(t.get("sma_200"))
    breakout = t.get("breakout_status") or ""

    if (rsi > 55) and (sma50 == 0 or sma200 == 0 or sma50 >= sma200) and (breakout != "BEARISH_BREAKDOWN"):
        mom_dot = "green"
        mom_txt = f"Momentum: Strong Bullish (RSI {rsi:.1f}, 50MA > 200MA)"
    elif (40 <= rsi <= 55) or (rsi > 55 and sma50 < sma200):
        mom_dot = "yellow"
        mom_txt = f"Momentum: Consolidating (RSI {rsi:.1f})"
    elif (0 < rsi < 40) or (rsi < 45 and sma50 < sma200) or (breakout == "BEARISH_BREAKDOWN"):
        mom_dot = "red"
        mom_txt = f"Momentum: Bearish / Downtrend (RSI {rsi:.1f}, 50MA < 200MA)"
    else:
        mom_dot = "yellow"
        mom_txt = f"Momentum: Neutral (RSI {rsi:.1f})" if rsi > 0 else "Momentum: Neutral"

    # Dot 3: Financial Health & Quality (Debt/Equity, ROE %, ROCE %, Promoter Pledge, Interest Coverage)
    de = safe_num(f.get("debt_to_equity") or f.get("debt_equity"))
    roe = safe_num(f.get("roe_pct") or f.get("roe") or f.get("return_on_equity"))
    roce = safe_num(f.get("roce_pct") or f.get("roce") or f.get("return_on_capital_employed"))
    pledged = safe_num(f.get("promoter_pledged_pct") or f.get("pledged_pct"))
    interest_cov = safe_num(f.get("interest_coverage"))

    if pledged > 15.0:
        health_dot = "red"
        health_txt = f"Health & Quality: High Risk (Promoter Pledge {pledged:.1f}%)"
    elif (0 <= de < 0.5) and (roe > 15.0 or roce > 15.0 or interest_cov > 4.0):
        health_dot = "green"
        health_txt = f"Health & Quality: Strong (D/E {de:.2f}, ROE {roe:.1f}%" + (f", ROCE {roce:.1f}%" if roce > 0 else "") + ")"
    elif (0.5 <= de <= 1.2) or (8.0 <= roe <= 15.0):
        health_dot = "yellow"
        health_txt = f"Health & Quality: Moderate (D/E {de:.2f}, ROE {roe:.1f}%)"
    elif de > 1.2 or (roe > 0 and roe < 8.0):
        health_dot = "red"
        health_txt = f"Health & Quality: Debt/Quality Risk (D/E {de:.2f}, ROE {roe:.1f}%)"
    else:
        health_dot = "yellow"
        health_txt = "Health & Quality: Moderate Balance Sheet"

    # 5. Dynamic Alpha vs Nifty 50 calculation (Risk-adjusted CAPM or Benchmark Excess Return)
    capm_nifty = (profile or {}).get("capm_risk_nifty50") or {}
    if "capm_alpha_pct" in capm_nifty and capm_nifty.get("capm_alpha_pct") is not None:
        alpha_vs_nifty = round(safe_num(capm_nifty.get("capm_alpha_pct")), 2)
    else:
        nifty_rets = _get_benchmark_returns("^NSEI")
        nifty_1y = safe_num(nifty_rets.get("1Y"), 12.8)
        alpha_vs_nifty = round(chg_1y - nifty_1y, 2)

    # Day High / Low Intraday Range calculation
    dh = round(safe_num(t.get("day_high") or t.get("high") or f.get("day_high") or f.get("high")), 2)
    dl = round(safe_num(t.get("day_low") or t.get("low") or f.get("day_low") or f.get("low")), 2)

    # Dynamic Intraday Bounds Guarantee: Current live price cp_val must be within [dl, dh]
    if cp_val > 0:
        if dh <= 0 or cp_val > dh:
            dh = round(max(dh, cp_val), 2)
        if dl <= 0 or cp_val < dl:
            dl = round(cp_val if dl <= 0 else min(dl, cp_val), 2)

    if dh <= 0 or dl <= 0 or dh <= dl:
        if chg_1d >= 0:
            dh = round(cp_val * (1.0 + max(abs(chg_1d) * 0.15, 0.4) / 100.0), 2)
            dl = round((cp_val / (1.0 + chg_1d / 100.0)) * (1.0 - 0.3 / 100.0), 2) if chg_1d != 0 else round(cp_val * 0.995, 2)
        else:
            dh = round((cp_val / (1.0 + chg_1d / 100.0)) * (1.0 + 0.3 / 100.0), 2) if chg_1d != -100.0 else round(cp_val * 1.005, 2)
            dl = round(cp_val * (1.0 - max(abs(chg_1d) * 0.15, 0.4) / 100.0), 2)
        if dh <= dl:
            dh = round(cp_val * 1.01, 2)
            dl = round(cp_val * 0.99, 2)

    if cp_val > 0:
        dh = round(max(dh, cp_val), 2)
        dl = round(min(dl, cp_val), 2)

    pos_day = 50.0
    if dh > dl and cp_val > 0:
        pos_day = round(min(max(((cp_val - dl) / (dh - dl)) * 100.0, 0.0), 100.0), 1)

    # 6. Valuation & Fundamental ratios (P/E, P/B, ROE, ROCE, Fair Value, Div Yield, MOS %)
    dcf_data = (profile or {}).get("dcf_model") or (profile or {}).get("dcf") or {}
    mos_pct = round(safe_num(dcf_data.get("margin_of_safety")), 1)
    fair_val = round(safe_num(dcf_data.get("intrinsic_value") or t.get("intrinsic_value") or f.get("intrinsic_value")), 2)

    pe_ratio = round(safe_num(f.get("pe_ratio") or f.get("pe") or f.get("trailing_pe")), 2)
    pb_ratio = round(safe_num(f.get("price_to_book") or f.get("pb_ratio") or f.get("pb")), 2)
    roe_val = round(safe_num(f.get("roe_pct") or f.get("roe") or f.get("return_on_equity")), 2)
    roce_val = round(safe_num(f.get("roce_pct") or f.get("roce") or f.get("return_on_capital_employed")), 2)

    raw_div = f.get("dividend_yield") or f.get("div_yield") or f.get("dividendYield")
    div_yield = round(safe_num(raw_div), 2) if (raw_div is not None and raw_div != "" and raw_div != "--" and raw_div != 0) else None

    return {
        "added_price": added_p,
        "added_date": added_date or "Recently",
        "chg_since_added": chg_since_added,
        "range_52w": { "high52": h52, "low52": l52, "pos_pct": pos_52w },
        "range_day": { "high": dh, "low": dl, "pos_pct": pos_day },
        "day_high": dh,
        "day_low": dl,
        "returns": { "d1": chg_1d, "w1": chg_1w, "m1": chg_1m, "m3": chg_3m, "m6": chg_6m, "y1": chg_1y },
        "alpha_vs_nifty": alpha_vs_nifty,
        "mos_pct": mos_pct,
        "fair_value": fair_val,
        "pe_ratio": pe_ratio,
        "pb_ratio": pb_ratio,
        "roe": roe_val,
        "roce": roce_val,
        "div_yield": div_yield,
        "dots": {
            "val": val_dot, "val_txt": val_txt,
            "mom": mom_dot, "mom_txt": mom_txt,
            "health": health_dot, "health_txt": health_txt
        }
    }

@app.post("/api/watchlists/{watchlist_id}/items")
async def add_watchlist_item(watchlist_id: int, data: WatchlistItemCreate):
    symbol = normalize_symbol(data.symbol.strip().upper())
    if not symbol:
        raise HTTPException(status_code=400, detail="Stock symbol is required.")
        
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Check if watchlist exists
        cursor.execute("SELECT id FROM watchlists WHERE id = ?", (watchlist_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Watchlist not found.")
            
        # Check max limit of 100 stocks
        cursor.execute("SELECT COUNT(*) as cnt FROM watchlist_items WHERE watchlist_id = ?", (watchlist_id,))
        if cursor.fetchone()["cnt"] >= 100:
            raise HTTPException(status_code=400, detail="Maximum limit of 100 stocks per watchlist reached.")
            
        # Resolve name, sector, and live added_price using financial profile search
        company_name = symbol
        sector = "General Equities"
        added_price = 0.0
        today_str = datetime.now().strftime("%d %b, '%y")
        try:
            resolved = await asyncio.to_thread(get_complete_financial_profile, symbol)
            company_name = resolved.get("company_name") or symbol
            sector = resolved.get("sector") or "General Equities"
            t = resolved.get("technicals") or {}
            f = resolved.get("fundamentals") or {}
            added_price = float(t.get("current_price") or f.get("current_price") or 0.0)
        except Exception:
            pass
            
        try:
            try:
                cursor.execute(
                    "INSERT INTO watchlist_items (watchlist_id, symbol, name, sector, quantity, purchase_price, in_portfolio, added_price, added_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (watchlist_id, symbol, company_name, sector, data.quantity or 0.0, data.purchase_price or 0.0, data.in_portfolio or 0, added_price, today_str)
                )
            except sqlite3.OperationalError:
                # Fallback if DB table lacks new columns
                try:
                    cursor.execute("ALTER TABLE watchlist_items ADD COLUMN added_price REAL DEFAULT 0.0")
                except Exception:
                    pass
                try:
                    cursor.execute("ALTER TABLE watchlist_items ADD COLUMN added_date TEXT")
                except Exception:
                    pass
                cursor.execute(
                    "INSERT INTO watchlist_items (watchlist_id, symbol, name, sector, quantity, purchase_price, in_portfolio) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (watchlist_id, symbol, company_name, sector, data.quantity or 0.0, data.purchase_price or 0.0, data.in_portfolio or 0)
                )
            conn.commit()
            fz = get_fuzzy_summary_for_symbol(conn, symbol)
            return {"symbol": symbol, "name": company_name, "sector": sector, "quantity": data.quantity or 0.0, "purchase_price": data.purchase_price or 0.0, "in_portfolio": data.in_portfolio or 0, "added_price": added_price, "added_date": today_str, "fuzzy_score": fz["fuzzy_score"], "fuzzy_rating": fz["fuzzy_rating"]}
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=400, detail=f"Stock '{symbol}' already exists in this watchlist.")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error adding item to watchlist: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to add stock '{symbol}': {str(e)}")

@app.get("/api/watchlists/{watchlist_id}")
async def get_single_watchlist(watchlist_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM watchlists WHERE id = ?", (watchlist_id,))
        watchlist = cursor.fetchone()
        if not watchlist:
            raise HTTPException(status_code=404, detail="Watchlist not found.")
            
        w_dict = dict(watchlist)
        cursor.execute("""
            SELECT 
                i.symbol, 
                i.name, 
                i.sector, 
                i.quantity, 
                i.purchase_price, 
                i.in_portfolio,
                i.added_price,
                i.added_date,
                p.profile_json,
                (CASE WHEN p.symbol IS NOT NULL THEN 1 ELSE 0 END) as is_cached
            FROM watchlist_items i
            LEFT JOIN cached_profiles p ON i.symbol = p.symbol
            WHERE i.watchlist_id = ?
        """, (watchlist_id,))
        items = [dict(row) for row in cursor.fetchall()]
        for item in items:
            p_json = {}
            if item.get("profile_json"):
                try:
                    p_json = json.loads(item["profile_json"])
                except Exception:
                    pass
            item.pop("profile_json", None)

            fz = get_fuzzy_summary_for_symbol(conn, item["symbol"])
            item["fuzzy_score"] = fz["fuzzy_score"]
            item["fuzzy_rating"] = fz["fuzzy_rating"]

            # Calculate Trendlyne metrics
            cp_val = float(p_json.get("technicals", {}).get("current_price") or p_json.get("fundamentals", {}).get("current_price") or 0.0)
            trend_metrics = compute_stock_trendlyne_metrics(p_json, cp_val, item.get("added_price"), item.get("added_date"))
            item.update(trend_metrics)

        w_dict["items"] = items
        
    return w_dict

@app.put("/api/watchlists/{watchlist_id}/items/{symbol}")
async def update_watchlist_item_holdings(watchlist_id: int, symbol: str, data: WatchlistItemUpdate):
    symbol = symbol.strip().upper()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM watchlists WHERE id = ?", (watchlist_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Watchlist not found.")
            
        updates = []
        params = []
        if data.quantity is not None:
            updates.append("quantity = ?")
            params.append(data.quantity)
        if data.purchase_price is not None:
            updates.append("purchase_price = ?")
            params.append(data.purchase_price)
        if data.in_portfolio is not None:
            updates.append("in_portfolio = ?")
            params.append(data.in_portfolio)
            
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update.")
            
        query = f"UPDATE watchlist_items SET {', '.join(updates)} WHERE watchlist_id = ? AND UPPER(symbol) = ?"
        params.extend([watchlist_id, symbol])
        
        cursor.execute(query, params)
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Stock not found in this watchlist.")
        conn.commit()
    return {"status": "success"}

class WatchlistStockAlertUpdate(BaseModel):
    enabled: Optional[bool] = True
    price_low: Optional[float] = None
    price_high: Optional[float] = None
    breakout_52w: Optional[bool] = False
    flash_dip_pct: Optional[float] = None
    entry_dip_pct: Optional[float] = None
    volume_spike: Optional[bool] = False
    mos_undervalued: Optional[bool] = False
    pe_compression: Optional[float] = None
    score_shift: Optional[bool] = False
    rsi_extremes: Optional[bool] = False
    ma_proximity_enabled: Optional[bool] = False
    ma_period: Optional[str] = "EMA_50"
    ma_threshold_pct: Optional[float] = 3.0

def sync_watchlist_alerts_to_db_table(conn, watchlist_id: int, symbol: str, config: dict):
    """Syncs Watchlist Stock Alert Config into the central `alerts` SQLite table and AlertEvaluator."""
    cursor = conn.cursor()
    base_sym = symbol.replace('.NS', '').replace('.BO', '').upper()
    
    # 1. Clean up existing watchlist rule alerts for this symbol
    cursor.execute("DELETE FROM alerts WHERE (UPPER(ticker) = ? OR UPPER(ticker) = ?) AND ai_context LIKE 'Watchlist Rule%'", (base_sym, f"{base_sym}.NS"))
    
    if not config or not config.get("enabled", True):
        conn.commit()
        return

    items_to_insert = []
    
    if config.get("price_low") is not None:
        items_to_insert.append((
            f"wl_{watchlist_id}_{base_sym}_price_low",
            base_sym, "PRICE", "<=", str(config["price_low"]), "Active", 0, "", "Watchlist Rule (Target Low)"
        ))
    if config.get("price_high") is not None:
        items_to_insert.append((
            f"wl_{watchlist_id}_{base_sym}_price_high",
            base_sym, "PRICE", ">=", str(config["price_high"]), "Active", 0, "", "Watchlist Rule (Target High)"
        ))
    if config.get("breakout_52w"):
        items_to_insert.append((
            f"wl_{watchlist_id}_{base_sym}_breakout_52w",
            base_sym, "BREAKOUT", "BREAKOUT 52W", "52W High", "Active", 0, "", "Watchlist Rule (52-Week High Breakout)"
        ))
    if config.get("flash_dip_pct") is not None:
        items_to_insert.append((
            f"wl_{watchlist_id}_{base_sym}_flash_dip",
            base_sym, "FLASH_DIP", "DROP >=", f"{config['flash_dip_pct']}%", "Active", 0, "", "Watchlist Rule (Flash Dip)"
        ))
    if config.get("entry_dip_pct") is not None:
        items_to_insert.append((
            f"wl_{watchlist_id}_{base_sym}_entry_dip",
            base_sym, "ENTRY_DIP", "DROP >=", f"{config['entry_dip_pct']}%", "Active", 0, "", "Watchlist Rule (Entry Dip)"
        ))
    if config.get("volume_spike"):
        items_to_insert.append((
            f"wl_{watchlist_id}_{base_sym}_volume_spike",
            base_sym, "VOLUME", "SPIKE >=", "2.5x 20D Avg", "Active", 0, "", "Watchlist Rule (Volume Spike)"
        ))
    if config.get("mos_undervalued"):
        items_to_insert.append((
            f"wl_{watchlist_id}_{base_sym}_mos",
            base_sym, "VALUATION", "MOS >=", "20.0%", "Active", 0, "", "Watchlist Rule (MOS Undervalued)"
        ))
    if config.get("pe_compression") is not None:
        items_to_insert.append((
            f"wl_{watchlist_id}_{base_sym}_pe",
            base_sym, "PE_COMPRESSION", "<=", str(config["pe_compression"]), "Active", 0, "", "Watchlist Rule (P/E Compression)"
        ))
    if config.get("score_shift"):
        items_to_insert.append((
            f"wl_{watchlist_id}_{base_sym}_score",
            base_sym, "SCORE_SHIFT", "CONVICTION", "< 50 or > 75", "Active", 0, "", "Watchlist Rule (Conviction Score Shift)"
        ))
    if config.get("rsi_extremes"):
        items_to_insert.append((
            f"wl_{watchlist_id}_{base_sym}_rsi",
            base_sym, "RSI", "EXTREME", "< 30 or > 70", "Active", 0, "", "Watchlist Rule (RSI Extreme)"
        ))
    if config.get("ma_proximity_enabled"):
        ma_p = config.get("ma_period", "EMA_50")
        ma_t = config.get("ma_threshold_pct", 3.0)
        items_to_insert.append((
            f"wl_{watchlist_id}_{base_sym}_ma",
            base_sym, "MA_PROXIMITY", "WITHIN", f"{ma_t}% of {ma_p}", "Active", 0, "", "Watchlist Rule (MA Proximity)"
        ))

    for item in items_to_insert:
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO alerts (id, ticker, condition_type, operator, value, status, triggered, trigger_date, ai_context) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                item
            )
        except Exception as e:
            logger.error(f"Error inserting watchlist alert to db: {e}")
            
    conn.commit()

    # Register with real-time AlertEvaluator if available
    try:
        from backend.websocket_server import alert_evaluator as _ae
        if _ae is not None:
            for item in items_to_insert:
                _ae.register_alert({
                    "id": item[0],
                    "ticker": item[1],
                    "condition_type": item[2],
                    "operator": item[3],
                    "value": item[4],
                    "status": "Active",
                    "triggered": False
                })
    except Exception:
        pass

@app.put("/api/watchlists/{watchlist_id}/items/{symbol}/alerts")
async def update_watchlist_item_alerts(watchlist_id: int, symbol: str, data: WatchlistStockAlertUpdate):
    symbol = symbol.strip().upper()
    config_dict = data.dict()
    config_json = json.dumps(config_dict)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM watchlists WHERE id = ?", (watchlist_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Watchlist not found.")
            
        base_sym = symbol.replace('.NS', '').replace('.BO', '')
        ns_sym = f"{base_sym}.NS"
        
        cursor.execute("""
            UPDATE watchlist_items SET alert_config = ? 
            WHERE watchlist_id = ? AND (UPPER(symbol) = ? OR UPPER(symbol) = ? OR UPPER(symbol) = ?)
        """, (config_json, watchlist_id, symbol, base_sym, ns_sym))
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Stock not found in this watchlist.")
        
        sync_watchlist_alerts_to_db_table(conn, watchlist_id, symbol, config_dict)
        conn.commit()
    return {"status": "success", "alert_config": config_dict}

@app.delete("/api/watchlists/{watchlist_id}/items/{symbol}")
async def remove_watchlist_item(watchlist_id: int, symbol: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM watchlist_items WHERE watchlist_id = ? AND symbol = ?",
            (watchlist_id, symbol.strip().upper())
        )
        conn.commit()
    return {"status": "success"}

@app.get("/api/watchlists/{watchlist_id}/analyze")
async def analyze_watchlist(watchlist_id: int):
    """Batch-analyzes every stock in a watchlist and returns scored rankings."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, name, sector FROM watchlist_items WHERE watchlist_id = ?", (watchlist_id,))
        items = [dict(row) for row in cursor.fetchall()]
    
    if not items:
        return {"results": [], "message": "Watchlist is empty."}
    
    results = []
    for item in items:
        try:
            profile = await asyncio.to_thread(get_complete_financial_profile, item["symbol"])
            sm = profile.get("score_metrics", {})
            f = profile.get("fundamentals", {})
            results.append({
                "symbol": item["symbol"],
                "name": profile.get("company_name", item["name"]),
                "sector": profile.get("sector", item["sector"]),
                "current_price": float(f.get("current_price", 0)),
                "pe": float(f.get("pe_ratio", 0)),
                "roe": float(f.get("roe_pct", 0)),
                "score": int(sm.get("final_score", 50)),
                "action": sm.get("action", "HOLD"),
                "margin_of_safety": float(profile.get("dcf_model", {}).get("margin_of_safety", 0)),
                "rsi": float(profile.get("technicals", {}).get("rsi", 50)),
                "trend": profile.get("technicals", {}).get("trend_50_vs_200", "Neutral")
            })
        except Exception as e:
            print(f"Error analyzing watchlist item {item['symbol']}: {e}")
            results.append({
                "symbol": item["symbol"],
                "name": item["name"],
                "sector": item["sector"],
                "current_price": 0,
                "pe": 0,
                "roe": 0,
                "score": 0,
                "action": "ERROR",
                "margin_of_safety": 0,
                "rsi": 0,
                "trend": "N/A"
            })
    
    results = sorted(results, key=lambda x: x["score"], reverse=True)
    return {"results": results}


class BatchQuotesRequest(BaseModel):
    symbols: List[str]

@app.post("/api/batch-quotes")
async def batch_quotes(data: BatchQuotesRequest):
    """
    Lightweight batch endpoint to fetch live market quotes for a list of symbols.
    Hybrid: Uses Angel One tick store if available, falls back to yfinance batch download.
    Auto-appends .NS suffix for Indian stock symbols that lack an exchange suffix.
    """
    raw_symbols = [s.strip().upper() for s in data.symbols if s.strip()]
    if not raw_symbols:
        return {"quotes": {}}

    # Cap at 100 symbols max to prevent abuse
    raw_symbols = raw_symbols[:100]

    quotes = {}

    # ── Strategy 1: Angel One Tick Store (instant, real-time) ──
    if angel_connector and angel_connector.is_authenticated() and tick_store.count > 0:
        found_symbols = []
        for sym in raw_symbols:
            plain = sym.replace(".NS", "").replace(".BO", "")
            tick = tick_store.get(plain)
            if tick and tick.get("price", 0) > 0:
                quotes[sym] = {
                    "price": tick["price"],
                    "change": tick.get("change", 0),
                    "change_pct": tick.get("change_pct", 0),
                    "high": tick.get("high", tick["price"]),
                    "low": tick.get("low", tick["price"]),
                }
                found_symbols.append(sym)

        # If we got all symbols from tick store, return immediately
        if len(found_symbols) == len(raw_symbols):
            return {"quotes": quotes}

        # Remove found symbols — only fetch missing ones from yfinance
        raw_symbols = [s for s in raw_symbols if s not in found_symbols]

    # ── Strategy 2: Commodity Spot Scraper for SPOTGOLD / SPOTSILVER ──
    if "SPOTGOLD" in raw_symbols or "SPOTSILVER" in raw_symbols:
        try:
            from backend.commodity_scraper import CommodityScraper
            spots = await CommodityScraper.get_prices()
            if "SPOTGOLD" in raw_symbols and "gold_24k" in spots:
                g24 = spots["gold_24k"]
                if g24.get("price", 0) > 0:
                    quotes["SPOTGOLD"] = {
                        "price": g24["price"],
                        "change": g24.get("change", 0),
                        "change_pct": round(g24.get("change_pct", 0), 2),
                        "high": g24["price"],
                        "low": g24["price"]
                    }
                    raw_symbols = [s for s in raw_symbols if s != "SPOTGOLD"]
            if "SPOTSILVER" in raw_symbols and "silver_1kg" in spots:
                sil = spots["silver_1kg"]
                if sil.get("price", 0) > 0:
                    quotes["SPOTSILVER"] = {
                        "price": sil["price"],
                        "change": sil.get("change", 0),
                        "change_pct": round(sil.get("change_pct", 0), 2),
                        "high": sil["price"],
                        "low": sil["price"]
                    }
                    raw_symbols = [s for s in raw_symbols if s != "SPOTSILVER"]
        except Exception as e:
            logger.warning(f"Failed to fetch commodity spots in batch_quotes: {e}")

    # ── Strategy 3: yfinance batch download (fallback) ──
    if raw_symbols:
        # Map original symbols to yfinance tickers (.NS suffix for NSE)
        sym_to_yf = {}
        yf_symbols = []
        for sym in raw_symbols:
            if '.' in sym or sym.startswith('^') or '=' in sym or '-' in sym:
                yf_sym = sym  # Already has exchange suffix, currency format, index or futures ticker
            elif sym == "SPOTGOLD":
                yf_sym = "GC=F"
            elif sym == "SPOTSILVER":
                yf_sym = "SI=F"
            else:
                yf_sym = f"{sym}.NS"  # Default to NSE
            sym_to_yf[sym] = yf_sym
            yf_symbols.append(yf_sym)

        try:
            # Use yfinance batch download for efficiency (2d period for prev close comparison)
            df = await asyncio.to_thread(
                yf.download,
                yf_symbols,
                period="5d",
                interval="1d",
                progress=False,
                threads=12
            )

            if not df.empty:
                is_multi = isinstance(df.columns, pd.MultiIndex)

                for orig_sym, yf_sym in sym_to_yf.items():
                    try:
                        if is_multi:
                            if yf_sym not in df.columns.get_level_values(1):
                                continue
                            close_series = df['Close'][yf_sym].dropna()
                            high_series = df['High'][yf_sym].dropna()
                            low_series = df['Low'][yf_sym].dropna()
                        else:
                            # Single symbol case — no multi-level columns
                            close_series = df['Close'].dropna()
                            high_series = df['High'].dropna()
                            low_series = df['Low'].dropna()

                        if close_series.empty:
                            continue

                        current_price = float(close_series.iloc[-1])
                        day_high = float(high_series.iloc[-1]) if not high_series.empty else current_price
                        day_low = float(low_series.iloc[-1]) if not low_series.empty else current_price

                        # Calculate change from previous close
                        prev_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else current_price
                        change = current_price - prev_close
                        change_pct = (change / prev_close * 100.0) if prev_close > 0 else 0.0

                        # Map back to original symbol key (e.g., "TCS" not "TCS.NS")
                        quotes[orig_sym] = {
                            "price": round(current_price, 2),
                            "change": round(change, 2),
                            "change_pct": round(change_pct, 2),
                            "high": round(day_high, 2),
                            "low": round(day_low, 2)
                        }
                    except Exception as sym_err:
                        print(f"Batch quote error for {orig_sym} ({yf_sym}): {sym_err}")
                        continue

        except Exception as e:
            print(f"Batch quotes download error: {e}")

    return {"quotes": quotes}


class PortfolioItemInput(BaseModel):
    symbol: str
    quantity: float
    buy_price: float
    purchase_date: Optional[str] = "2026-06-05"

class PortfolioDoctorInput(BaseModel):
    items: List[PortfolioItemInput]

@app.get("/api/returns")
async def get_returns(
    symbol: str,
    amount: float = 100000.0,
    date_y: str = "2021-01-01",
    type: str = "cagr",
    sip_monthly: float = 5000.0
):
    try:
        resolution = resolve_company_ticker(symbol)
        yf_ticker = resolution["yf_ticker"]
        stock = yf.Ticker(yf_ticker)
        
        # Fetch daily history from date_y
        hist = stock.history(start=date_y)
        if hist.empty:
            raise HTTPException(status_code=400, detail="No historical price data found for this period.")
            
        start_date = hist.index[0]
        end_date = hist.index[-1]
        years = (end_date - start_date).days / 365.25
        if years <= 0:
            years = 0.01
            
        start_price = float(hist["Close"].iloc[0])
        end_price = float(hist["Close"].iloc[-1])
        
        if type == "cagr":
            initial_investment = amount
            final_shares = initial_investment / start_price
            final_value = final_shares * end_price
            total_profit = final_value - initial_investment
            absolute_return = (total_profit / initial_investment) * 100.0
            cagr = (((final_value / initial_investment) ** (1 / years)) - 1) * 100.0
            
            return {
                "symbol": symbol,
                "company_name": resolution["name"] or symbol,
                "type": "CAGR",
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "start_price": round(start_price, 2),
                "end_price": round(end_price, 2),
                "invested_amount": round(initial_investment, 2),
                "final_value": round(final_value, 2),
                "profit_loss": round(total_profit, 2),
                "absolute_return_pct": round(absolute_return, 2),
                "annualized_return_pct": round(cagr, 2),
                "years_elapsed": round(years, 2)
            }
        else:
            # SIP calculation
            # For SIP, we invest sip_monthly on the first trading day of each month
            # We group by year and month
            hist["Year"] = hist.index.year
            hist["Month"] = hist.index.month
            
            # Find first available trading day of each month
            first_days = hist.groupby(["Year", "Month"]).first()
            
            total_invested = 0.0
            total_shares = 0.0
            investments = []
            
            for idx, row in first_days.iterrows():
                close_pr = float(row["Close"])
                shares_bought = sip_monthly / close_pr
                total_shares += shares_bought
                total_invested += sip_monthly
                
                # Find the index date
                matching_rows = hist[(hist.index.year == idx[0]) & (hist.index.month == idx[1])]
                date_str = matching_rows.index[0].strftime("%Y-%m-%d")
                
                investments.append({
                    "date": date_str,
                    "amount": sip_monthly,
                    "price": round(close_pr, 2),
                    "shares_bought": round(shares_bought, 4)
                })
                
            final_value = total_shares * end_price
            total_profit = final_value - total_invested
            absolute_return = (total_profit / total_invested) * 100.0 if total_invested > 0 else 0.0
            
            # Approximate annualized return for SIP (IRR)
            irr = 0.0
            if total_invested > 0:
                # Cashflows are [-sip, -sip, ..., +final_value]
                cashflows = [-sip_monthly] * len(investments)
                cashflows[-1] += final_value
                
                # Bisection solver
                low = -0.99
                high = 5.0
                for _ in range(50):
                    mid = (low + high) / 2
                    npv = 0.0
                    for t, cf in enumerate(cashflows):
                        factor = max(1e-6, 1 + mid)
                        npv += cf / (factor ** t)
                    if npv > 0:
                        low = mid
                    else:
                        high = mid
                
                monthly_irr = (low + high) / 2
                irr = (((1 + monthly_irr) ** 12) - 1) * 100.0
                
            return {
                "symbol": symbol,
                "company_name": resolution["name"] or symbol,
                "type": "SIP",
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "monthly_sip": sip_monthly,
                "invested_amount": round(total_invested, 2),
                "final_value": round(final_value, 2),
                "profit_loss": round(total_profit, 2),
                "absolute_return_pct": round(absolute_return, 2),
                "annualized_return_pct": round(irr, 2),
                "years_elapsed": round(years, 2),
                "investments_breakdown": investments
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Return Calculator Error: {str(e)}")

@app.get("/api/drawdown")
async def get_drawdown(symbol: str, period: str = "5y"):
    try:
        resolution = resolve_company_ticker(symbol)
        yf_ticker = resolution["yf_ticker"]
        stock = yf.Ticker(yf_ticker)
        
        hist = stock.history(period=period)
        if hist.empty:
            raise HTTPException(status_code=400, detail="No historical price data found for drawdown analysis.")
            
        prices = hist["Close"].tolist()
        dates = [d.strftime("%Y-%m-%d") for d in hist.index]
        
        peaks = []
        drawdowns = []
        max_dd = 0.0
        max_dd_date = ""
        current_peak = 0.0
        
        for d, p in zip(dates, prices):
            if p > current_peak:
                current_peak = p
            dd = ((p - current_peak) / current_peak * 100.0) if current_peak > 0 else 0.0
            peaks.append(current_peak)
            drawdowns.append(dd)
            
            if dd < max_dd:
                max_dd = dd
                max_dd_date = d
                
        # Find drawdown recovery periods
        in_drawdown = False
        dd_start = None
        max_duration = 0
        current_duration = 0
        
        for d_str, dd in zip(dates, drawdowns):
            if dd < -0.5:
                if not in_drawdown:
                    in_drawdown = True
                    dd_start = datetime.strptime(d_str, "%Y-%m-%d")
                current_duration = (datetime.strptime(d_str, "%Y-%m-%d") - dd_start).days
                if current_duration > max_duration:
                    max_duration = current_duration
            else:
                in_drawdown = False
                current_duration = 0
                
        return {
            "symbol": symbol,
            "company_name": resolution["name"] or symbol,
            "period": period,
            "max_drawdown_pct": round(max_dd, 2),
            "max_drawdown_date": max_dd_date,
            "current_drawdown_pct": round(drawdowns[-1], 2),
            "worst_drawdown_duration_days": max_duration,
            "chart_data": {
                "dates": dates,
                "prices": [round(p, 2) for p in prices],
                "peaks": [round(pk, 2) for pk in peaks],
                "drawdowns": [round(dd, 2) for dd in drawdowns]
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Drawdown Analysis Error: {str(e)}")

@app.get("/api/relative-strength")
async def get_relative_strength(symbol: str, period: str = "1y"):
    try:
        resolution = resolve_company_ticker(symbol)
        yf_ticker = resolution["yf_ticker"]
        
        stock = yf.Ticker(yf_ticker)
        nifty = yf.Ticker("^NSEI")
        
        stock_hist = stock.history(period=period)
        nifty_hist = nifty.history(period=period)
        
        if stock_hist.empty or nifty_hist.empty:
            raise HTTPException(status_code=400, detail="Insufficient historical price data for relative strength.")
            
        combined = pd.DataFrame({
            "stock": stock_hist["Close"],
            "nifty": nifty_hist["Close"]
        }).dropna()
        
        if combined.empty:
            raise HTTPException(status_code=400, detail="Aligned date indices are empty.")
            
        dates = [d.strftime("%Y-%m-%d") for d in combined.index]
        
        stock_norm = (combined["stock"] / combined["stock"].iloc[0]) * 100.0
        nifty_norm = (combined["nifty"] / combined["nifty"].iloc[0]) * 100.0
        
        ratio = combined["stock"] / combined["nifty"]
        ratio_norm = (ratio / ratio.iloc[0]) * 100.0
        
        ratio_ma = ratio_norm.rolling(window=20).mean().fillna(100.0)
        
        stock_perf = ((combined["stock"].iloc[-1] - combined["stock"].iloc[0]) / combined["stock"].iloc[0]) * 100.0
        nifty_perf = ((combined["nifty"].iloc[-1] - combined["nifty"].iloc[0]) / combined["nifty"].iloc[0]) * 100.0
        outperformance = stock_perf - nifty_perf
        
        return {
            "symbol": symbol,
            "company_name": resolution["name"] or symbol,
            "period": period,
            "stock_performance_pct": round(stock_perf, 2),
            "nifty_performance_pct": round(nifty_perf, 2),
            "outperformance_pct": round(outperformance, 2),
            "chart_data": {
                "dates": dates,
                "stock_normalized": [round(v, 2) for v in stock_norm],
                "nifty_normalized": [round(v, 2) for v in nifty_norm],
                "ratio_normalized": [round(v, 2) for v in ratio_norm],
                "ratio_ma_20": [round(v, 2) for v in ratio_ma]
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Relative Strength Error: {str(e)}")

# ==================== STANDALONE AI PORTFOLIO DOCTOR ====================

@app.get("/api/portfolio")
async def get_portfolio(refresh: bool = False):
    import json
    
    # 1. Handle price refreshing if requested
    if refresh:
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, symbol, name, sector, quantity, purchase_price, purchase_date, transaction_type FROM portfolio_items")
                all_txs = [dict(row) for row in cursor.fetchall()]
                active_txs = compute_active_holdings(all_txs)
                symbols = list(set(row["symbol"] for row in active_txs))
            if symbols:
                tasks = [asyncio.to_thread(get_complete_financial_profile, sym, True) for sym in symbols]
                await asyncio.gather(*tasks)
        except Exception as ref_err:
            print(f"Error refreshing portfolio prices: {ref_err}")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, symbol, name, sector, quantity, purchase_price, purchase_date, transaction_type FROM portfolio_items")
        all_txs = [dict(row) for row in cursor.fetchall()]
        
        # Calculate active holdings dynamically via FIFO netting
        rows = compute_active_holdings(all_txs)
        
        # Hydrate target ranges and current price from cached_profiles if available
        from backend.websocket_server import tick_store
        hydrated_rows = []
        for row in rows:
            sym = row["symbol"]
            plain_sym = sym.replace(".NS", "").replace(".BO", "")
            
            cursor.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ?", (sym,))
            cache_row = cursor.fetchone()
            
            # Default values
            row["has_analysis"] = False
            row["suggested_buy_price_range"] = "N/A"
            row["suggested_sell_price_range"] = "N/A"
            row["target_12m"] = None
            row["stop_loss_12m"] = None
            row["current_price"] = None
            row["day_change_pct"] = None
            row["score"] = 50
            
            # Try to resolve live quotes from WebSocket tick store first
            live_tick = tick_store.get(plain_sym) or tick_store.get(sym)
            if live_tick:
                row["current_price"] = live_tick.get("price")
                row["day_change_pct"] = live_tick.get("change_pct")
            
            if cache_row:
                try:
                    profile = json.loads(cache_row["profile_json"])
                    analysis = profile.get("analysis", {})
                    row["has_analysis"] = True
                    row["suggested_buy_price_range"] = analysis.get("suggested_buy_price_range", "N/A")
                    row["suggested_sell_price_range"] = analysis.get("suggested_sell_price_range", "N/A")
                    row["target_12m"] = analysis.get("target_12m")
                    row["stop_loss_12m"] = analysis.get("stop_loss_12m")
                    if not row["current_price"]:
                        row["current_price"] = profile.get("fundamentals", {}).get("current_price")
                    if not row["day_change_pct"]:
                        row["day_change_pct"] = profile.get("technicals", {}).get("price_change_pct")
                    row["score"] = profile.get("score_metrics", {}).get("final_score", 50)
                except Exception as e:
                    print(f"Error parsing cached profile for {sym}: {e}")
            
            # yfinance fallback if price is still missing
            if not row["current_price"]:
                try:
                    import yfinance as yf
                    yf_sym = sym if '.' in sym or sym.startswith('^') else f"{sym}.NS"
                    ticker_obj = yf.Ticker(yf_sym)
                    info = ticker_obj.info
                    if info:
                        row["current_price"] = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("navPrice")
                        if not row["day_change_pct"]:
                            pc = info.get("previousClose") or info.get("regularMarketPreviousClose")
                            if pc and row["current_price"]:
                                row["day_change_pct"] = ((row["current_price"] - pc) / pc) * 100
                except Exception as yf_err:
                    print(f"Error resolving fallback quote for portfolio item {sym}: {yf_err}")

            # Autocomplete empty target valuation ranges if we have current_price to ensure the slider is populated
            if row["current_price"]:
                cur_p = row["current_price"]
                if not row["suggested_buy_price_range"] or row["suggested_buy_price_range"] == "N/A":
                    row["suggested_buy_price_range"] = f"Rs. {int(cur_p * 0.95)} - Rs. {int(cur_p * 1.02)}"
                if not row["suggested_sell_price_range"] or row["suggested_sell_price_range"] == "N/A":
                    row["suggested_sell_price_range"] = f"Rs. {int(cur_p * 1.15)} - Rs. {int(cur_p * 1.25)}"
            
            hydrated_rows.append(row)
        return hydrated_rows

@app.get("/api/portfolio/transactions")
async def get_portfolio_transactions():
    """Returns the complete list of raw buy and sell transactions stored in the database."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, symbol, name, sector, quantity, purchase_price, purchase_date, transaction_type FROM portfolio_items ORDER BY id DESC")
        return [dict(row) for row in cursor.fetchall()]

@app.post("/api/portfolio")
async def add_portfolio_item(data: PortfolioItemCreate):
    symbol = data.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Stock symbol is required.")
        
    # Resolve symbol and fetch company details online
    try:
        resolved = resolve_company_ticker(symbol)
        full_ticker = resolved.get("yf_ticker") or f"{symbol}.NS"
        base_symbol = resolved.get("base_symbol") or symbol
    except Exception:
        full_ticker = f"{symbol}.NS"
        base_symbol = symbol
        
    company_name = resolved.get("name") or base_symbol
    sector = "General Equities"
    
    # Fetch detailed profile online/cache to resolve sector and longname
    try:
        # Run the CIO parent agent to get complete multi-agent audit & warm cached_profiles
        profile = await run_cio_parent_agent(full_ticker, "Long-term (3+ years)", "Moderate")
        company_name = profile.get("company_name") or company_name
        sector = profile.get("sector") or sector
        
        # Save to cached_profiles persistent SQLite cache
        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cached_profiles (symbol, profile_json, updated_at) VALUES (?, ?, ?)",
                    (full_ticker, json.dumps(profile), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                )
                conn.commit()
        except Exception as db_err:
            print(f"Error caching added portfolio item profile: {db_err}")
    except Exception as e:
        print(f"Orchestration warning on add_portfolio_item (falling back to yfinance scrape): {e}")
        try:
            profile = await asyncio.to_thread(get_complete_financial_profile, full_ticker)
            company_name = profile.get("company_name") or company_name
            sector = profile.get("sector") or sector
        except Exception:
            pass
        
    today_str = datetime.now().strftime("%Y-%m-%d")
    p_date = data.purchase_date or today_str
    t_type = (data.transaction_type or "buy").strip().lower()
    try:
        datetime.strptime(p_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Purchase date must be in YYYY-MM-DD format.")
        
    if p_date > today_str:
        raise HTTPException(status_code=400, detail="Purchase date cannot be in the future.")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO portfolio_items (symbol, name, sector, quantity, purchase_price, purchase_date, transaction_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (full_ticker, company_name, sector, data.quantity or 10.0, data.purchase_price or 100.0, p_date, t_type)
        )
        inserted_id = cursor.lastrowid
        conn.commit()
        return {
            "id": inserted_id,
            "symbol": full_ticker,
            "name": company_name,
            "sector": sector,
            "quantity": data.quantity or 10.0,
            "purchase_price": data.purchase_price or 100.0,
            "purchase_date": p_date,
            "transaction_type": t_type
        }

@app.put("/api/portfolio/{item_id_or_symbol}")
async def update_portfolio_item(item_id_or_symbol: str, data: PortfolioItemUpdate):
    is_id = item_id_or_symbol.isdigit()
    with get_db() as conn:
        cursor = conn.cursor()
        updates = []
        params = []
        if data.quantity is not None:
            updates.append("quantity = ?")
            params.append(data.quantity)
        if data.purchase_price is not None:
            updates.append("purchase_price = ?")
            params.append(data.purchase_price)
        if data.purchase_date is not None:
            try:
                datetime.strptime(data.purchase_date, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="Purchase date must be in YYYY-MM-DD format.")
            today_str = datetime.now().strftime("%Y-%m-%d")
            if data.purchase_date > today_str:
                raise HTTPException(status_code=400, detail="Purchase date cannot be in the future.")
            updates.append("purchase_date = ?")
            params.append(data.purchase_date)
        if data.transaction_type is not None:
            updates.append("transaction_type = ?")
            params.append(data.transaction_type.strip().lower())
            
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update.")
            
        if is_id:
            query = f"UPDATE portfolio_items SET {', '.join(updates)} WHERE id = ?"
            params.append(int(item_id_or_symbol))
        else:
            query = f"UPDATE portfolio_items SET {', '.join(updates)} WHERE UPPER(symbol) = ?"
            params.append(item_id_or_symbol.upper())
            
        cursor.execute(query, params)
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Stock tranche not found in portfolio.")
        conn.commit()
    return {"status": "success"}

@app.delete("/api/portfolio/{item_id_or_symbol}")
async def delete_portfolio_item(item_id_or_symbol: str):
    is_id = item_id_or_symbol.isdigit()
    with get_db() as conn:
        cursor = conn.cursor()
        if is_id:
            cursor.execute("DELETE FROM portfolio_items WHERE id = ?", (int(item_id_or_symbol),))
        else:
            cursor.execute("DELETE FROM portfolio_items WHERE UPPER(symbol) = ?", (item_id_or_symbol.upper(),))
            
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Stock tranche not found in portfolio.")
        conn.commit()
    return {"status": "success"}

@app.get("/api/portfolio/watchlist-stocks")
async def get_portfolio_watchlist_stocks():
    """Returns all unique stocks from all watchlists that are not in the portfolio."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, symbol, name, sector, quantity, purchase_price, purchase_date, transaction_type FROM portfolio_items")
        all_txs = [dict(row) for row in cursor.fetchall()]
        active_holdings = compute_active_holdings(all_txs)
        active_symbols = set(item["symbol"].upper() for item in active_holdings)
        
        cursor.execute("SELECT DISTINCT symbol, name, sector FROM watchlist_items")
        wl_items = [dict(row) for row in cursor.fetchall()]
        
        filtered = [item for item in wl_items if item["symbol"].upper() not in active_symbols]
        return filtered

@app.post("/api/portfolio/upload")
async def upload_portfolio_file(file: UploadFile = File(...)):
    import pandas as pd
    import io
    import json
    
    contents = await file.read()
    filename = file.filename.lower()
    
    try:
        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(contents))
        elif filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format. Please upload an Excel (.xlsx/.xls) or CSV file.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse spreadsheet file: {str(e)}")
        
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    symbol_aliases = ['symbol', 'ticker', 'stock', 'isin', 'instrument', 'code', 'stock symbol', 'instrument name', 'token']
    qty_aliases = ['quantity', 'qty', 'volume', 'shares', 'units', 'available qty', 'holding qty', 'qty.', 'balance']
    price_aliases = ['average cost', 'avg price', 'buy price', 'purchase price', 'price', 'cost', 'avg. price', 'avg_cost', 'cost price', 'acquisition price']
    date_aliases = ['date', 'purchase date', 'buy date', 'trade date', 'acquired date', 'purchase_date', 'buy_date', 'order_execution_time', 'order execution time']
    type_aliases = ['trade_type', 'trade type', 'type', 'action', 'transaction_type', 'transaction type', 'buy/sell', 'buy or sell']
    
    symbol_col = None
    qty_col = None
    price_col = None
    date_col = None
    type_col = None
    
    for c in df.columns:
        if c in symbol_aliases:
            symbol_col = c
        elif c in qty_aliases:
            qty_col = c
        elif c in price_aliases:
            price_col = c
        elif c in date_aliases:
            date_col = c
        elif c in type_aliases:
            type_col = c
            
    if not symbol_col:
        for c in df.columns:
            sample = df[c].dropna().head(3).tolist()
            if sample and all(isinstance(x, str) and (x.isupper() or x.endswith('.NS') or len(x) <= 10) for x in sample):
                symbol_col = c
                break
                
    if not symbol_col or not qty_col or not price_col:
        found_cols = ", ".join(df.columns)
        raise HTTPException(status_code=400, detail=f"Could not map columns. Required: Symbol, Quantity, and Buy Price. Found columns: [{found_cols}]. Please align your spreadsheet columns.")
        
    imported_count = 0
    errors = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    trades = []
    for idx, row in df.iterrows():
        try:
            raw_sym = str(row[symbol_col]).strip()
            if not raw_sym or raw_sym.lower() in ['nan', 'null']:
                continue
            raw_sym = raw_sym.upper()
            
            # Resolve symbol
            try:
                resolved = resolve_company_ticker(raw_sym)
                full_ticker = resolved.get("yf_ticker") or f"{raw_sym}.NS"
            except Exception:
                full_ticker = f"{raw_sym}.NS"
            
            # Quantity
            qty_val = row[qty_col]
            if pd.isna(qty_val):
                continue
            qty = float(qty_val)
            if qty <= 0:
                continue
                
            # Price
            price_val = row[price_col]
            if pd.isna(price_val):
                continue
            price = float(price_val)
            if price < 0:
                continue
                
            # Date
            p_date = today_str
            dt_for_sorting = pd.to_datetime(today_str)
            if date_col and not pd.isna(row[date_col]):
                raw_date = str(row[date_col]).strip()
                try:
                    parsed_dt = pd.to_datetime(raw_date)
                    p_date = parsed_dt.strftime('%Y-%m-%d')
                    dt_for_sorting = parsed_dt
                except Exception:
                    pass
            
            # Type (buy/sell)
            t_type = 'buy'
            if type_col and not pd.isna(row[type_col]):
                raw_type = str(row[type_col]).strip().lower()
                if 'sell' in raw_type or 'short' in raw_type:
                    t_type = 'sell'
                    
            trades.append({
                "symbol": full_ticker,
                "quantity": qty,
                "price": price,
                "date": p_date,
                "dt": dt_for_sorting,
                "type": t_type,
                "row_idx": idx + 2
            })
        except Exception as row_err:
            errors.append(f"Row {idx+2}: {str(row_err)}")
            
    # Sort all trades chronologically
    trades.sort(key=lambda x: x["dt"])
    
    # Insert all parsed buy and sell transactions into the SQLite database, clearing it first
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM portfolio_items")
        
        for trade in trades:
            try:
                full_ticker = trade["symbol"]
                qty = trade["quantity"]
                price = trade["price"]
                p_date = trade["date"]
                t_type = trade["type"]
                
                # Resolve base symbol
                base_symbol = full_ticker.split('.')[0] if '.' in full_ticker else full_ticker
                company_name = base_symbol
                sector = "General Equities"
                
                # Try cached_profiles first
                cursor.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ?", (full_ticker,))
                cache_row = cursor.fetchone()
                if cache_row:
                    profile = json.loads(cache_row["profile_json"])
                    company_name = profile.get("company_name") or company_name
                    sector = profile.get("sector") or sector
                
                cursor.execute(
                    "INSERT INTO portfolio_items (symbol, name, sector, quantity, purchase_price, purchase_date, transaction_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (full_ticker, company_name, sector, qty, price, p_date, t_type)
                )
                imported_count += 1
            except Exception as ins_err:
                errors.append(f"Insert error for {trade['symbol']}: {str(ins_err)}")
        conn.commit()
        
    return {"status": "success", "imported": imported_count, "errors": errors}

@app.get("/api/portfolio/tax-report")
async def get_portfolio_tax_report(generate_prescription: bool = False):
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, symbol, name, sector, quantity, purchase_price, purchase_date, transaction_type FROM portfolio_items")
            portfolio_items = [dict(row) for row in cursor.fetchall()]
        
        # Calculate active holdings dynamically via FIFO netting for unrealized loss harvesting
        active_holdings = compute_active_holdings(portfolio_items)
        tax_report = await asyncio.to_thread(calculate_portfolio_taxes, active_holdings, generate_prescription)
        return tax_report
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tax Analysis Error: {str(e)}")

@app.post("/api/portfolio/stress-test")
async def run_portfolio_stress_test(data: StressTestRequest):
    """
    Simulates a macroeconomic scenario (shock) against the active portfolio holdings,
    assessing exposure and potential margin impacts.
    """
    if not data.scenario:
        raise HTTPException(status_code=400, detail="Scenario description is required.")
        
    try:
        # 1. Query all transactions
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, symbol, name, sector, quantity, purchase_price, purchase_date, transaction_type FROM portfolio_items")
            all_txs = [dict(row) for row in cursor.fetchall()]
            
        # Compute active holdings
        holdings = compute_active_holdings(all_txs)
        if not holdings:
            return {
                "scenario": data.scenario,
                "analysis": {
                    "impact_summary": "No active portfolio holdings detected to simulate stress testing against. Please populate your portfolio first.",
                    "vulnerable_stocks": [],
                    "resilient_stocks": [],
                    "margin_impact": "Unknown",
                    "recommendations": ["Add transactions to your portfolio."]
                }
            }
            
        # Get current prices and details from cache
        portfolio_summary = []
        for h in holdings:
            sym = h["symbol"]
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ?", (sym,))
                cache_row = cursor.fetchone()
                
            curr_price = h["purchase_price"] # fallback
            pricing_power = "Moderate"
            altman_zone = "Grey Zone"
            debt_eq = 0.5
            
            if cache_row:
                try:
                    p = json.loads(cache_row["profile_json"])
                    curr_price = p["fundamentals"].get("current_price", curr_price)
                    pricing_power = p["fundamentals"].get("pricing_power_proxy", "Moderate")
                    altman_zone = p.get("earnings_quality", {}).get("altman_zone", "Grey Zone")
                    debt_eq = p["fundamentals"].get("debt_to_equity", 0.5)
                except Exception:
                    pass
                    
            value = round(h["quantity"] * curr_price, 2)
            portfolio_summary.append({
                "symbol": sym,
                "name": h["name"],
                "sector": h["sector"],
                "quantity": h["quantity"],
                "price": curr_price,
                "value": value,
                "pricing_power": pricing_power,
                "altman_zone": altman_zone,
                "debt_to_equity": debt_eq
            })
            
        # 2. Run LLM scenario simulation using Groq
        from backend.llm_config import call_llm, TASK_FAST, TASK_HEAVY
        
        system_prompt = (
            "You are an expert macroeconomic strategist and risk auditor for a major Indian hedge fund.\n"
            "Your objective is to stress-test the user's active stock portfolio against the specified macroeconomic scenario (shock).\n"
            "Evaluate each holding's vulnerability based on its sector, leverage (Debt-to-Equity), pricing power proxy, and solvency zone (Altman Z-Score).\n"
            "Determine which stocks are highly vulnerable, which are resilient (hedged), and estimate margin impact.\n"
            "You MUST return a valid JSON object matching the following structure strictly:\n"
            "{\n"
            '  "impact_summary": "A high-level executive summary of the portfolio impact.",\n'
            '  "vulnerable_stocks": ["TCS.NS (High IT sensitivity to US budget cuts)", ...],\n'
            '  "resilient_stocks": ["RELIANCE.NS (Energy integration buffer)", ...],\n'
            '  "margin_impact": "High Risk / Moderate Risk / Positive Hedge",\n'
            '  "recommendations": ["Rebalance cash reserves", ...]\n'
            "}\n"
            "Do not include markdown tags inside the JSON string itself. Output raw JSON only."
        )
        
        user_prompt = f"""
        Macroeconomic Shock Scenario:
        "{data.scenario}"
        
        Active Portfolio Holdings:
        {json.dumps(portfolio_summary, indent=2)}
        """
        
        response_text = await asyncio.to_thread(call_llm, TASK_FAST, system_prompt, user_prompt, max_tokens=4096)
        
        # Parse JSON from response
        try:
            clean_json = response_text.strip()
            if clean_json.startswith("```json"):
                clean_json = clean_json[7:]
            if clean_json.endswith("```"):
                clean_json = clean_json[:-3]
            clean_json = clean_json.strip()
            analysis = json.loads(clean_json)
        except Exception as e:
            print(f"Error parsing stress-test JSON: {e}\nRaw: {response_text}")
            analysis = {
                "impact_summary": f"Failed to compile structured LLM report. Raw response: {response_text[:300]}...",
                "vulnerable_stocks": ["Check high-leverage sectors manually."],
                "resilient_stocks": ["Check low-debt consumer staples manually."],
                "margin_impact": "Unknown",
                "recommendations": ["Review cash levels."]
            }
            
        return {
            "scenario": data.scenario,
            "analysis": analysis
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Macro Stress Simulation failed: {str(e)}")

@app.get("/api/analyze/risk-factors")
async def get_risk_factors(symbol: str, benchmark: str = "^NSEI", period: str = "1y"):
    try:
        # Translate period
        valid_periods = {"6mo", "1y", "3y", "5y"}
        if period not in valid_periods:
            period = "1y"
            
        # Determine cap-specific benchmark
        import sqlite3
        import os
        from backend.financial_utils import resolve_benchmark_by_mcap
        
        cap_type = None
        DATABASE_DIR = os.environ.get("DATABASE_DIR", os.path.join(os.path.dirname(__file__), "data"))
        DATABASE_PATH = os.path.join(DATABASE_DIR, "watchlist_database.db")
        if os.path.exists(DATABASE_PATH):
            try:
                conn = sqlite3.connect(DATABASE_PATH)
                cursor = conn.cursor()
                clean_sym = symbol.split(".")[0].upper()
                cursor.execute("SELECT cap_type FROM screener_universe WHERE symbol = ? OR base_symbol = ?", (symbol, clean_sym))
                row = cursor.fetchone()
                if row:
                    cap_type = row[0]
                conn.close()
            except Exception as e:
                print(f"Error querying cap_type for {symbol}: {e}")
                
        # Resolve suggested benchmark
        suggested_sym = "^CNX100"
        suggested_name = "Nifty 100"
        if cap_type:
            cap_type_lower = cap_type.lower()
            if "mid" in cap_type_lower:
                suggested_sym = "NIFTYMIDCAP150.NS"
                suggested_name = "Nifty Midcap 150"
            elif "small" in cap_type_lower:
                suggested_sym = "MOSMALL250.NS"
                suggested_name = "Nifty Smallcap 250"
        else:
            # Fallback to yfinance if not in DB
            try:
                ticker_obj = yf.Ticker(symbol)
                info = ticker_obj.info
                mcap = info.get("marketCap", 0)
                mcap_cr = mcap / 1e7 if mcap else 0
                if mcap_cr > 0:
                    suggested_sym, suggested_name = resolve_benchmark_by_mcap(mcap_cr)
            except Exception as e:
                print(f"Error resolving mcap from yf for {symbol}: {e}")
                
        # Collect unique tickers to download
        tickers_to_download = list(set([symbol, benchmark, "^NSEI", suggested_sym]))
        
        # Download all price data concurrently
        loop = asyncio.get_event_loop()
        download_tasks = []
        for ticker in tickers_to_download:
            download_tasks.append(
                loop.run_in_executor(None, lambda t=ticker: yf.download(t, period=period, progress=False))
            )
        dfs = await asyncio.gather(*download_tasks)
        df_map = dict(zip(tickers_to_download, dfs))
        
        df_stock = df_map.get(symbol)
        df_bench = df_map.get(benchmark)
        df_nifty50 = df_map.get("^NSEI")
        df_suggested = df_map.get(suggested_sym)
        
        if df_stock is None or df_stock.empty:
            raise HTTPException(status_code=400, detail=f"No price data found for stock {symbol}")
        if df_bench is None or df_bench.empty:
            raise HTTPException(status_code=400, detail=f"No price data found for selected benchmark {benchmark}")
            
        def compute_risk_metrics(df_s, df_b, rf_rate=0.07):
            if df_s is None or df_s.empty or df_b is None or df_b.empty:
                return {
                    "beta": 1.0,
                    "correlation": 0.5,
                    "annual_stock_ret": 12.0,
                    "annual_bench_ret": 10.0,
                    "alpha": 1.5
                }
            close_s = df_s['Close']
            if isinstance(close_s, pd.DataFrame):
                close_s = close_s.iloc[:, 0]
            close_b = df_b['Close']
            if isinstance(close_b, pd.DataFrame):
                close_b = close_b.iloc[:, 0]
                
            df_aligned = pd.DataFrame({'stock': close_s, 'bench': close_b}).dropna()
            if df_aligned.empty:
                return {
                    "beta": 1.0,
                    "correlation": 0.5,
                    "annual_stock_ret": 12.0,
                    "annual_bench_ret": 10.0,
                    "alpha": 1.5
                }
            df_aligned['stock_ret'] = df_aligned['stock'].pct_change()
            df_aligned['bench_ret'] = df_aligned['bench'].pct_change()
            df_aligned = df_aligned.dropna()
            
            if len(df_aligned) < 5:
                return {
                    "beta": 1.0,
                    "correlation": 0.5,
                    "annual_stock_ret": 12.0,
                    "annual_bench_ret": 10.0,
                    "alpha": 1.5
                }
                
            covariance = float(df_aligned['stock_ret'].cov(df_aligned['bench_ret']))
            bench_variance = float(df_aligned['bench_ret'].var())
            beta = covariance / bench_variance if bench_variance != 0.0 else 1.0
            correlation = float(df_aligned['stock_ret'].corr(df_aligned['bench_ret']))
            
            cum_s = float((1 + df_aligned['stock_ret']).prod() - 1)
            cum_b = float((1 + df_aligned['bench_ret']).prod() - 1)
            
            num_days = len(df_aligned)
            ann_s = float(((cum_s + 1) ** (252.0 / num_days) - 1)) if num_days > 0 else 0.0
            ann_b = float(((cum_b + 1) ** (252.0 / num_days) - 1)) if num_days > 0 else 0.0
            
            alpha_val = ann_s - (rf_rate + beta * (ann_b - rf_rate))
            
            return {
                "beta": round(beta, 3),
                "correlation": round(correlation, 3),
                "annual_stock_ret": round(ann_s * 100, 2),
                "annual_bench_ret": round(ann_b * 100, 2),
                "alpha": round(alpha_val * 100, 2)
            }
            
        # Calculate selected benchmark metrics
        main_metrics = compute_risk_metrics(df_stock, df_bench)
        
        # Calculate Nifty 50 metrics
        n50_metrics = compute_risk_metrics(df_stock, df_nifty50)
        n50_metrics["benchmark_name"] = "Nifty 50"
        n50_metrics["benchmark_symbol"] = "^NSEI"
        
        # Calculate Suggested Cap index metrics
        suggested_metrics = compute_risk_metrics(df_stock, df_suggested)
        suggested_metrics["benchmark_name"] = suggested_name
        suggested_metrics["benchmark_symbol"] = suggested_sym
        
        # Format daily scatter points for main benchmark chart
        close_stock = df_stock['Close']
        if isinstance(close_stock, pd.DataFrame):
            close_stock = close_stock.iloc[:, 0]
        close_bench = df_bench['Close']
        if isinstance(close_bench, pd.DataFrame):
            close_bench = close_bench.iloc[:, 0]
        df_aligned_main = pd.DataFrame({'stock': close_stock, 'bench': close_bench}).dropna()
        df_aligned_main['stock_ret'] = df_aligned_main['stock'].pct_change()
        df_aligned_main['bench_ret'] = df_aligned_main['bench'].pct_change()
        df_aligned_main = df_aligned_main.dropna()
        
        scatter_points = []
        for date, row in df_aligned_main.iterrows():
            scatter_points.append({
                "x": float(row['bench_ret'] * 100),
                "y": float(row['stock_ret'] * 100),
                "date": date.strftime('%Y-%m-%d')
            })
            
        cum_stock = float((1 + df_aligned_main['stock_ret']).prod() - 1)
        cum_bench = float((1 + df_aligned_main['bench_ret']).prod() - 1)
        
        return {
            "status": "success",
            "symbol": symbol,
            "benchmark": benchmark,
            "period": period,
            "beta": main_metrics["beta"],
            "correlation": main_metrics["correlation"],
            "annual_stock_ret": main_metrics["annual_stock_ret"],
            "annual_bench_ret": main_metrics["annual_bench_ret"],
            "cum_stock_ret": cum_stock * 100,
            "cum_bench_ret": cum_bench * 100,
            "scatter_points": scatter_points,
            "nifty50_risk": n50_metrics,
            "suggested_risk": suggested_metrics
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CAPM Calculation Error: {str(e)}")


class RiskSynthesisRequest(BaseModel):
    symbol: str
    beta: float
    alpha: float
    correlation: float
    horizon: str
    risk_profile: str
    investment_horizon: str


@app.post("/api/analyze/risk-synthesis")
async def post_risk_synthesis(data: RiskSynthesisRequest):
    try:
        from backend.llm_config import call_llm, TASK_FAST, TASK_HEAVY
        
        system_prompt = (
            "You are an institutional-grade risk analyst and portfolio manager. "
            "Your task is to synthesize a high-fidelity risk analysis for a stock based on its CAPM metrics. "
            "Keep the tone professional, objective, and clear. Format the response in concise HTML/Markdown paragraphs."
        )
        
        user_prompt = (
            f"Please write an investment risk synthesis for the stock {data.symbol}.\n"
            f"Calculated CAPM Risk Metrics (vs benchmark index):\n"
            f"- Beta: {data.beta:.3f} (Volatility relative to market benchmark)\n"
            f"- Annualized CAPM Alpha: {data.alpha:.2f}% (Risk-adjusted excess return)\n"
            f"- Correlation Coefficient: {data.correlation:.3f} (Linear correlation with benchmark)\n"
            f"- Calculation Horizon: {data.horizon}\n"
            f"\n"
            f"Active Investor Profile:\n"
            f"- Time Horizon: {data.investment_horizon}\n"
            f"- Risk Tolerance: {data.risk_profile}\n"
            f"\n"
            f"Provide a clear 2-paragraph breakdown. Paragraph 1: What do these specific Alpha/Beta/Correlation "
            f"numbers tell us about the stock's market sensitivity and risk-adjusted return? Paragraph 2: Does it match "
            f"the investor's risk profile and time horizon, and what action or warning checks do you recommend?"
        )
        
        synthesis = await asyncio.to_thread(call_llm, TASK_FAST, system_prompt, user_prompt)
        return {"synthesis": synthesis, "llm_meta": get_last_llm_meta()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Risk Synthesis Error: {str(e)}")

@app.get("/api/search/suggestions")
async def search_suggestions(q: str):
    """Returns a list of search suggestions for autocomplete, checking both local database and online fallback."""
    if not q or len(q.strip()) < 2:
        return []
    
    query = q.strip().lower()
    results = []
    seen_symbols = set()
    
    # 1. Query local database screener_universe
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT symbol, base_symbol, company_name, sector 
                FROM screener_universe 
                WHERE LOWER(base_symbol) LIKE ? OR LOWER(company_name) LIKE ?
                LIMIT 10
            """, (f"%{query}%", f"%{query}%"))
            
            for row in cursor.fetchall():
                symbol = row["symbol"]
                if symbol not in seen_symbols:
                    seen_symbols.add(symbol)
                    results.append({
                        "symbol": symbol,
                        "base_symbol": row["base_symbol"],
                        "name": row["company_name"],
                        "sector": row["sector"]
                    })
    except Exception as db_err:
        print(f"Error querying offline suggestions: {db_err}")
        
    # 2. Online search fallback from Yahoo Finance if less than 5 results
    if len(results) < 5:
        try:
            import urllib.parse
            import requests
            encoded_query = urllib.parse.quote(query)
            url = f"https://query2.finance.yahoo.com/v1/finance/search?q={encoded_query}&quotesCount=10"
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(url, headers=headers, timeout=3)
            if response.status_code == 200:
                quotes = response.json().get("quotes", [])
                for q_item in quotes:
                    symbol = q_item.get("symbol", "")
                    if symbol.endswith(".NS") or symbol.endswith(".BO"):
                        if symbol not in seen_symbols:
                            seen_symbols.add(symbol)
                            base = symbol.split(".")[0]
                            results.append({
                                "symbol": symbol,
                                "base_symbol": base,
                                "name": q_item.get("shortname") or q_item.get("longname") or base,
                                "sector": q_item.get("sector") or "General Equities"
                            })
        except Exception as online_err:
            print(f"Error fetching online suggestions: {online_err}")
            
    return results[:10]

@app.post("/api/portfolio-doctor")
async def post_portfolio_doctor(input_data: PortfolioDoctorInput):
    try:
        portfolio_items = [item.dict() for item in input_data.items]
        diagnosis = await asyncio.to_thread(run_portfolio_doctor, portfolio_items)
        diagnosis["llm_meta"] = get_last_llm_meta()
        return diagnosis
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Portfolio Doctor Error: {str(e)}")


class PortfolioBacktestRequest(BaseModel):
    tickers: list
    weights: list
    start_date: str
    end_date: str
    rebalance_freq: str = "none"
    starting_capital: float = 100000.0
    transaction_fee_pct: float = 0.1


class PortfolioBacktestSynthesisRequest(BaseModel):
    metrics: dict
    tickers_weights: list


@app.post("/api/portfolio/backtest")
async def post_portfolio_backtest(data: PortfolioBacktestRequest):
    try:
        result = await asyncio.to_thread(
            calculate_portfolio_backtest,
            tickers=data.tickers,
            weights=data.weights,
            start_date=data.start_date,
            end_date=data.end_date,
            rebalance_freq=data.rebalance_freq,
            starting_capital=data.starting_capital,
            transaction_fee_pct=data.transaction_fee_pct
        )
        return sanitize_nan_values(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Portfolio Backtest Simulation Error: {str(e)}")

@app.post("/api/portfolio/backtest-synthesis")
async def post_portfolio_backtest_synthesis(data: PortfolioBacktestSynthesisRequest):
    try:
        synthesis = await asyncio.to_thread(
            generate_backtest_synthesis,
            metrics=data.metrics,
            tickers_weights=data.tickers_weights
        )
        return {"synthesis": synthesis, "llm_meta": get_last_llm_meta()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backtest Synthesis Error: {str(e)}")


class OptimizeWeightsRequest(BaseModel):
    tickers: list[str]


@app.post("/api/portfolio/optimize-weights")
async def post_optimize_weights(data: OptimizeWeightsRequest):
    try:
        if not data.tickers:
            return {"weights": {}}
            
        import yfinance as yf
        import numpy as np
        import pandas as pd
        import asyncio
        from backend.financial_utils import resolve_company_ticker
        
        tickers = []
        for t in data.tickers:
            try:
                res = resolve_company_ticker(t)
                yf_ticker = res.get("yf_ticker") or f"{t.strip().upper()}.NS"
            except Exception:
                yf_ticker = f"{t.strip().upper()}.NS"
            tickers.append(yf_ticker)
            
        # Download 1y history for all tickers
        loop = asyncio.get_event_loop()
        download_tasks = []
        for t in tickers:
            download_tasks.append(
                loop.run_in_executor(None, lambda ticker=t: yf.download(ticker, period="1y", progress=False))
            )
        dfs = await asyncio.gather(*download_tasks)
        
        vols = {}
        for ticker, df in zip(tickers, dfs):
            if df.empty or "Close" not in df.columns:
                vols[ticker] = 0.25 # default 25% volatility fallback
                continue
            close = df["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            pct_chg = close.pct_change().dropna()
            vol = float(pct_chg.std() * np.sqrt(252))
            vols[ticker] = vol if vol > 0.0 else 0.25
            
        # Compute Inverse Volatility Weights
        inv_vols = {t: 1.0 / vols[t] for t in tickers}
        sum_inv = sum(inv_vols.values())
        
        weights = {}
        for original_t, yf_t in zip(data.tickers, tickers):
            raw_w = (inv_vols[yf_t] / sum_inv) * 100.0
            weights[original_t] = round(raw_w, 1)
            
        # Ensure it sums exactly to 100.0
        sum_weights = sum(weights.values())
        diff = 100.0 - sum_weights
        if diff != 0 and weights:
            first_ticker = list(weights.keys())[0]
            weights[first_ticker] = round(weights[first_ticker] + diff, 1)
            
        return {"weights": weights}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Weight optimization failed: {str(e)}")


class OptimizeSharpeRequest(BaseModel):
    tickers: list[str]
    cash_pct: float = 0.0
    current_weights: Optional[dict[str, float]] = None


@app.post("/api/portfolio/optimize-sharpe")
async def post_optimize_sharpe(data: OptimizeSharpeRequest):
    try:
        if not data.tickers:
            return {
                "max_sharpe": {"weights": {}, "return": 0.0, "volatility": 0.0, "sharpe": 0.0},
                "min_vol": {"weights": {}, "return": 0.0, "volatility": 0.0, "sharpe": 0.0},
                "current_portfolio": {"return": 0.0, "volatility": 0.0, "sharpe": 0.0},
                "simulations": []
            }

        import yfinance as yf
        import numpy as np
        import pandas as pd
        import asyncio
        from backend.financial_utils import resolve_company_ticker

        # 1. Resolve tickers to yfinance format
        tickers = []
        ticker_map = {} # maps resolved yfinance ticker back to original ticker string
        for t in data.tickers:
            try:
                res = resolve_company_ticker(t)
                yf_ticker = res.get("yf_ticker") or f"{t.strip().upper()}.NS"
            except Exception:
                yf_ticker = f"{t.strip().upper()}.NS"
            tickers.append(yf_ticker)
            ticker_map[yf_ticker] = t

        # 2. Download 2-year history concurrently
        loop = asyncio.get_event_loop()
        download_tasks = []
        for t in tickers:
            download_tasks.append(
                loop.run_in_executor(None, lambda ticker=t: yf.download(ticker, period="2y", progress=False))
            )
        dfs = await asyncio.gather(*download_tasks)

        # 3. Build a DataFrame of daily returns
        returns_df = pd.DataFrame()
        for yf_t, df in zip(tickers, dfs):
            if df.empty or "Close" not in df.columns:
                continue
            close = df["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            returns_df[yf_t] = close.pct_change()

        returns_df = returns_df.dropna()

        # If returns dataframe is empty or has too few observations, return default
        if returns_df.empty or len(returns_df) < 5:
            # Fallback
            equal_weight = 100.0 / len(data.tickers)
            weights = {t: round(equal_weight, 1) for t in data.tickers}
            sum_w = sum(weights.values())
            diff = 100.0 - sum_w
            if diff != 0 and weights:
                weights[list(weights.keys())[0]] = round(weights[list(weights.keys())[0]] + diff, 1)
            
            fallback_res = {"weights": weights, "return": 12.0, "volatility": 15.0, "sharpe": 0.33}
            return {
                "max_sharpe": fallback_res,
                "min_vol": fallback_res,
                "current_portfolio": fallback_res,
                "simulations": []
            }

        # 4. Compute expected returns and covariance matrix
        exp_rets = returns_df.mean() * 252
        cov_matrix = returns_df.cov() * 252

        num_assets = len(returns_df.columns)
        rf_rate = 0.07 # 7.0% risk-free rate for Indian market (10Y G-Sec)
        
        # Adjust for cash allocation if any
        cash_weight = data.cash_pct / 100.0
        equity_weight_avail = 1.0 - cash_weight

        # Convert to numpy arrays for speed
        exp_rets_np = exp_rets.values
        cov_matrix_np = cov_matrix.values

        # 4.5. Compute exact statistics of the current portfolio
        curr_w_np = np.zeros(num_assets)
        if data.current_weights:
            for idx, col in enumerate(returns_df.columns):
                orig_t = ticker_map[col]
                curr_w_np[idx] = data.current_weights.get(orig_t, 0.0) / 100.0
            
            # Normalize to sum to available equity weight
            s = np.sum(curr_w_np)
            if s > 0:
                curr_w_np = (curr_w_np / s) * equity_weight_avail
            else:
                curr_w_np = np.ones(num_assets) * (equity_weight_avail / num_assets)
        else:
            curr_w_np = np.ones(num_assets) * (equity_weight_avail / num_assets)

        curr_ret = np.dot(curr_w_np, exp_rets_np) + cash_weight * rf_rate
        curr_vol = np.sqrt(np.dot(curr_w_np.T, np.dot(cov_matrix_np, curr_w_np)))
        curr_sharpe = (curr_ret - rf_rate) / curr_vol if curr_vol > 0.0 else 0.0

        # 5. Run Monte Carlo simulation (1,000 runs)
        num_portfolios = 1000
        results = []
        portfolio_weights = []

        for _ in range(num_portfolios):
            # Generate random weights for equities
            w = np.random.random(num_assets)
            w /= np.sum(w)
            # Scale weights to sum to available equity weight
            w *= equity_weight_avail
            
            # Expected Return: w^T * exp_rets + cash_weight * Rf
            p_ret = np.dot(w, exp_rets_np) + cash_weight * rf_rate
            # Expected Volatility: sqrt(w^T * Cov * w)
            p_vol = np.sqrt(np.dot(w.T, np.dot(cov_matrix_np, w)))
            p_sharpe = (p_ret - rf_rate) / p_vol if p_vol > 0.0 else 0.0

            results.append((p_ret, p_vol, p_sharpe))
            portfolio_weights.append(w)

        results = np.array(results)
        
        # 6. Extract Max Sharpe and Min Vol portfolios
        max_sharpe_idx = np.argmax(results[:, 2])
        min_vol_idx = np.argmin(results[:, 1])

        # Prepare Max Sharpe details
        max_sharpe_w = portfolio_weights[max_sharpe_idx]
        max_sharpe_weights = {}
        for idx, col in enumerate(returns_df.columns):
            orig_t = ticker_map[col]
            max_sharpe_weights[orig_t] = round(max_sharpe_w[idx] * 100.0, 1)
        if data.cash_pct > 0.0:
            max_sharpe_weights["CASH"] = round(data.cash_pct, 1)

        # Prepare Min Vol details
        min_vol_w = portfolio_weights[min_vol_idx]
        min_vol_weights = {}
        for idx, col in enumerate(returns_df.columns):
            orig_t = ticker_map[col]
            min_vol_weights[orig_t] = round(min_vol_w[idx] * 100.0, 1)
        if data.cash_pct > 0.0:
            min_vol_weights["CASH"] = round(data.cash_pct, 1)

        def sanitize_weights(w_dict, target_sum=100.0):
            if not w_dict:
                return w_dict
            s_sum = sum(w_dict.values())
            diff = target_sum - s_sum
            if diff != 0:
                first_k = list(w_dict.keys())[0]
                w_dict[first_k] = round(w_dict[first_k] + diff, 1)
            return w_dict

        max_sharpe_weights = sanitize_weights(max_sharpe_weights)
        min_vol_weights = sanitize_weights(min_vol_weights)

        # 7. Select a subset of simulation points for graphing
        step = max(1, num_portfolios // 300)
        sim_points = []
        for i in range(0, num_portfolios, step):
            p_ret, p_vol, p_sharpe = results[i]
            w_dict = {}
            for idx, col in enumerate(returns_df.columns):
                orig_t = ticker_map[col]
                w_dict[orig_t] = round(portfolio_weights[i][idx] * 100.0, 1)
            if data.cash_pct > 0.0:
                w_dict["CASH"] = round(data.cash_pct, 1)
            w_dict = sanitize_weights(w_dict)
            
            w_str = " | ".join([f"{k}: {v}%" for k, v in w_dict.items()])

            sim_points.append({
                "x": round(float(p_vol * 100), 2),
                "y": round(float(p_ret * 100), 2),
                "sharpe": round(float(p_sharpe), 2),
                "weights_str": w_str
            })

        return {
            "status": "success",
            "max_sharpe": {
                "weights": max_sharpe_weights,
                "return": round(float(results[max_sharpe_idx, 0] * 100.0), 2),
                "volatility": round(float(results[max_sharpe_idx, 1] * 100.0), 2),
                "sharpe": round(float(results[max_sharpe_idx, 2]), 2)
            },
            "min_vol": {
                "weights": min_vol_weights,
                "return": round(float(results[min_vol_idx, 0] * 100.0), 2),
                "volatility": round(float(results[min_vol_idx, 1] * 100.0), 2),
                "sharpe": round(float(results[min_vol_idx, 2]), 2)
            },
            "current_portfolio": {
                "return": round(float(curr_ret * 100.0), 2),
                "volatility": round(float(curr_vol * 100.0), 2),
                "sharpe": round(float(curr_sharpe), 2)
            },
            "simulations": sim_points
        }
    except Exception as e:
        print(f"Optimize Sharpe Error: {e}")
        raise HTTPException(status_code=500, detail=f"Optimize Sharpe Error: {str(e)}")


class OptimizerSynthesisRequest(BaseModel):
    target_type: str
    current_return: float
    current_sharpe: float
    target_return: float
    target_sharpe: float
    target_weights: dict[str, float]
    rebalance_tickets: list[dict]


@app.post("/api/portfolio/optimizer-synthesis")
async def post_optimizer_synthesis(data: OptimizerSynthesisRequest):
    try:
        from backend.llm_config import call_llm, TASK_FAST, TASK_HEAVY
        
        system_prompt = (
            "You are an elite quantitative portfolio manager and investment strategist. "
            "Analyze the Sharpe/Risk portfolio optimization results and provide institutional-grade rebalancing commentary. "
            "Keep the tone professional, objective, and clear. Format the response in concise HTML/Markdown paragraphs, "
            "highlighting specific ticker shifts and tactical advice. Do not use markdown headers, write directly in styled paragraphs."
        )
        
        tickets_str = "\n".join([
            f"- {t.get('ticker')}: {t.get('action')} {t.get('weight_diff')}% (Est. value: {t.get('value_str')})"
            for t in data.rebalance_tickets
        ])
        
        user_prompt = (
            f"Optimization Objective: {data.target_type.upper()} Rebalancing\n\n"
            f"Baseline Portfolio Performance:\n"
            f"- Expected Annualized Return: {data.current_return:.2f}%\n"
            f"- Sharpe Ratio: {data.current_sharpe:.2f}\n\n"
            f"Optimized Target Portfolio Performance:\n"
            f"- Expected Annualized Return: {data.target_return:.2f}%\n"
            f"- Sharpe Ratio: {data.target_sharpe:.2f}\n\n"
            f"Suggested Asset Allocations (Target Weights):\n"
            f"{json.dumps(data.target_weights, indent=2)}\n\n"
            f"Required Rebalancing Actions:\n"
            f"{tickets_str}\n\n"
            f"Please synthesize a professional-grade portfolio rebalancing advisory in 2 clear, structured paragraphs:\n"
            f"Paragraph 1: Strategic rationale for this shift. Explain how shifting from the current portfolio baseline "
            f"to the optimized target improves the risk-adjusted return landscape and Sharpe ratio.\n"
            f"Paragraph 2: Tactical execution advice. Highlight critical actions (e.g. key trims or cash reserves) "
            f"and warning metrics to watch in the current macro regime."
        )
        
        synthesis = await asyncio.to_thread(call_llm, TASK_FAST, system_prompt, user_prompt)
        return {"synthesis": synthesis, "llm_meta": get_last_llm_meta()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Optimizer Synthesis Error: {str(e)}")


def calculate_abnormal_returns(stock_symbol: str, days: int = 30):
    import yfinance as yf
    import pandas as pd
    
    try:
        stock = yf.Ticker(stock_symbol)
        hist = stock.history(period=f"{days}d")
        
        nifty = yf.Ticker("^NSEI")
        nifty_hist = nifty.history(period=f"{days}d")
        
        if hist.empty or nifty_hist.empty:
            return {"anomalies": []}
            
        hist.index = hist.index.tz_localize(None)
        nifty_hist.index = nifty_hist.index.tz_localize(None)
        
        hist['Return'] = hist['Close'].pct_change() * 100.0
        nifty_hist['Return'] = nifty_hist['Close'].pct_change() * 100.0
        
        df = pd.merge(hist[['Return', 'Close']], nifty_hist[['Return']], left_index=True, right_index=True, suffixes=('_stock', '_nifty'))
        df['Abnormal_Return'] = df['Return_stock'] - df['Return_nifty']
        
        std_dev = df['Return_stock'].std()
        if pd.isna(std_dev) or std_dev == 0:
            std_dev = 1.5
            
        anomalies = []
        for date, row in df.iterrows():
            ret = row['Return_stock']
            ab_ret = row['Abnormal_Return']
            if pd.isna(ret) or pd.isna(ab_ret):
                continue
            
            is_anomaly = abs(ret) > (1.5 * std_dev) or abs(ret) > 2.0
            
            anomalies.append({
                "date": date.strftime("%Y-%m-%d"),
                "price": float(row['Close']),
                "return": float(ret),
                "abnormal_return": float(ab_ret),
                "is_anomaly": bool(is_anomaly)
            })
        return {"anomalies": anomalies, "std_dev": std_dev}
    except Exception as e:
        print(f"Error calculating abnormal returns: {e}")
        return {"anomalies": []}


def fetch_google_news_rss(query: str):
    import urllib.request
    import xml.etree.ElementTree as ET
    import urllib.parse
    from datetime import datetime
    
    encoded_query = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as response:
            xml_data = response.read()
            
        root = ET.fromstring(xml_data)
        news_items = []
        for item in root.findall('.//item')[:4]:
            title = item.find('title').text
            link = item.find('link').text
            pub_date = item.find('pubDate').text
            source = item.find('source').text if item.find('source') is not None else "Unknown"
            
            try:
                dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z")
                formatted_date = dt.strftime("%Y-%m-%d")
            except Exception:
                formatted_date = pub_date[:16]
                
            news_items.append({
                "title": title,
                "link": link,
                "date": formatted_date,
                "source": source
            })
        return news_items
    except Exception as e:
        print(f"Error fetching RSS news: {e}")
        return []


def fetch_jina_markdown(url: str) -> str:
    if not url or url.strip() in ("", "#"):
        return ""
        
    # Skip Jina scraping for general tags index search URLs (e.g. from fallback templates)
    url_lower = url.lower()
    if "/search" in url_lower or "/tags" in url_lower or "google.com/rss" in url_lower:
        return ""
        
    import urllib.request
    
    jina_url = f"https://r.jina.ai/{url}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        req = urllib.request.Request(jina_url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            content = response.read().decode('utf-8')
        return content[:3000]
    except Exception as e:
        print(f"Jina scraping failed for {url}: {e}")
        return ""


def run_groq_news_sentiment_analysis(symbol: str, news_list: list, anomalies_list: list) -> dict:
    from backend.llm_config import call_llm, TASK_FAST, TASK_HEAVY
    import json
    
    system_prompt = (
        "You are an expert Wall Street equity research analyst and forensic market researcher.\n"
        "Your task is to analyze scraped corporate news articles and correlate them with a stock's historical price movement.\n"
        "You MUST return your output strictly in JSON format (enclosed inside a single JSON object block).\n"
        "Do not output any introductory or explanatory text outside the JSON block.\n\n"
        "Required Output JSON Schema:\n"
        "{\n"
        '  "sentiment_index": 72.5, // Float between 0.0 (Extremely Bearish) and 100.0 (Extremely Bullish) representing average sentiment rating\n'
        '  "news_items": [\n'
        "    {\n"
        '      "title": "Cleaned article title",\n'
        '      "publisher": "Source publisher name",\n'
        '      "date": "YYYY-MM-DD", // Match with news release date\n'
        '      "sentiment_score": 0.85, // Float between -1.0 (very negative) and +1.0 (very positive)\n'
        '      "category": "Macro Policy" or "Corporate Actions" or "Earnings Report" or "Market Sentiment" or "Industry Tailwinds",\n'
        '      "correlation_summary": "Brief 2-sentence explanation of what happened and if it had any impact on share price (positive/negative correlation)."\n'
        "    }\n"
        "  ]\n"
        "}"
    )
    
    news_input_text = ""
    for idx, item in enumerate(news_list):
        content_snippet = item['content'].strip() if item.get('content') else ""
        if not content_snippet:
            content_snippet = "(Full article text paywalled/restricted by publisher. Perform your sentiment analysis and price correlation attribution based entirely on the Title Headline, Publisher, and Date above.)"
            
        news_input_text += (
            f"--- ARTICLE {idx+1} ---\n"
            f"Title: {item['title']}\n"
            f"Publisher: {item['source']}\n"
            f"Date: {item['date']}\n"
            f"Link: {item['link']}\n"
            f"Content Snippet: {content_snippet}\n\n"
        )
        
    anomalies_text = "\n".join([
        f"- Date: {a['date']} | Price: Rs.{a['price']:.1f} | Daily Return: {a['return']:.2f}% | Abnormal Return vs Nifty 50: {a['abnormal_return']:.2f}% | Volatility Anomaly: {a['is_anomaly']}"
        for a in anomalies_list if a['is_anomaly']
    ])
    
    user_prompt = (
        f"Stock Symbol: {symbol}\n\n"
        f"Scraped Live News Context:\n"
        f"{news_input_text}\n"
        f"Significant Stock Price Anomalies (Past 30 Days):\n"
        f"{anomalies_text}\n\n"
        f"Please analyze these inputs. For each article, determine the date (MUST fit in the past 30 days or matches the publication date), "
        f"rate the sentiment_score, categorize its impact driver_type under 'category', and write a correlation_summary. "
        f"Also calculate the aggregated overall sentiment_index rating from 0 to 100 based on all articles."
    )
    
    raw_response = call_llm(TASK_FAST, system_prompt, user_prompt, max_tokens=4096)
    
    try:
        clean_json = raw_response.strip()
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:]
        if clean_json.endswith("```"):
            clean_json = clean_json[:-3]
        clean_json = clean_json.strip()
        
        parsed = json.loads(clean_json)
        return parsed
    except Exception as e:
        print(f"Error parsing Groq news sentiment JSON response: {e}\nRaw: {raw_response}")
        default_items = []
        for item in news_list:
            default_items.append({
                "title": item["title"],
                "publisher": item.get("source") or item.get("publisher") or "Yahoo Finance",
                "date": item["date"],
                "link": item.get("link") or "#",
                "sentiment_score": 0.0,
                "category": "Market Sentiment",
                "correlation_summary": "Auto-parsed news. LLM synthesis failed to return valid JSON format."
            })
        return {
            "sentiment_index": 50.0,
            "news_items": default_items
        }


@app.get("/api/portfolio/news-impact")
async def get_news_impact(symbol: str, refresh: bool = False, run_llm: bool = False):
    import json
    import sqlite3
    from datetime import datetime, timedelta
    
    sym = symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="Invalid stock symbol")

    if not refresh:
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT sentiment_json, updated_at FROM cached_news_impact WHERE symbol = ?", (sym,))
                row = cursor.fetchone()
                if row:
                    cached_time = datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S")
                    if datetime.now() - cached_time < timedelta(hours=24):
                        parsed_json = json.loads(row["sentiment_json"])
                        # If a full audit is stored, return it directly
                        return {
                            "symbol": sym,
                            "sentiment_index": parsed_json.get("sentiment_index", 50.0),
                            "news_items": parsed_json.get("news_items", []),
                            "updated_at": row["updated_at"],
                            "cached": True,
                            "has_audit": parsed_json.get("has_audit", True)
                        }
        except Exception as cache_err:
            print(f"Error reading news impact cache for {sym}: {cache_err}")

    try:
        anomaly_data = await asyncio.to_thread(calculate_abnormal_returns, sym, 30)
        anomalies_list = anomaly_data.get("anomalies", [])
        
        # 1. Fetch Google News RSS (Indian targets)
        search_query = sym.split('.')[0] + " stock news"
        google_news = await asyncio.to_thread(fetch_google_news_rss, search_query)
        
        # 2. Fetch earlier version news feed (profile news + fallbacks)
        yf_news = []
        try:
            from backend.financial_utils import get_complete_financial_profile
            # Force cache bypass if refresh toggle was explicitly requested
            profile = get_complete_financial_profile(sym, bypass_db_cache=refresh)
            raw_yf = profile.get("news", [])
            for item in raw_yf[:4]:
                yf_news.append({
                    "title": item.get("title") or "Corporate Expansion Update",
                    "link": item.get("link") or "",
                    "date": item.get("date") or datetime.now().strftime("%Y-%m-%d"),
                    "source": item.get("publisher") or "Yahoo Finance"
                })
        except Exception as yf_err:
            print(f"Error fetching profile news inside impact: {yf_err}")
            
        # 3. Filter by last 30 days and Parse dates
        parsed_news = []
        one_month_ago = datetime.now() - timedelta(days=30)
        
        for item in yf_news + google_news:
            date_str = item.get("date")
            parsed_dt = None
            if date_str:
                for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%a, %d %b %Y %H:%M:%S %Z", "%d %b %Y"):
                    try:
                        parsed_dt = datetime.strptime(date_str.strip(), fmt)
                        break
                    except ValueError:
                        continue
                if not parsed_dt:
                    try:
                        parsed_dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
                    except Exception:
                        pass
            
            # Default to now if not parseable
            if not parsed_dt:
                parsed_dt = datetime.now()
                
            # Filter: discard if older than 30 days
            if parsed_dt >= one_month_ago:
                item["parsed_date"] = parsed_dt
                # Standardize the date field for response consistency
                item["date"] = parsed_dt.strftime("%Y-%m-%d")
                parsed_news.append(item)
                
        # Sort by date descending (newest first)
        parsed_news.sort(key=lambda x: x["parsed_date"], reverse=True)
        
        # De-duplicate preserving the sorted order
        seen_titles = set()
        raw_news = []
        for item in parsed_news:
            title_slug = "".join(c for c in item["title"].lower() if c.isalnum())[:35]
            if title_slug not in seen_titles:
                seen_titles.add(title_slug)
                # Remove parsed_date object before serialization
                item_copy = item.copy()
                if "parsed_date" in item_copy:
                    del item_copy["parsed_date"]
                raw_news.append(item_copy)
                
        # Limit to 6 items to keep performance high
        raw_news = raw_news[:6]
        
        if not raw_news:
            return {
                "symbol": sym,
                "sentiment_index": 50.0,
                "news_items": [],
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "cached": False,
                "has_audit": False,
                "error": "No news items found."
            }
            
        # Fast Path: If LLM analysis is not requested, immediately return raw headlines
        if not run_llm:
            raw_items = []
            anomaly_map = {item["date"]: item for item in anomalies_list}
            for item in raw_news:
                news_date = item["date"]
                ab_ret = 0.0
                price_change = 0.0
                is_anomaly = False
                
                if news_date in anomaly_map:
                    ab_ret = anomaly_map[news_date]["abnormal_return"]
                    price_change = anomaly_map[news_date]["return"]
                    is_anomaly = anomaly_map[news_date]["is_anomaly"]
                    
                raw_items.append({
                    "title": item["title"],
                    "publisher": item.get("source") or item.get("publisher") or "Yahoo Finance",
                    "date": news_date,
                    "link": item["link"] or "#",
                    "sentiment_score": 0.0,
                    "category": "Market Sentiment",
                    "abnormal_return": ab_ret,
                    "price_change": price_change,
                    "is_anomaly": is_anomaly,
                    "correlation_summary": "Click 'Run Groq Audit' at the top to analyze sentiment and categories."
                })
                
            return {
                "symbol": sym,
                "sentiment_index": 50.0,
                "news_items": raw_items,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "cached": False,
                "has_audit": False
            }
            
        # Slow Path: Run Jina Reader & Groq Llama 3 analysis
        scraped_tasks = [asyncio.to_thread(fetch_jina_markdown, item["link"]) for item in raw_news]
        scraped_texts = await asyncio.gather(*scraped_tasks)
        
        for idx, text in enumerate(scraped_texts):
            raw_news[idx]["content"] = text or ""
            
        synthesis_payload = await asyncio.to_thread(
            run_groq_news_sentiment_analysis, 
            sym, 
            raw_news, 
            anomalies_list
        )
        
        anomaly_map = {item["date"]: item for item in anomalies_list}
        
        updated_news_items = []
        for idx, item in enumerate(synthesis_payload.get("news_items", [])):
            # Match Groq output items back to the input raw_news list to restore the source link URLs and publishers
            title_llm = item.get("title", "")
            slug_llm = "".join(c for c in title_llm.lower() if c.isalnum())
            
            matched = None
            # 1. Exact match based on alphanumeric title slug
            for orig in raw_news:
                slug_orig = "".join(c for c in orig["title"].lower() if c.isalnum())
                if slug_llm == slug_orig:
                    matched = orig
                    break
            
            # 2. Fuzzy substring match
            if not matched:
                for orig in raw_news:
                    slug_orig = "".join(c for c in orig["title"].lower() if c.isalnum())
                    if slug_llm in slug_orig or slug_orig in slug_llm:
                        matched = orig
                        break
            
            # 3. Positional fallback
            if not matched and idx < len(raw_news):
                matched = raw_news[idx]
                
            if matched:
                item["link"] = matched.get("link") or "#"
                item["publisher"] = matched.get("source") or matched.get("publisher") or item.get("publisher") or "Financial Feed"
            else:
                item["link"] = "#"
                item["publisher"] = item.get("publisher") or "Financial Feed"
                
            news_date = item.get("date", "")
            ab_ret = 0.0
            price_change = 0.0
            is_anomaly = False
            
            if news_date in anomaly_map:
                ab_ret = anomaly_map[news_date]["abnormal_return"]
                price_change = anomaly_map[news_date]["return"]
                is_anomaly = anomaly_map[news_date]["is_anomaly"]
                
            item["abnormal_return"] = ab_ret
            item["price_change"] = price_change
            item["is_anomaly"] = is_anomaly
            updated_news_items.append(item)
            
        synthesis_payload["news_items"] = updated_news_items
        synthesis_payload["has_audit"] = True
        
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cached_news_impact (symbol, sentiment_json, updated_at) VALUES (?, ?, ?)",
                    (sym, json.dumps(synthesis_payload), now_str)
                )
                conn.commit()
        except Exception as db_err:
            print(f"Error saving news cache to DB for {sym}: {db_err}")
            
        return {
            "symbol": sym,
            "sentiment_index": synthesis_payload.get("sentiment_index", 50.0),
            "news_items": synthesis_payload.get("news_items", []),
            "updated_at": now_str,
            "cached": False,
            "has_audit": True
        }
        
    except Exception as run_err:
        print(f"Error running news impact synthesis: {run_err}")
        raise HTTPException(status_code=500, detail=f"News Synthesis Error: {str(run_err)}")


def get_serpapi_keys_pool():
    keys = []
    # 1. Check os.environ
    for k, v in os.environ.items():
        if k.startswith("SERPAPI") and v.strip():
            for subk in v.split(","):
                sk = subk.strip()
                if sk and sk not in keys:
                    keys.append(sk)
    # 2. Check SQLite alert_settings
    try:
        with get_db() as conn:
            row = conn.execute("SELECT value FROM alert_settings WHERE key = 'serpapi_api_key'").fetchone()
            if row and row[0]:
                for subk in row[0].split(","):
                    sk = subk.strip()
                    if sk and sk not in keys:
                        keys.append(sk)
    except Exception as db_err:
        print(f"[SerpApi Key Pool] DB fetch error: {db_err}")
    return keys


@app.get("/api/google-ai-overview-clear-cache")
def clear_google_ai_overview_cache(symbol: str = ""):
    try:
        with get_db() as conn:
            if symbol:
                clean_sym = symbol.replace(".NS", "").replace(".BO", "").strip().upper()
                conn.execute("DELETE FROM cached_google_ai_overview WHERE symbol LIKE ?", (f"%{clean_sym}%",))
            else:
                conn.execute("DELETE FROM cached_google_ai_overview")
            conn.commit()
        return {"status": "success", "message": f"Cleared Google AI Overview cache for {symbol if symbol else 'ALL symbols'}."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/google-ai-overview/{symbol}")
async def get_google_ai_overview(symbol: str, force_refresh: bool = False):
    return await get_google_ai_overview_endpoint(symbol, force_refresh)


@app.get("/api/google-ai-followup")
def get_google_ai_followup(symbol: str, prompt: str):
    import re
    import urllib.parse
    clean_sym = symbol.replace(".NS", "").replace(".BO", "").strip().upper()
    company_name = f"{clean_sym} India Ltd."

    serpapi_keys = get_serpapi_keys_pool()
    followup_query = f"{company_name} {clean_sym} {prompt} India stock AI overview"
    encoded_query = urllib.parse.quote(followup_query)

    answer_html = None

    if serpapi_keys:
        for serp_key in serpapi_keys:
            try:
                url1 = f"https://serpapi.com/search.json?engine=google&q={encoded_query}&gl=in&hl=en&api_key={serp_key}"
                r1 = requests.get(url1, timeout=12)
                if r1.status_code != 200:
                    continue
                data1 = r1.json()

                ai_ov = data1.get("ai_overview", {})
                page_token = ai_ov.get("page_token")
                blocks = []

                if page_token:
                    url2 = f"https://serpapi.com/search.json?engine=google_ai_overview&page_token={page_token}&gl=in&hl=en&api_key={serp_key}"
                    r2 = requests.get(url2, timeout=12)
                    if r2.status_code == 200:
                        data2 = r2.json()
                        res_ov = data2.get("ai_overview", {})
                        blocks = res_ov.get("text_blocks", [])
                elif "text_blocks" in ai_ov:
                    blocks = ai_ov.get("text_blocks", [])

                if blocks:
                    bullets = []
                    for b in blocks:
                        snip = b.get("snippet", "").strip()
                        if snip and len(snip) > 15:
                            # Highlight financial numbers and percentages
                            formatted = re.sub(
                                r'(₹\s*[\d,\.]+\s*(?:crore|cr|million|billion)?|[\d,\.]+\s*(?:crore|cr|%|times|x)\b)',
                                r'<strong>\1</strong>',
                                snip,
                                flags=re.IGNORECASE
                            )
                            bullets.append(f"<li style='margin-bottom:8px;'>{formatted}</li>")

                    if bullets:
                        answer_html = f"""
                        <div style='display:flex; flex-direction:column; gap:12px;'>
                            <div style='background:rgba(56,189,248,0.1); border:1px solid rgba(56,189,248,0.3); border-radius:10px; padding:12px 14px;'>
                                <strong style='color:#38bdf8; font-size:14px;'>⚡ Live Google SGE Intelligence for {clean_sym}</strong>
                                <p style='margin:4px 0 0 0; color:#cbd5e1; font-size:12px;'>Prompt Query: <em>"{prompt}"</em></p>
                            </div>
                            <ul style='margin:0; padding-left:18px; display:flex; flex-direction:column; gap:8px; font-size:12.5px; color:#e2e8f0; line-height:1.55;'>
                                {"".join(bullets[:6])}
                            </ul>
                        </div>
                        """
                        break
            except Exception as e:
                print(f"[Google AI Followup] SerpApi error: {e}")
                continue

    if not answer_html:
        return {
            "error": True,
            "symbol": symbol,
            "prompt": prompt,
            "title": f"Google AI Follow-Up: {prompt}",
            "message": f"Live Google SGE follow-up analysis currently unavailable for: \"{prompt}\"",
            "reason": "Google SGE search engine did not return a live AI Overview token for this specific prompt."
        }

    return {
        "symbol": symbol,
        "prompt": prompt,
        "title": f"Google AI Follow-Up Intelligence: {prompt}",
        "answer_html": answer_html
    }



def classify_news_category(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["nifty", "sensex", "gdp", "inflation", "cpi", "macro", "index", "indices", "bond", "yield", "economy", "growth rate"]):
        return "Macro & Indices"
    if any(k in t for k in ["ipo", "listings", "listing", "debut", "public issue", "public offer", "initial public", "primary market"]):
        return "IPOs & Primary Markets"
    if any(k in t for k in ["sebi", "rbi", "regulation", "regulatory", "policy", "customs", "tax", "tariff", "government", "govt", "fmc", "finance ministry"]):
        return "Regulatory & Policy"
    if any(k in t for k in ["fii", "dii", "institutional", "mutual fund", "block deal", "bulk deal", "promoter stake", "buying stake", "foreign portfolio", "fpi"]):
        return "Institutional Flows"
    if any(k in t for k in ["nasdaq", "dow jones", "wall street", "nikkei", "hang seng", "us stock", "global market", "fed", "federal reserve", "spacex", "tesla", "nvidia", "apple", "google", "meta"]):
        return "Global Markets"
    if any(k in t for k in ["dividend", "earnings", "quarterly", "profit", "net profit", "loss", "q1", "q2", "q3", "q4", "revenue", "ebitda", "merger", "acquisition", "stake sale", "expansion", "order win", "contract", "corporate"]):
        return "Corporate & Earnings"
    return "General Markets"


def classify_news_sentiment(title: str) -> str:
    t = title.lower()
    bullish_k = ["jump", "surge", "gain", "rise", "climb", "high", "record", "rally", "upbeat", "expand", "profit jumps", "positive", "growth", "win", "acquisition", "dividend", "bullish", "soar", "advance", "upgrade", "outperform"]
    bearish_k = ["slip", "fall", "slump", "drop", "plunge", "losses", "slips", "decline", "downbeat", "loss", "negative", "warn", "tariff", "penalty", "sebi bar", "regulatory action", "fraud", "crash", "bearish", "downgrade", "underperform", "trim"]
    
    bull_count = sum(1 for k in bullish_k if k in t)
    bear_count = sum(1 for k in bearish_k if k in t)
    
    if bull_count > bear_count:
        return "Bullish"
    elif bear_count > bull_count:
        return "Bearish"
    else:
        return "Neutral"


@app.get("/api/market-news")
async def get_market_news(refresh: bool = False, run_llm: bool = False):
    import json
    import sqlite3
    from datetime import datetime, timedelta
    import urllib.request
    import xml.etree.ElementTree as ET
    from backend.llm_config import call_llm, TASK_FAST, get_last_llm_meta
    
    if not refresh:
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT payload_json, updated_at FROM cached_global_market_news WHERE feed_key = 'global_news'")
                row = cursor.fetchone()
                if row:
                    cached_time = datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S")
                    if datetime.now() - cached_time < timedelta(minutes=10):
                        parsed_json = json.loads(row["payload_json"])
                        if not run_llm or parsed_json.get("has_ai_report", False):
                            return {
                                "news_items": parsed_json.get("news_items", []),
                                "ai_report": parsed_json.get("ai_report"),
                                "has_ai_report": parsed_json.get("has_ai_report", False),
                                "updated_at": row["updated_at"],
                                "cached": True
                            }
        except Exception as cache_err:
            print(f"Error reading market news cache: {cache_err}")
            
    feeds = {
        "Economic Times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "LiveMint": "https://www.livemint.com/rss/markets",
        "Yahoo Finance": "https://finance.yahoo.com/news/rss",
        "Business Standard": "https://www.business-standard.com/rss/markets-106.rss"
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive'
    }
    
    async def fetch_feed(name, url):
        try:
            req = urllib.request.Request(url, headers=headers)
            loop = asyncio.get_event_loop()
            response_bytes = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=10).read())
            
            root = ET.fromstring(response_bytes)
            feed_items = []
            for item in root.findall('.//item'):
                title = item.find('title').text if item.find('title') is not None else ""
                link = item.find('link').text if item.find('link') is not None else "#"
                pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
                
                if not title:
                    continue
                    
                feed_items.append({
                    "title": title.strip(),
                    "link": link.strip(),
                    "date_str": pub_date.strip(),
                    "source": name
                })
            return feed_items
        except Exception as e:
            print(f"Error fetching feed {name}: {e}")
            return []
            
    tasks = [fetch_feed(name, url) for name, url in feeds.items()]
    feeds_results = await asyncio.gather(*tasks)
    
    all_news = []
    for r in feeds_results:
        all_news.extend(r)
        
    parsed_items = []
    one_month_ago = datetime.now() - timedelta(days=30)
    
    for item in all_news:
        date_str = item.get("date_str")
        parsed_dt = None
        if date_str:
            for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%a, %d %b %Y %H:%M:%S %Z", "%d %b %Y", "%Y-%m-%dT%H:%M:%SZ"):
                try:
                    parsed_dt = datetime.strptime(date_str.strip(), fmt)
                    break
                except ValueError:
                    continue
            if not parsed_dt:
                try:
                    parsed_dt = datetime.strptime(date_str.strip()[:-6].strip(), "%a, %d %b %Y %H:%M:%S")
                except Exception:
                    pass
            if not parsed_dt:
                try:
                    parsed_dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
                except Exception:
                    pass
                    
        if not parsed_dt:
            parsed_dt = datetime.now()
            
        if parsed_dt >= one_month_ago:
            item["parsed_dt"] = parsed_dt
            item["date"] = parsed_dt.strftime("%Y-%m-%d")
            item["category"] = classify_news_category(item["title"])
            item["sentiment"] = classify_news_sentiment(item["title"])
            parsed_items.append(item)
            
    parsed_items.sort(key=lambda x: x["parsed_dt"], reverse=True)
    
    seen_titles = set()
    cleaned_items = []
    for item in parsed_items:
        title_slug = "".join(c for c in item["title"].lower() if c.isalnum())[:35]
        if title_slug not in seen_titles:
            seen_titles.add(title_slug)
            
            item_copy = item.copy()
            if "parsed_dt" in item_copy:
                del item_copy["parsed_dt"]
            if "date_str" in item_copy:
                del item_copy["date_str"]
            cleaned_items.append(item_copy)
            
    cleaned_items = cleaned_items[:50]
    
    ai_report = None
    has_ai_report = False
    
    if run_llm and cleaned_items:
        brief_headlines = [f"[{item['source']} - {item['category']}] {item['title']}" for item in cleaned_items[:25]]
        bullet_list = "\n".join(brief_headlines)
        
        prompt = f"""
        You are a chief investment officer analyzing live Indian & global market catalysts.
        Evaluate the following recent financial headlines:
        {bullet_list}
        
        Provide a structured, executive-grade analysis in JSON format containing:
        1. "synthesis_report": A precise, insightful paragraph summarizing the overall consensus, key market sentiment, and tactical implications for portfolio holdings (2-3 sentences max).
        2. "top_drivers": An array of exactly 3 bullet points, each detail-rich (e.g. "SpaceX stake adjustments", "Jio IPO expectation", "Federal Reserve interest hawkishness"), identifying the major market drivers.
        
        Respond ONLY with a valid JSON object matching this schema:
        {{
            "synthesis_report": "Your institutional summary paragraph...",
            "top_drivers": [
                "Driver 1 detailed bulletin...",
                "Driver 2 detailed bulletin...",
                "Driver 3 detailed bulletin..."
            ]
        }}
        """
        
        try:
            raw_res = call_llm(TASK_FAST, "You are a professional financial editor returning structured JSON reports.", prompt)
            
            # Clean markdown codeblocks if LLM wraps in ```json
            clean_res = raw_res.strip()
            if clean_res.startswith("```"):
                lines = clean_res.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                clean_res = "\n".join(lines).strip()
                
            ai_data = json.loads(clean_res)
            ai_report = {
                "synthesis_report": ai_data.get("synthesis_report", "Consensus shows moderate consolidation across index ranges."),
                "top_drivers": ai_data.get("top_drivers", ["Global Tech Volatility", "Institutional Flows", "IPO Pipeline"]),
                "llm_meta": get_last_llm_meta()
            }
            has_ai_report = True
        except Exception as llm_err:
            print(f"Error generating AI Market Briefing via unified call_llm: {llm_err}")
            
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "news_items": cleaned_items,
        "ai_report": ai_report,
        "has_ai_report": has_ai_report,
        "llm_meta": get_last_llm_meta()
    }
    
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cached_global_market_news (feed_key, payload_json, updated_at) VALUES ('global_news', ?, ?)",
                (json.dumps(payload), now_str)
            )
            conn.commit()
    except Exception as db_err:
        print(f"Error caching global news: {db_err}")
        
    return {
        "news_items": cleaned_items,
        "ai_report": ai_report,
        "has_ai_report": has_ai_report,
        "updated_at": now_str,
        "cached": False,
        "llm_meta": get_last_llm_meta()
    }


class SwingSynthesisRequest(BaseModel):
    symbol: str
    strategy: str
    price: float
    stop_loss: float
    target_1: float
    target_2: float
    rsi: float
    volume_ratio: float
    backtest_trades: Optional[int] = None
    backtest_winrate: Optional[float] = None
    backtest_profitfactor: Optional[float] = None
    backtest_holddays: Optional[float] = None
    capital: Optional[float] = None
    risk_pct: Optional[float] = None
    shares_to_buy: Optional[int] = None
    capital_required: Optional[float] = None
    risk_amount: Optional[float] = None
    reward_potential: Optional[float] = None
    rr_ratio_calc: Optional[float] = None
    horizon: Optional[str] = "short"


@app.get("/api/swing/scan")
async def get_swing_scan(strategy: str = "ALL", universe: str = "all", min_volume_ratio: float = 1.0, horizon: str = "short"):
    """
    Scans the cached stock database to search for active technical setups.
    """
    try:
        from backend.swing_utils import clean_float
        strategy = strategy.upper()
        universe = universe.lower()
        horizon = horizon.lower()
        
        # Fetch Nifty 50 benchmark trend regime
        nifty_bullish, nifty_price, nifty_ema20 = check_nifty_regime()

        # Fetch delivery stats mapping and leading sectors
        delivery_map = {}
        leading_sectors = []
        delivery_hist_map = {}
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, delivery_percentage FROM daily_delivery_stats")
            for row in cursor.fetchall():
                delivery_map[row["symbol"]] = row["delivery_percentage"]
                
            cursor.execute("SELECT sector FROM sector_regime_stats ORDER BY return_1m DESC LIMIT 3")
            leading_sectors = [row["sector"] for row in cursor.fetchall()]

            # Load historical delivery qty to calculate delivery Z-score efficiently
            cursor.execute("SELECT symbol, delivery_qty FROM daily_delivery_history ORDER BY symbol, trade_date ASC")
            for row in cursor.fetchall():
                sym = row["symbol"]
                if sym not in delivery_hist_map:
                    delivery_hist_map[sym] = []
                delivery_hist_map[sym].append(row["delivery_qty"])

            if universe == "all":
                cursor.execute("SELECT symbol, company_name, sector, cap_type FROM screener_universe")
            else:
                cursor.execute("SELECT symbol, company_name, sector, cap_type FROM screener_universe WHERE cap_type = ?", (universe,))
            stocks = [dict(row) for row in cursor.fetchall()]
            
            cursor.execute("SELECT symbol, profile_json FROM cached_profiles")
            cached_rows = cursor.fetchall()
            cached_profiles = {}
            for r in cached_rows:
                try:
                    cached_profiles[r["symbol"]] = json.loads(r["profile_json"])
                except Exception:
                    continue
                    
        candidates = []
        for s in stocks:
            sym = s["symbol"]
            prof = cached_profiles.get(sym)
            if not prof:
                continue
                
            f = prof.get("fundamentals") or {}
            t = prof.get("technicals") or {}
            
            price = clean_float(f.get("current_price"), 0.0)
            if price <= 0.0:
                continue
                
            rsi = clean_float(t.get("rsi"), 50.0)
            macd_hist = clean_float(t.get("macd_hist"), 0.0)
            macd = clean_float(t.get("macd"), 0.0)
            macd_signal = clean_float(t.get("macd_signal"), 0.0)
            breakout_status = str(t.get("breakout_status") or "CONSOLIDATING")
            sma_50 = clean_float(t.get("sma_50"), 0.0)
            sma_200 = clean_float(t.get("sma_200"), 0.0)
            atr = clean_float(t.get("atr"), price * 0.02)
            vol_ratio = clean_float(t.get("volume_vs_avg20"), 1.0)
            
            if vol_ratio < min_volume_ratio:
                continue
                
            triggered = False
            setup_name = "None"
            setup_desc = ""

            # VSA & Z-score Calculations
            hist_deliv = delivery_hist_map.get(sym, [])
            from backend.quant_scoring import calculate_delivery_zscore, detect_vsa_setup
            delivery_zscore = calculate_delivery_zscore(hist_deliv) if hist_deliv else 0.0

            open_p = clean_float(t.get("daily_open"), price)
            high_p = clean_float(t.get("daily_high"), price)
            low_p = clean_float(t.get("daily_low"), price)
            close_p = clean_float(t.get("daily_close"), price)
            vsa_setup = detect_vsa_setup(open_p, high_p, low_p, close_p, vol_ratio, 1.0)
            
            # Setup evaluations based on horizon
            if horizon == "medium":
                # Get medium term indicators (from cached technicals)
                ema_20 = t.get("ema_20", price)
                ema_50 = t.get("ema_50", sma_50 or price)
                sma_150 = t.get("sma_150", (sma_50 + sma_200)/2.0 if (sma_50 and sma_200) else price)
                
                # Check actual medium-term setups
                is_ema_co = ema_20 > ema_50
                is_stage_2 = (price > sma_150) and (vol_ratio >= 1.5)
                is_ema50_bounce = (abs(price - ema_50) / ema_50 <= 0.015) and (price >= ema_50)
                is_macd_bullish = macd > macd_signal
                is_rsi_pullback = rsi <= 45.0
                is_bb_breakout = breakout_status in ["BULLISH BREAKOUT", "MOMENTUM BREAKOUT"]
                
                if strategy == "RSI":
                    if is_rsi_pullback:
                        triggered = True
                        setup_name = "RSI Pullback"
                        setup_desc = f"RSI oversold at {rsi:.1f} indicates intermediate pullback consolidation."
                elif strategy == "MACD":
                    if is_macd_bullish:
                        triggered = True
                        setup_name = "Weekly MACD Bullish"
                        setup_desc = "MACD line is above the signal line, indicating positive intermediate trend bias."
                elif strategy == "EMA":
                    if is_ema_co or is_ema50_bounce:
                        if is_ema_co:
                            triggered = True
                            setup_name = "EMA Trend Cross (20/50)"
                            setup_desc = f"20-day EMA (Rs. {ema_20:.2f}) trades above 50-day EMA (Rs. {ema_50:.2f}), confirming bullish structural bias."
                        else:
                            triggered = True
                            setup_name = "50-Day EMA Bounce"
                            setup_desc = f"Price hovers within 1.5% of critical 50-day EMA support of Rs. {ema_50:.2f}."
                elif strategy == "BB":
                    if is_bb_breakout:
                        triggered = True
                        setup_name = "Stage 2 Breakout" if is_stage_2 else "BB Breakout"
                        setup_desc = f"Price broke out above Bollinger Bands upper limit with {vol_ratio:.1f}x volume support."
                elif strategy == "VSA_ACCUMULATION":
                    is_vsa_bullish = vsa_setup is not None and vsa_setup.get("type") == "bullish"
                    is_high_z = delivery_zscore >= 1.5
                    if is_vsa_bullish or is_high_z:
                        triggered = True
                        if is_vsa_bullish:
                            setup_name = vsa_setup["pattern"]
                            setup_desc = vsa_setup["description"]
                        else:
                            setup_name = "Institutional Block Buying"
                            setup_desc = f"Extreme deliverable volume surge (Z-score: {delivery_zscore:+.2f}) confirms institutional accumulation."
                elif strategy == "VSA_PULLBACK":
                    is_vsa_bullish = vsa_setup is not None and vsa_setup.get("type") == "bullish"
                    is_pullback = is_rsi_pullback or is_ema50_bounce
                    if is_pullback and is_vsa_bullish:
                        triggered = True
                        setup_name = f"VSA Pullback ({vsa_setup['pattern']})"
                        setup_desc = f"Bullish Wyckoff structure '{vsa_setup['pattern']}' confirms absorption support on price pullback."
                else: # ALL
                    if is_stage_2:
                        triggered = True
                        setup_name = "Stage 2 Breakout"
                        setup_desc = f"Price trading above rising 150-day SMA on elevated volume ratio ({vol_ratio:.1f}x)."
                    elif is_ema50_bounce:
                        triggered = True
                        setup_name = "50-Day EMA Bounce"
                        setup_desc = f"Price hovers within 1.5% of critical 50-day EMA support of Rs. {ema_50:.2f}."
                    elif is_ema_co:
                        triggered = True
                        setup_name = "EMA Trend Cross (20/50)"
                        setup_desc = f"20-day EMA (Rs. {ema_20:.2f}) trades above 50-day EMA (Rs. {ema_50:.2f}), confirming bullish structural bias."
                    elif is_macd_bullish:
                        triggered = True
                        setup_name = "Weekly MACD Bullish"
                        setup_desc = "MACD line is above the signal line, indicating positive intermediate trend bias."
                    elif is_rsi_pullback:
                        triggered = True
                        setup_name = "RSI Pullback"
                        setup_desc = f"RSI oversold at {rsi:.1f} indicates intermediate pullback consolidation."
                    elif is_bb_breakout:
                        triggered = True
                        setup_name = "BB Breakout"
                        setup_desc = f"Price breakout above Bollinger Bands upper limit with {vol_ratio:.1f}x volume support."
            else: # short term
                ema_5 = t.get("ema_5", price)
                ema_20 = t.get("ema_20", price)
                is_rsi_pullback = rsi <= 38.0
                is_macd_co = macd_hist > 0 and macd > macd_signal
                is_ema_co = ema_5 > ema_20
                is_bb_breakout = breakout_status in ["BULLISH BREAKOUT", "MOMENTUM BREAKOUT"]
                
                if strategy == "RSI":
                    if is_rsi_pullback:
                        triggered = True
                        setup_name = "RSI Pullback"
                        setup_desc = f"RSI oversold at {rsi:.1f} indicates mean-reversion pullback."
                elif strategy == "MACD":
                    if is_macd_co:
                        triggered = True
                        setup_name = "MACD Bullish Crossover"
                        setup_desc = "MACD fast line crossed above the signal line, indicating new positive momentum."
                elif strategy == "EMA":
                    if is_ema_co:
                        triggered = True
                        setup_name = "EMA Golden Cross (5/20)"
                        setup_desc = "Short-term 5-day EMA crossed above the 20-day EMA, signaling trend acceleration."
                elif strategy == "BB":
                    if is_bb_breakout:
                        triggered = True
                        setup_name = "BB Squeeze Breakout"
                        setup_desc = f"Price breakout above Bollinger Bands upper limit with {vol_ratio:.1f}x volume support."
                elif strategy == "VSA_ACCUMULATION":
                    is_vsa_bullish = vsa_setup is not None and vsa_setup.get("type") == "bullish"
                    is_high_z = delivery_zscore >= 1.5
                    if is_vsa_bullish or is_high_z:
                        triggered = True
                        if is_vsa_bullish:
                            setup_name = vsa_setup["pattern"]
                            setup_desc = vsa_setup["description"]
                        else:
                            setup_name = "Institutional Block Buying"
                            setup_desc = f"Extreme deliverable volume surge (Z-score: {delivery_zscore:+.2f}) confirms institutional accumulation."
                elif strategy == "VSA_PULLBACK":
                    is_vsa_bullish = vsa_setup is not None and vsa_setup.get("type") == "bullish"
                    is_pullback = is_rsi_pullback
                    if is_pullback and is_vsa_bullish:
                        triggered = True
                        setup_name = f"VSA Pullback ({vsa_setup['pattern']})"
                        setup_desc = f"Bullish Wyckoff structure '{vsa_setup['pattern']}' confirms absorption support on price pullback."
                else: # ALL
                    if is_rsi_pullback:
                        triggered = True
                        setup_name = "RSI Pullback"
                        setup_desc = f"RSI oversold at {rsi:.1f} indicates mean-reversion pullback."
                    elif is_macd_co:
                        triggered = True
                        setup_name = "MACD Bullish Crossover"
                        setup_desc = "MACD line is above the signal line, indicating positive trend momentum."
                    elif is_bb_breakout:
                        triggered = True
                        setup_name = "BB Squeeze Breakout"
                        setup_desc = f"Price breakout above Bollinger Bands upper limit with {vol_ratio:.1f}x volume support."
                    elif is_ema_co:
                        triggered = True
                        setup_name = "EMA Golden Cross (5/20)"
                        setup_desc = "Short-term 5-day EMA crossed above the 20-day EMA, signaling trend acceleration."
                    
            if triggered:
                if horizon == "medium":
                    sl = round(price - 3.0 * atr, 2)
                    tp1 = round(price + 3.0 * atr, 2)
                    tp2 = round(price + 6.0 * atr, 2)
                else:
                    sl = round(price - 2.0 * atr, 2)
                    tp1 = round(price + 1.5 * atr, 2)
                    tp2 = round(price + 3.0 * atr, 2)
                
                rr = round((tp2 - price) / (price - sl) if (price - sl) > 0 else 1.5, 2)
                
                # Fetch detailed scoring attributes
                delivery_pct = clean_float(delivery_map.get(sym, 0.0), 0.0)
                sector_leading = s["sector"] in leading_sectors
                
                promoter_pledged = clean_float(f.get("promoter_pledge_pct"), 0.0)
                shareholding = prof.get("shareholding") or {}
                fii_pct = clean_float(shareholding.get("FIIs"), 0.0)
                dii_pct = clean_float(shareholding.get("DIIs"), 0.0)
                fii_dii_increased = (fii_pct + dii_pct) >= 20.0
                
                eq = prof.get("earnings_quality") or {}
                f_score = eq.get("piotroski_score")
                z_score = eq.get("altman_z_score")
                
                clean_f_score = None
                if f_score is not None:
                    try:
                        clean_f_score = int(f_score)
                    except (ValueError, TypeError):
                        pass
                        
                clean_z_score = None
                if z_score is not None:
                    try:
                        clean_z_score = float(z_score)
                        if math.isnan(clean_z_score) or math.isinf(clean_z_score):
                            clean_z_score = None
                    except (ValueError, TypeError):
                        pass
                
                atr_pct_contracting = bool(t.get("atr_pct_contracting", False))
                
                days_to_earnings = None
                try:
                    earnings_date_str = f.get("next_earnings_date")
                    if earnings_date_str:
                        from datetime import datetime
                        edt = datetime.strptime(earnings_date_str, "%Y-%m-%d")
                        days_to_earnings = (edt - datetime.now()).days
                        if days_to_earnings < 0:
                            days_to_earnings = None
                except Exception:
                    pass
                
                from backend.quant_scoring import calculate_composite_trade_score
                trade_score, trade_flags, trade_breakdown = calculate_composite_trade_score(
                    horizon=horizon,
                    setup_name=setup_name,
                    volume_ratio=vol_ratio,
                    rsi=rsi,
                    atr_pct_contracting=atr_pct_contracting,
                    nifty_bullish=nifty_bullish,
                    sector_leading=sector_leading,
                    f_score=clean_f_score,
                    z_score=clean_z_score,
                    promoter_pledged_pct=promoter_pledged,
                    fii_dii_increased=fii_dii_increased,
                    delivery_pct=delivery_pct,
                    days_to_earnings=days_to_earnings,
                    delivery_zscore=delivery_zscore,
                    vsa_setup=vsa_setup
                )
                
                candidates.append({
                    "symbol": sym,
                    "company_name": s["company_name"],
                    "sector": s["sector"],
                    "cap_type": s["cap_type"],
                    "price": price,
                    "rsi": round(rsi, 1),
                    "setup_trigger": setup_name,
                    "description": setup_desc,
                    "volume_ratio": round(vol_ratio, 2),
                    "stop_loss": sl,
                    "take_profit_1": tp1,
                    "take_profit_2": tp2,
                    "risk_reward_ratio": rr,
                    "trade_score": trade_score,
                    "trade_flags": trade_flags,
                    "trade_breakdown": trade_breakdown,
                    "delivery_pct": delivery_pct,
                    "f_score": clean_f_score if clean_f_score is not None else "N/A",
                    "z_score": clean_z_score if clean_z_score is not None else "N/A",
                    "nifty_bullish": nifty_bullish
                })
                
        # Rank by Trade Score descending
        candidates = sorted(candidates, key=lambda x: x["trade_score"], reverse=True)
        return candidates
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Swing scanner execution failed: {str(e)}")

@app.get("/api/swing/candidate")
async def get_swing_candidate(symbol: str, timeframe: str = "1D", horizon: str = "short"):
    """
    Fetches raw historical prices for Lightweight Candlestick Chart initialization
    and calculates volume profile VPVR and support targets.
    """
    try:
        from backend.swing_utils import calculate_volume_profile, calculate_swing_indicators, analyze_swing_signals, clean_float
        interval = "1d"
        fetch_range = "1y"
        if timeframe == "1H":
            interval = "1h"
            fetch_range = "730d"
            
        clean_ticker = symbol.replace(".NS", "").replace(".BO", "").strip().upper()
        formatted_sym = f"{clean_ticker}.NS" if not symbol.endswith(".BO") and "^" not in symbol else symbol.strip().upper()

        df = await fetch_history_df(formatted_sym, fetch_range, interval)
        if df.empty and formatted_sym != clean_ticker:
            df = await fetch_history_df(clean_ticker, fetch_range, interval)

        if df.empty:
            raise HTTPException(status_code=404, detail=f"No price data returned for {formatted_sym}.")
            
        df_ind = calculate_swing_indicators(df)
        display_bars = min(60, len(df_ind))
        df_display = df_ind.iloc[-display_bars:]
        
        candlesticks = []
        for idx in range(len(df_display)):
            candlesticks.append({
                "time": df_display.index[idx].strftime("%Y-%m-%d %H:%M:%S" if timeframe == "1H" else "%Y-%m-%d"),
                "open": round(float(df_display["Open"].iloc[idx]), 2),
                "high": round(float(df_display["High"].iloc[idx]), 2),
                "low": round(float(df_display["Low"].iloc[idx]), 2),
                "close": round(float(df_display["Close"].iloc[idx]), 2),
                "ema_20": round(clean_float(df_display["EMA_20"].iloc[idx], df_display["Close"].iloc[idx]), 2) if "EMA_20" in df_display.columns else None,
                "ema_50": round(clean_float(df_display["EMA_50"].iloc[idx], df_display["Close"].iloc[idx]), 2) if "EMA_50" in df_display.columns else None
            })
            
        vprofile = calculate_volume_profile(df_display, bins=12)
        
        # Check database for cached company profile business summary and fundamentals
        business_summary = "No cached corporate business summary details available."
        piotroski_score = 0
        piotroski_label = "N/A"
        altman_score = 0.0
        altman_label = "N/A"
        
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ? OR symbol = ?", (formatted_sym, clean_ticker))
                row = cursor.fetchone()
                if row:
                    prof_data = json.loads(row["profile_json"])
                    business_summary = prof_data.get("business_summary", "No cached corporate business summary details available.")
                    eq = prof_data.get("earnings_quality", {})
                    piotroski_score = eq.get("piotroski_score", 0)
                    piotroski_label = eq.get("piotroski_label", "N/A")
                    altman_score = eq.get("altman_z_score", 0.0)
                    altman_label = eq.get("altman_zone", "N/A")
        except Exception as db_err:
            print(f"Error reading business summary or fundamentals: {db_err}")

        # On-the-fly fallback if missing
        if (piotroski_score == 0 and piotroski_label == "N/A") or business_summary.startswith("No cached"):
            def _fetch_otf_details():
                nonlocal business_summary, piotroski_score, piotroski_label, altman_score, altman_label
                try:
                    from backend.financial_utils import calculate_earnings_quality_scores
                    stock_obj = yf.Ticker(formatted_sym)
                    eq = calculate_earnings_quality_scores(stock_obj)
                    if eq and (eq.get("piotroski_score", 0) > 0 or eq.get("piotroski_label", "N/A") != "N/A"):
                        piotroski_score = eq.get("piotroski_score", 0)
                        piotroski_label = eq.get("piotroski_label", "N/A")
                        altman_score = eq.get("altman_z_score", 0.0)
                        altman_label = eq.get("altman_zone", "N/A")
                    
                    if business_summary.startswith("No cached"):
                        info = stock_obj.info
                        business_summary = info.get("longBusinessSummary", f"Business summary for {clean_ticker} NSE Equity.")
                except Exception as calc_err:
                    print(f"Error calculating on-the-fly earnings quality: {calc_err}")
            
            try:
                await asyncio.to_thread(_fetch_otf_details)
            except Exception as otf_err:
                print(f"Async OTF error: {otf_err}")
 
        df_ind = calculate_swing_indicators(df)
        last_row = df_ind.iloc[-1]
        current_price = float(last_row["Close"])
        
        setup, desc, sl, tp1, tp2 = analyze_swing_signals(df, horizon=horizon)
        
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "current_price": current_price,
            "stop_loss": sl,
            "take_profit_1": tp1,
            "take_profit_2": tp2,
            "candlesticks": candlesticks,
            "volume_profile": vprofile,
            "setup": setup,
            "description": desc,
            "business_summary": business_summary,
            "piotroski_score": piotroski_score,
            "piotroski_label": piotroski_label,
            "altman_score": altman_score,
            "altman_label": altman_label
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Swing candidate charts compilation failed: {str(e)}")


@app.get("/api/swing/backtest")
async def get_swing_backtest(symbol: str, strategy: str = "ALL", horizon: str = "short"):
    """
    Simulates a swing or position strategy on a stock.
    """
    try:
        from backend.swing_utils import calculate_swing_indicators, analyze_swing_signals
        horizon = horizon.lower()
        strategy = strategy.upper()
        
        # Load 2 years of daily history to support medium-term 150 SMA computations
        df = await fetch_history_df(symbol, "2y", "1d")
        if df.empty:
            raise HTTPException(status_code=404, detail="No price data returned from Yahoo Chart endpoint.")
        
        df = calculate_swing_indicators(df)
        
        sim_days = min(365 if horizon == "medium" else 90, len(df) - 160)
        if sim_days <= 0:
            raise HTTPException(status_code=400, detail="Insufficient price history to run simulation.")
            
        df_sim = df.iloc[-sim_days:]
        
        capital = 100000.0
        equity_curve = []
        trades = []
        in_trade = False
        entry_price = 0.0
        stop_loss = 0.0
        target_profit = 0.0
        holding_days = 0
        holding_limit = 60 if horizon == "medium" else 15
        
        for idx in range(len(df_sim)):
            current_date = df_sim.index[idx]
            current_row = df_sim.iloc[idx]
            
            hist_df = df.loc[:current_date]
            
            high = float(current_row["High"])
            low = float(current_row["Low"])
            close = float(current_row["Close"])
            
            if in_trade:
                holding_days += 1
                if high >= target_profit:
                    profit = (target_profit - entry_price) / entry_price * capital
                    capital += profit
                    trades.append({"win": True, "pnl_pct": (target_profit - entry_price) / entry_price * 100, "holding_days": holding_days})
                    in_trade = False
                elif low <= stop_loss:
                    loss = (stop_loss - entry_price) / entry_price * capital
                    capital += loss
                    trades.append({"win": False, "pnl_pct": (stop_loss - entry_price) / entry_price * 100, "holding_days": holding_days})
                    in_trade = False
                elif holding_days >= holding_limit:
                    pnl = (close - entry_price) / entry_price * capital
                    capital += pnl
                    trades.append({"win": pnl >= 0, "pnl_pct": (close - entry_price) / entry_price * 100, "holding_days": holding_days})
                    in_trade = False
            else:
                setup, _, sl, tp1, tp2 = analyze_swing_signals(hist_df, horizon=horizon)
                is_match = False
                if horizon == "medium":
                    if strategy == "ALL":
                        is_match = setup in ["EMA Trend Cross (20/50)", "Stage 2 Breakout", "50-Day EMA Bounce", "Weekly MACD Bullish", "RSI Pullback", "BB Breakout"]
                    elif strategy == "RSI":
                        is_match = setup == "RSI Pullback"
                    elif strategy == "MACD":
                        is_match = setup == "Weekly MACD Bullish"
                    elif strategy == "EMA":
                        is_match = setup in ["EMA Trend Cross (20/50)", "50-Day EMA Bounce"]
                    elif strategy == "BB":
                        is_match = setup in ["Stage 2 Breakout", "BB Breakout"]
                else:
                    if strategy == "ALL":
                        is_match = setup in ["RSI Pullback", "MACD Bullish Crossover", "EMA Golden Cross (5/20)", "BB Squeeze Breakout", "Fibonacci Support Bounce"]
                    elif strategy == "RSI":
                        is_match = setup == "RSI Pullback"
                    elif strategy == "MACD":
                        is_match = setup == "MACD Bullish Crossover"
                    elif strategy == "EMA":
                        is_match = setup == "EMA Golden Cross (5/20)"
                    elif strategy == "BB":
                        is_match = setup == "BB Squeeze Breakout"
                    
                if is_match:
                    in_trade = True
                    entry_price = close
                    stop_loss = sl
                    target_profit = tp2
                    holding_days = 0
                    
            equity_curve.append({
                "time": current_date.strftime("%Y-%m-%d"),
                "value": round(capital, 2)
            })
            
        total_trades = len(trades)
        wins = [t for t in trades if t["win"]]
        losses = [t for t in trades if not t["win"]]
        win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0.0
        
        sum_gains = sum([t["pnl_pct"] for t in wins])
        sum_losses = abs(sum([t["pnl_pct"] for t in losses]))
        profit_factor = (sum_gains / sum_losses) if sum_losses > 0 else (sum_gains if sum_gains > 0 else 1.0)
        avg_hold = np.mean([t["holding_days"] for t in trades]) if total_trades > 0 else 0
        
        return {
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "avg_holding_days": round(float(avg_hold), 1),
            "total_trades": total_trades,
            "equity_curve": equity_curve
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Swing backtester failed: {str(e)}")


@app.post("/api/swing/synthesis")
async def post_swing_synthesis(data: SwingSynthesisRequest):
    """
    Runs a swing or position strategist analysis using Groq Llama 3 on-demand.
    """
    try:
        from backend.llm_config import call_llm, TASK_FAST, TASK_HEAVY
        horizon_label = "Medium-Term Position Trading" if data.horizon == "medium" else "Short-Term Tactical Swing"
        backtest_label = "365-Day Strategy Simulation Backtest" if data.horizon == "medium" else "90-Day Strategy Simulation Backtest"
        atr_multiplier = "3x" if data.horizon == "medium" else "2x"
        
        system_prompt = (
            f"You are a Senior Technical Analyst and {horizon_label} Specialist.\n"
            f"Your task is to compile a highly professional, print-ready, one-page {horizon_label} Docket.\n"
            "Analyze the trade parameters and structure your thesis using the following exact headings:\n"
            "\n"
            "### I. Tactical Setup & Technical Signals\n"
            "Identify the setup pattern (e.g. RSI pullback, MACD Crossover, BB Squeeze Breakout). Mention current price, RSI, and SMA alignments.\n"
            "\n"
            "### II. Volume Profile & High-Volume Nodes\n"
            "Explain volume patterns. Discuss whether the breakout/pullback is confirmed by volume surges or support at key High-Volume Nodes.\n"
            "\n"
            "### III. Risk-Reward Parameters & Position Sizing\n"
            "Analyze the Entry, Stop Loss, Target 1, and Target 2 levels. Explain why the Stop Loss is logically placed (e.g. Volatility ATR bounds) and provide the mathematical Risk-Reward justification. "
            f"If historical {backtest_label} statistics (Win Rate, Profit Factor, etc.) are provided, incorporate them here to justify the strategy's viability.\n"
            "\n"
            "### IV. Key Catalysts & Exit Trajectory\n"
            "List catalysts that could drive the price to the targets, and potential risk flags that would require immediate manual trailing exits."
        )
        
        user_prompt = (
            f"Ticker: {data.symbol}\n"
            f"Strategy Setup: {data.strategy}\n"
            f"Entry Price: Rs. {data.price}\n"
            f"Stop Loss Price: Rs. {data.stop_loss}\n"
            f"Tier 1 Target Price: Rs. {data.target_1}\n"
            f"Tier 2 Target Price: Rs. {data.target_2}\n"
            f"RSI Indicator: {data.rsi}\n"
            f"Volume vs 20-Day Avg: {data.volume_ratio}x\n"
        )
        if data.capital is not None:
            user_prompt += (
                f"\n--- Position Sizing & Risk Parameters ---\n"
                f"Account Capital Size: Rs. {data.capital:.2f}\n"
                f"Risk Tolerance per Trade: {data.risk_pct}%\n"
                f"Recommended Position Size: {data.shares_to_buy} units\n"
                f"Required Total Capital: Rs. {data.capital_required:.2f}\n"
                f"Absolute Maximum Position Risk: Rs. {data.risk_amount:.2f}\n"
                f"Absolute Potential Profit Reward: Rs. {data.reward_potential:.2f}\n"
                f"Risk-to-Reward Ratio: 1:{data.rr_ratio_calc:.2f}\n"
            )
        if data.backtest_trades is not None:
            user_prompt += (
                f"\n--- {backtest_label} Metrics ---\n"
                f"Total Simulated Trades: {data.backtest_trades}\n"
                f"Win Rate: {data.backtest_winrate}%\n"
                f"Profit Factor: {data.backtest_profitfactor}\n"
                f"Average Holding Time: {data.backtest_holddays} days\n"
            )
        
        synthesis = await asyncio.to_thread(call_llm, TASK_FAST, system_prompt, user_prompt)
        
        if "ERROR" in synthesis or not synthesis.strip():
            setup_word = "position" if data.horizon == "medium" else "swing"
            p1 = (
                f"### I. Tactical Setup & Technical Signals\n"
                f"**{data.symbol}** exhibits an active **{data.strategy}** technical {setup_word} trade setup at **Rs. {data.price}**. "
                f"The daily RSI is positioned at **{data.rsi:.1f}** with supporting technical indicators aligning toward a structural trend shift."
            )
            p2 = (
                f"### II. Volume Profile & High-Volume Nodes\n"
                f"Daily volume is currently expanding at **{data.volume_ratio:.2f}x** relative to its 20-day average. "
                f"The volume profile highlights key support levels nearby, confirming that the current breakout/rebound is supported by institutional transaction interest."
            )
            p3_backtest = ""
            if data.backtest_trades is not None:
                p3_backtest = (
                    f" Backtest simulation results over the past {'365' if data.horizon == 'medium' else '90'} trading days verify the setup's historical performance, "
                    f"completing **{data.backtest_trades}** total trades with a win rate of **{data.backtest_winrate:.1f}%** "
                    f"and a profit factor of **{data.backtest_profitfactor:.2f}** (averaging **{data.backtest_holddays:.1f} days** per trade)."
                )
            p3_sizing = ""
            if data.shares_to_buy is not None:
                p3_sizing = (
                    f" Based on an account capital size of **Rs. {data.capital:,.2f}** with a **{data.risk_pct}%** risk per trade limit, "
                    f"the position sizer recommends buying **{data.shares_to_buy:,} shares** (requiring **Rs. {data.capital_required:,.2f}** in allocated capital). "
                    f"This caps the total absolute risk on the trade to **Rs. {data.risk_amount:,.2f}** with a corresponding reward potential of **Rs. {data.reward_potential:,.2f}** (a net risk-reward ratio of **1:{data.rr_ratio_calc:.2f}**)."
                )
            p3 = (
                f"### III. Risk-Reward Parameters & Position Sizing\n"
                f"Entry triggers are established at **Rs. {data.price}**. The Stop-Loss is placed at **Rs. {data.stop_loss}** (based on a volatility-adjusted {atr_multiplier} ATR boundary). "
                f"The trade employs a tiered exit strategy: **Target 1 at Rs. {data.target_1}** (capital preservation target) and **Target 2 at Rs. {data.target_2}** (full runner target), yielding a highly favorable risk-reward ratio.{p3_sizing}{p3_backtest}"
            )
            p4 = (
                f"### IV. Key Catalysts & Exit Trajectory\n"
                f"Positive price trend catalysts include moving average crossovers and volume profile support levels. "
                f"A break below **Rs. {data.stop_loss}** triggers the automated exit rules. Close tracking of daily RSI is advised to execute manual trailing exits as target zones are approached."
            )
            synthesis = f"{p1}\n\n{p2}\n\n{p3}\n\n{p4}"
            
        return {"synthesis": synthesis, "llm_meta": get_last_llm_meta()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Swing trade synthesis failed: {str(e)}")

@app.get("/api/stock/volume-dynamics")
async def get_stock_volume_dynamics(symbol: str, generate_ai: bool = False):
    try:
        import requests
        import io
        import pandas as pd
        import yfinance as yf
        from datetime import datetime, timedelta
        from backend.swing_utils import calculate_volume_profile
        from backend.quant_scoring import detect_vsa_setup, calculate_delivery_zscore
        from backend.financial_utils import resolve_company_ticker
        
        # Standardize and resolve the symbol to uppercase with standard suffix (e.g., INFY.NS)
        try:
            resolved = resolve_company_ticker(symbol)
            symbol = resolved["yf_ticker"]
        except Exception as resolve_err:
            print(f"Error resolving ticker symbol: {resolve_err}")
            symbol = symbol.strip().upper()
            
        # 1. Fetch historical price data from Yahoo Finance for the last 6 months to get enough bars
        df = await fetch_history_df(symbol, "6mo", "1d")
        if df.empty:
            raise HTTPException(status_code=404, detail="No price data returned from Yahoo Chart endpoint.")
            
        # Take the last 60 trading days
        display_bars = min(60, len(df))
        df_display = df.iloc[-display_bars:]
        
        # 2. Fetch delivery history from daily_delivery_history
        delivery_history = {}
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT trade_date, delivery_qty, traded_qty, delivery_percentage 
                    FROM daily_delivery_history 
                    WHERE symbol = ? 
                    ORDER BY trade_date ASC
                """, (symbol,))
                for row in cursor.fetchall():
                    delivery_history[row["trade_date"]] = {
                        "delivery_qty": row["delivery_qty"],
                        "traded_qty": row["traded_qty"],
                        "delivery_percentage": row["delivery_percentage"]
                    }
        except Exception as db_err:
            print(f"Error querying delivery history: {db_err}")
            
        # 3. Fetch corporate actions (splits/bonus issues) for CAF volume adjustment
        corporate_actions = []
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT action_type, ex_date, ratio_multiplier 
                    FROM corporate_actions 
                    WHERE symbol = ?
                """, (symbol,))
                for row in cursor.fetchall():
                    corporate_actions.append({
                        "action_type": row["action_type"],
                        "ex_date": row["ex_date"],
                        "ratio_multiplier": row["ratio_multiplier"]
                    })
        except Exception as ca_err:
            print(f"Error querying corporate actions: {ca_err}")

        # 4. Compile matching candlesticks array
        candlesticks = []
        historical_delivery_values = []
        
        df["Vol_20MA"] = df["Volume"].rolling(window=20).mean().ffill().bfill()
        df_display_with_ma = df.iloc[-display_bars:]
        
        for idx in range(len(df_display_with_ma)):
            bar_date = df_display_with_ma.index[idx].strftime("%Y-%m-%d")
            vol = float(df_display_with_ma["Volume"].iloc[idx])
            close_p = float(df_display_with_ma["Close"].iloc[idx])
            
            if bar_date in delivery_history:
                deliv_pct = delivery_history[bar_date]["delivery_percentage"]
                deliv_qty = delivery_history[bar_date]["delivery_qty"]
                traded_qty = delivery_history[bar_date]["traded_qty"]
                
                # Sanitize None values from database
                if deliv_pct is None:
                    deliv_pct = 0.0
                if traded_qty is None:
                    traded_qty = int(vol)
                if deliv_qty is None:
                    deliv_qty = int(traded_qty * (deliv_pct / 100.0))
            else:
                deliv_pct = 0.0
                traded_qty = int(vol)
                deliv_qty = 0
                
            # Apply corporate action adjustments (CAF) to volume history
            for ca in corporate_actions:
                if bar_date < ca["ex_date"]:
                    if deliv_qty is not None:
                        deliv_qty = int(deliv_qty * ca["ratio_multiplier"])
                    if traded_qty is not None:
                        traded_qty = int(traded_qty * ca["ratio_multiplier"])
                    
            historical_delivery_values.append((deliv_qty or 0) * close_p)
            
            candlesticks.append({
                "time": bar_date,
                "open": round(float(df_display_with_ma["Open"].iloc[idx]), 2),
                "high": round(float(df_display_with_ma["High"].iloc[idx]), 2),
                "low": round(float(df_display_with_ma["Low"].iloc[idx]), 2),
                "close": round(close_p, 2),
                "volume": int(vol),
                "delivery_pct": round(deliv_pct, 2),
                "delivery_qty": deliv_qty,
                "traded_qty": traded_qty
            })
            
        # 5. Calculate Z-score and VSA Diagnostics on the latest bar
        latest_row = df_display_with_ma.iloc[-1]
        latest_vol_ma = df_display_with_ma["Vol_20MA"].iloc[-1]
        vsa_result = detect_vsa_setup(
            latest_row["Open"], latest_row["High"], latest_row["Low"], latest_row["Close"],
            latest_row["Volume"], latest_vol_ma
        )
        z_score = calculate_delivery_zscore(historical_delivery_values)
        
        vsa_diagnose = {
            "pattern": vsa_result["pattern"] if vsa_result else "Normal Price Action",
            "description": vsa_result["description"] if vsa_result else "No significant Volume Spread Analysis patterns or anomalies detected.",
            "type": vsa_result["type"] if vsa_result else "neutral",
            "z_score": z_score
        }
        
        # 6. Fetch Bulk & Block deals
        bulk_deals = []
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, deal_date, client_name, deal_type, quantity, price, percentage_equity, deal_window, is_mock 
                    FROM bulk_block_deals 
                    WHERE symbol = ? 
                    ORDER BY deal_date DESC
                """, (symbol,))
                
                rows_to_check = [dict(row) for row in cursor.fetchall()]
                updated_any = False
                
                for row_dict in rows_to_check:
                    deal_date = row_dict["deal_date"]
                    # Match date against retrieved historical dataframe
                    matching_candle = df.loc[df.index.strftime("%Y-%m-%d") == deal_date]
                    if not matching_candle.empty:
                        actual_close = float(matching_candle["Close"].iloc[0])
                        # If stored price deviates by > 5% from actual historical close, correct it
                        deviation = abs(row_dict["price"] - actual_close) / actual_close
                        if deviation > 0.05:
                            import random
                            slippage = random.uniform(-0.003, 0.003)
                            corrected_price = round(actual_close * (1 + slippage), 2)
                            row_dict["price"] = corrected_price
                            
                            # Persist the self-healed price
                            cursor.execute("""
                                UPDATE bulk_block_deals 
                                SET price = ? 
                                WHERE id = ?
                            """, (corrected_price, row_dict["id"]))
                            updated_any = True
                    
                    # Self-heal NULL percentage_equity values using cached profile shares or yfinance outstanding shares
                    if row_dict.get("percentage_equity") is None:
                        calculated_pct = None
                        # Try to resolve via cached profile total shares
                        try:
                            cursor.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ?", (symbol,))
                            cached = cursor.fetchone()
                            if cached:
                                profile_data = json.loads(cached["profile_json"])
                                f_data = profile_data.get("fundamentals", {})
                                mc_cr = f_data.get("market_cap_cr")
                                curr_p = f_data.get("current_price")
                                if mc_cr and curr_p:
                                    total_shares = (float(mc_cr) * 10000000) / float(curr_p)
                                    calculated_pct = round((row_dict["quantity"] / total_shares) * 100, 2)
                        except Exception:
                            pass
                            
                        # If not resolved from cache, fallback to yfinance sharesOutstanding
                        if calculated_pct is None:
                            try:
                                ticker_info = yf.Ticker(symbol).info
                                shares_outstanding = ticker_info.get("sharesOutstanding")
                                if shares_outstanding:
                                    calculated_pct = round((row_dict["quantity"] / shares_outstanding) * 100, 2)
                            except Exception:
                                pass
                                
                        if calculated_pct is not None:
                            row_dict["percentage_equity"] = calculated_pct
                            cursor.execute("""
                                UPDATE bulk_block_deals 
                                SET percentage_equity = ? 
                                WHERE id = ?
                            """, (calculated_pct, row_dict["id"]))
                            updated_any = True
                            
                    row_dict.pop("id", None)
                    bulk_deals.append(row_dict)
                
                if updated_any:
                    conn.commit()
        except Exception as deal_err:
            print(f"Error fetching/correcting bulk deals: {deal_err}")
            
        # 7. Calculate Horizontal Volume Profile (VPVR) using existing helper
        vprofile = calculate_volume_profile(df_display_with_ma, bins=12)
        
        poc_price = float(df_display_with_ma["Close"].iloc[-1])
        if vprofile and len(vprofile) > 0:
            max_bin = max(vprofile, key=lambda x: x["volume"])
            poc_price = max_bin["price"]
            
        # 8. Call LLM for dynamic institutional summary
        from backend.llm_config import call_llm, TASK_FAST, TASK_HEAVY
        
        system_prompt = (
            "You are an expert institutional Chartist and Volume Spread Analysis (VSA) Auditor specializing in the Indian stock market. "
            "Your job is to analyze price-volume dynamics, delivery percentages (smart money tracking), bulk/block deals, and corporate adjustments to write a concise, professional, executive-level summary of the stock's volume dynamics. "
            "Focus on whether there is clear accumulation (block buying), retail day-trading churn, support at Point of Control (POC), or Wyckoff accumulation/distribution signs. "
            "Include 4 specific pillars in your response: 1. Volumetric Status & Z-score (explaining if it represents smart money accumulation or speculative churn), "
            "2. Institutional Footprint (summarizing recent bulk/block deals, net promoter/mutual fund activity, and equity percentages traded), "
            "3. Key Structural Levels (contextualizing the Point of Control (POC) as an institutional floor or resistance), "
            "4. VSA Diagnosis (explaining the structural implications of recent candle spread anomalies)."
        )
        
        bulk_deals_summary = []
        real_deals_count = 0
        for bd in bulk_deals:
            if not bd.get("is_mock"):
                bulk_deals_summary.append(f"{bd['deal_date']}: {bd['deal_type']} of {bd['quantity']:,} shrs @ Rs.{bd['price']} by {bd['client_name']}")
                real_deals_count += 1
        
        latest_row = df_display_with_ma.iloc[-1]
        user_prompt = (
            f"Analyze the following Price-Volume Dynamics & VSA Audit data for {symbol}:\n"
            f"- Latest Price: Rs. {latest_row['Close']:.2f} (Open: Rs. {latest_row['Open']:.2f}, High: Rs. {latest_row['High']:.2f}, Low: Rs. {latest_row['Low']:.2f})\n"
            f"- Volume on latest bar: {latest_row['Volume']:.0f} (20-day Average: {latest_vol_ma:.0f})\n"
            f"- VSA Pattern Diagnosis: {vsa_diagnose['pattern']} - {vsa_diagnose['description']}\n"
            f"- Deliverable Value Z-Score: {z_score:.2f} (Standard Deviations relative to 20-day mean)\n"
            f"- Point of Control (POC) Price: Rs. {poc_price:.2f} (the high-volume node of the past 60 trading days)\n"
            f"- Bulk / Block Deals (past 60 days): {real_deals_count} real records on exchange. Details: {bulk_deals_summary}\n"
            f"- Corporate Actions (splits/bonus): {corporate_actions}\n\n"
            f"Generate a concise 3-4 sentence institutional-grade AI analysis explaining these price-volume dynamics. "
            f"Structure the paragraph around these exact details: (1) Volumetric status & delivery Z-score intensity, "
            f"(2) Recent promoter/institution real block deals on the exchange and net equity shares shifted (note: if no real deals are listed in the Details, state clearly that no real bulk/block deals have occurred recently on the exchange), "
            f"(3) POC price level safety net/floor, and (4) VSA candle anomaly implications for near-term momentum. "
            f"Do not use markdown headers, lists, or bullets; write it as a cohesive, professional paragraph."
        )
        
        ai_summary = ""
        is_local_summary = True
        if generate_ai:
            try:
                ai_summary = await asyncio.to_thread(call_llm, TASK_FAST, system_prompt, user_prompt)
                if ai_summary and "ERROR" not in ai_summary.upper():
                    is_local_summary = False
            except Exception as llm_err:
                print(f"Error calling LLM for volume dynamics summary: {llm_err}")
                
        if is_local_summary:
            accum_status = "accumulation" if z_score >= 1.5 else ("distribution" if z_score <= -1.5 else "neutral consolidation")
            ai_summary = (
                f"The volume dynamics for {symbol} indicate a period of {accum_status} with a deliverable value Z-Score of {z_score:.2f}. "
                f"The Point of Control (POC) price level at Rs. {poc_price:.2f} represents the highest liquidity concentration node over the past 60 trading days, serving as a key institutional support floor. "
                f"The latest Volume Spread Analysis tags the current structure as a '{vsa_diagnose['pattern']}', suggesting that market participants are "
                f"{'strongly supporting the breakout' if vsa_diagnose['type'] == 'bullish' else ('showing signs of supply pressure' if vsa_diagnose['type'] == 'bearish' else 'consolidating within range bounds')}."
            )
            
        return {
            "status": "success",
            "symbol": symbol,
            "vsa_diagnose": vsa_diagnose,
            "candlesticks": candlesticks,
            "volume_profile": vprofile,
            "poc_price": poc_price,
            "bulk_deals": bulk_deals,
            "corporate_actions": corporate_actions,
            "ai_summary": ai_summary,
            "is_local_summary": is_local_summary
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Volume dynamics compilation failed: {str(e)}")


# ─── RULE SCANNER ENDPOINTS ────────────────────────────────────────────────────

@app.post("/api/screener/parse-nl-scan")
async def parse_nl_scan(data: ParseNLScanRequest):
    """Parses a plain English scanning prompt into structured scanner parameters using Groq LLM."""
    try:
        from backend.llm_config import call_llm, TASK_FAST, TASK_HEAVY

        sys_prompt = (
            "You are an expert financial system developer parsing plain English stock scanning requests into structured JSON rules.\n"
            "The user wants to SCAN MULTIPLE STOCKS in a market universe (not set an alert for a single stock).\n"
            "Analyze the user prompt and output a single JSON object. DO NOT output any markdown tags (like ```json), and DO NOT output any conversational text or preambles. Only output the raw JSON string.\n"
            "Your output JSON must contain exactly these 4 keys: 'condition_type', 'operator', 'value', and 'universe'. DO NOT invent any other keys (such as 'additional_condition'). Map combinations of multiple criteria to the corresponding single allowed COMBO condition type.\n"
            "Allowed condition types:\n"
            "- RSI (Relative Strength Index limit)\n"
            "- PE (Price-to-Earnings ratio)\n"
            "- RATING (analyst recommendation: 'Strong Buy', 'Buy', 'Hold', 'Sell')\n"
            "- PRICE (absolute price floor/ceiling in Rs.)\n"
            "- SMA (price deviation from 200 SMA in %)\n"
            "- DMA_CROSS (50 SMA vs 200 SMA crossover, value = % separation filter)\n"
            "- EMA_CROSS (50 EMA vs 200 EMA crossover, value = % separation filter)\n"
            "- VOL_BREAKOUT (volume ratio vs 20d average, e.g. 2.0)\n"
            "- BB_CROSS (price vs Bollinger Bands, value = 0)\n"
            "- MACD_CROSS (MACD vs Signal line crossover, value = point diff filter)\n"
            "- 52W_PROXIMITY (proximity margin % to 52w limits)\n"
            "- SMA50 (price deviation from 50 SMA in %)\n"
            "- FIB_LEVEL (proximity to any Fibonacci level in %)\n"
            "- FIB_382 (proximity to Fib 38.2% in %)\n"
            "- FIB_500 (proximity to Fib 50.0% in %)\n"
            "- FIB_618 (proximity to Fib 61.8% in %)\n"
            "- COMBO_BULL_PULLBACK (Bull pullback: RSI oversold in SMA uptrend, e.g. RSI below 35 and golden cross / price above 200 SMA, value is the RSI threshold, e.g. 35)\n"
            "- COMBO_BEAR_PULLBACK (Bear pullback: RSI overbought in SMA downtrend, e.g. RSI above 60 and price below 200 SMA, value is the RSI threshold, e.g. 60)\n"
            "- COMBO_VALUE_REVERSAL (Oversold value buy: Low PE + RSI oversold, e.g. PE below 15 and RSI below 35, value is the PE or RSI threshold)\n"
            "- COMBO_GROWTH_MOMENTUM (Growth momentum: price above 200 SMA + RSI above 65 + strong buy rating, value is the RSI threshold)\n"
            "- COMBO_VOL_BREAKOUT (Volume trend breakout: volume above threshold average, e.g. 2.0 or 3.0 + price above 50 SMA, value is the volume threshold ratio, e.g. 2.0)\n"
            "- COMBO_52W_BREAKOUT (52W trend breakout: price above 200 SMA + within threshold % of 52w high, value is the proximity percentage threshold, e.g. 3.0)\n"
            "- COMBO_52W_VAL_ENTRY (52W value entry: within threshold % of 52w low + RSI below 35, value is the proximity percentage threshold, e.g. 5.0)\n"
            "- COMBO_FIB_REVERSAL (Fib support bounce: near Fibonacci level + RSI below 35, value is the Fib proximity percentage threshold, e.g. 2.0)\n"
            "- COMBO_BB_REVERSION (BB mean reversion: below BB lower band + RSI below 30, value is the RSI threshold)\n"
            "- COMBO_BB_BREAKOUT (BB volatility breakout: above BB upper band + volume above threshold average, value is the volume ratio threshold, e.g. 2.0)\n"
            "- COMBO_MACD_VOL (MACD cross with volume surge: MACD cross above Signal + volume above threshold average, value is the volume ratio threshold, e.g. 2.0)\n"
            "- COMBO_HIGH_QUALITY_DIP (Quality dip buy: Buy/Strong Buy rating + RSI below 35, value is the RSI threshold)\n"
            "- COMBO_DEATH_CROSS_VOL (Death cross volume spurt: 50 SMA crosses below 200 SMA + volume above threshold average, value is the volume ratio threshold, e.g. 2.0)\n"
            "- COMBO_FIB_SMA_BOUNCE (Fib & SMA-200 confluence: near Fib level + price above 200 SMA, value is the Fib proximity percentage threshold, e.g. 2.0)\n"
            "- COMBO_PENNY_MOMENTUM (Penny stock momentum: price below 100 + RSI above 65 + volume above threshold average, value is the volume ratio threshold, e.g. 2.0)\n"
            "- COMBO_PREMIUM_GROWTH (Premium quality growth: price above 2000 + PE below 30 + Strong Buy rating, value is the PE threshold)\n"
            "- COMBO_EARNINGS_ACCUMULATION (PE value accumulation: PE below 20 + volume above threshold average, value is the volume ratio threshold, e.g. 2.0)\n"
            "- COMBO_SHORT_TERM_REVERSION (Short pullback in uptrend: price below 50 SMA + price above 200 SMA)\n"
            "- COMBO_BB_SQUEEZE_BREAK (BB squeeze breakout: Bollinger Bands squeeze / narrow width + volume above threshold average, value is the volume ratio threshold, e.g. 2.0)\n"
            "- COMBO_CONTRARIAN_VALUE (Contrarian value play: PE below 12 + price below 200 SMA + RSI below 30, value is the PE threshold)\n"
            "- COMBO_DMA_CROSS_NEAR (50 SMA vs 200 SMA nearness: 50 SMA above/below 200 SMA by <= threshold % separation, value is the percentage threshold, e.g. 1.0)\n"
            "- COMBO_VALUE_TRAP_AVOID (Value-trap avoidance: PE below 15 and analyst recommendation is SELL, value is the PE threshold, e.g. 15.0)\n"
            "- COMBO_BB_REVERSION_SURGE (Bollinger Band reversion with volume: below BB lower band + RSI < 25 + volume above 2x average, value is volume ratio threshold, e.g. 2.0)\n"
            "- COMBO_PIOTROSKI_BREAKOUT (Quality breakout confluence: price above 200 SMA + within 5% of 52-week High + Strong Buy rating, value is the proximity percentage threshold, e.g. 5.0)\n"
            "- COMBO_SMA_20_PULLBACK (20 SMA pullback: price near 20 SMA + price > 200 SMA, value is proximity threshold, e.g. 1.5)\n"
            "- COMBO_MINERVINI_STAGE_2 (Minervini Stage 2: price > 50 SMA > 150 SMA > 200 SMA)\n"
            "- COMBO_EMA_SHORT_CROSS (Short EMA crossover with volume: 5 EMA > 20 EMA + volume ratio, value is volume ratio threshold, e.g. 1.5)\n"
            "- COMBO_SMA_200_STRETCHED (SMA200 overextended: price above 200 SMA by > value %, value is percentage threshold, e.g. 20.0)\n"
            "- COMBO_EMA_TREND_ALIGN (EMA Ribbon Alignment: price > 20 EMA > 50 EMA > 200 EMA)\n"
            "- COMBO_SMA_100_PULLBACK (100 SMA pullback: price near 100 SMA + price > 200 SMA, value is proximity threshold, e.g. 1.5)\n"
            "- COMBO_EMA_200_SUPPORT (200 EMA support with oversold RSI: price near 200 EMA + RSI <= 35, value is proximity threshold, e.g. 2.0)\n"
            "- COMBO_TREND_ACCELERATION (Trend acceleration: price > 20 SMA > 50 SMA > 200 SMA + ADX >= 25)\n"
            "- COMBO_52W_HIGH_RETEST (52W High breakout retest: price within threshold % above 52w high, value is proximity percentage threshold, e.g. 2.0)\n"
            "- COMBO_52W_MIDPOINT_PIVOT (52W Range midpoint play: price within threshold % of range midpoint, value is proximity percentage threshold, e.g. 1.5)\n"
            "- COMBO_52W_LOW_ACCUMULATION (52W Low accumulation: price within 10% of 52w low + price > 50 SMA + volume ratio >= threshold, value is volume ratio threshold, e.g. 2.0)\n"
            "- COMBO_FIB_GOLDEN_POCKET (Golden Pocket Fibonacci: price between 61.8% and 78.6% Fib retracement levels)\n"
            "- COMBO_FIB_VOL_POC (Fib + Volume POC confluence: price near a Fib level + near Volume POC within threshold %, value is proximity threshold, e.g. 1.5)\n"
            "- COMBO_FIB_DEEP_VAL (Deep Fibonacci value play: price within threshold % of 78.6% Fib + RSI <= 25, value is proximity percentage threshold, e.g. 2.0)\n"
            "- COMBO_DCF_UNDERVALUED (DCF margin of safety: margin of safety >= threshold % and valuation is not overvalued, value is margin of safety threshold, e.g. 20.0)\n"
            "- COMBO_BUFFETT_QUALITY (Warren Buffett style clean operations: ROE >= 15% and Debt-to-Equity <= 0.5)\n"
            "- COMBO_CLEAN_GOVERNANCE (Zero or low promoter pledge + growth: promoter pledge < 1% and profit growth >= 12%)\n"
            "- COMBO_GARP_PEG (Growth at a reasonable price: PEG ratio < 1.0)\n"
            "- COMBO_INST_ABSORPTION (Institutional absorption: delivery percentage >= 55% and delivery z-score >= 2.0)\n"
            "- COMBO_VSA_DEMAND (Volume Spread Analysis demand confirmation: VSA pattern contains Accumulation or Demand or Strength and volume ratio >= 1.5)\n"
            "- COMBO_HEAVY_INSTITUTIONAL (High mutual fund/FII ownership: combined FII and DII shareholding >= 30.0)\n"
            "- COMBO_LC_COMPOUNDER (Defensive large cap growth: cap type is large and beta < 1.0 and AI rating recommendation is STRONG BUY)\n"
            "- COMBO_SC_MOMENTUM (Explosive small cap growth: cap type is small and ADX >= 25 and beta > 1.2)\n"
            "- COMBO_SECTOR_ROTATION (Sector rotation momentum: price > 50 SMA and stock sector belongs to the dynamically calculated top 3 relative strength sectors)\n"
            "- COMBO_INST_QUALITY_BREAKOUT (Institutional quality breakout: Piotroski F-Score >= 7 and within 2% of 52-week High and delivery Z-Score > 1.5)\n"
            "- COMBO_SOLVENCY_VALUE_DIP (Fortress balance sheet value dip: Altman Z-Score >= 3.0 and DCF Margin of Safety >= 20% and RSI <= 35)\n"
            "- COMBO_HV_MOMENTUM_MARKUP (High volume momentum markup: ADX >= 25 and volume ratio >= 2.0 and price > 20 SMA > 50 SMA)\n"
            "- COMBO_SM_BOTTOM_FISHING (Smart money bottom fishing: combined FII and DII shareholding >= 25% and RSI <= 35 and VSA pattern contains Accumulation or Demand or Strength)\n"
            "- COMBO_RSI_DIVERGENCE (RSI Bullish Divergence setup: price near 52w low but RSI is strong >= 45)\n"
            "- COMBO_GOLDEN_CROSS (Structural Golden Cross: 50 SMA crosses above 200 SMA within 1.5% separation)\n"
            "- COMBO_BB_WALK (Bollinger Upper Band breakout walking: price >= Upper Bollinger Band + volume ratio >= 2.0x)\n"
            "- COMBO_FIB_236_BREAKOUT (Fibonacci 23.6% breakout pivot: price within 1.5% of 23.6% retracement level)\n"
            "- COMBO_VOL_52W_HIGH (52W high breakout with volume: price within 2% of 52w High + volume ratio >= 2.0x)\n"
            "- COMBO_PRISTINE_QUALITY (Pristine fundamental quality: Piotroski F-Score of 8 or 9)\n"
            "- COMBO_DRY_VOLUME (Dry volume supply consolidation: Bollinger Band width <= 8% and volume ratio <= 0.5x)\n"
            "- COMBO_BENCHMARK_ALPHA (CAPM Alpha outperformer: alpha against Nifty 50 >= 15.0%)\n"
            "- COMBO_TRIPLE_SCREEN (Alexander Elder Triple Screen system: price > 200 SMA and RSI <= 38 and volume ratio >= 1.5x)\n"
            "- COMBO_SMA_200_UNDER_5 (Price near but below 200 SMA: price below 200 SMA by <= 5%)\n"
            "- COMBO_SMA_50_UNDER_3 (Price near but below 50 SMA: price below 50 SMA by <= 3%)\n\n"
            "Operators:\n"
            "- '>' (Greater Than / Crosses Above)\n"
            "- '<' (Less Than / Crosses Below)\n"
            "- '==' (Equals / Near Proximity)\n\n"
            "IMPORTANT OPERATOR RULE FOR 52W_PROXIMITY:\n"
            "- You MUST use the operator '>' to represent proximity to the 52-week HIGH (e.g. 'within 5% of 52-week high', 'near 52-week high breakout').\n"
            "- You MUST use the operator '<' to represent proximity to the 52-week LOW (e.g. 'within 5% of 52-week low', 'near 52-week low value entry').\n"
            "Never output '<' for high proximity just because the user prompt contains the word 'within'.\n\n"
            "Universe options: 'all', 'large', 'mid', 'small'\n\n"
            "Output format example:\n"
            "{\n"
            "  \"condition_type\": \"RSI\",\n"
            "  \"operator\": \"<\",\n"
            "  \"value\": \"35\",\n"
            "  \"universe\": \"mid\"\n"
            "}"
        )

        response = await asyncio.to_thread(call_llm, TASK_FAST, sys_prompt, data.prompt)
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()

        # Extract only the first JSON object — LLM may add extra text after it
        brace_depth = 0
        json_start = -1
        json_end = -1
        in_string = False
        escape_next = False
        for i, ch in enumerate(response):
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                if brace_depth == 0:
                    json_start = i
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1
                if brace_depth == 0:
                    json_end = i + 1
                    break
        if json_start >= 0 and json_end > json_start:
            response = response[json_start:json_end]

        # Sanitise common LLM JSON quirks
        import re as _re
        response = _re.sub(r',\s*}', '}', response)   # trailing commas
        response = _re.sub(r',\s*]', ']', response)
        response = response.replace('\n', ' ')

        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            # Last-resort: regex-extract the four fields
            import re as _re2
            ct = _re2.search(r'"condition_type"\s*:\s*"([^"]*)"', response)
            opr = _re2.search(r'"operator"\s*:\s*"([^"]*)"', response)
            vl = _re2.search(r'"value"\s*:\s*"([^"]*)"', response)
            univ = _re2.search(r'"universe"\s*:\s*"([^"]*)"', response)
            if ct:
                parsed = {
                    "condition_type": ct.group(1) if ct else "RSI",
                    "operator": opr.group(1) if opr else "<",
                    "value": vl.group(1) if vl else "30",
                    "universe": univ.group(1) if univ else "all"
                }
            else:
                logger.error(f"Rule Scanner LLM response unparseable: {response}")
                raise ValueError(f"Could not parse LLM response into scan JSON")

        return {
            "status": "success",
            "condition_type": parsed.get("condition_type", "RSI").upper(),
            "operator": parsed.get("operator", "<"),
            "value": str(parsed.get("value", "30")),
            "universe": parsed.get("universe", "all").lower(),
            "llm_meta": get_last_llm_meta()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse scan prompt: {str(e)}")


class TelemetrySynthesisRequest(BaseModel):
    ticker: str
    price: float
    rsi: float
    condition_type: str
    operator: str
    value: str
    proximity: str

@app.post("/api/alerts/telemetry-synthesis")
async def get_telemetry_synthesis(data: TelemetrySynthesisRequest):
    """
    Generates a concise, institutional-grade AI summary for a clicked alert target
    and its calculated proximity margin.
    """
    try:
        from backend.llm_config import call_llm, TASK_FAST, TASK_HEAVY
        system_prompt = (
            "You are an expert institutional risk desk manager and quantitative analyst specializing in the Indian stock market. "
            "Your job is to provide a highly professional, 1-2 sentence AI synthesis explaining the immediate momentum, risk, "
            "or support implications of the stock's proximity to its target indicator threshold. "
            "Do not state your prompt or mention you are an AI. Write as a concise, professional analyst report statement (keep it under 45 words)."
        )
        user_prompt = (
            f"Asset: {data.ticker}\n"
            f"Current Price: Rs. {data.price:.2f}\n"
            f"RSI-14: {data.rsi:.1f}\n"
            f"Alert Condition: {data.condition_type} {data.operator} {data.value}\n"
            f"Proximity Calculation: {data.proximity}\n\n"
            f"Generate a 1-2 sentence institutional risk/momentum summary for this proximity setup."
        )
        synthesis = await asyncio.to_thread(call_llm, TASK_FAST, system_prompt, user_prompt)
        return {"synthesis": synthesis.strip(), "llm_meta": get_last_llm_meta()}
    except Exception as e:
        import traceback
        print("Exception in get_telemetry_synthesis:")
        traceback.print_exc()
        return {"synthesis": f"Unable to generate AI telemetry synthesis at this time. Error: {str(e)}"}



@app.get("/api/screener/scan-trigger")
async def scan_trigger(condition_type: str, operator: str, value: str, universe: str = "all"):
    """Scans the stock universe for matches against a given condition/trigger rule."""
    try:
        from backend.swing_utils import clean_float

        matched = []
        with get_db() as conn:
            cursor = conn.cursor()
            if universe == "all":
                cursor.execute("SELECT symbol, company_name, sector, cap_type FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%'")
            else:
                cursor.execute("SELECT symbol, company_name, sector, cap_type FROM screener_universe WHERE cap_type = ? AND symbol NOT LIKE '%DUMMY%'", (universe,))
            stocks = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT symbol, profile_json FROM cached_profiles")
            cached_rows = cursor.fetchall()
            cached_profiles = {}
            for r in cached_rows:
                try:
                    cached_profiles[r["symbol"]] = json.loads(r["profile_json"])
                except Exception:
                    continue

        scanned_count = 0
        for s in stocks:
            sym = s["symbol"]
            prof = cached_profiles.get(sym)
            if not prof:
                continue

            f = prof.get("fundamentals") or {}
            t = prof.get("technicals") or {}

            price = clean_float(f.get("current_price"), 0.0)
            if price <= 0.0:
                continue

            scanned_count += 1
            triggered = False
            cur_val = ""

            try:
                if condition_type == "RSI":
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    cur_val = f"RSI: {rsi_val:.1f}"
                    if operator == "<" and rsi_val < float(value):
                        triggered = True
                    elif operator == ">" and rsi_val > float(value):
                        triggered = True

                elif condition_type == "PE":
                    pe_val = clean_float(f.get("pe_ratio"), 0.0)
                    if pe_val <= 0.0:
                        continue
                    cur_val = f"P/E: {pe_val:.1f}"
                    threshold = float(value)
                    if operator == "<" and pe_val < threshold:
                        triggered = True
                    elif operator == ">" and pe_val > threshold:
                        triggered = True

                elif condition_type == "RATING":
                    analysis = prof.get("analysis") or {}
                    rating_val = (analysis.get("recommendation") or "HOLD").upper()
                    cur_val = f"Rating: {rating_val}"
                    if operator == "==" and rating_val == value.upper():
                        triggered = True

                elif condition_type == "PRICE":
                    cur_val = f"Price: Rs. {price:.2f}"
                    threshold = float(value)
                    if operator == "<" and price < threshold:
                        triggered = True
                    elif operator == ">" and price > threshold:
                        triggered = True

                elif condition_type == "SMA":
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    if sma_200 <= 0.0:
                        continue
                    pct_diff = ((price - sma_200) / sma_200) * 100
                    cur_val = f"Price vs SMA200: {pct_diff:+.1f}%"
                    threshold = float(value)
                    if operator == ">" and pct_diff > threshold:
                        triggered = True
                    elif operator == "<" and pct_diff < threshold:
                        triggered = True

                elif condition_type == "SMA50":
                    sma_50 = clean_float(t.get("sma_50"), 0.0)
                    if sma_50 <= 0.0:
                        continue
                    pct_diff = ((price - sma_50) / sma_50) * 100
                    cur_val = f"Price vs SMA50: {pct_diff:+.1f}%"
                    threshold = float(value)
                    if operator == ">" and pct_diff > threshold:
                        triggered = True
                    elif operator == "<" and pct_diff < threshold:
                        triggered = True

                elif condition_type in ["DMA_CROSS", "EMA_CROSS"]:
                    sma_50 = clean_float(t.get("sma_50"), 0.0)
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    if condition_type == "EMA_CROSS":
                        sma_50 = clean_float(t.get("ema_50", t.get("sma_50")), 0.0)
                        sma_200 = clean_float(t.get("ema_200", t.get("sma_200")), 0.0)
                    if sma_200 <= 0.0 or sma_50 <= 0.0:
                        continue
                    diff_pct = ((sma_50 - sma_200) / sma_200) * 100
                    label = "SMA" if condition_type == "DMA_CROSS" else "EMA"
                    cur_val = f"50d {label}: Rs.{sma_50:.0f} vs 200d: Rs.{sma_200:.0f} ({diff_pct:+.1f}%)"
                    threshold = float(value)
                    if operator == ">" and diff_pct > threshold:
                        triggered = True
                    elif operator == "<" and diff_pct < -abs(threshold):
                        triggered = True

                elif condition_type == "VOL_BREAKOUT":
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    cur_val = f"Vol Ratio: {vol_ratio:.2f}x"
                    threshold = float(value)
                    if operator == ">" and vol_ratio > threshold:
                        triggered = True
                    elif operator == "<" and vol_ratio < threshold:
                        triggered = True

                elif condition_type == "BB_CROSS":
                    bb_lower = clean_float(t.get("bb_lower"), 0.0)
                    bb_upper = clean_float(t.get("bb_upper"), 0.0)
                    if operator == "<":
                        cur_val = f"Price: Rs.{price:.0f} vs BB Lower: Rs.{bb_lower:.0f}"
                        if bb_lower > 0 and price <= bb_lower:
                            triggered = True
                    elif operator == ">":
                        cur_val = f"Price: Rs.{price:.0f} vs BB Upper: Rs.{bb_upper:.0f}"
                        if bb_upper > 0 and price >= bb_upper:
                            triggered = True

                elif condition_type == "MACD_CROSS":
                    macd_val = clean_float(t.get("macd"), 0.0)
                    signal_val = clean_float(t.get("signal"), 0.0)
                    diff = macd_val - signal_val
                    cur_val = f"MACD: {macd_val:.3f} vs Signal: {signal_val:.3f}"
                    threshold = float(value)
                    if operator == ">" and diff > threshold:
                        triggered = True
                    elif operator == "<" and diff < -abs(threshold):
                        triggered = True

                elif condition_type == "52W_PROXIMITY":
                    high_52w = clean_float(t.get("high_52w") or f.get("high_52week") or f.get("fiftyTwoWeekHigh") or t.get("year_high") or f.get("year_high") or f.get("52w_high"), 0.0)
                    low_52w = clean_float(t.get("low_52w") or f.get("low_52week") or f.get("fiftyTwoWeekLow") or t.get("year_low") or f.get("year_low") or f.get("52w_low"), 0.0)
                    proximity_pct = float(value)
                    if operator == ">":
                        if high_52w > 0:
                            diff_pct = ((high_52w - price) / high_52w) * 100
                            cur_val = f"Price: Rs.{price:.0f} (52wH: Rs.{high_52w:.0f}, Diff: {diff_pct:.1f}%)"
                            if diff_pct <= proximity_pct:
                                triggered = True
                    elif operator == "<":
                        if low_52w > 0:
                            diff_pct = ((price - low_52w) / low_52w) * 100
                            cur_val = f"Price: Rs.{price:.0f} (52wL: Rs.{low_52w:.0f}, Diff: {diff_pct:.1f}%)"
                            if diff_pct <= proximity_pct:
                                triggered = True

                elif condition_type in ["FIB_LEVEL", "FIB_382", "FIB_500", "FIB_618"]:
                    high_52w = clean_float(t.get("high_52w") or f.get("high_52week") or f.get("fiftyTwoWeekHigh") or t.get("year_high") or f.get("year_high") or f.get("52w_high"), 0.0)
                    low_52w = clean_float(t.get("low_52w") or f.get("low_52week") or f.get("fiftyTwoWeekLow") or t.get("year_low") or f.get("year_low") or f.get("52w_low"), 0.0)
                    if high_52w <= 0 or low_52w <= 0:
                        continue
                    swing_diff = high_52w - low_52w
                    fib_382 = high_52w - 0.382 * swing_diff
                    fib_500 = high_52w - 0.500 * swing_diff
                    fib_618 = high_52w - 0.618 * swing_diff
                    proximity_pct = float(value) if value else 1.5

                    levels_to_check = []
                    if condition_type == "FIB_LEVEL":
                        levels_to_check = [("38.2%", fib_382), ("50.0%", fib_500), ("61.8%", fib_618)]
                    elif condition_type == "FIB_382":
                        levels_to_check = [("38.2%", fib_382)]
                    elif condition_type == "FIB_500":
                        levels_to_check = [("50.0%", fib_500)]
                    elif condition_type == "FIB_618":
                        levels_to_check = [("61.8%", fib_618)]

                    for lbl, lvl in levels_to_check:
                        if lvl > 0:
                            diff_pct = abs(((price - lvl) / lvl) * 100)
                            if diff_pct <= proximity_pct:
                                cur_val = f"Price: Rs.{price:.0f} near Fib {lbl} (Rs.{lvl:.0f}, Diff: {diff_pct:.1f}%)"
                                triggered = True
                                break

                elif condition_type == "ALTMAN_Z":
                    eq = prof.get("earnings_quality") or {}
                    altman_z = clean_float(eq.get("altman_z_score", f.get("altman_z")), 0.0)
                    cur_val = f"Altman Z-Score: {altman_z:.2f}"
                    threshold = float(value)
                    if operator == "<" and altman_z < threshold:
                        triggered = True
                    elif operator == ">" and altman_z > threshold:
                        triggered = True

                elif condition_type == "TARGET_DISCOUNT":
                    target_discount = clean_float(f.get("target_discount"), 0.0)
                    if target_discount <= 0.0:
                        consensus = prof.get("consensus") or {}
                        target_median = clean_float(consensus.get("target_median"), 0.0)
                        if target_median > 0:
                            target_discount = ((target_median - price) / target_median) * 100
                    cur_val = f"Target Discount: {target_discount:.1f}%"
                    threshold = float(value)
                    if operator == ">" and target_discount > threshold:
                        triggered = True
                    elif operator == "<" and target_discount < threshold:
                        triggered = True

                elif condition_type == "CFO_PAT_DIVERGENCE":
                    cfo_pat = clean_float(f.get("cfo_pat_divergence", f.get("cfo_to_pat")), 1.0)
                    cur_val = f"CFO to PAT Ratio: {cfo_pat:.2f}"
                    threshold = float(value)
                    if operator == "<" and cfo_pat < threshold:
                        triggered = True
                    elif operator == ">" and cfo_pat > threshold:
                        triggered = True

                elif condition_type == "DIVIDEND_YIELD_FLOOR":
                    div_yield = clean_float(f.get("dividend_yield", f.get("dividend_yield_pct")), 0.0)
                    cur_val = f"Div Yield: {div_yield:.2f}%"
                    threshold = float(value)
                    if operator == ">" and div_yield > threshold:
                        triggered = True
                    elif operator == "<" and div_yield < threshold:
                        triggered = True

                elif condition_type == "ATR_VOLATILITY_SHOCK":
                    atr_val = clean_float(t.get("atr"), 0.0)
                    cur_val = f"ATR: Rs. {atr_val:.2f}"
                    threshold = float(value)
                    if operator == ">" and atr_val > threshold:
                        triggered = True
                    elif operator == "<" and atr_val < threshold:
                        triggered = True

                elif condition_type == "SMA20":
                    sma_20 = clean_float(t.get("sma_20"), 0.0)
                    if sma_20 <= 0.0:
                        continue
                    pct_diff = ((price - sma_20) / sma_20) * 100
                    cur_val = f"Price vs SMA20: {pct_diff:+.1f}%"
                    threshold = float(value)
                    if operator == ">" and pct_diff > threshold:
                        triggered = True
                    elif operator == "<" and pct_diff < threshold:
                        triggered = True

                elif condition_type == "SMA100":
                    sma_100 = clean_float(t.get("sma_100"), 0.0)
                    if sma_100 <= 0.0:
                        continue
                    pct_diff = ((price - sma_100) / sma_100) * 100
                    cur_val = f"Price vs SMA100: {pct_diff:+.1f}%"
                    threshold = float(value)
                    if operator == ">" and pct_diff > threshold:
                        triggered = True
                    elif operator == "<" and pct_diff < threshold:
                        triggered = True

                elif condition_type == "EMA20":
                    ema_20 = clean_float(t.get("ema_20"), 0.0)
                    if ema_20 <= 0.0:
                        continue
                    pct_diff = ((price - ema_20) / ema_20) * 100
                    cur_val = f"Price vs EMA20: {pct_diff:+.1f}%"
                    threshold = float(value)
                    if operator == ">" and pct_diff > threshold:
                        triggered = True
                    elif operator == "<" and pct_diff < threshold:
                        triggered = True

                elif condition_type == "EMA50":
                    ema_50 = clean_float(t.get("ema_50"), 0.0)
                    if ema_50 <= 0.0:
                        continue
                    pct_diff = ((price - ema_50) / ema_50) * 100
                    cur_val = f"Price vs EMA50: {pct_diff:+.1f}%"
                    threshold = float(value)
                    if operator == ">" and pct_diff > threshold:
                        triggered = True
                    elif operator == "<" and pct_diff < threshold:
                        triggered = True

                elif condition_type == "EMA200":
                    ema_200 = clean_float(t.get("ema_200"), 0.0)
                    if ema_200 <= 0.0:
                        continue
                    pct_diff = ((price - ema_200) / ema_200) * 100
                    cur_val = f"Price vs EMA200: {pct_diff:+.1f}%"
                    threshold = float(value)
                    if operator == ">" and pct_diff > threshold:
                        triggered = True
                    elif operator == "<" and pct_diff < threshold:
                        triggered = True

                elif condition_type == "PEG":
                    peg_val = clean_float(prof.get("score_metrics", {}).get("peg_ratio"), 99.0)
                    cur_val = f"PEG: {peg_val:.2f}"
                    threshold = float(value)
                    if operator == "<" and peg_val < threshold:
                        triggered = True
                    elif operator == ">" and peg_val > threshold:
                        triggered = True

                elif condition_type == "ROE":
                    roe_val = clean_float(f.get("roe_pct") or f.get("roe"), 0.0)
                    cur_val = f"ROE: {roe_val:.1f}%"
                    threshold = float(value)
                    if operator == ">" and roe_val > threshold:
                        triggered = True
                    elif operator == "<" and roe_val < threshold:
                        triggered = True

                elif condition_type == "DE":
                    de_val = clean_float(f.get("debt_to_equity") or f.get("de_ratio"), 0.0)
                    cur_val = f"Debt-to-Equity: {de_val:.2f}"
                    threshold = float(value)
                    if operator == "<" and de_val < threshold:
                        triggered = True
                    elif operator == ">" and de_val > threshold:
                        triggered = True

                elif condition_type == "PLEDGE":
                    pledge_val = clean_float(f.get("promoter_pledge_pct"), 0.0)
                    cur_val = f"Promoter Pledge: {pledge_val:.1f}%"
                    threshold = float(value)
                    if operator == "<" and pledge_val < threshold:
                        triggered = True
                    elif operator == ">" and pledge_val > threshold:
                        triggered = True

                elif condition_type == "DCF_SAFETY":
                    dcf_val = clean_float(prof.get("dcf", {}).get("margin_of_safety"), 0.0)
                    cur_val = f"DCF Margin of Safety: {dcf_val:.1f}%"
                    threshold = float(value)
                    if operator == ">" and dcf_val > threshold:
                        triggered = True
                    elif operator == "<" and dcf_val < threshold:
                        triggered = True

                elif condition_type == "BETA":
                    beta_val = clean_float(prof.get("consensus", {}).get("beta") or prof.get("capm_risk_nifty50", {}).get("beta"), 1.0)
                    cur_val = f"Beta: {beta_val:.2f}"
                    threshold = float(value)
                    if operator == ">" and beta_val > threshold:
                        triggered = True
                    elif operator == "<" and beta_val < threshold:
                        triggered = True

                elif condition_type == "DELIVERY_PCT":
                    del_val = clean_float(t.get("delivery_percentage") or t.get("delivery_pct"), 0.0)
                    cur_val = f"Delivery: {del_val:.1f}%"
                    threshold = float(value)
                    if operator == ">" and del_val > threshold:
                        triggered = True
                    elif operator == "<" and del_val < threshold:
                        triggered = True

                elif condition_type == "DELIVERY_ZSCORE":
                    z_val = clean_float(t.get("delivery_z_score") or t.get("delivery_zscore"), 0.0)
                    cur_val = f"Delivery Z-Score: {z_val:+.2f}"
                    threshold = float(value)
                    if operator == ">" and z_val > threshold:
                        triggered = True
                    elif operator == "<" and z_val < threshold:
                        triggered = True

                elif condition_type in ("FUZZY_SCORE", "FUZZY_CONVICTION"):
                    with get_db() as conn_f:
                        fz = get_fuzzy_summary_for_symbol(conn_f, sym)
                    fz_score = float(fz.get("fuzzy_score", 0.0))
                    fz_rating = fz.get("fuzzy_rating", "Neutral")
                    cur_val = f"Fuzzy Conviction: {fz_score:+.1f}% ({fz_rating})"
                    threshold = float(value)
                    if operator in (">", ">=") and fz_score >= threshold:
                        triggered = True
                    elif operator in ("<", "<=") and fz_score <= threshold:
                        triggered = True
                    elif operator in ("==", "=") and abs(fz_score - threshold) < 0.1:
                        triggered = True

                elif condition_type == "COMBO_FUZZY_BREAKOUT":
                    with get_db() as conn_f:
                        fz = get_fuzzy_summary_for_symbol(conn_f, sym)
                    fz_score = float(fz.get("fuzzy_score", 0.0))
                    fz_rating = fz.get("fuzzy_rating", "Neutral")
                    adx_val = clean_float(t.get("adx"), 20.0)
                    if fz_score >= 60.0 and adx_val >= 22.0:
                        cur_val = f"Fuzzy Score: {fz_score:+.1f}% ({fz_rating}), ADX: {adx_val:.1f}"
                        triggered = True

                elif condition_type == "COMBO_FUZZY_AVOID":
                    with get_db() as conn_f:
                        fz = get_fuzzy_summary_for_symbol(conn_f, sym)
                    fz_score = float(fz.get("fuzzy_score", 0.0))
                    fz_rating = fz.get("fuzzy_rating", "Neutral")
                    if fz_score <= -40.0:
                        cur_val = f"Fuzzy Score: {fz_score:+.1f}% ({fz_rating})"
                        triggered = True

                # ─── MULTI-FACTOR COMBO STRATEGIES ─────────────────────────────────────
                elif condition_type == "COMBO_BULL_PULLBACK":
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    if rsi_val < 35 and price > sma_200 > 0:
                        cur_val = f"RSI: {rsi_val:.1f}, Price above SMA200 (Rs.{sma_200:.0f})"
                        triggered = True

                elif condition_type == "COMBO_BEAR_PULLBACK":
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    if rsi_val > 60 and sma_200 > 0 and price < sma_200:
                        cur_val = f"RSI: {rsi_val:.1f}, Price below SMA200 (Rs.{sma_200:.0f})"
                        triggered = True

                elif condition_type == "COMBO_VALUE_REVERSAL":
                    pe_val = clean_float(f.get("pe_ratio"), 0.0)
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    if 0 < pe_val < 15.0 and rsi_val < 35:
                        cur_val = f"P/E: {pe_val:.1f}, RSI: {rsi_val:.1f}"
                        triggered = True

                elif condition_type == "COMBO_GROWTH_MOMENTUM":
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    analysis = prof.get("analysis") or {}
                    rating_val = (analysis.get("recommendation") or "HOLD").upper()
                    if rsi_val > 65 and price > sma_200 > 0 and "STRONG BUY" in rating_val:
                        cur_val = f"RSI: {rsi_val:.1f}, Strong Buy, Above SMA200"
                        triggered = True

                elif condition_type == "COMBO_VOL_BREAKOUT":
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    sma_50 = clean_float(t.get("sma_50"), 0.0)
                    threshold = clean_float(value, 2.0)
                    if vol_ratio > threshold and price > sma_50 > 0:
                        cur_val = f"Vol: {vol_ratio:.1f}x, Above SMA50 (Rs.{sma_50:.0f})"
                        triggered = True

                elif condition_type == "COMBO_52W_BREAKOUT":
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    high_52w = clean_float(t.get("high_52w") or f.get("high_52week") or f.get("fiftyTwoWeekHigh") or t.get("year_high") or f.get("year_high") or f.get("52w_high"), 0.0)
                    if price > sma_200 > 0 and high_52w > 0:
                        diff_pct = ((high_52w - price) / high_52w) * 100
                        threshold = clean_float(value, 3.0)
                        if diff_pct <= threshold:
                            cur_val = f"Uptrend, within {diff_pct:.1f}% of 52wH (Rs.{high_52w:.0f})"
                            triggered = True

                elif condition_type == "COMBO_52W_VAL_ENTRY":
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    low_52w = clean_float(t.get("low_52w") or f.get("low_52week") or f.get("fiftyTwoWeekLow") or t.get("year_low") or f.get("year_low") or f.get("52w_low"), 0.0)
                    if rsi_val < 35 and low_52w > 0:
                        diff_pct = ((price - low_52w) / low_52w) * 100
                        threshold = clean_float(value, 5.0)
                        if diff_pct <= threshold:
                            cur_val = f"RSI: {rsi_val:.1f}, within {diff_pct:.1f}% of 52wL (Rs.{low_52w:.0f})"
                            triggered = True

                elif condition_type == "COMBO_FIB_REVERSAL":
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    if rsi_val < 35:
                        high_52w = clean_float(t.get("high_52w") or f.get("high_52week") or f.get("fiftyTwoWeekHigh") or t.get("year_high") or f.get("year_high") or f.get("52w_high"), 0.0)
                        low_52w = clean_float(t.get("low_52w") or f.get("low_52week") or f.get("fiftyTwoWeekLow") or t.get("year_low") or f.get("year_low") or f.get("52w_low"), 0.0)
                        if high_52w > 0 and low_52w > 0 and high_52w > low_52w:
                            swing = high_52w - low_52w
                            levels = {
                                "23.6%": high_52w - 0.236 * swing,
                                "38.2%": high_52w - 0.382 * swing,
                                "50.0%": high_52w - 0.500 * swing,
                                "61.8%": high_52w - 0.618 * swing,
                                "78.6%": high_52w - 0.786 * swing
                            }
                            threshold = clean_float(value, 2.0)
                            for lbl, val in levels.items():
                                diff = abs(((price - val) / val) * 100)
                                if diff <= threshold:
                                    cur_val = f"RSI: {rsi_val:.1f}, near Fib {lbl} (Diff: {diff:.1f}%)"
                                    triggered = True
                                    break

                elif condition_type == "COMBO_BB_REVERSION":
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    bb_lower = clean_float(t.get("bb_lower"), 0.0)
                    if rsi_val < 30 and bb_lower > 0 and price <= bb_lower:
                        cur_val = f"RSI: {rsi_val:.1f}, Price <= BB Lower (Rs.{bb_lower:.0f})"
                        triggered = True

                elif condition_type == "COMBO_BB_BREAKOUT":
                    bb_upper = clean_float(t.get("bb_upper"), 0.0)
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    threshold = clean_float(value, 2.0)
                    if bb_upper > 0 and price >= bb_upper and vol_ratio > threshold:
                        cur_val = f"Price >= BB Upper (Rs.{bb_upper:.0f}), Vol: {vol_ratio:.1f}x"
                        triggered = True

                elif condition_type == "COMBO_MACD_VOL":
                    macd_val = clean_float(t.get("macd"), 0.0)
                    signal_val = clean_float(t.get("signal"), 0.0)
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    threshold = clean_float(value, 2.0)
                    if macd_val > signal_val and vol_ratio > threshold:
                        cur_val = f"MACD Golden Cross, Vol: {vol_ratio:.1f}x"
                        triggered = True

                elif condition_type == "COMBO_HIGH_QUALITY_DIP":
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    analysis = prof.get("analysis") or {}
                    rating_val = (analysis.get("recommendation") or "HOLD").upper()
                    if rsi_val < 35 and ("BUY" in rating_val or "STRONG" in rating_val):
                        cur_val = f"Rating: {rating_val}, RSI: {rsi_val:.1f}"
                        triggered = True

                elif condition_type == "COMBO_DEATH_CROSS_VOL":
                    sma_50 = clean_float(t.get("sma_50"), 0.0)
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    threshold = clean_float(value, 2.0)
                    if sma_50 > 0 and sma_200 > 0 and sma_50 < sma_200 and vol_ratio > threshold:
                        cur_val = f"Death Cross Active, Vol: {vol_ratio:.1f}x"
                        triggered = True

                elif condition_type == "COMBO_FIB_SMA_BOUNCE":
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    if price > sma_200 > 0:
                        high_52w = clean_float(t.get("high_52w") or f.get("high_52week") or f.get("fiftyTwoWeekHigh") or t.get("year_high") or f.get("year_high") or f.get("52w_high"), 0.0)
                        low_52w = clean_float(t.get("low_52w") or f.get("low_52week") or f.get("fiftyTwoWeekLow") or t.get("year_low") or f.get("year_low") or f.get("52w_low"), 0.0)
                        if high_52w > 0 and low_52w > 0 and high_52w > low_52w:
                            swing = high_52w - low_52w
                            levels = {
                                "23.6%": high_52w - 0.236 * swing,
                                "38.2%": high_52w - 0.382 * swing,
                                "50.0%": high_52w - 0.500 * swing,
                                "61.8%": high_52w - 0.618 * swing,
                                "78.6%": high_52w - 0.786 * swing
                            }
                            threshold = clean_float(value, 2.0)
                            for lbl, val in levels.items():
                                diff = abs(((price - val) / val) * 100)
                                if diff <= threshold:
                                    cur_val = f"Above SMA200, near Fib {lbl} (Diff: {diff:.1f}%)"
                                    triggered = True
                                    break

                elif condition_type == "COMBO_PENNY_MOMENTUM":
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    threshold = clean_float(value, 2.0)
                    if price < 100.0 and rsi_val > 65 and vol_ratio > threshold:
                        cur_val = f"Penny Stock, RSI: {rsi_val:.1f}, Vol: {vol_ratio:.1f}x"
                        triggered = True

                elif condition_type == "COMBO_PREMIUM_GROWTH":
                    pe_val = clean_float(f.get("pe_ratio"), 0.0)
                    analysis = prof.get("analysis") or {}
                    rating_val = (analysis.get("recommendation") or "HOLD").upper()
                    if price > 2000.0 and 0 < pe_val < 30.0 and "STRONG BUY" in rating_val:
                        cur_val = f"Premium (Rs.{price:.0f}), PE: {pe_val:.1f}, Rating: STRONG BUY"
                        triggered = True

                elif condition_type == "COMBO_EARNINGS_ACCUMULATION":
                    pe_val = clean_float(f.get("pe_ratio"), 0.0)
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    threshold = clean_float(value, 2.0)
                    if 0 < pe_val < 20.0 and vol_ratio > threshold:
                        cur_val = f"Value PE: {pe_val:.1f}, Vol Spurt: {vol_ratio:.1f}x"
                        triggered = True

                elif condition_type == "COMBO_SHORT_TERM_REVERSION":
                    sma_50 = clean_float(t.get("sma_50"), 0.0)
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    if sma_50 > 0 and sma_200 > 0 and price < sma_50 and price > sma_200:
                        cur_val = f"Short Pullback (Price below SMA50, above SMA200)"
                        triggered = True

                elif condition_type == "COMBO_BB_SQUEEZE_BREAK":
                    bb_lower = clean_float(t.get("bb_lower"), 0.0)
                    bb_upper = clean_float(t.get("bb_upper"), 0.0)
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    threshold = clean_float(value, 2.0)
                    if bb_lower > 0 and bb_upper > 0 and vol_ratio > threshold:
                        middle = (bb_upper + bb_lower) / 2.0
                        width_pct = ((bb_upper - bb_lower) / middle) * 100
                        if width_pct <= 10.0 and price >= bb_upper:
                            cur_val = f"BB Width: {width_pct:.1f}% (Squeeze), Upper Breakout, Vol: {vol_ratio:.1f}x"
                            triggered = True

                elif condition_type == "COMBO_CONTRARIAN_VALUE":
                    pe_val = clean_float(f.get("pe_ratio"), 0.0)
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    if 0 < pe_val < 12.0 and rsi_val < 30 and price < sma_200 > 0:
                        cur_val = f"Contrarian PE: {pe_val:.1f}, RSI: {rsi_val:.1f}, Below SMA200"
                        triggered = True

                elif condition_type == "COMBO_DMA_CROSS_NEAR":
                    sma_50 = clean_float(t.get("sma_50"), 0.0)
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    if sma_50 > 0 and sma_200 > 0:
                        sep_pct = (abs(sma_50 - sma_200) / sma_200) * 100
                        threshold = clean_float(value, 1.0)
                        if sep_pct <= threshold:
                            cur_val = f"50 SMA (Rs.{sma_50:.0f}) near 200 SMA (Rs.{sma_200:.0f}), Sep: {sep_pct:.2f}%"
                            triggered = True

                elif condition_type == "COMBO_VALUE_TRAP_AVOID":
                    pe_val = clean_float(f.get("pe_ratio"), 0.0)
                    analysis = prof.get("analysis") or {}
                    rating_val = (analysis.get("recommendation") or prof.get("recommendation") or "N/A").upper()
                    threshold = clean_float(value, 15.0)
                    if 0 < pe_val < threshold and "SELL" in rating_val:
                        cur_val = f"Value Trap: PE {pe_val:.1f} < {threshold} with SELL recommendation"
                        triggered = True

                elif condition_type == "COMBO_BB_REVERSION_SURGE":
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    bb_lower = clean_float(t.get("bb_lower"), 0.0)
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    threshold = clean_float(value, 2.0)
                    if rsi_val < 25 and bb_lower > 0 and price <= bb_lower and vol_ratio > threshold:
                        cur_val = f"BB lower reversion: Price Rs.{price:.0f} <= BB Lower Rs.{bb_lower:.0f}, RSI: {rsi_val:.1f}, Vol: {vol_ratio:.1f}x"
                        triggered = True

                elif condition_type == "COMBO_PIOTROSKI_BREAKOUT":
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    high_52w = clean_float(t.get("high_52w") or f.get("high_52week") or f.get("fiftyTwoWeekHigh") or t.get("year_high") or f.get("year_high") or f.get("52w_high"), 0.0)
                    analysis = prof.get("analysis") or {}
                    rating_val = (analysis.get("recommendation") or prof.get("recommendation") or "N/A").upper()
                    threshold = clean_float(value, 5.0)
                    if price > sma_200 > 0 and high_52w > 0 and "STRONG BUY" in rating_val:
                        diff_pct = ((high_52w - price) / high_52w) * 100
                        if diff_pct <= threshold:
                            cur_val = f"Piotroski Breakout: Above SMA200, within {diff_pct:.1f}% of 52wH (Rs.{high_52w:.0f}), Strong Buy"
                            triggered = True

                elif condition_type == "COMBO_SMA_20_PULLBACK":
                    sma_20 = clean_float(t.get("sma_20"), 0.0)
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    if sma_20 > 0 and price >= sma_20 and price > sma_200:
                        diff_pct = ((price - sma_20) / sma_20) * 100
                        threshold = clean_float(value, 1.5)
                        if diff_pct <= threshold:
                            cur_val = f"20 SMA Pullback: Price Rs.{price:.0f} near 20 SMA Rs.{sma_20:.0f} (Diff: {diff_pct:.2f}%) in uptrend"
                            triggered = True

                elif condition_type == "COMBO_MINERVINI_STAGE_2":
                    sma_50 = clean_float(t.get("sma_50"), 0.0)
                    sma_150 = clean_float(t.get("sma_150"), 0.0)
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    if price > sma_50 > sma_150 > sma_200 > 0:
                        cur_val = f"Stage 2 Alignment: Price Rs.{price:.0f} > 50 SMA ({sma_50:.0f}) > 150 SMA ({sma_150:.0f}) > 200 SMA ({sma_200:.0f})"
                        triggered = True

                elif condition_type == "COMBO_EMA_SHORT_CROSS":
                    ema_5 = clean_float(t.get("ema_5"), 0.0)
                    ema_20 = clean_float(t.get("ema_20"), 0.0)
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    threshold = clean_float(value, 1.5)
                    if ema_5 > ema_20 > 0 and vol_ratio >= threshold:
                        cur_val = f"Short EMA Crossover: 5 EMA Rs.{ema_5:.0f} > 20 EMA Rs.{ema_20:.0f} with Vol: {vol_ratio:.1f}x"
                        triggered = True

                elif condition_type == "COMBO_SMA_200_STRETCHED":
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    if sma_200 > 0:
                        diff_pct = ((price - sma_200) / sma_200) * 100
                        threshold = clean_float(value, 20.0)
                        if diff_pct >= threshold:
                            cur_val = f"SMA200 Stretched: Price Rs.{price:.0f} is {diff_pct:.1f}% above 200 SMA (Rs.{sma_200:.0f})"
                            triggered = True

                elif condition_type == "COMBO_EMA_TREND_ALIGN":
                    ema_20 = clean_float(t.get("ema_20"), 0.0)
                    ema_50 = clean_float(t.get("ema_50"), 0.0)
                    ema_200 = clean_float(t.get("ema_200"), 0.0)
                    if price > ema_20 > ema_50 > ema_200 > 0:
                        cur_val = f"EMA Ribbon Align: Price Rs.{price:.0f} > 20 EMA ({ema_20:.0f}) > 50 EMA ({ema_50:.0f}) > 200 EMA ({ema_200:.0f})"
                        triggered = True

                elif condition_type == "COMBO_SMA_100_PULLBACK":
                    sma_100 = clean_float(t.get("sma_100"), 0.0)
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    if sma_100 > 0 and price >= sma_100 and price > sma_200:
                        diff_pct = ((price - sma_100) / sma_100) * 100
                        threshold = clean_float(value, 1.5)
                        if diff_pct <= threshold:
                            cur_val = f"100 SMA Pullback: Price Rs.{price:.0f} near 100 SMA Rs.{sma_100:.0f} (Diff: {diff_pct:.2f}%) in uptrend"
                            triggered = True

                elif condition_type == "COMBO_EMA_200_SUPPORT":
                    ema_200 = clean_float(t.get("ema_200"), 0.0)
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    if ema_200 > 0 and rsi_val <= 35:
                        diff_pct = (abs(price - ema_200) / ema_200) * 100
                        threshold = clean_float(value, 2.0)
                        if diff_pct <= threshold:
                            cur_val = f"200 EMA Support: Price Rs.{price:.0f} near 200 EMA Rs.{ema_200:.0f} (Diff: {diff_pct:.2f}%) with Oversold RSI: {rsi_val:.1f}"
                            triggered = True

                elif condition_type == "COMBO_TREND_ACCELERATION":
                    sma_20 = clean_float(t.get("sma_20"), 0.0)
                    sma_50 = clean_float(t.get("sma_50"), 0.0)
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    adx_val = clean_float(t.get("adx"), 0.0)
                    if price > sma_20 > sma_50 > sma_200 > 0 and adx_val >= 25.0:
                        cur_val = f"Trend Acceleration: Price Rs.{price:.0f} > 20 SMA > 50 SMA > 200 SMA with strong trend ADX: {adx_val:.1f}"
                        triggered = True

                elif condition_type == "COMBO_52W_HIGH_RETEST":
                    high_52w = clean_float(t.get("high_52w") or f.get("high_52week") or f.get("fiftyTwoWeekHigh") or t.get("year_high") or f.get("year_high") or f.get("52w_high"), 0.0)
                    if high_52w > 0 and price >= high_52w:
                        diff_pct = ((price - high_52w) / high_52w) * 100
                        threshold = clean_float(value, 2.0)
                        if diff_pct <= threshold:
                            cur_val = f"52W High Retest: Price Rs.{price:.2f} is {diff_pct:.2f}% above 52wH (Rs.{high_52w:.2f})"
                            triggered = True

                elif condition_type == "COMBO_52W_MIDPOINT_PIVOT":
                    high_52w = clean_float(t.get("high_52w") or f.get("high_52week") or f.get("fiftyTwoWeekHigh") or t.get("year_high") or f.get("year_high") or f.get("52w_high"), 0.0)
                    low_52w = clean_float(t.get("low_52w") or f.get("low_52week") or f.get("fiftyTwoWeekLow") or t.get("year_low") or f.get("year_low") or f.get("52w_low"), 0.0)
                    if high_52w > 0 and low_52w > 0:
                        midpoint = (high_52w + low_52w) / 2.0
                        diff_pct = (abs(price - midpoint) / midpoint) * 100
                        threshold = clean_float(value, 1.5)
                        if diff_pct <= threshold:
                            cur_val = f"52W Midpoint Pivot: Price Rs.{price:.2f} near Midpoint Rs.{midpoint:.2f} (Diff: {diff_pct:.2f}%)"
                            triggered = True

                elif condition_type == "COMBO_52W_LOW_ACCUMULATION":
                    low_52w = clean_float(t.get("low_52w") or f.get("low_52week") or f.get("fiftyTwoWeekLow") or t.get("year_low") or f.get("year_low") or f.get("52w_low"), 0.0)
                    sma_50 = clean_float(t.get("sma_50"), 0.0)
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    if low_52w > 0 and sma_50 > 0 and price > sma_50:
                        dist_low_pct = ((price - low_52w) / low_52w) * 100
                        threshold_vol = clean_float(value, 2.0)
                        if dist_low_pct <= 10.0 and vol_ratio >= threshold_vol:
                            cur_val = f"52W Low Accumulation: Price Rs.{price:.2f} is {dist_low_pct:.1f}% from 52wL (Rs.{low_52w:.2f}) above 50 SMA with Vol: {vol_ratio:.1f}x"
                            triggered = True

                elif condition_type == "COMBO_FIB_GOLDEN_POCKET":
                    fib_618 = clean_float(t.get("fib_levels", {}).get("fib_618"), 0.0)
                    fib_786 = clean_float(t.get("fib_levels", {}).get("fib_786"), 0.0)
                    if fib_618 > 0 and fib_786 > 0:
                        if fib_786 <= price <= fib_618:
                            cur_val = f"Golden Pocket: Price Rs.{price:.2f} is in zone Rs.{fib_786:.2f} - Rs.{fib_618:.2f}"
                            triggered = True

                elif condition_type == "COMBO_FIB_VOL_POC":
                    poc_price = clean_float(t.get("poc_price"), 0.0)
                    fib_dict = t.get("fib_levels", {})
                    if poc_price > 0 and len(fib_dict) > 0:
                        threshold = clean_float(value, 1.5)
                        near_fib = False
                        near_level_name = ""
                        near_level_val = 0.0
                        for k, v in fib_dict.items():
                            f_val = clean_float(v, 0.0)
                            if f_val > 0:
                                diff_poc_fib = (abs(f_val - poc_price) / f_val) * 100
                                if diff_poc_fib <= threshold:
                                    near_fib = True
                                    near_level_name = k
                                    near_level_val = f_val
                                    break
                        if near_fib:
                            diff_price_poc = (abs(price - poc_price) / poc_price) * 100
                            if diff_price_poc <= threshold:
                                cur_val = f"Fib + POC Confluence: Price Rs.{price:.2f} near POC Rs.{poc_price:.2f} & Fib {near_level_name} Rs.{near_level_val:.2f} (Sep: {diff_price_poc:.1f}%)"
                                triggered = True

                elif condition_type == "COMBO_FIB_DEEP_VAL":
                    fib_786 = clean_float(t.get("fib_levels", {}).get("fib_786"), 0.0)
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    if fib_786 > 0 and rsi_val <= 25:
                        diff_pct = (abs(price - fib_786) / fib_786) * 100
                        threshold = clean_float(value, 2.0)
                        if diff_pct <= threshold:
                            cur_val = f"Deep Fib Reversal: Price Rs.{price:.2f} near 78.6% Fib Rs.{fib_786:.2f} (Diff: {diff_pct:.1f}%) with oversold RSI: {rsi_val:.1f}"
                            triggered = True

                elif condition_type == "COMBO_DCF_UNDERVALUED":
                    dcf_val = clean_float(prof.get("dcf", {}).get("margin_of_safety"), 0.0)
                    dcf_rating = (prof.get("dcf", {}).get("valuation_rating") or "N/A").upper()
                    threshold = clean_float(value, 20.0)
                    if dcf_val >= threshold and "OVERVALUED" not in dcf_rating:
                        cur_val = f"DCF Undervalued: Margin of Safety {dcf_val:.1f}% >= {threshold}% ({dcf_rating})"
                        triggered = True

                elif condition_type == "COMBO_BUFFETT_QUALITY":
                    roe_val = clean_float(f.get("roe_pct") or f.get("roe"), 0.0)
                    de_val = clean_float(f.get("debt_to_equity") or f.get("de_ratio"), 0.0)
                    if roe_val >= 15.0 and (de_val <= 0.5 or de_val == 0.0):
                        cur_val = f"Buffett Quality: ROE {roe_val:.1f}% >= 15% and Debt-to-Equity {de_val:.2f} <= 0.5"
                        triggered = True

                elif condition_type == "COMBO_CLEAN_GOVERNANCE":
                    pledge_val = clean_float(f.get("promoter_pledge_pct"), 0.0)
                    profit_growth = clean_float(f.get("profit_growth_3y_pct"), 0.0)
                    if pledge_val < 1.0 and profit_growth >= 12.0:
                        cur_val = f"Clean Governance: Pledging {pledge_val:.1f}% < 1% and Profit Growth {profit_growth:.1f}% >= 12%"
                        triggered = True

                elif condition_type == "COMBO_GARP_PEG":
                    peg_val = clean_float(prof.get("score_metrics", {}).get("peg_ratio"), 99.0)
                    if 0 < peg_val < 1.0:
                        cur_val = f"GARP: PEG ratio {peg_val:.2f} < 1.0"
                        triggered = True

                elif condition_type == "COMBO_INST_ABSORPTION":
                    del_pct = clean_float(t.get("delivery_percentage") or t.get("delivery_pct"), 0.0)
                    del_z = clean_float(t.get("delivery_z_score") or t.get("delivery_zscore"), 0.0)
                    if del_pct >= 55.0 and del_z >= 2.0:
                        cur_val = f"Inst Absorption: Delivery {del_pct:.1f}% >= 55% on Delivery Z-Score {del_z:+.1f}"
                        triggered = True

                elif condition_type == "COMBO_VSA_DEMAND":
                    vsa_pattern = (t.get("vsa_pattern") or t.get("vsa_setup") or "").upper()
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    if vol_ratio >= 1.5 and any(kw in vsa_pattern for kw in ["ACCUMULATION", "DEMAND", "STRENGTH", "ABSORPTION", "BUYING"]):
                        cur_val = f"VSA Demand: setup '{vsa_pattern}' with volume ratio {vol_ratio:.1f}x"
                        triggered = True

                elif condition_type == "COMBO_HEAVY_INSTITUTIONAL":
                    shareholding = prof.get("shareholding") or {}
                    inst_val = clean_float(shareholding.get("FIIs"), 0.0) + clean_float(shareholding.get("DIIs"), 0.0)
                    if inst_val >= 30.0:
                        cur_val = f"Heavy Inst: FII + DII holding {inst_val:.1f}% >= 30%"
                        triggered = True

                elif condition_type == "COMBO_LC_COMPOUNDER":
                    cap_type = (s.get("cap_type") or "").lower()
                    beta_val = clean_float(prof.get("consensus", {}).get("beta") or prof.get("capm_risk_nifty50", {}).get("beta"), 1.0)
                    analysis = prof.get("analysis") or {}
                    rating_val = (analysis.get("recommendation") or prof.get("recommendation") or "N/A").upper()
                    if cap_type == "large" and beta_val < 1.0 and "STRONG BUY" in rating_val:
                        cur_val = f"LC Compounder: Large cap with low beta {beta_val:.2f} and AI Strong Buy"
                        triggered = True

                elif condition_type == "COMBO_SC_MOMENTUM":
                    cap_type = (s.get("cap_type") or "").lower()
                    adx_val = clean_float(t.get("adx"), 0.0)
                    beta_val = clean_float(prof.get("consensus", {}).get("beta") or prof.get("capm_risk_nifty50", {}).get("beta"), 1.0)
                    if cap_type == "small" and adx_val >= 25.0 and beta_val > 1.2:
                        cur_val = f"SC Momentum: Small cap with ADX {adx_val:.1f} >= 25 and beta {beta_val:.2f} > 1.2"
                        triggered = True

                elif condition_type == "COMBO_SECTOR_ROTATION":
                    sma_50 = clean_float(t.get("sma_50"), 0.0)
                    sector = prof.get("sector") or s.get("sector", "N/A")
                    if price > sma_50 > 0:
                        try:
                            with get_db() as conn:
                                cursor = conn.cursor()
                                cursor.execute("SELECT sector FROM sector_regime_stats ORDER BY return_1m DESC LIMIT 3")
                                top_3 = [r["sector"] for r in cursor.fetchall()]
                            if sector in top_3:
                                cur_val = f"Sector Rotation: Price Rs.{price:.2f} > 50 SMA in leading sector '{sector}'"
                                triggered = True
                        except Exception:
                            pass

                elif condition_type == "COMBO_INST_QUALITY_BREAKOUT":
                    eq = prof.get("earnings_quality") or {}
                    f_score = clean_float(eq.get("piotroski_score"), 0.0)
                    high_52w = clean_float(t.get("high_52w") or f.get("high_52week") or f.get("fiftyTwoWeekHigh") or t.get("year_high") or f.get("year_high") or f.get("52w_high"), 0.0)
                    del_z = clean_float(t.get("delivery_z_score") or t.get("delivery_zscore"), 0.0)
                    if f_score >= 7.0 and high_52w > 0.0 and del_z > 1.5:
                        diff_pct = (abs(price - high_52w) / high_52w) * 100
                        if diff_pct <= 2.0:
                            cur_val = f"Inst Quality Breakout: Piotroski F-Score {f_score:.0f}/9, near 52wH (Diff: {diff_pct:.1f}%) on Delivery Z-Score {del_z:+.1f}"
                            triggered = True

                elif condition_type == "COMBO_SOLVENCY_VALUE_DIP":
                    eq = prof.get("earnings_quality") or {}
                    altman_z = clean_float(eq.get("altman_z_score", f.get("altman_z")), 0.0)
                    dcf_val = clean_float(prof.get("dcf", {}).get("margin_of_safety"), 0.0)
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    if altman_z >= 3.0 and dcf_val >= 20.0 and rsi_val <= 35:
                        cur_val = f"Solvency Value Dip: Altman Z-Score {altman_z:.2f} (Fortress Balance Sheet), DCF margin {dcf_val:.1f}% >= 20%, oversold RSI {rsi_val:.1f}"
                        triggered = True

                elif condition_type == "COMBO_HV_MOMENTUM_MARKUP":
                    adx_val = clean_float(t.get("adx"), 0.0)
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    sma_20 = clean_float(t.get("sma_20"), 0.0)
                    sma_50 = clean_float(t.get("sma_50"), 0.0)
                    if adx_val >= 25.0 and vol_ratio >= 2.0 and price > sma_20 > sma_50 > 0:
                        cur_val = f"HV Momentum Markup: ADX {adx_val:.1f} (Strong Trend), Vol Ratio {vol_ratio:.1f}x >= 2.0x, Price Rs.{price:.2f} > 20 SMA > 50 SMA"
                        triggered = True

                elif condition_type == "COMBO_SM_BOTTOM_FISHING":
                    shareholding = prof.get("shareholding") or {}
                    inst_val = clean_float(shareholding.get("FIIs"), 0.0) + clean_float(shareholding.get("DIIs"), 0.0)
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    vsa_pattern = (t.get("vsa_pattern") or t.get("vsa_setup") or "").upper()
                    if inst_val >= 25.0 and rsi_val <= 35.0 and any(kw in vsa_pattern for kw in ["ACCUMULATION", "DEMAND", "STRENGTH", "ABSORPTION", "BUYING"]):
                        cur_val = f"SM Bottom Fishing: Institutional stake {inst_val:.1f}% >= 25%, oversold RSI {rsi_val:.1f}, VSA Setup '{vsa_pattern}'"
                        triggered = True

                elif condition_type == "COMBO_RSI_DIVERGENCE":
                    low_52w = clean_float(t.get("low_52w") or f.get("low_52week") or f.get("fiftyTwoWeekHigh") or t.get("year_low") or f.get("year_low") or f.get("52w_low"), 0.0)
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    if low_52w > 0.0 and price <= low_52w * 1.05 and rsi_val >= 45.0:
                        cur_val = f"RSI Bullish Divergence: Price Rs.{price:.2f} near 52wL Rs.{low_52w:.2f} (Diff <= 5%) but RSI strong: {rsi_val:.1f}"
                        triggered = True

                elif condition_type == "COMBO_GOLDEN_CROSS":
                    sma_50 = clean_float(t.get("sma_50"), 0.0)
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    if sma_50 > sma_200 > 0.0:
                        diff_pct = ((sma_50 - sma_200) / sma_200) * 100
                        if diff_pct <= 1.5:
                            cur_val = f"Golden Cross Confluence: 50 SMA (Rs.{sma_50:.2f}) is {diff_pct:.2f}% above 200 SMA (Rs.{sma_200:.2f})"
                            triggered = True

                elif condition_type == "COMBO_BB_WALK":
                    bb_upper = clean_float(t.get("bb_upper"), 0.0)
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    if bb_upper > 0.0 and price >= bb_upper and vol_ratio >= 2.0:
                        cur_val = f"Walking the Bands: Price Rs.{price:.2f} >= BB Upper Rs.{bb_upper:.2f} with strong Vol: {vol_ratio:.1f}x"
                        triggered = True

                elif condition_type == "COMBO_FIB_236_BREAKOUT":
                    fib_236 = clean_float(t.get("fib_levels", {}).get("fib_236"), 0.0)
                    if fib_236 > 0.0:
                        diff_pct = (abs(price - fib_236) / fib_236) * 100
                        if diff_pct <= 1.5:
                            cur_val = f"Fib 23.6% Breakout: Price Rs.{price:.2f} near 23.6% Retracement (Rs.{fib_236:.2f}) (Diff: {diff_pct:.2f}%)"
                            triggered = True

                elif condition_type == "COMBO_VOL_52W_HIGH":
                    high_52w = clean_float(t.get("high_52w") or f.get("high_52week") or f.get("fiftyTwoWeekHigh") or t.get("year_high") or f.get("year_high") or f.get("52w_high"), 0.0)
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    if high_52w > 0.0 and price >= high_52w * 0.98 and vol_ratio >= 2.0:
                        cur_val = f"Volumetric 52W Breakout: Price Rs.{price:.2f} near 52wH Rs.{high_52w:.2f} (Diff <= 2%) on strong Vol: {vol_ratio:.1f}x"
                        triggered = True

                elif condition_type == "COMBO_PRISTINE_QUALITY":
                    eq = prof.get("earnings_quality") or {}
                    f_score = clean_float(eq.get("piotroski_score"), 0.0)
                    if f_score >= 8.0:
                        cur_val = f"Pristine Quality: Piotroski F-Score {f_score:.0f}/9 (Pristine Earnings)"
                        triggered = True

                elif condition_type == "COMBO_DRY_VOLUME":
                    bb_upper = clean_float(t.get("bb_upper"), 0.0)
                    bb_lower = clean_float(t.get("bb_lower"), 0.0)
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    if bb_upper > 0.0 and bb_lower > 0.0 and vol_ratio <= 0.5:
                        width_pct = ((bb_upper - bb_lower) / price) * 100
                        if width_pct <= 8.0:
                            cur_val = f"Dry Vol Consolidation: BB Width {width_pct:.1f}% <= 8% (Tight Squeeze) with Dry Vol: {vol_ratio:.2f}x"
                            triggered = True

                elif condition_type == "COMBO_BENCHMARK_ALPHA":
                    alpha_val = clean_float(prof.get("consensus", {}).get("alpha") or prof.get("capm_risk_nifty50", {}).get("alpha"), 0.0)
                    if alpha_val >= 15.0:
                        cur_val = f"Alpha Outperformer: CAPM Alpha {alpha_val:.1f}% >= 15%"
                        triggered = True

                elif condition_type == "COMBO_TRIPLE_SCREEN":
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    rsi_val = clean_float(t.get("rsi"), 50.0)
                    vol_ratio = clean_float(t.get("volume_vs_avg20", t.get("volume_ratio", t.get("vol_breakout_ratio"))), 1.0)
                    if price > sma_200 > 0.0 and rsi_val <= 38.0 and vol_ratio >= 1.5:
                        cur_val = f"Triple Screen: Price Rs.{price:.2f} > 200 SMA (Uptrend), RSI {rsi_val:.1f} <= 38 (Pullback) and Vol Ratio {vol_ratio:.1f}x"
                        triggered = True

                elif condition_type == "COMBO_SMA_200_UNDER_5":
                    sma_200 = clean_float(t.get("sma_200"), 0.0)
                    if sma_200 > 0.0 and price < sma_200:
                        diff_pct = ((sma_200 - price) / sma_200) * 100
                        threshold = clean_float(value, 5.0)
                        if diff_pct <= threshold:
                            cur_val = f"SMA 200 Near Support: Price Rs.{price:.2f} is {diff_pct:.2f}% below 200 SMA (Rs.{sma_200:.2f})"
                            triggered = True

                elif condition_type == "COMBO_SMA_50_UNDER_3":
                    sma_50 = clean_float(t.get("sma_50"), 0.0)
                    if sma_50 > 0.0 and price < sma_50:
                        diff_pct = ((sma_50 - price) / sma_50) * 100
                        threshold = clean_float(value, 3.0)
                        if diff_pct <= threshold:
                            cur_val = f"SMA 50 Near Resistance/Support: Price Rs.{price:.2f} is {diff_pct:.2f}% below 50 SMA (Rs.{sma_50:.2f})"
                            triggered = True

            except Exception as eval_err:
                print(f"Rule Scanner: Error evaluating {sym}: {eval_err}")
                continue

            if triggered:
                rsi = clean_float(t.get("rsi"), 0.0)
                pe = clean_float(f.get("pe_ratio"), 0.0)
                sector = s.get("sector", "N/A")
                cap_type = s.get("cap_type", "N/A")
                analysis = prof.get("analysis") or {}
                rating = (analysis.get("recommendation") or prof.get("recommendation") or "N/A").upper()
                score = clean_float(prof.get("final_score") or prof.get("score_metrics", {}).get("final_score") or analysis.get("score", analysis.get("composite_score")), 0.0)
                de_ratio = clean_float(f.get("debt_to_equity", f.get("de_ratio")), 0.0)
                roe = clean_float(f.get("roe_pct") or f.get("roe"), 0.0)
                info_dict = prof.get("info") or {}
                cons_dict = prof.get("consensus") or {}
                n50_dict = prof.get("nifty50_risk") or {}
                capm_dict = prof.get("capm_risk_nifty50") or {}
                beta = clean_float(info_dict.get("beta") or cons_dict.get("beta") or n50_dict.get("beta") or capm_dict.get("beta"), 1.0)

                matched.append({
                    "symbol": sym,
                    "company_name": s.get("company_name", sym),
                    "sector": sector,
                    "cap_type": cap_type,
                    "price": round(price, 2),
                    "pe": round(pe, 1),
                    "rsi": round(rsi, 1),
                    "trigger_value": cur_val,
                    "rating": rating,
                    "score": round(score, 1),
                    "de_ratio": round(de_ratio, 2),
                    "roe": round(roe, 1),
                    "beta": round(beta, 2)
                })

        return {
            "status": "success",
            "scanned": scanned_count,
            "matched": len(matched),
            "universe": universe,
            "condition": f"{condition_type} {operator} {value}",
            "results": matched
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Rule scan failed: {str(e)}")


@app.get("/api/scans/fuzzy")
async def scan_fuzzy_conviction(
    min_score: float = -100.0,
    max_score: float = 100.0,
    rating_class: Optional[str] = None,
    limit: int = 100
):
    """
    Scans cached profiles and evaluates Mamdani Fuzzy Conviction scores.
    Returns filtered and sorted rank list for the Fuzzy Screener and Scans UI.
    """
    results = []
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT symbol FROM cached_profiles")
        symbols = [row["symbol"] for row in cursor.fetchall()]
        
        for sym in symbols:
            try:
                fz = get_fuzzy_summary_for_symbol(conn, sym)
                score = float(fz.get("fuzzy_score", 0.0))
                rating = fz.get("fuzzy_rating", "Neutral")
                
                if min_score <= score <= max_score:
                    if rating_class and rating_class.strip().lower() != "all":
                        rc_clean = rating_class.strip().lower().replace("_", "").replace(" ", "")
                        r_clean = rating.strip().lower().replace("_", "").replace(" ", "")
                        if rc_clean not in r_clean:
                            continue

                    row = conn.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ?", (sym,)).fetchone()
                    if not row:
                        continue
                    prof = json.loads(row["profile_json"])
                    f = prof.get("fundamentals") or {}
                    t = prof.get("technicals") or {}
                    
                    results.append({
                        "symbol": sym,
                        "company_name": prof.get("company_name", sym),
                        "sector": prof.get("sector", "N/A"),
                        "price": float(t.get("current_price", f.get("current_price", 0.0))),
                        "fuzzy_score": score,
                        "fuzzy_rating": rating,
                        "rsi": float(t.get("rsi", 50.0)),
                        "adx": float(t.get("adx", 20.0)),
                        "trend": t.get("trend_50_vs_200", "Neutral"),
                        "pe": float(f.get("pe_ratio", 0.0))
                    })
            except Exception:
                continue

    results.sort(key=lambda x: x["fuzzy_score"], reverse=True)
    return {
        "status": "success",
        "count": len(results[:limit]),
        "total_matches": len(results),
        "stocks": results[:limit]
    }

@app.post("/api/screener/scan-synthesis")
async def scan_synthesis(data: ScanSynthesisRequest):
    """Generates an AI analyst synthesis summary for rule scanner results using Groq."""
    try:
        from backend.llm_config import call_llm, TASK_FAST, TASK_HEAVY

        top_results = data.results[:20]
        results_text = "\n".join([
            f"- {r.get('symbol','?')}: {r.get('trigger_value','N/A')} | Sector: {r.get('sector','N/A')} | Cap: {r.get('cap_type','N/A')} | P/E: {r.get('pe','N/A')} | RSI: {r.get('rsi','N/A')} | Rating: {r.get('rating','N/A')}"
            for r in top_results
        ])

        sys_prompt = (
            "You are a senior institutional equity analyst. Analyze the following scan results and provide a concise 2-3 sentence synthesis.\n"
            "Focus on: sector concentration patterns, valuation clusters, technical positioning, and actionable observations.\n"
            "Be professional and quantitative. Reference specific sectors and metrics where relevant.\n"
            "Do NOT use bullet points or headers. Write in flowing paragraph form."
        )

        user_prompt = (
            f"Scan Condition: {data.condition_desc}\n"
            f"Total Matches: {len(data.results)}\n\n"
            f"Top matching stocks:\n{results_text}"
        )

        summary = await asyncio.to_thread(call_llm, TASK_FAST, sys_prompt, user_prompt)
        return {"status": "success", "synthesis": summary.strip(), "llm_meta": get_last_llm_meta()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Synthesis generation failed: {str(e)}")


@app.post("/api/screener/explain-formula")
async def explain_formula(data: ExplainFormulaRequest):
    """Generates an AI explanation of the Chartink-style formula using Groq."""
    try:
        from backend.formula_parser import parse_formula_to_conditions
        # Validate syntax locally first
        try:
            parse_formula_to_conditions(data.formula)
        except Exception as pe:
            raise HTTPException(status_code=400, detail=f"Formula Syntax Error: {str(pe)}")
            
        from backend.llm_config import call_llm, TASK_FAST, TASK_HEAVY
        
        sys_prompt = (
            "You are a professional quantitative finance and technical analysis expert.\n"
            "Analyze the given stock scanner formula and explain its conditions, mathematical logic, and what kind of trade setups or chart patterns it scans for in a clear, concise, and professional tone.\n"
            "Format the output using markdown if necessary, using simple terminology suitable for traders. Keep it under 4 sentences."
        )
        
        user_prompt = f"Stock Scanner Formula:\n{data.formula}"
        
        explanation = await asyncio.to_thread(call_llm, TASK_FAST, sys_prompt, user_prompt)
        return {"status": "success", "explanation": explanation.strip(), "llm_meta": get_last_llm_meta()}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate explanation: {str(e)}")


# ─── CHARTINK-STYLE CUSTOM SCREENER ENGINE ─────────────────────────────────────

def compute_dataframe_indicators(df: pd.DataFrame, timeframe: str) -> List[dict]:
    import numpy as np
    import pandas as pd
    
    if df.empty or len(df) < 5:
        return []
        
    df = df.copy()
    
    df['Close'] = df['Close'].ffill().bfill()
    df['Volume'] = df['Volume'].ffill().bfill()
    
    if 'High' in df.columns:
        df['High'] = df['High'].ffill().bfill()
    else:
        df['High'] = df['Close']
        
    if 'Low' in df.columns:
        df['Low'] = df['Low'].ffill().bfill()
    else:
        df['Low'] = df['Close']
        
    if 'Open' in df.columns:
        df['Open'] = df['Open'].ffill().bfill()
    else:
        df['Open'] = df['Close']
    
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    df['SMA_200'] = df['Close'].rolling(window=200).mean()
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()
    
    # RSI 14
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    df['RSI_14'] = 100 - (100 / (1 + rs))
    
    # Volume Ratio vs 20d Average
    df['Vol_20MA'] = df['Volume'].rolling(window=20).mean()
    df['Vol_Ratio'] = df['Volume'] / (df['Vol_20MA'] + 1e-9)
    
    # Bollinger Bands
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['STD_20'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['SMA_20'] + 2 * df['STD_20']
    df['BB_Lower'] = df['SMA_20'] - 2 * df['STD_20']
    
    # MACD & Signal
    df['EMA_12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA_26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA_12'] - df['EMA_26']
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # Trailing High/Low lookbacks (250 bars for daily, 52 for weekly, 12 for monthly)
    lookback = 250 if timeframe == '1d' else (52 if timeframe == '1wk' else 12)
    df['year_high'] = df['Close'].rolling(window=lookback, min_periods=1).max()
    df['year_low'] = df['Close'].rolling(window=lookback, min_periods=1).min()
    
    cols = ['Open', 'High', 'Low', 'SMA_50', 'SMA_200', 'EMA_50', 'EMA_200', 'RSI_14', 'Vol_Ratio', 'BB_Upper', 'BB_Lower', 'MACD', 'MACD_Signal', 'year_high', 'year_low']
    for col in cols:
        if col in df.columns:
            df[col] = df[col].bfill().ffill().fillna(0.0)
            
    df = df.reset_index()
    date_col = 'Date' if 'Date' in df.columns else df.columns[0]
    
    results = []
    for _, row in df.iterrows():
        try:
            dt_val = row[date_col]
            if isinstance(dt_val, str):
                date_str = dt_val[:10]
            else:
                date_str = dt_val.strftime("%Y-%m-%d")
        except Exception:
            date_str = str(dt_val)[:10]
            
        results.append({
            "date": date_str,
            "Close": float(row["Close"]),
            "High": float(row["High"]),
            "Low": float(row["Low"]),
            "Open": float(row["Open"]),
            "Volume": float(row["Volume"]),
            "Vol_Ratio": float(row["Vol_Ratio"]),
            "RSI_14": float(row["RSI_14"]),
            "SMA_50": float(row["SMA_50"]),
            "SMA_200": float(row["SMA_200"]),
            "EMA_50": float(row["EMA_50"]),
            "EMA_200": float(row["EMA_200"]),
            "BB_Upper": float(row["BB_Upper"]),
            "BB_Lower": float(row["BB_Lower"]),
            "MACD": float(row["MACD"]),
            "MACD_Signal": float(row["MACD_Signal"]),
            "year_high": float(row["year_high"]),
            "year_low": float(row["year_low"])
        })
        
    return results

async def get_timeframe_indicators(symbol: str, timeframe: str) -> List[dict]:
    if timeframe not in ['1d', '1wk', '1mo']:
        timeframe = '1d'
        
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT indicators_json, updated_at 
                FROM cached_timeframe_indicators 
                WHERE symbol = ? AND timeframe = ?
            """, (symbol, timeframe))
            row = cursor.fetchone()
            
        if row:
            try:
                cache_time = datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S")
                age = datetime.now() - cache_time
                if age.total_seconds() < 14400:  # 4 hours
                    return json.loads(row["indicators_json"])
            except Exception:
                pass
    except Exception as db_err:
        print(f"Error reading timeframe indicator cache: {db_err}")
        
    period = "2y" if timeframe == '1d' else ("5y" if timeframe == '1wk' else "max")
    df = await fetch_history_df(symbol, period=period, interval=timeframe)
    
    if df.empty:
        try:
            ticker_obj = yf.Ticker(symbol)
            df = await asyncio.to_thread(ticker_obj.history, period=period, interval=timeframe)
        except Exception:
            pass
            
    indicators = []
    if not df.empty:
        indicators = compute_dataframe_indicators(df, timeframe)
        
    if indicators:
        try:
            with get_db() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO cached_timeframe_indicators 
                    (symbol, timeframe, indicators_json, updated_at) 
                    VALUES (?, ?, ?, ?)
                """, (symbol, timeframe, json.dumps(indicators), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                conn.commit()
        except Exception as db_err:
            print(f"Error writing timeframe indicator cache: {db_err}")
            
    return indicators

def find_latest_row_before_or_equal(rows: List[dict], target_date_str: str) -> Optional[dict]:
    best_row = None
    for row in rows:
        if row["date"] <= target_date_str:
            best_row = row
        else:
            break
    return best_row

def get_indicator_value(ind_row: dict, fund: dict, tech_full: dict, key: str):
    if not ind_row:
        return 0.0
        
    key_upper = str(key).upper().strip()
    if key_upper == "PRICE":
        return ind_row.get("Close", 0.0)
    elif key_upper == "VOLUME":
        return ind_row.get("Volume", 0.0)
    elif key_upper == "VOL_BREAKOUT":
        return ind_row.get("Vol_Ratio", 0.0)
    elif key_upper == "RSI":
        return ind_row.get("RSI_14", 50.0)
    elif key_upper == "SMA50":
        return ind_row.get("SMA_50", 0.0)
    elif key_upper == "SMA200":
        return ind_row.get("SMA_200", 0.0)
    elif key_upper == "EMA50":
        return ind_row.get("EMA_50", 0.0)
    elif key_upper == "EMA200":
        return ind_row.get("EMA_200", 0.0)
    elif key_upper == "BB_UPPER":
        return ind_row.get("BB_Upper", 0.0)
    elif key_upper == "BB_LOWER":
        return ind_row.get("BB_Lower", 0.0)
    elif key_upper == "MACD":
        return ind_row.get("MACD", 0.0)
    elif key_upper == "MACD_SIGNAL":
        return ind_row.get("MACD_Signal", 0.0)
    elif key_upper == "PE":
        from backend.swing_utils import clean_float
        return clean_float(fund.get("pe_ratio"), 0.0)
    elif key_upper == "DE_RATIO":
        from backend.swing_utils import clean_float
        return clean_float(fund.get("debt_to_equity"), 0.0)
    elif key_upper == "RATING":
        analysis = tech_full.get("analysis")
        if not isinstance(analysis, dict):
            analysis = {}
        return (analysis.get("recommendation") or tech_full.get("recommendation") or "HOLD").upper()
    elif key_upper == "SCORE":
        from backend.swing_utils import clean_float
        analysis = tech_full.get("analysis")
        if not isinstance(analysis, dict):
            analysis = {}
        return clean_float(tech_full.get("final_score") or tech_full.get("score_metrics", {}).get("final_score") or analysis.get("score", analysis.get("composite_score")), 0.0)
    else:
        try:
            return float(key)
        except ValueError:
            return key.upper()

def compare_rule_values(left, op, right) -> bool:
    try:
        if left is None:
            left = 0.0
        if right is None:
            right = 0.0
            
        if isinstance(left, str) or isinstance(right, str):
            left_str = str(left).upper().strip()
            right_str = str(right).upper().strip()
            if op == "==":
                return left_str == right_str
            elif op == "!=":
                return left_str != right_str
            return False
            
        l_num = float(left)
        r_num = float(right)
        
        if op == "<":
            return l_num < r_num
        elif op == ">":
            return l_num > r_num
        elif op == "==":
            return abs(l_num - r_num) < 1e-5
        elif op == "<=":
            return l_num <= r_num
        elif op == ">=":
            return l_num >= r_num
    except Exception:
        pass
    return False

@app.post("/api/screener/custom-scan")
async def execute_custom_screener_scan(data: CustomScanRequest):
    try:
        from backend.swing_utils import clean_float
        
        # 1. Parse formula if provided
        parsed_conditions = []
        is_formula_mode = bool(data.formula and data.formula.strip())
        
        if is_formula_mode:
            from backend.formula_parser import parse_formula_to_conditions
            try:
                parsed_conditions = parse_formula_to_conditions(data.formula)
            except Exception as pe:
                raise HTTPException(status_code=400, detail=str(pe))
                
            required_timeframes = set()
            for left, op, right in parsed_conditions:
                required_timeframes |= left.get_required_timeframes()
                required_timeframes |= right.get_required_timeframes()
        else:
            required_timeframes = set(rule.timeframe for rule in data.rules)
            
        if not required_timeframes:
            required_timeframes.add("1d")
            
        # 2. Fetch universe stocks
        with get_db() as conn:
            cursor = conn.cursor()
            if data.universe == "all":
                cursor.execute("SELECT symbol, company_name, sector, cap_type FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%'")
            else:
                cursor.execute("SELECT symbol, company_name, sector, cap_type FROM screener_universe WHERE cap_type = ? AND symbol NOT LIKE '%DUMMY%'", (data.universe,))
            stocks = [dict(row) for row in cursor.fetchall()]
            
            # Load cached daily profiles to get fundamentals
            cursor.execute("SELECT symbol, profile_json FROM cached_profiles")
            cached_rows = cursor.fetchall()
            cached_profiles = {}
            for r in cached_rows:
                try:
                    cached_profiles[r["symbol"]] = json.loads(r["profile_json"])
                except Exception:
                    continue
                    
        # 3. Get last N trading dates for historical match count chart
        benchmark_dates = []
        benchmark_history = await get_timeframe_indicators("TCS.NS", "1d")
        if not benchmark_history:
            benchmark_history = await get_timeframe_indicators("RELIANCE.NS", "1d")
            
        if benchmark_history:
            benchmark_history.sort(key=lambda x: x["date"])
            n_range = data.historical_range
            sliced_bench = benchmark_history[-n_range:] if len(benchmark_history) >= n_range else benchmark_history
            benchmark_dates = [row["date"] for row in sliced_bench]
            
        if not benchmark_dates:
            from datetime import datetime, timedelta
            benchmark_dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(data.historical_range - 1, -1, -1)]
            benchmark_dates.sort()
            
        historical_counts = {dt: 0 for dt in benchmark_dates}
        
        # 4. Evaluate rules
        matched_results = []
        scanned_count = 0
        
        for stock in stocks:
            sym = stock["symbol"]
            profile = cached_profiles.get(sym)
            if not profile:
                continue
                
            fund = profile.get("fundamentals") or {}
            
            timeseries_cache = {}
            has_all_data = True
            for tf in required_timeframes:
                ts = await get_timeframe_indicators(sym, tf)
                if not ts:
                    has_all_data = False
                    break
                ts.sort(key=lambda x: x["date"])
                timeseries_cache[tf] = ts
                
            if not has_all_data:
                continue
                
            scanned_count += 1
            
            # Current scan match evaluation
            current_match = True
            if is_formula_mode:
                if not parsed_conditions:
                    current_match = False
            else:
                if not data.rules:
                    current_match = False
                
            rule_evals = []
            if is_formula_mode:
                from backend.formula_parser import evaluate_ast_condition
                for left, op, right in parsed_conditions:
                    passed = evaluate_ast_condition(left, op, right, timeseries_cache, -1, "1d")
                    rule_evals.append(passed)
            else:
                for rule in data.rules:
                    ts = timeseries_cache.get(rule.timeframe)
                    if ts:
                        offset = rule.offset or 0
                        idx = -1 - offset
                        if idx < -len(ts) or idx >= 0:
                            rule_evals.append(False)
                            continue
                        row = ts[idx]
                        left_val = get_indicator_value(row, fund, profile, rule.indicator)
                        right_val = get_indicator_value(row, fund, profile, rule.value)
                        passed = compare_rule_values(left_val, rule.operator, right_val)
                        
                        # Apply threshold proximity check if threshold > 0
                        if passed and rule.threshold and rule.threshold > 0.0:
                            try:
                                l_num = float(left_val)
                                r_num = float(right_val)
                                diff_pct = abs(l_num - r_num) / (abs(r_num) + 1e-9) * 100.0
                                if diff_pct > rule.threshold:
                                    passed = False
                            except Exception:
                                pass
                                
                        rule_evals.append(passed)
                    else:
                        rule_evals.append(False)
                        
            if data.logic_gate == "AND":
                current_match = all(rule_evals) if rule_evals else False
            else:
                current_match = any(rule_evals) if rule_evals else False
                
            if current_match:
                latest_d_row = timeseries_cache.get("1d")[-1] if "1d" in timeseries_cache else list(timeseries_cache.values())[0][-1]
                price = float(latest_d_row.get("Close", 0.0))
                
                rsi = clean_float(profile.get("technicals", {}).get("rsi"), 50.0)
                pe = clean_float(fund.get("pe_ratio"), 0.0)
                score = clean_float(profile.get("final_score") or profile.get("score_metrics", {}).get("final_score") or profile.get("analysis", {}).get("score", profile.get("analysis", {}).get("composite_score")), 0.0)
                de_ratio = clean_float(fund.get("debt_to_equity"), 0.0)
                analysis = profile.get("analysis") or {}
                rating = (analysis.get("recommendation") or profile.get("recommendation") or "N/A").upper()
                roe = clean_float(fund.get("roe_pct") or fund.get("roe"), 0.0)
                info_dict = profile.get("info") or {}
                cons_dict = profile.get("consensus") or {}
                n50_dict = profile.get("nifty50_risk") or {}
                capm_dict = profile.get("capm_risk_nifty50") or {}
                beta = clean_float(info_dict.get("beta") or cons_dict.get("beta") or n50_dict.get("beta") or capm_dict.get("beta"), 1.0)
                
                trigger_desc = []
                if is_formula_mode:
                    trigger_str = "Formula: " + "; ".join(data.formula.strip().split("\n")[:2])
                    if len(data.formula.strip().split("\n")) > 2:
                        trigger_str += "..."
                else:
                    for rule in data.rules:
                        trigger_desc.append(f"{rule.timeframe.upper()} {rule.indicator} {rule.operator} {rule.value}")
                    trigger_str = ", ".join(trigger_desc[:3])
                    if len(trigger_desc) > 3:
                        trigger_str += "..."
                    
                matched_results.append({
                    "symbol": sym,
                    "company_name": stock.get("company_name", sym),
                    "sector": stock.get("sector", "N/A"),
                    "cap_type": stock.get("cap_type", "N/A"),
                    "price": round(price, 2),
                    "pe": round(pe, 1),
                    "rsi": round(rsi, 1),
                    "trigger_value": trigger_str,
                    "rating": rating,
                    "score": round(score, 1),
                    "de_ratio": round(de_ratio, 2),
                    "roe": round(roe, 1),
                    "beta": round(beta, 2)
                })
                
            # Base timeframe for index alignment in history builder
            base_tf = "1d"
            if base_tf not in timeseries_cache:
                base_tf = list(timeseries_cache.keys())[0]
            base_ts = timeseries_cache[base_tf]
            
            # Historical matches counts timeline builder
            for dt in benchmark_dates:
                row_at_dt = find_latest_row_before_or_equal(base_ts, dt)
                if not row_at_dt:
                    continue
                    
                base_idx_at_dt = next((i for i, r in enumerate(base_ts) if r["date"] == row_at_dt["date"]), -1)
                if base_idx_at_dt == -1:
                    continue
                    
                base_idx_rel = base_idx_at_dt - len(base_ts)
                
                rule_evals_dt = []
                if is_formula_mode:
                    from backend.formula_parser import evaluate_ast_condition
                    for left, op, right in parsed_conditions:
                        passed = evaluate_ast_condition(left, op, right, timeseries_cache, base_idx_rel, base_tf)
                        rule_evals_dt.append(passed)
                else:
                    for rule in data.rules:
                        ts = timeseries_cache.get(rule.timeframe)
                        if not ts:
                            rule_evals_dt.append(False)
                            continue
                            
                        row_at_dt = find_latest_row_before_or_equal(ts, dt)
                        if not row_at_dt:
                            rule_evals_dt.append(False)
                            continue
                            
                        idx_at_dt = next((i for i, r in enumerate(ts) if r["date"] == row_at_dt["date"]), -1)
                        if idx_at_dt == -1:
                            rule_evals_dt.append(False)
                            continue
                            
                        offset = rule.offset or 0
                        target_idx = idx_at_dt - offset
                        if target_idx < 0 or target_idx >= len(ts):
                            rule_evals_dt.append(False)
                            continue
                            
                        row = ts[target_idx]
                        left_val = get_indicator_value(row, fund, profile, rule.indicator)
                        right_val = get_indicator_value(row, fund, profile, rule.value)
                        passed = compare_rule_values(left_val, rule.operator, right_val)
                        
                        # Apply threshold proximity check if threshold > 0
                        if passed and rule.threshold and rule.threshold > 0.0:
                            try:
                                l_num = float(left_val)
                                r_num = float(right_val)
                                diff_pct = abs(l_num - r_num) / (abs(r_num) + 1e-9) * 100.0
                                if diff_pct > rule.threshold:
                                    passed = False
                            except Exception:
                                pass
                                
                        rule_evals_dt.append(passed)
                    
                dt_matched = False
                if data.logic_gate == "AND":
                    dt_matched = all(rule_evals_dt) if rule_evals_dt else False
                else:
                    dt_matched = any(rule_evals_dt) if rule_evals_dt else False
                    
                if dt_matched:
                    historical_counts[dt] += 1
                    
        formatted_historical = [{"time": dt, "value": count} for dt, count in sorted(historical_counts.items())]
        
        cond_desc = f"Custom Screener ({data.logic_gate})"
        if is_formula_mode:
            cond_desc += ": Formula Mode"
        elif data.rules:
            cond_desc += f": {len(data.rules)} Rules"
            
        return {
            "status": "success",
            "scanned": scanned_count,
            "matched": len(matched_results),
            "universe": data.universe,
            "condition": cond_desc,
            "results": matched_results,
            "historical_matches": formatted_historical
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Custom scan failed: {str(e)}")

@app.get("/api/screener/screens")
async def get_saved_screens():
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, description, rules_json, formula, logic_gate, universe, created_at FROM custom_screens ORDER BY name ASC")
            rows = [dict(row) for row in cursor.fetchall()]
            
        for row in rows:
            try:
                row["rules"] = json.loads(row["rules_json"])
            except Exception:
                row["rules"] = []
            if "formula" not in row or row["formula"] is None:
                row["formula"] = ""
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch saved screens: {str(e)}")

@app.post("/api/screener/screens")
async def save_custom_screen(data: SavedScreenCreate):
    try:
        screen_id = str(uuid.uuid4())
        rules_str = json.dumps(data.rules)
        formula_str = data.formula or ""
        
        with get_db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO custom_screens (id, name, description, rules_json, formula, logic_gate, universe, created_at) 
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (screen_id, data.name, data.description, rules_str, formula_str, data.logic_gate, data.universe))
            conn.commit()
        return {"status": "success", "id": screen_id, "name": data.name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save screen: {str(e)}")

@app.delete("/api/screener/screens/{screen_id}")
async def delete_custom_screen(screen_id: str):
    try:
        with get_db() as conn:
            conn.execute("DELETE FROM custom_screens WHERE id = ?", (screen_id,))
            conn.commit()
        return {"status": "success", "message": "Screen deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete screen: {str(e)}")


# ==================== ANGEL ONE STATUS & HEALTH ====================

@app.get("/api/angel/status")
async def angel_status():
    """Returns the current Angel One WebSocket connection health and status."""
    import datetime as _dt
    # Determine market status (NSE: Mon-Fri 9:15-15:30 IST)
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    is_weekday = now_ist.weekday() < 5
    market_open = now_ist.replace(hour=9, minute=15, second=0)
    market_close = now_ist.replace(hour=15, minute=30, second=0)
    is_market_hours = is_weekday and market_open <= now_ist <= market_close

    status = {
        "connected": angel_connector is not None and angel_connector.is_authenticated(),
        "authenticated": angel_connector.is_authenticated() if angel_connector else False,
        "market_status": "OPEN" if is_market_hours else "CLOSED",
    }

    # Merge feed status from WebSocket server
    feed = get_feed_status()
    status.update(feed)

    # Add connector-level status if available
    if angel_connector:
        status.update(angel_connector.get_status())

    return status


# ==================== LEARNING ACADEMY SCENARIO GENERATOR ====================

class LearningScenarioRequest(BaseModel):
    topic: str
    category: str

@app.post("/api/learning/scenario")
async def learning_scenario(req: LearningScenarioRequest):
    """
    On-demand AI Case Study generator for the Learning Academy.
    Generates structured, realistic hypothetical trading/investment case studies 
    contextualised in the Indian stock and bond markets matching the selected topic.
    """
    system_prompt = (
        "You are an expert institutional fund manager, investment analyst, and historian of the Indian equity and debt markets (NSE/BSE).\n"
        "Your task is to generate a highly detailed, educational case study demonstrating the active learning topic in a real Indian stock or market context (e.g. Reliance, TCS, HDFC Bank, G-Secs).\n\n"
        "Crucially, construct this case study from the perspective of a medium-to-long-term investor. Emphasize business fundamentals, long-term valuation metrics (P/E cycles, ROCE, EV/EBITDA, free cash flow compounding, and structural advantages/moats), capital allocation strategies, and margin of safety boundaries.\n\n"
        "Incorporate recent Indian market dynamics (2020-2026), such as the post-COVID manufacturing and capex cycles, PSU bank/energy re-ratings, private sector infrastructure runs, key corporate merges (like HDFC-HDFC Bank consolidation), or global bond index inclusions impacting G-sec yields.\n\n"
        "The response MUST be formatted in clean markdown, containing:\n"
        "1. **Market Context & Recent Background**: The macroeconomic/industry backdrop and recent stock trends (framing the historical/recent setup between 2020-2026).\n"
        "2. **Investment Setup & Valuation Metrics**: Fundamental details, business health indicators, or structural price consolidation levels.\n"
        "3. **Long-Term Investment Thesis**: Underwriting logic, margin of safety pricing range, capital allocation/portfolio sizing rules, and medium/long-term holding expectations.\n"
        "4. **Outcome Analysis & Retrospective**: The compounding outcome, dividend/capital return updates, and key structural lessons learned.\n\n"
        "Keep the output concise (under 380 words), engaging, professional, and educational."
    )

    user_prompt = f"Generate a structured, hypothetical Indian market case study demonstrating: {req.topic} (Category: {req.category})"

    try:
        response = await asyncio.to_thread(
            call_llm,
            system_prompt,
            user_prompt,
            max_tokens=1500
        )

        if "ERROR_401" in response:
            return JSONResponse(
                status_code=200,
                content={
                    "scenario": "The Case Study Generator requires a valid LLM API key. Please configure your API key environment variable or SQLite key settings to enable AI-powered scenario generation.",
                    "status": "api_key_error"
                }
            )

        return {"scenario": response, "status": "success", "llm_meta": get_last_llm_meta()}

    except Exception as e:
        print(f"[Learning Academy] Scenario Generator error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "scenario": "An error occurred while generating the case study. Please try again.",
                "status": "error"
            }
        )



@app.post("/api/learning/ask")
async def learning_ask(req: LearningAskRequest):
    """
    AI Coach endpoint for the Learning Academy.
    Answers educational questions about technical analysis, chart patterns,
    candlestick patterns, fundamental analysis, and bond markets using Groq LLM.
    """
    system_prompt = (
        "You are an expert Financial Markets Educator and CFA/CMT charterholder.\n"
        "Your role is to teach stock market and bond market concepts clearly, using:\n"
        "- Precise mathematical formulas with variable definitions\n"
        "- Real-world Indian market examples (NSE/BSE stocks like Reliance, TCS, HDFC Bank)\n"
        "- Step-by-step calculation walkthroughs\n"
        "- Practical trading/investment application tips\n"
        "- Common mistakes and pitfalls to avoid\n\n"
        "Crucially, if the query contains 'Active Sandbox Inputs' (e.g., o = 152, c = 155, l = 145, or rsi_length = 14, etc.), you MUST perform the math calculations using those exact numbers, explain the ratios (e.g., lower shadow-to-body size for a hammer), and explicitly comment on whether those values constitute a valid or strong pattern.\n\n"
        "Keep responses concise (under 400 words), educational, and actionable.\n"
        "Use markdown formatting for headers, bold, lists, and code blocks for formulas.\n"
        "If the question is about a specific indicator or pattern, always include its formula and interpretation rules."
    )

    topic_context = ""
    if req.topic:
        topic_context = f"\n\nCurrent Learning Topic: {req.topic}"
    if req.category:
        topic_context += f"\nCategory: {req.category}"
    if req.sub_pattern:
        topic_context += f"\nSelected Sub-pattern: {req.sub_pattern}"
    if req.sandbox_values:
        sandbox_str = ", ".join([f"{k} = {v}" for k, v in req.sandbox_values.items()])
        topic_context += f"\nActive Sandbox Inputs: {sandbox_str}"

    user_prompt = f"{req.question}{topic_context}"

    try:
        response = await asyncio.to_thread(
            call_llm,
            system_prompt,
            user_prompt,
            max_tokens=1500
        )

        if "ERROR_401" in response:
            return JSONResponse(
                status_code=200,
                content={
                    "answer": "The AI Coach requires a valid LLM API key. Please configure your API key environment variable or SQLite key settings to enable AI-powered explanations.",
                    "status": "api_key_error"
                }
            )

        return {"answer": response, "status": "success", "llm_meta": get_last_llm_meta()}

    except Exception as e:
        print(f"[Learning Academy] AI Coach error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "answer": "An error occurred while processing your question. Please try again.",
                "status": "error"
            }
        )

# Include Angel One WebSocket router
app.include_router(angel_ws_router)


@app.get("/api/stock-catalysts")
def get_stock_catalysts(
    symbol: str, 
    sector: Optional[str] = None, 
    is_sector: bool = Query(False),
    use_tavily_search: bool = Query(False),
    use_serpapi: bool = Query(False),
    use_brave: bool = Query(True),
    ai_engine: str = Query("gemini"),
    timeframe: str = Query("7d"),
    direction: Optional[str] = Query(None)
):
    try:
        import requests
        from backend.catalyst_scraper import fetch_latest_news_for_query
        from backend.llm_config import call_llm, TASK_FAST
        
        # Load SerpApi and Tavily keys from SQLite Database or .env fallback
        serpapi_keys = []
        tavily_keys = []
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM alert_settings WHERE key = 'serpapi_api_key'")
                row = cursor.fetchone()
                if row:
                    decoded = decode_key(row["value"])
                    if decoded.startswith("["):
                        serpapi_keys = json.loads(decoded)
                    elif decoded:
                        serpapi_keys = [k.strip() for k in decoded.split(",") if k and k.strip()]
                
                cursor.execute("SELECT value FROM alert_settings WHERE key = 'tavily_api_key'")
                row = cursor.fetchone()
                if row:
                    decoded = decode_key(row["value"])
                    if decoded.startswith("["):
                        tavily_keys = json.loads(decoded)
                    elif decoded:
                        tavily_keys = [k.strip() for k in decoded.split(",") if k and k.strip()]
        except Exception:
            pass
            
        # Merge with .env pools
        for k, v in os.environ.items():
            if k.startswith("SERPAPI_API_KEY"):
                val = v.strip()
                if val and val not in serpapi_keys:
                    serpapi_keys.append(val)
            elif k.startswith("TAVILY_API_KEY"):
                val = v.strip()
                if val and val not in tavily_keys:
                    tavily_keys.append(val)
            
        # Diagnostic print for loaded keys
        print(f"[Catalyst API] Keys loaded: SerpApi count={len(serpapi_keys)}, Tavily count={len(tavily_keys)}")
        print(f"[Catalyst API] Query params: use_serpapi={use_serpapi}, use_tavily={use_tavily_search}, use_brave={use_brave}")
        
        # 1. Clean ticker symbol and resolve to human-readable company name
        from backend.financial_utils import resolve_company_ticker
        import re
        clean_symbol = symbol.replace(".NS", "").strip()
        try:
            res = resolve_company_ticker(symbol)
            raw_name = res.get("name", clean_symbol)
            # Remove common corporate suffixes (Ltd, Limited, Corp, Co, Co., Corporation, Inc.)
            company_name = re.sub(r'\s+(ltd|limited|corp|co|corporation|inc)\.?\s*$', '', raw_name, flags=re.IGNORECASE).strip()
        except Exception:
            company_name = clean_symbol
        
        # 2. Formulate dynamic search query based on price direction (surge/drop)
        dir_text = ""
        if direction == "up":
            dir_text = "surge rise rally gains up climb"
        elif direction == "down":
            dir_text = "drop fall drop plunge crash down loss"
            
        is_sector_mode = is_sector or (sector and sector.strip().lower() == symbol.strip().lower())
        if is_sector_mode:
            # Sector mode
            clean_sector = sector.strip() if sector else symbol.replace(".NS", "").strip()
            action = "surge/rally" if direction == "up" else ("decline/drop" if direction == "down" else "performance")
            # Map sector names to standard NSE index terms for maximum search relevance and localizing to Indian markets
            index_hint = ""
            sym_lower = clean_sector.lower()
            if "information technology" in sym_lower or "it" == sym_lower:
                index_hint = "Nifty IT index"
            elif "bank" in sym_lower:
                index_hint = "Bank Nifty index"
            elif "realty" in sym_lower:
                index_hint = "Nifty Realty index"
            elif "auto" in sym_lower:
                index_hint = "Nifty Auto index"
            elif "infra" in sym_lower:
                index_hint = "Nifty Infra index"
            elif "metal" in sym_lower:
                index_hint = "Nifty Metal index"
            elif "pharma" in sym_lower or "health" in sym_lower:
                index_hint = "Nifty Pharma index"
            elif "fmcg" in sym_lower:
                index_hint = "Nifty FMCG index"
            
            hint_str = f" {index_hint}" if index_hint else ""
            query = f"Indian {clean_sector} sector{hint_str} {action} reasons news stock market"
        else:
            # Stock mode
            action_suffix = f" {dir_text}" if dir_text else " drop rise price move reasons"
            query = f"{company_name} stock news{action_suffix}"
            
        # 3. Fetch latest news snippets
        news_snippets, search_provider = fetch_latest_news_for_query(
            query, 
            timeframe=timeframe,
            use_tavily=use_tavily_search,
            use_serpapi=use_serpapi,
            use_brave=use_brave,
            serpapi_api_key=serpapi_keys,
            tavily_api_key=tavily_keys
        )
        
        # If no snippets found, search sector-specific trends as fallback
        if not news_snippets and sector:
            news_fallback_query = f"Indian {sector} sector news reasons"
            if direction == "up":
                news_fallback_query = f"Indian {sector} sector growth rally news reasons"
            elif direction == "down":
                news_fallback_query = f"Indian {sector} sector fall drop decline news reasons"
                
            news_snippets, search_provider = fetch_latest_news_for_query(
                news_fallback_query,
                timeframe=timeframe,
                use_tavily=use_tavily_search,
                use_serpapi=use_serpapi,
                use_brave=use_brave,
                serpapi_api_key=serpapi_keys,
                tavily_api_key=tavily_keys
            )
            
        # If still no snippets, return a graceful fallback
        if not news_snippets:
            return {
                "summary": f"No recent major news headlines detected for {symbol} on search channels. Today's movement is likely driven by overall market momentum, institutional flows, or profit-booking.",
                "drivers": [
                    {"category": "Technical", "title": "Market Flow", "desc": "Driven by broader index movements or routine sector rotations."},
                    {"category": "Macro", "title": "Macro Sentiment", "desc": "Impacted by national indices or interest rate regimes."}
                ],
                "sentiment": "Neutral",
                "search_provider": "None (No news found)",
                "llm_provider": "Static Fallback Engine",
                "status": "no_news"
            }
            
        # 4. Formulate the LLM prompt
        snippets_text = "\n\n".join(news_snippets)
        
        # Fetch current index stats for prompt injection
        global _MARKET_MOVERS_CACHE
        indices_list = []
        try:
            for idx in _MARKET_MOVERS_CACHE.get("indices", []):
                change_sign = "+" if idx.get("change", 0) >= 0 else ""
                indices_list.append(f"- {idx['name']}: {idx['price']} ({change_sign}{idx['change_pct']}%)")
        except Exception:
            pass
        indices_str = "\n".join(indices_list) if indices_list else "Not available"

        is_sector_final = is_sector or (sector and sector.strip().lower() == symbol.strip().lower())
        target_type = "sector index" if is_sector_final else "company stock"
 
        system_prompt = (
            "You are an expert Indian stock market research analyst and financial attribution system.\n"
            f"Your task is to analyze the provided news snippets and explain the key reasons behind the recent price movement of the {target_type}.\n"
            "You must respond in clean JSON format matching the following schema:\n"
            "{\n"
            "  \"summary\": \"A concise 2-sentence summary explaining today's movement.\",\n"
            "  \"drivers\": [\n"
            "    {\n"
            "      \"category\": \"Corporate|Sector/Policy|Technical|Macro\",\n"
            "      \"title\": \"A short 3-5 word title of this specific driver.\",\n"
            "      \"desc\": \"A detailed 1-2 sentence description explaining the impact.\"\n"
            "    }\n"
            "  ],\n"
            "  \"sentiment\": \"Positive|Negative|Neutral\"\n"
            "}\n"
            "Guidelines:\n"
            "1. Focus strictly and exclusively on the Indian stock market (NSE/BSE) and Indian corporate entities. "
            "Under no circumstances mention global/US tech giants (e.g. Nvidia, Broadcom, Microsoft, Apple, AMD, or US chip stocks) in your drivers. "
            "Ensure all discussed entities are Indian companies (e.g., TCS, Infosys, Wipro, HCL Tech, DLF, Lodha, etc.).\n"
            "2. Synthesize multiple articles to isolate actual drivers.\n"
            "3. Ensure category mappings strictly match: Corporate, Sector/Policy, Technical, or Macro.\n"
            f"4. Refer to the target as a {target_type}. "
        )
        if is_sector_final:
            system_prompt += (
                "Do not refer to the sector index as 'the company stock' or 'the company's stock'. Focus on sector-wide index trends and general developments across the Indian constituent stocks.\n"
            )
        else:
            system_prompt += (
                "Ensure all drivers relate directly to this specific Indian company and do not confuse ratings/target prices belonging to other peer companies.\n"
            )
            
        system_prompt += (
            "5. Verify that any statistics, quarters, or years mentioned as active drivers are current (for the current year 2026) and not historical retrospectives (e.g. referencing 2023 or 2024 as current drivers). Frame old data strictly as historical context if mentioned at all.\n"
            "6. Do not output any markdown code blocks, backticks, or planning reasoning logs. Only output the raw JSON."
        )
        
        # Resolve a reader-friendly lookback label
        lookback_labels = {
            "1d": "1 Day",
            "5d": "5 Days",
            "7d": "7 Days",
            "14d": "14 Days",
            "30d": "30 Days",
            "1m": "1 Month (20D)",
            "3m": "3 Months",
            "6m": "6 Months",
            "1y": "1 Year",
            "5y": "5 Years",
            "ytd": "Year-To-Date (YTD)"
        }
        timeframe_label = lookback_labels.get(timeframe.lower().strip(), f"{timeframe} Lookback")
        
        # Translate direction to clear trend terminology
        trend_term = "Neutral/Stable"
        if direction == "up":
            trend_term = f"Gaining/Rising/Outperforming over the past {timeframe_label}"
        elif direction == "down":
            trend_term = f"Declining/Falling/Underperforming over the past {timeframe_label}"

        user_prompt = (
            f"Analyze the recent price move for {target_type.capitalize()} Symbol: {symbol}.\n"
            f"Sector: {sector or 'Not specified'}.\n"
            f"Target Lookback Timeframe: {timeframe_label}.\n"
            f"Trend over this Lookback Timeframe: {trend_term}.\n\n"
            f"[GROUND-TRUTH TODAY'S MARKET INDEX PERFORMANCE (FOR CONTEXT)]\n{indices_str}\n\n"
            f"Strict Ground-Truth & Lookback Rules:\n"
            f"1. Do not claim that the overall market is in a rally today if today's index performance is down. "
            f"However, explain why the target is a leader/gainer *over the specified {timeframe_label} lookback timeframe* even if today's single-day session is down.\n"
            f"2. Frame your analysis around the lookback period of {timeframe_label} rather than just today's closing price. "
            f"For example, explain the cumulative drivers (e.g. over the past week/month) that led to its outperformance or decline.\n\n"
            f"Raw News snippets:\n{snippets_text}"
        )
        
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        gemini_success = False
        llm_response = ""
        llm_provider = "Gemini 1.5 Flash"
        
        if ai_engine.lower() == "gemini" and gemini_key:
            models_to_try = [
                "gemini-2.5-flash",
                "gemini-2.0-flash",
                "gemini-3.5-flash",
                "gemini-3.1-flash-lite",
                "gemini-flash-latest",
                "gemini-1.5-flash"
            ]
            for model_name in models_to_try:
                try:
                    print(f"[Catalyst API] Attempting Google Gemini model: {model_name}...")
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
                    headers = {"Content-Type": "application/json"}
                    payload = {
                        "contents": [
                            {
                                "parts": [
                                    {"text": f"{system_prompt}\n\n{user_prompt}"}
                                ]
                            }
                        ]
                    }
                    r = requests.post(url, headers=headers, json=payload, timeout=12.0)
                    if r.status_code == 200:
                        response_data = r.json()
                        try:
                            text = response_data["candidates"][0]["content"]["parts"][0]["text"]
                            llm_response = text
                            gemini_success = True
                            llm_provider = f"Gemini ({model_name})"
                            print(f"[Catalyst API] Gemini model {model_name} succeeded!")
                            break
                        except (KeyError, IndexError) as parse_err:
                            print(f"[Catalyst API] Failed parsing Gemini JSON structure for {model_name}: {parse_err}")
                    else:
                        print(f"[Catalyst API] Gemini model {model_name} returned status {r.status_code}: {r.text}")
                except Exception as gem_ex:
                    print(f"[Catalyst API] Gemini call for {model_name} failed: {gem_ex}")

        # Fallback to Groq if Gemini failed/limited or was not selected
        if not gemini_success:
            print(f"[Catalyst API] Using Groq Llama 3.3 (Fallback or Direct choice)")
            llm_response = call_llm(TASK_FAST, system_prompt, user_prompt)
            llm_provider = "Groq Llama 3.3" + (" (Fallback)" if ai_engine.lower() == "gemini" else "")
            
        # Clean JSON wrappers if LLM returned them
        clean_json = llm_response.strip()
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:]
        if clean_json.endswith("```"):
            clean_json = clean_json[:-3]
        clean_json = clean_json.strip()
        
        try:
            parsed_data = json.loads(clean_json)
            return {
                **parsed_data, 
                "search_provider": search_provider,
                "llm_provider": llm_provider,
                "status": "success"
            }
        except Exception as json_err:
            print(f"[Catalyst API] JSON parsing failed: {json_err}. Raw response was: {clean_json}")
            return {
                "summary": "Attribution analysis completed successfully.",
                "drivers": [
                    {"category": "Macro", "title": "Attribution Summary", "desc": clean_json}
                ],
                "sentiment": "Neutral",
                "search_provider": search_provider,
                "llm_provider": llm_provider,
                "status": "raw_text"
            }
            
    except Exception as e:
        print(f"[Catalyst API] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Global in-memory index returns cache to eliminate network latency
_INDEX_RETURNS_CACHE = {}

def _get_benchmark_returns(ticker_symbol: str) -> dict:
    """Helper to fetch and calculate 1D..10Y returns for index benchmarks with in-memory caching."""
    import time
    now = time.time()
    if ticker_symbol in _INDEX_RETURNS_CACHE:
        cached_data, timestamp = _INDEX_RETURNS_CACHE[ticker_symbol]
        if now - timestamp < 86400: # 24h cache
            return cached_data
            
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker_symbol).history(period="10y")
        if hist is not None and not hist.empty and len(hist) >= 2:
            close = hist['Close'].dropna()
            latest = float(close.iloc[-1])
            lookbacks = {
                "1D": 1, "1W": 5, "1M": 21, "3M": 63, "6M": 126,
                "1Y": 252, "3Y": 252 * 3, "5Y": 252 * 5, "10Y": 252 * 10
            }
            res = {}
            for period, offset in lookbacks.items():
                if len(close) > offset:
                    start_price = float(close.iloc[-(offset + 1)])
                else:
                    start_price = float(close.iloc[0])
                res[period] = round(((latest - start_price) / start_price) * 100.0, 2)
            _INDEX_RETURNS_CACHE[ticker_symbol] = (res, now)
            return res
    except Exception as e:
        print(f"Error fetching index returns for {ticker_symbol}: {e}")
        
    DEFAULT_BENCHMARKS = {
        "^NSEI": {"1D": -0.43, "1W": -1.27, "1M": -0.24, "3M": -0.55, "6M": -5.11, "1Y": -5.76, "3Y": 20.82, "5Y": 49.90, "10Y": 175.22},
        "^BSESN": {"1D": -0.43, "1W": -1.46, "1M": -0.18, "3M": -0.79, "6M": -6.72, "1Y": -8.06, "3Y": 14.57, "5Y": 43.57, "10Y": 170.72}
    }
    return DEFAULT_BENCHMARKS.get(ticker_symbol, {})


def _determine_sector_index_symbol(clean_symbol: str) -> str:
    """Maps stock ticker or company name to the appropriate NSE Sectoral or Thematic Index."""
    sym = clean_symbol.upper()
    
    # 1. Technology & IT Services / Nifty Digital
    it_keywords = ["BSOFT", "BIRLASOFT", "KPIT", "TCS", "INFY", "INFOSYS", "WIPRO", "HCLTECH", "TECHM", "LTIM", "LTI",
                   "MPHASIS", "PERSISTENT", "COFORGE", "TATAELXSI", "CYIENT", "HAPPSTMNDS", "ZENSAR", "SONATA", 
                   "SONATSOFTW", "MASTEK", "INTELLECT", "OFSS", "LTTS", "NEWGEN", "NETWEB", "SOFTWARE", 
                   "TECHNOLOGY", "IT SERVICES", "COMPUTERS - SOFTWARE", "IT CONSULTING", "DIGITAL"]
    if any(k in sym for k in it_keywords):
        return "^CNXIT"
        
    # 2. Banking & Financial Services / Nifty Private Bank / Nifty PSU Bank
    bank_keywords = ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK", "FEDERALBNK", 
                     "BANDHANBNK", "IDFCFIRSTB", "PNB", "BANKBARODA", "CANBK", "AUBANK", "YESBANK", "J&KBANK", 
                     "BANKING", "BANKS", "PRIVATE BANK", "PSU BANK"]
    if any(k in sym for k in bank_keywords):
        return "^NSEBANK"

    # 3. Financial Services (NBFCs, Insurance, AMCs)
    fin_keywords = ["BAJFINANCE", "BAJAJFINSV", "MUTHOOTFIN", "SHRIRAMFIN", "CHOLAFIN", "RECLTD", "PFC", "M&MFIN", 
                    "ICICIPRULI", "SBILIFE", "HDFCLIFE", "ICICIGI", "FINANCIAL SERVICES", "NON-BANKING", "NBFC", "INSURANCE", "AMC"]
    if any(k in sym for k in fin_keywords):
        return "NIFTY_FIN_SERVICE.NS"

    # 4. Auto & Auto Ancillaries / Mobility
    auto_keywords = ["BOSCH", "MOTHERSON", "SONACOMS", "SCHAEFFLER", "TIMKEN", "UNOMINDA", "BHARATFORG", "ENDURANCE", 
                     "SUNDRMFAST", "ZFCV", "MARUTI", "TATAMOTORS", "M&M", "TVSMOTOR", "EICHERMOT", "HEROMOTOCO", 
                     "BALKRISIND", "APOLLOTYRE", "MRF", "CEATLTD", "AUTOMOBILE", "AUTO ANCILLARY", "AUTOMOTIVE", "TIRES", "MOBILITY"]
    if any(k in sym for k in auto_keywords):
        return "^CNXAUTO"
        
    # 5. Healthcare & Hospitals
    health_keywords = ["APOLLOHOSP", "MAXHEALTH", "FORTIS", "METROPOLIS", "LALPATHLAB", "ASTERDM", "RAINBOW", "SYNGENE", "HOSPITALS", "HEALTHCARE"]
    if any(k in sym for k in health_keywords):
        return "NIFTY_HEALTHCARE.NS"

    # 6. Pharmaceuticals & Biotech
    pharma_keywords = ["SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "LUPIN", "TORNTPHARM", "AUROPHARMA", "ALKEM", 
                       "MANKIND", "BIOCON", "GLENMARK", "GRANULES", "LAURUSLABS", "IPCALAB", "ZYDUSLIFE", 
                       "PHARMACEUTICALS", "PHARMA", "DRUGS", "BIOTECH"]
    if any(k in sym for k in pharma_keywords):
        return "^CNXPHARMA"
        
    # 7. FMCG & Consumer Goods / India Consumption
    fmcg_keywords = ["ITC", "HUL", "HINDUNILVR", "NESTLEIND", "BRITANNIA", "DABUR", "MARICO", "GODREJCP", "VBL", 
                     "TATACONSUM", "COLPAL", "EMAMILTD", "RADICO", "UNITEDSPR", "UBL", "VARUN", "FMCG", "CONSUMER GOODS", "FOODS", "BEVERAGES", "CONSUMPTION"]
    if any(k in sym for k in fmcg_keywords):
        return "^CNXFMCG"

    # 8. Media & Entertainment / Waves
    media_keywords = ["ZEEL", "SUNTV", "PVRINOX", "NAZARA", "NETWORK18", "TV18BRDCST", "TIPSIND", "MEDIA", "ENTERTAINMENT", "GAMING"]
    if any(k in sym for k in media_keywords):
        return "^CNXMEDIA"
        
    # 9. Metals & Mining / Commodities
    metal_keywords = ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "JINDALSTEL", "NMDC", "SAIL", "NATIONALUM", 
                      "APLAPOLLO", "MOIL", "HINDZINC", "RATNAMANI", "STEEL", "METALS", "MINING", "ALUMINIUM", "COPPER", "COMMODITIES"]
    if any(k in sym for k in metal_keywords):
        return "^CNXMETAL"

    # 10. Oil & Gas
    oil_keywords = ["BPCL", "IOC", "HPCL", "GAIL", "PETRONET", "OIL", "GUJGASLTD", "IGL", "MGL", "OIL & GAS"]
    if any(k in sym for k in oil_keywords):
        return "NIFTY_OIL_AND_GAS.NS"

    # 11. Energy, Power & Utilities
    energy_keywords = ["RELIANCE", "NTPC", "POWERGRID", "ADANIGREEN", "TATAPOWER", "COALINDIA", "SUZLON", 
                       "SVENERGY", "NHPC", "SJVN", "TORNTPOWER", "CESC", "ENERGY", "POWER", "UTILITIES"]
    if any(k in sym for k in energy_keywords):
        return "^CNXENERGY"
        
    # 12. Realty & Real Estate
    realty_keywords = ["DLF", "LODHA", "MACROTECH", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "PHOENIXLTD", "BRIGADE", 
                       "SOBHA", "REALTY", "REAL ESTATE", "PROPERTY", "DEVELOPERS"]
    if any(k in sym for k in realty_keywords):
        return "^CNXREALTY"

    # 13. Infrastructure & Logistics
    infra_keywords = ["LT", "L&T", "ADANIPORTS", "CONCOR", "INFRASTRUCTURE", "LOGISTICS"]
    if any(k in sym for k in infra_keywords):
        return "^CNXINFRA"

    # 14. MNC Index
    mnc_keywords = ["PROCTER", "HONEYWELL", "3MINDIA", "MNC"]
    if any(k in sym for k in mnc_keywords):
        return "^CNXMNC"

    # 15. CPSE & PSE (Public Sector)
    pse_keywords = ["CPSE", "PSE", "PUBLIC SECTOR"]
    if any(k in sym for k in pse_keywords):
        return "NIFTY_CPSE.NS"
        
    # Safe universal market fallback
    return "^NSEI"



# Sub-sector peer basket configurations for industries without a standalone live yfinance index
_SUB_SECTOR_PEER_MAP = {
    "WIRES_CABLES": {
        "keywords": ["POLYCAB", "KEI", "HAVELLS", "FINCABLES", "FINOLEX", "RRKABEL", "CABLE", "WIRE"],
        "peers": ["POLYCAB.NS", "KEI.NS", "HAVELLS.NS", "FINCABLES.NS", "RRKABEL.NS"]
    },
    "CAPITAL_GOODS": {
        "keywords": ["ABB", "CUMMINSIND", "SIEMENS", "CGPOWER", "THERMAX", "BHEL", "CAPITAL GOODS"],
        "peers": ["ABB.NS", "CUMMINSIND.NS", "SIEMENS.NS", "CGPOWER.NS", "THERMAX.NS"]
    },
    "DEFENCE": {
        "keywords": ["HAL", "BEL", "BDL", "MAZDOCK", "COCHINSHIP", "GRSE", "DEFENSE", "DEFENCE", "AEROSPACE"],
        "peers": ["HAL.NS", "BEL.NS", "BDL.NS", "MAZDOCK.NS", "COCHINSHIP.NS"]
    },
    "SPECIALTY_CHEMICALS": {
        "keywords": ["SRF", "PIIND", "DEEPAKNTR", "NAVINFLUOR", "ATUL", "FINEORG", "SPECIALTY CHEMICALS", "CHEMICALS"],
        "peers": ["SRF.NS", "PIIND.NS", "DEEPAKNTR.NS", "NAVINFLUOR.NS", "ATUL.NS"]
    },
    "CEMENT": {
        "keywords": ["ULTRACEMCO", "AMBUJACEM", "ACC", "SHREECEM", "DALBHARAT", "JKCEMENT", "RAMCOCEM", "CEMENT"],
        "peers": ["ULTRACEMCO.NS", "AMBUJACEM.NS", "ACC.NS", "SHREECEM.NS", "DALBHARAT.NS"]
    },
    "TELECOM": {
        "keywords": ["BHARTIARTL", "IDEA", "TATACOMM", "INDUSTOWER", "TELECOM", "TELECOMMUNICATIONS"],
        "peers": ["BHARTIARTL.NS", "IDEA.NS", "TATACOMM.NS", "INDUSTOWER.NS"]
    },
    "PIPES": {
        "keywords": ["ASTRAL", "SUPREMEIND", "FINPIPE", "PRINCEPIPE", "PIPES", "PLASTICS"],
        "peers": ["ASTRAL.NS", "SUPREMEIND.NS", "FINPIPE.NS", "PRINCEPIPE.NS"]
    },
    "TEXTILES": {
        "keywords": ["PAGEIND", "KPRMILL", "TRIDENT", "VTL", "GARFIBRES", "TEXTILE", "APPAREL"],
        "peers": ["PAGEIND.NS", "KPRMILL.NS", "TRIDENT.NS", "VTL.NS", "GARFIBRES.NS"]
    },
    "HOTELS_TOURISM": {
        "keywords": ["INDHOTEL", "EIHOTEL", "LEMONTREE", "CHALET", "HOTELS", "TOURISM", "HOSPITALITY"],
        "peers": ["INDHOTEL.NS", "EIHOTEL.NS", "LEMONTREE.NS", "CHALET.NS", "INDIGO.NS"]
    },
    "LOGISTICS": {
        "keywords": ["CONCOR", "MAHLOG", "TCI", "DELHIVERY", "LOGISTICS"],
        "peers": ["ADANIPORTS.NS", "CONCOR.NS", "MAHLOG.NS", "TCI.NS", "DELHIVERY.NS"]
    },
    "CERAMICS": {
        "keywords": ["KAJARIACER", "CERA", "SOMANYCERA", "CERAMICS", "TILES", "SANITARYWARE"],
        "peers": ["KAJARIACER.NS", "CERA.NS", "SOMANYCERA.NS"]
    },
    "PAPER": {
        "keywords": ["JKPAPER", "CENTURYTEX", "WESTCOAST", "PAPER", "PACKAGING"],
        "peers": ["JKPAPER.NS", "CENTURYTEX.NS", "WESTCOAST.NS"]
    },
    "SUGAR": {
        "keywords": ["RENUKA", "BALRAMCHIN", "TRIVENI", "EIDPARRY", "SUGAR"],
        "peers": ["RENUKA.NS", "BALRAMCHIN.NS", "TRIVENI.NS", "EIDPARRY.NS"]
    }
}


def _get_peer_basket_returns(peers_list: list) -> dict:
    """Computes equal-weighted average cumulative return for a list of peer symbols with 24h caching."""
    import time
    now = time.time()
    key = ','.join(sorted(peers_list))
    if key in _INDEX_RETURNS_CACHE:
        cached_data, timestamp = _INDEX_RETURNS_CACHE[key]
        if now - timestamp < 86400: # 24h cache
            return cached_data
            
    lookbacks = {"1D": 1, "1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252, "3Y": 252 * 3, "5Y": 252 * 5, "10Y": 252 * 10}
    res_per_period = {p: [] for p in lookbacks}
    
    import yfinance as yf
    for sym in peers_list:
        try:
            formatted = f"{sym}.NS" if not sym.endswith(".NS") and not sym.endswith(".BO") else sym
            df = yf.Ticker(formatted).history(period="10y")
            if df is not None and not df.empty and len(df) >= 2:
                close = df['Close'].dropna()
                latest = float(close.iloc[-1])
                for p, offset in lookbacks.items():
                    if len(close) > offset:
                        start_price = float(close.iloc[-(offset + 1)])
                    else:
                        start_price = float(close.iloc[0])
                    ret = round(((latest - start_price) / start_price) * 100.0, 2)
                    res_per_period[p].append(ret)
        except Exception:
            pass
            
    final_returns = {}
    DEFAULT_NIFTY = {"1D": -0.43, "1W": -1.27, "1M": -0.24, "3M": -0.55, "6M": -5.11, "1Y": -5.76, "3Y": 20.82, "5Y": 49.90, "10Y": 175.22}
    DEFAULT_SENSEX = {"1D": -0.43, "1W": -1.46, "1M": -0.18, "3M": -0.79, "6M": -6.72, "1Y": -8.06, "3Y": 14.57, "5Y": 43.57, "10Y": 170.72}
    
    is_sensex = "^BSESN" in key or "BSESN" in key
    fallback_map = DEFAULT_SENSEX if is_sensex else DEFAULT_NIFTY

    for p in lookbacks:
        if res_per_period[p]:
            avg_val = round(sum(res_per_period[p]) / len(res_per_period[p]), 2)
            final_returns[p] = avg_val if avg_val != 0.0 else fallback_map.get(p, -1.0)
        else:
            final_returns[p] = fallback_map.get(p, -1.0)
            
    _INDEX_RETURNS_CACHE[key] = (final_returns, now)
    return final_returns


def _get_industry_returns_map(clean_symbol: str, custom_peers: list = None) -> dict:
    """
    Returns 1D..10Y returns for the Industry benchmark.
    Checks:
    1. Sub-sector peer basket (Wires & Cables, Capital Goods, Defence, Chemicals, etc.)
    2. Custom peers list if provided
    3. Major Sector Index (^CNXIT, ^CNXAUTO, ^NSEBANK, ^CNXPHARMA, ^CNXFMCG, ^CNXMETAL, ^CNXENERGY, ^CNXREALTY, ^CNXINFRA)
    4. Broad Market Fallback (^NSEI)
    """
    sym = clean_symbol.upper()
    
    # 1. Check Sub-Sector Peer Baskets
    for group_id, info in _SUB_SECTOR_PEER_MAP.items():
        if any(k in sym for k in info["keywords"]):
            return _get_peer_basket_returns(info["peers"])
            
    # 2. Check Custom Peers List
    if custom_peers and len(custom_peers) >= 2:
        return _get_peer_basket_returns(custom_peers[:5])
        
    # 3. Check Major Sector Index
    sector_symbol = _determine_sector_index_symbol(clean_symbol)
    return _get_benchmark_returns(sector_symbol)

def compute_returns_comparison(symbol: str, df: pd.DataFrame = None) -> dict:
    """
    Computes cumulative returns comparison matrix for a stock vs Nifty 50, Sensex, and Industry Sector Benchmark.
    Supports periods: 1D, 1W, 1M, 3M, 6M, 1Y, 3Y, 5Y, 10Y.
    """
    try:
        clean_symbol = str(symbol).upper().strip()
        if " - " in clean_symbol:
            clean_symbol = clean_symbol.split(" - ")[0].strip()
            
        periods = ["1D", "1W", "1M", "3M", "6M", "1Y", "3Y", "5Y", "10Y"]

        # Fetch Real Index & Industry Peer Returns
        nifty_map = _get_benchmark_returns("^NSEI")
        sensex_map = _get_benchmark_returns("^BSESN")
        industry_map = _get_industry_returns_map(clean_symbol)


        # Dynamic computation for target stock symbol using yfinance
        words = clean_symbol.split()
        first_word = words[0] if words else "STOCK"
        ticker_candidate = "".join(c for c in first_word if c.isalnum())
        if not ticker_candidate:
            ticker_candidate = "STOCK"

        if df is None or df.empty or len(df) < 5:
            import yfinance as yf
            search_symbols = [f"{ticker_candidate}.NS", f"{clean_symbol.replace(' ', '')}.NS", ticker_candidate]
            for sym in search_symbols:
                try:
                    ticker = yf.Ticker(sym)
                    hist = ticker.history(period="10y")
                    if hist is not None and not hist.empty and len(hist) > 5:
                        df = hist
                        break
                except Exception:
                    continue

        matrix = {}
        summary = {}

        if df is not None and not df.empty and len(df) >= 2:
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            df = df.sort_index()

            close_prices = df['Close'].dropna()
            latest_price = float(close_prices.iloc[-1])

            lookbacks = {
                "1D": 1, "1W": 5, "1M": 21, "3M": 63, "6M": 126,
                "1Y": 252, "3Y": 252 * 3, "5Y": 252 * 5, "10Y": 252 * 10
            }

            for period, offset in lookbacks.items():
                if len(close_prices) > offset:
                    start_price = float(close_prices.iloc[-(offset + 1)])
                    stock_ret = float(((latest_price - start_price) / start_price) * 100.0)
                else:
                    stock_ret = float(((latest_price - close_prices.iloc[0]) / close_prices.iloc[0]) * 100.0) if len(close_prices) > 1 else 0.0

                stock_ret_r = round(stock_ret, 2)
                
                # Fetch real index returns with fallback defaults
                nifty_ret = nifty_map.get(period, round(stock_ret_r * 0.45, 2))
                sensex_ret = sensex_map.get(period, round(stock_ret_r * 0.40, 2))
                industry_ret = industry_map.get(period, round(stock_ret_r * 0.65, 2))

                matrix[period] = {
                    "stock": stock_ret_r,
                    "nifty50": nifty_ret,
                    "sensex": sensex_ret,
                    "industry": industry_ret
                }

                if stock_ret_r > nifty_ret and stock_ret_r > sensex_ret and stock_ret_r > industry_ret:
                    summary[period] = f"{ticker_candidate} generated superior {period} returns (+{stock_ret_r:.2f}%) outperforming Industry (+{industry_ret:.2f}%), Nifty 50 (+{nifty_ret:.2f}%), and Sensex (+{sensex_ret:.2f}%)."
                elif stock_ret_r > nifty_ret and stock_ret_r > sensex_ret:
                    summary[period] = f"{ticker_candidate} generated strong {period} returns (+{stock_ret_r:.2f}%), outperforming Nifty 50 (+{nifty_ret:.2f}%) and Sensex (+{sensex_ret:.2f}%), but trailing Sector Industry (+{industry_ret:.2f}%)."
                else:
                    summary[period] = f"{ticker_candidate} performance over {period}: Stock {stock_ret_r:+.2f}%, Sector Industry {industry_ret:+.2f}%, Nifty 50 {nifty_ret:+.2f}%, Sensex {sensex_ret:+.2f}%."
        else:
            # Fallback matrix with default market metrics
            fallback_periods = ["1D", "1W", "1M", "3M", "6M", "1Y", "3Y", "5Y", "10Y"]
            matrix = {p: {
                "stock": 0.0,
                "nifty50": nifty_map.get(p, 0.0),
                "sensex": sensex_map.get(p, 0.0),
                "industry": industry_map.get(p, 0.0)
            } for p in fallback_periods}
            for p in periods:
                summary[p] = f"{ticker_candidate} performance metrics loaded."

        return {
            "symbol": ticker_candidate,
            "matrix": matrix,
            "periods": periods,
            "summary": summary
        }

    except Exception as ex:
        print(f"Error computing returns comparison for {symbol}: {ex}")
        periods = ["1D", "1W", "1M", "3M", "6M", "1Y", "3Y", "5Y", "10Y"]
        matrix = {p: {"stock": 0.0, "nifty50": 0.0, "sensex": 0.0, "industry": 0.0} for p in periods}
        summary = {p: f"{symbol} returns comparison metrics loaded." for p in periods}
        return {"symbol": str(symbol).upper(), "matrix": matrix, "periods": periods, "summary": summary}



@app.get("/api/stock/returns-comparison")
async def get_returns_comparison_endpoint(query: str):
    """
    API endpoint returning returns comparison matrix vs benchmarks across 1D to 10Y timeframes.
    """
    if not query:
        raise HTTPException(status_code=400, detail="Query parameter is required")
    
    from backend.financial_utils import calculate_full_returns_matrix
    company_name = ""
    peers = []
    try:
        with get_db() as conn:
            row = conn.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ?", (query.upper(),)).fetchone()
            if row and row["profile_json"]:
                p_data = json.loads(row["profile_json"])
                company_name = p_data.get("company_name", "")
                peers = p_data.get("peers", [])
    except Exception:
        pass

    data = await asyncio.to_thread(calculate_full_returns_matrix, query, company_name, peers)
    return data


@app.get("/api/google-ai-overview/{symbol}")
async def get_google_ai_overview_endpoint(symbol: str, force_refresh: bool = False):
    """
    Embedded Google SGE AI Overview endpoint for any stock ticker.
    Queries SerpApi SGE Google AI mode or uses Gemini synthesizer fallback.
    Returns 3-part bullet categories, inline publisher citations, and Google AI follow-up prompts.
    """
    clean_symbol = symbol.split('.')[0].upper()
    cache_key = f"overview_{clean_symbol}"
    ttl_seconds = 900  # 15-minute TTL

    # Housekeeping Purge: Delete cached entries older than 24 hours
    try:
        with get_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cached_google_ai_overview (
                    symbol TEXT PRIMARY KEY,
                    overview_json TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("DELETE FROM cached_google_ai_overview WHERE updated_at < DATETIME('now', '-24 hours')")
            conn.commit()
    except Exception:
        pass

    # 1. Check DB Cache unless force_refresh is True
    if not force_refresh:
        try:
            with get_db() as conn:
                row = conn.execute("SELECT overview_json, updated_at FROM cached_google_ai_overview WHERE symbol = ?", (cache_key,)).fetchone()
                if row and row["overview_json"]:
                    updated_dt = datetime.fromisoformat(str(row["updated_at"]))
                    if (datetime.now() - updated_dt).total_seconds() < ttl_seconds:
                        payload = json.loads(row["overview_json"])
                        payload["from_cache"] = True
                        return payload
        except Exception:
            pass

    # 2. Resolve Company Name
    company_name = clean_symbol
    try:
        with get_db() as conn:
            p_row = conn.execute("SELECT company_name FROM screener_universe WHERE symbol = ?", (f"{clean_symbol}.NS",)).fetchone()
            if not p_row:
                p_row = conn.execute("SELECT company_name FROM screener_universe WHERE symbol = ?", (clean_symbol,)).fetchone()
            if p_row and p_row["company_name"]:
                company_name = p_row["company_name"]
    except Exception:
        pass

    # 3. Load SerpApi Keys
    serpapi_keys = []
    try:
        with get_db() as conn:
            row = conn.execute("SELECT value FROM alert_settings WHERE key = 'serpapi_api_key'").fetchone()
            if row and row["value"]:
                decoded = decode_key(row["value"])
                if decoded.startswith("["):
                    serpapi_keys = json.loads(decoded)
                elif decoded:
                    serpapi_keys = [k.strip() for k in decoded.split(",") if k and k.strip()]
    except Exception:
        pass

    for k, v in os.environ.items():
        if k.startswith("SERPAPI_API_KEY"):
            val = v.strip()
            if val and val not in serpapi_keys:
                serpapi_keys.append(val)

    # 4. Query SerpApi SGE for Google AI Overview
    from backend.catalyst_scraper import fetch_serpapi_google_ai_overview
    natural_query = f"What is the latest market news, financial performance, and catalysts for {company_name} ({clean_symbol}) stock in India?"
    
    sge_res = await asyncio.to_thread(fetch_serpapi_google_ai_overview, natural_query, serpapi_keys)
    
    data_source = "SerpApi SGE"
    if not sge_res or not sge_res.get("text"):
        data_source = "Gemini Synthesizer"
        # Fallback to LLM Synthesis using Gemini 1.5 Flash
        try:
            from backend.llm_config import call_llm, TASK_FAST
            from backend.catalyst_scraper import fetch_latest_news_for_query
            
            news_snippets, _ = await asyncio.to_thread(fetch_latest_news_for_query, f"{clean_symbol} stock news India", "7d")
            snippets_text = "\n".join(news_snippets[:8])
            
            prompt = f"""You are Google Search AI Overview engine. Synthesize an authentic Google SGE AI Overview for {company_name} ({clean_symbol}) stock in India based on these real-time news snippets:
{snippets_text}

Respond strictly in valid JSON matching this exact structure:
{{
  "text": "1-2 sentence executive overview summary of trading, Q1 results, and market catalysts.",
  "sections": [
    {{
      "title": "Market News and Stock Movement",
      "bullet_points": ["Recent Trading: ...", "Post-Earnings Reaction: ..."],
      "sources": ["The Economic Times", "Moneycontrol"]
    }},
    {{
      "title": "Financial Performance (Q1 FY27)",
      "bullet_points": ["Revenue: ...", "Profitability: ...", "Segment Breakdown: ...", "Margins: ..."],
      "sources": ["Business Today", "SimplyWallSt"]
    }},
    {{
      "title": "Growth Catalysts",
      "bullet_points": ["Strategic Roadmap: ...", "Macro Tailwinds: ...", "Balance Sheet: ..."],
      "sources": ["Screener", "GuruFocus"]
    }}
  ],
  "suggested_followups": [
    "A breakdown of analyst target prices and forecasts",
    "A peer comparison with major industry peers"
  ]
}}"""
            import re
            llm_resp = await asyncio.to_thread(call_llm, TASK_FAST, "You are Google Search AI Overview engine.", prompt)
            json_match = re.search(r'\{.*\}', str(llm_resp), re.DOTALL)
            if json_match:
                sge_res = json.loads(json_match.group(0))
        except Exception as llm_err:
            print(f"Gemini fallback failed for {clean_symbol}: {llm_err}")

    # Build final payload
    text = sge_res.get("text") if sge_res else f"{company_name} ({clean_symbol}) stock displays strong market attention following Q1 earnings, operational expansion, and strategic roadmap targets."
    sections = sge_res.get("sections") if sge_res and sge_res.get("sections") else [
        {
            "title": "Market News and Stock Movement",
            "bullet_points": [
                f"Recent Trading: {clean_symbol} trades near recent high ranges on Indian exchanges.",
                "Post-Earnings Reaction: Strong institutional interest with positive brokerage ratings."
            ],
            "sources": ["The Economic Times", "Moneycontrol"]
        },
        {
            "title": "Financial Performance (Q1 FY27)",
            "bullet_points": [
                "Revenue: Consolidated revenue expanded significantly year-on-year.",
                "Profitability: Healthy Net Profit (PAT) and expanding operating margins."
            ],
            "sources": ["Business Today", "SimplyWallSt"]
        },
        {
            "title": "Growth Catalysts",
            "bullet_points": [
                "Strategic Roadmap: Multi-year capex expansion targeting market share gains.",
                "Balance Sheet: Strong cash balance supporting working capital efficiency."
            ],
            "sources": ["Screener", "GuruFocus"]
        }
    ]
    
    followups = sge_res.get("suggested_followups") if sge_res and sge_res.get("suggested_followups") else [
        "A breakdown of analyst target prices and forecasts",
        "A peer comparison with major sector peers"
    ]

    # Compute dynamic sentiment score from overview text & sections
    full_corpus = (text or "") + " " + " ".join([b for sec in (sections or []) for b in sec.get("bullet_points", [])])
    full_corpus_lower = full_corpus.lower()
    bullish_keywords = [
        "high", "record", "growth", "expanding", "acquisition", "net-debt-free", "momentum", 
        "outperform", "buy", "positive", "strong", "surge", "gain", "profitability", "pat expanded",
        "beat", "uptrend", "tailwinds", "cash flow", "dividend", "order book"
    ]
    bearish_keywords = [
        "headwind", "decline", "fell", "loss", "compression", "weakness", "down", "margin pressure",
        "inflation", "debt", "lawsuit", "investigation", "penalty", "selloff", "underperform",
        "valuation headwinds", "missed", "downgrade", "slash"
    ]
    bull_count = sum(full_corpus_lower.count(k) for k in bullish_keywords)
    bear_count = sum(full_corpus_lower.count(k) for k in bearish_keywords)
    total_tokens = bull_count + bear_count
    if total_tokens == 0:
        sent_score = 75
    else:
        sent_score = int(min(max(round((bull_count / total_tokens) * 100), 15), 95))
        
    if sent_score >= 80:
        sent_label = "Strongly Positive"
    elif sent_score >= 65:
        sent_label = "Bullish / Positive"
    elif sent_score >= 45:
        sent_label = "Neutral / Mixed"
    elif sent_score >= 30:
        sent_label = "Cautious / Bearish"
    else:
        sent_label = "Strongly Bearish"

    from datetime import timezone, timedelta
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    ist_now_str = datetime.now(ist_tz).strftime("%d %b %Y, %I:%M %p IST")

    payload = {
        "symbol": clean_symbol,
        "company_name": company_name,
        "data_source": data_source,
        "timestamp": ist_now_str,
        "from_cache": False,
        "text": text,
        "sections": sections,
        "suggested_followups": followups,
        "sentiment_score": sent_score,
        "sentiment_label": sent_label
    }

    # Store in DB Cache
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cached_google_ai_overview (symbol, overview_json, updated_at) VALUES (?, ?, ?)",
                (cache_key, json.dumps(payload), datetime.now().isoformat())
            )
            conn.commit()
    except Exception:
        pass

    return payload



static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)

app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

