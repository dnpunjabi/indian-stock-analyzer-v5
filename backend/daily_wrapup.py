import os
import json
import sqlite3
import asyncio
from datetime import datetime
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup

from backend.main import get_db, compute_active_holdings, fetch_enriched_sector_regime, _MARKET_MOVERS_CACHE, get_market_news
from backend.financial_utils import get_complete_financial_profile
from backend.llm_config import call_llm, TASK_FAST

def fetch_portfolio_summary() -> dict:
    """
    Computes active holdings using FIFO netting and aggregates their performance.
    Calculates total daily valuation changes (both absolute in INR and percentage).
    Identifies top gainer and top loser in active holdings.
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, symbol, name, sector, quantity, purchase_price, purchase_date, transaction_type FROM portfolio_items")
            all_txs = [dict(row) for row in cursor.fetchall()]
        
        # Calculate active holdings dynamically via FIFO netting
        active_holdings = compute_active_holdings(all_txs)
        if not active_holdings:
            return {"active": False}

        symbols = list(set(h["symbol"] for h in active_holdings))
        
        # Batch fetch price information using yfinance
        quotes = {}
        try:
            df = yf.download(symbols, period="2d", interval="1d", progress=False)
            if not df.empty:
                is_multi = isinstance(df.columns, pd.MultiIndex)
                for sym in symbols:
                    try:
                        if is_multi:
                            close_series = df['Close'][sym].dropna()
                        else:
                            close_series = df['Close'].dropna()
                        
                        if len(close_series) >= 1:
                            current_price = float(close_series.iloc[-1])
                            prev_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else current_price
                            day_change_pct = ((current_price - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0
                            day_change_val = current_price - prev_close
                            quotes[sym] = {
                                "current_price": current_price,
                                "day_change_pct": day_change_pct,
                                "day_change_val": day_change_val
                            }
                    except Exception:
                        pass
        except Exception as batch_err:
            print(f"Daily Wrap-up: Portfolio batch download failed: {batch_err}")

        # Fallback to cached profiles if batch failed or is incomplete
        with get_db() as conn:
            cursor = conn.cursor()
            for h in active_holdings:
                sym = h["symbol"]
                if sym not in quotes:
                    cursor.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ?", (sym,))
                    cache_row = cursor.fetchone()
                    if cache_row:
                        try:
                            profile = json.loads(cache_row["profile_json"])
                            curr = profile.get("fundamentals", {}).get("current_price")
                            chg = profile.get("technicals", {}).get("price_change_pct") or 0.0
                            if curr:
                                prev = curr / (1 + (chg / 100.0))
                                quotes[sym] = {
                                    "current_price": curr,
                                    "day_change_pct": chg,
                                    "day_change_val": curr - prev
                                }
                        except Exception:
                            pass
                
                # Ultimate yfinance fallback
                if sym not in quotes:
                    try:
                        ticker = yf.Ticker(sym)
                        info = ticker.info
                        curr = info.get("currentPrice") or info.get("regularMarketPrice")
                        prev = info.get("previousClose")
                        if curr and prev:
                            quotes[sym] = {
                                "current_price": curr,
                                "day_change_pct": ((curr - prev) / prev * 100.0),
                                "day_change_val": curr - prev
                            }
                    except Exception:
                        pass

        # Calculate portfolio performance totals
        total_cost = 0.0
        total_value = 0.0
        total_daily_change_val = 0.0
        
        enriched_holdings = []
        for h in active_holdings:
            sym = h["symbol"]
            qty = h["quantity"]
            purchase_price = h["purchase_price"]
            
            quote = quotes.get(sym, {"current_price": purchase_price, "day_change_pct": 0.0, "day_change_val": 0.0})
            curr_p = quote["current_price"]
            day_chg_pct = quote["day_change_pct"]
            day_chg_val = quote["day_change_val"]
            
            total_cost += qty * purchase_price
            total_value += qty * curr_p
            total_daily_change_val += qty * day_chg_val
            
            enriched_holdings.append({
                "symbol": sym,
                "name": h.get("name") or sym,
                "qty": qty,
                "cost": qty * purchase_price,
                "value": qty * curr_p,
                "day_change_pct": day_chg_pct,
                "day_change_val": qty * day_chg_val
            })

        total_daily_change_pct = (total_daily_change_val / (total_value - total_daily_change_val) * 100.0) if (total_value - total_daily_change_val) > 0 else 0.0
        total_return_val = total_value - total_cost
        total_return_pct = (total_return_val / total_cost * 100.0) if total_cost > 0 else 0.0

        # Sort holdings by day_change_pct to find leaders/laggards
        enriched_holdings.sort(key=lambda x: x["day_change_pct"], reverse=True)
        top_gainer = enriched_holdings[0] if enriched_holdings else None
        top_loser = enriched_holdings[-1] if enriched_holdings else None

        # Check for distressed assets
        distressed_symbols = []
        for h in active_holdings:
            sym = h["symbol"]
            try:
                profile = get_complete_financial_profile(sym)
                eq = profile.get("earnings_quality", {})
                piotroski = eq.get("piotroski_score", 5)
                altman_z = eq.get("altman_z_score", 3.0)
                if altman_z < 1.81 or piotroski < 4:
                    distressed_symbols.append(sym.replace(".NS", "").replace(".BO", ""))
            except Exception:
                pass

        return {
            "active": True,
            "total_cost": total_cost,
            "total_value": total_value,
            "total_daily_change_val": total_daily_change_val,
            "total_daily_change_pct": total_daily_change_pct,
            "total_return_val": total_return_val,
            "total_return_pct": total_return_pct,
            "top_gainer": top_gainer,
            "top_loser": top_loser,
            "distressed_symbols": distressed_symbols
        }
    except Exception as e:
        print(f"Daily Wrap-up: Portfolio aggregation error: {e}")
        return {"active": False}

def fetch_watchlist_summary() -> dict:
    """
    Gathers all watchlist stock tickers and fetches their daily returns.
    Identifies top watchlist gainers and losers.
    """
    try:
        symbols = set()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol FROM watchlist_items")
            for row in cursor.fetchall():
                symbols.add(row["symbol"])
                
        if not symbols:
            return {"active": False}
            
        watchlist_items = []
        try:
            df = yf.download(list(symbols), period="2d", interval="1d", progress=False)
            if not df.empty:
                is_multi = isinstance(df.columns, pd.MultiIndex)
                for sym in symbols:
                    try:
                        if is_multi:
                            close_series = df['Close'][sym].dropna()
                        else:
                            close_series = df['Close'].dropna()
                        if len(close_series) >= 1:
                            curr = float(close_series.iloc[-1])
                            prev = float(close_series.iloc[-2]) if len(close_series) >= 2 else curr
                            chg_pct = ((curr - prev) / prev * 100.0) if prev > 0 else 0.0
                            watchlist_items.append({
                                "symbol": sym,
                                "price": curr,
                                "change_pct": chg_pct
                            })
                    except Exception:
                        pass
        except Exception as w_err:
            print(f"Daily Wrap-up: Watchlist batch fetch failed: {w_err}")
            
        if not watchlist_items:
            return {"active": False}
            
        # Sort items by change_pct
        watchlist_items.sort(key=lambda x: x["change_pct"], reverse=True)
        gainers = [x for x in watchlist_items if x["change_pct"] > 0][:2]
        losers = [x for x in watchlist_items if x["change_pct"] < 0]
        # Sort losers ascending so top loser is first
        losers.sort(key=lambda x: x["change_pct"])
        losers = losers[:2]
        
        return {
            "active": True,
            "gainers": gainers,
            "losers": losers
        }
    except Exception as e:
        print(f"Daily Wrap-up: Watchlist aggregation error: {e}")
        return {"active": False}

def fetch_sector_momentum() -> dict:
    """
    Fetches daily sector returns from sector_regime_stats table.
    Ranks them to isolate top 2 strongest and top 2 weakest sectors.
    Finds leading and lagging stocks inside each sector.
    """
    try:
        with get_db() as conn:
            sectors = fetch_enriched_sector_regime(conn)
            
        if not sectors:
            return {"active": False}
            
        # Sort sectors by return_1d
        sectors_sorted = [s for s in sectors if s.get("return_1d") is not None]
        sectors_sorted.sort(key=lambda x: x["return_1d"], reverse=True)
        
        strongest = sectors_sorted[:2]
        weakest = sectors_sorted[-2:] if len(sectors_sorted) >= 4 else sectors_sorted[2:]
        weakest.reverse() # Sort worst performing first
        
        def enrich_sector_detail(sec_list):
            results = []
            for s in sec_list:
                sec_name = s["sector"]
                ret_1d = s["return_1d"]
                stocks = s.get("stocks", [])
                
                leader = None
                laggard = None
                if stocks:
                    # Sort stocks by return_1d
                    stocks_sorted = sorted(stocks, key=lambda x: x.get("return_1d", 0.0), reverse=True)
                    leader = stocks_sorted[0]
                    laggard = stocks_sorted[-1]
                    
                results.append({
                    "name": sec_name,
                    "return_1d": ret_1d,
                    "leader": leader,
                    "laggard": laggard
                })
            return results

        return {
            "active": True,
            "strongest": enrich_sector_detail(strongest),
            "weakest": enrich_sector_detail(weakest)
        }
    except Exception as e:
        print(f"Daily Wrap-up: Sector momentum aggregation error: {e}")
        return {"active": False}

async def fetch_global_news_summary() -> list:
    """
    Queries the latest global news items from the local feed cache.
    Extracts the top 3 headlines featuring high-impact Bullish or Bearish sentiments.
    """
    try:
        data = await get_market_news(refresh=False, run_llm=False)
        news_items = data.get("news_items", [])
        if not news_items:
            return []
            
        # Filter for items with clear sentiment if possible
        impactful = [n for n in news_items if n.get("sentiment") in ["Bullish", "Bearish"]]
        if len(impactful) < 3:
            impactful += [n for n in news_items if n not in impactful]
            
        selected_news = impactful[:3]
        formatted = []
        for n in selected_news:
            source = n.get("source", "Market News")
            sentiment = n.get("sentiment", "Neutral")
            title = n.get("title", "")
            
            emoji = "⚪"
            if sentiment == "Bullish":
                emoji = "🟢"
            elif sentiment == "Bearish":
                emoji = "🔴"
                
            formatted.append({
                "source": source,
                "emoji": emoji,
                "title": title
            })
        return formatted
    except Exception as e:
        print(f"Daily Wrap-up: Global news fetch error: {e}")
        return []

def fetch_upcoming_events_summary(portfolio_symbols: list, watchlist_symbols: list, days: int = 7) -> dict:
    """
    Queries SQLite cache for upcoming results, dividends, splits, bonuses in the next 7 days.
    Capped at 3 details for portfolio holdings, with watchlist aggregated into a count.
    """
    from datetime import date, timedelta
    import json
    
    result = {
        "portfolio_text": "",
        "watchlist_count": 0
    }
    
    port_set = {s.replace(".NS", "").replace(".BO", "").strip().upper() for s in portfolio_symbols if s}
    watch_set = {s.replace(".NS", "").replace(".BO", "").strip().upper() for s in watchlist_symbols if s}
    
    today_str = date.today().isoformat()
    end_str = (date.today() + timedelta(days=days)).isoformat()
    
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT symbol, event_type, event_date, description, details_json 
                   FROM stock_events 
                   WHERE event_date >= ? AND event_date <= ? 
                   ORDER BY event_date ASC, symbol ASC""",
                (today_str, end_str)
            )
            rows = [dict(r) for r in cursor.fetchall()]
            
        port_events = []
        watch_events_count = 0
        
        for r in rows:
            sym = r["symbol"].upper()
            if sym in port_set:
                port_events.append(r)
            elif sym in watch_set:
                watch_events_count += 1
                
        lines = []
        event_labels = {
            "quarterly_results": "Results",
            "dividend": "Dividend",
            "split": "Split",
            "bonus": "Bonus",
            "rights": "Rights",
            "buyback": "Buyback"
        }
        
        for ev in port_events[:3]:
            lbl = event_labels.get(ev["event_type"], ev["event_type"].title().replace("_", " "))
            try:
                date_obj = datetime.strptime(ev["event_date"], "%Y-%m-%d")
                date_fmt = date_obj.strftime("%d-%b")
            except Exception:
                date_fmt = ev["event_date"]
            
            detail_str = ""
            if ev["details_json"]:
                try:
                    details = json.loads(ev["details_json"])
                    if ev["event_type"] == "dividend":
                        rate = details.get("dividend_rate") or details.get("trailing_annual_rate")
                        if rate:
                            detail_str = f" (₹{float(rate):.2f})"
                    elif ev["event_type"] == "split":
                        ratio = details.get("split_factor")
                        if ratio:
                            detail_str = f" ({ratio})"
                except Exception:
                    pass
            lines.append(f"• {ev['symbol']}: {lbl} ({date_fmt}){detail_str}")
            
        if len(port_events) > 3:
            lines.append(f"• ...and {len(port_events) - 3} other portfolio events.")
            
        result["portfolio_text"] = "\n".join(lines) if lines else "_No upcoming portfolio events scheduled._"
        result["watchlist_count"] = watch_events_count
        
    except Exception as e:
        print(f"Daily Wrap-up: Events summary error: {e}")
        result["portfolio_text"] = "_Failed to fetch upcoming events._"
        
    return result

def fetch_recent_deals_summary(portfolio_symbols: list, watchlist_symbols: list, days: int = 3) -> dict:
    """
    Queries SQLite cache for promoter & large institutional trades in the last 3 days.
    Capped at 3 details for portfolio holdings, with watchlist aggregated into a count.
    """
    from datetime import datetime, timedelta
    import json
    
    result = {
        "portfolio_text": "",
        "watchlist_count": 0
    }
    
    port_set = {s.replace(".NS", "").replace(".BO", "").strip().upper() for s in portfolio_symbols if s}
    watch_set = {s.replace(".NS", "").replace(".BO", "").strip().upper() for s in watchlist_symbols if s}
    
    def parse_deal_date(date_str):
        if not date_str:
            return datetime.min
        for fmt in ('%d %b %Y', '%b %Y', '%Y-%m-%d'):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                pass
        return datetime.min
        
    now = datetime.now()
    cutoff = now - timedelta(days=days)
    
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, data_json FROM cached_trades")
            rows = [dict(r) for r in cursor.fetchall()]
            
        all_deals = []
        for r in rows:
            symbol = r["symbol"].upper()
            try:
                data = json.loads(r["data_json"])
            except Exception:
                continue
                
            for item in data.get("insider_trades", []):
                item["category"] = "Insider"
                item["symbol"] = symbol
                all_deals.append(item)
                
            for item in data.get("bulk_deals", []):
                item["category"] = "Bulk"
                item["symbol"] = symbol
                all_deals.append(item)
                
            for item in data.get("block_deals", []):
                item["category"] = "Block"
                item["symbol"] = symbol
                all_deals.append(item)
                
            for item in data.get("sast_deals", []):
                item["category"] = "SAST"
                item["symbol"] = symbol
                all_deals.append(item)
                
        port_deals = []
        watch_deals_count = 0
        
        for d in all_deals:
            deal_dt = parse_deal_date(d.get("date"))
            if deal_dt == datetime.min or deal_dt < cutoff:
                continue
                
            sym = d["symbol"]
            if sym in port_set:
                port_deals.append(d)
            elif sym in watch_set:
                watch_deals_count += 1
                
        # Sort portfolio deals by value descending
        port_deals.sort(key=lambda x: x.get("value", 0), reverse=True)
        
        lines = []
        def format_indian_rupees(num):
            if not num:
                return "₹0"
            if num >= 10000000:
                return f"₹{num / 10000000:.2f} Cr"
            elif num >= 100000:
                return f"₹{num / 100000:.2f} L"
            return f"₹{num:,.0f}"
            
        for d in port_deals[:3]:
            val_str = format_indian_rupees(d.get("value", 0))
            category = d.get("category", "Insider")
            dtype = d.get("type", "Trade")
            person = d.get("person", "")
            if len(person) > 20:
                person = person[:18] + ".."
                
            if category == "Insider":
                lines.append(f"• {d['symbol']}: Promoter {dtype} of {val_str} ({person})")
            else:
                lines.append(f"• {d['symbol']}: {category} {dtype} of {val_str} ({person})")
                
        if len(port_deals) > 3:
            lines.append(f"• ...and {len(port_deals) - 3} other portfolio deals.")
            
        result["portfolio_text"] = "\n".join(lines) if lines else "_No recent promoter or institutional deals._"
        result["watchlist_count"] = watch_deals_count
        
    except Exception as e:
        print(f"Daily Wrap-up: Deals summary error: {e}")
        result["portfolio_text"] = "_No recent promoter or institutional deals._"
        
    return result

def fetch_market_sentiment_header() -> str:
    """
    Computes market sentiment index score (0 to 100 Fear & Greed scale) using India VIX 
    and actual Advances/Declines stock counts across the scanned stock universe.
    Returns a clean, transparent header line for the daily report.
    """
    vix_val = 14.50
    vix_chg = 0.0
    try:
        df = yf.download("^INDIAVIX", period="2d", interval="1d", progress=False)
        if not df.empty:
            close_s = df['Close'].dropna()
            if isinstance(close_s, pd.DataFrame):
                close_s = close_s.iloc[:, 0]
            if len(close_s) >= 1:
                vix_val = float(close_s.values[-1])
                prev_vix = float(close_s.values[-2]) if len(close_s) >= 2 else vix_val
                vix_chg = ((vix_val - prev_vix) / prev_vix * 100.0) if prev_vix > 0 else 0.0
    except Exception as e:
        print(f"Daily Wrap-up: VIX fetch error: {e}")
        
    import backend.main as bmain
    cache = bmain._MARKET_MOVERS_CACHE or {}
    adv = cache.get("advances", 0)
    dec = cache.get("declines", 0)
    
    # Fallback to database cached profiles if market movers cache is empty
    if adv == 0 and dec == 0:
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT profile_json FROM cached_profiles")
                rows = cursor.fetchall()
                for r in rows:
                    if r["profile_json"]:
                        p_data = json.loads(r["profile_json"])
                        chg = p_data.get("technicals", {}).get("price_change_pct", 0.0)
                        if chg > 0:
                            adv += 1
                        elif chg < 0:
                            dec += 1
        except Exception as db_err:
            print(f"Daily Wrap-up: DB breadth calculation fallback error: {db_err}")
            
    tot = max(1, adv + dec)
    breadth_ratio = (adv / tot) * 100.0
    
    # Low VIX + High Breadth = High Bullish Sentiment Index Score (0 to 100 scale)
    vix_score = max(0.0, min(100.0, 120.0 - (vix_val * 3.0)))
    sentiment_score = int(round((0.6 * breadth_ratio) + (0.4 * vix_score)))
    
    regime = "Bullish 🚀" if sentiment_score >= 65 else ("Bearish 🔴" if sentiment_score <= 40 else "Neutral 🟡")
    vix_sign = "+" if vix_chg >= 0 else ""
    breadth_str = f"{adv} Adv / {dec} Dec" if (adv + dec) > 0 else "N/A"
    
    return f"🎯 *Market Sentiment Index:* {regime} (`{sentiment_score}/100`) | Breadth: `{breadth_str}` | India VIX: `{vix_val:.2f} ({vix_sign}{vix_chg:.2f}%)`\n"

def fetch_52w_breakouts(portfolio_symbols: list, watchlist_symbols: list) -> str:
    """
    Scans portfolio and watchlist tickers for 52-week High breakouts or 52-week Low breakdowns.
    """
    all_syms = list(set([s.strip().upper() for s in portfolio_symbols + watchlist_symbols if s]))
    if not all_syms:
        return ""
        
    high_breakouts = []
    low_breakdowns = []
    
    try:
        df = yf.download(all_syms, period="1y", interval="1d", progress=False)
        if not df.empty:
            is_multi = isinstance(df.columns, pd.MultiIndex)
            for sym in all_syms:
                try:
                    if is_multi:
                        close_s = df['Close'][sym].dropna()
                        high_s = df['High'][sym].dropna()
                        low_s = df['Low'][sym].dropna()
                    else:
                        close_s = df['Close'].dropna()
                        high_s = df['High'].dropna()
                        low_s = df['Low'].dropna()
                        
                    if len(close_s) >= 20:
                        curr_p = float(close_s.iloc[-1])
                        yr_high = float(high_s.max())
                        yr_low = float(low_s.min())
                        sym_clean = sym.replace(".NS", "").replace(".BO", "")
                        
                        if curr_p >= (yr_high * 0.995):
                            high_breakouts.append(f"{sym_clean} (`₹{curr_p:,.2f}`)")
                        elif curr_p <= (yr_low * 1.005):
                            low_breakdowns.append(f"{sym_clean} (`₹{curr_p:,.2f}`)")
                except Exception:
                    pass
    except Exception as e:
        print(f"Daily Wrap-up: 52W breakout scan error: {e}")
        
    if not high_breakouts and not low_breakdowns:
        return ""
        
    res = "🚀 *52W BREAKOUT RADAR*\n"
    if high_breakouts:
        res += f"• 🟢 *52W Highs:* {', '.join(high_breakouts[:4])}\n"
    if low_breakdowns:
        res += f"• 🔴 *52W Lows:* {', '.join(low_breakdowns[:4])}\n"
    res += "\n"
    return res

def fetch_smart_money_delivery_radar(portfolio_symbols: list, watchlist_symbols: list) -> str:
    """
    Scans portfolio and watchlist tickers for unusual volume surges and high delivery % accumulation.
    """
    all_syms = list(set([s.strip().upper() for s in portfolio_symbols + watchlist_symbols if s]))
    if not all_syms:
        return ""
        
    delivery_map = {}
    hist_deliv_map = {}
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, delivery_percentage, delivery_qty, traded_qty FROM daily_delivery_stats")
            for r in cursor.fetchall():
                sym = r["symbol"].upper()
                delivery_map[sym] = {
                    "deliv_pct": float(r["delivery_percentage"] or 0.0),
                    "deliv_qty": int(r["delivery_qty"] or 0),
                    "traded_qty": int(r["traded_qty"] or 0)
                }
            
            cursor.execute("""
                SELECT symbol, 
                       AVG(delivery_percentage) as avg_deliv_pct, 
                       AVG(delivery_qty) as avg_deliv_qty
                FROM daily_delivery_history
                WHERE trade_date >= date('now', '-15 days')
                GROUP BY symbol
            """)
            for r in cursor.fetchall():
                sym = r["symbol"].upper()
                hist_deliv_map[sym] = {
                    "avg_deliv_pct": float(r["avg_deliv_pct"] or 0.0),
                    "avg_deliv_qty": float(r["avg_deliv_qty"] or 0.0)
                }
    except Exception as e:
        print(f"Daily Wrap-up: Delivery stats DB error: {e}")

    spikes = []
    try:
        df = yf.download(all_syms, period="15d", interval="1d", progress=False)
        if not df.empty:
            is_multi = isinstance(df.columns, pd.MultiIndex)
            for sym in all_syms:
                try:
                    if is_multi:
                        vols = df['Volume'][sym].dropna()
                        closes = df['Close'][sym].dropna()
                    else:
                        vols = df['Volume'].dropna()
                        closes = df['Close'].dropna()
                        
                    if len(vols) >= 5:
                        curr_vol = float(vols.iloc[-1])
                        avg_10d_vol = float(vols.iloc[-11:-1].mean()) if len(vols) >= 11 else float(vols.iloc[:-1].mean())
                        curr_p = float(closes.iloc[-1])
                        prev_p = float(closes.iloc[-2]) if len(closes) >= 2 else curr_p
                        p_chg = ((curr_p - prev_p) / prev_p * 100.0) if prev_p > 0 else 0.0
                        
                        vol_ratio = (curr_vol / avg_10d_vol) if avg_10d_vol > 0 else 1.0
                        sym_base = sym.replace(".NS", "").replace(".BO", "")
                        
                        db_stats = delivery_map.get(sym_base, delivery_map.get(sym, {}))
                        deliv_pct = db_stats.get("deliv_pct", 52.5)
                        
                        hist_stats = hist_deliv_map.get(sym_base, hist_deliv_map.get(sym, {}))
                        avg_deliv_pct = hist_stats.get("avg_deliv_pct", 40.0)
                        
                        deliv_pct_surge = (deliv_pct / avg_deliv_pct) if avg_deliv_pct > 0 else 1.0
                        
                        if vol_ratio >= 1.5 or deliv_pct >= 55.0 or deliv_pct_surge >= 1.4:
                            signal = "Strong institutional accumulation" if p_chg >= 0 else "Institutional distribution"
                            spikes.append(f"• *{sym_base}*: `{deliv_pct:.1f}% Delivery` (`{vol_ratio:.1f}x` 10-day avg volume) — _{signal}_")
                except Exception:
                    pass
    except Exception as e:
        print(f"Daily Wrap-up: Volume radar error: {e}")
        
    if not spikes:
        return ""
        
    res = "📦 *SMART MONEY ACCUMULATION RADAR*\n"
    res += "\n".join(spikes[:4]) + "\n\n"
    return res

def fetch_fii_dii_daily_flows() -> dict:
    """
    Scrapes live FII and DII net cash activity (in ₹ Cr) from Economic Times.
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        res = requests.get('https://economictimes.indiatimes.com/markets/fii-dii-activity', headers=headers, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            for table in soup.find_all('table'):
                rows = table.find_all('tr')
                for i, r in enumerate(rows):
                    text = r.get_text()
                    if 'FII Cash' in text and 'DII Cash' in text:
                        if i + 1 < len(rows):
                            data_cols = [c.get_text(strip=True) for c in rows[i+1].find_all(['td', 'th']) if c.get_text(strip=True)]
                            if len(data_cols) >= 2:
                                fii_val = float(data_cols[0].replace(',', ''))
                                dii_val = float(data_cols[1].replace(',', ''))
                                return {
                                    'fii_net': fii_val,
                                    'dii_net': dii_val,
                                    'active': True
                                }
    except Exception as e:
        print(f"Daily Wrap-up: FII/DII fetch error: {e}")
    return {'active': False}

def fetch_tech_levels(symbol: str) -> dict:
    """
    Calculates Pivot, Support (S1) and Resistance (R1) levels for a given ticker symbol.
    """
    try:
        ticker_sym = symbol if symbol.endswith('.NS') or symbol.endswith('.BO') or symbol.startswith('^') else f'{symbol}.NS'
        df = yf.Ticker(ticker_sym).history(period='1mo')
        if not df.empty and len(df) >= 2:
            high = float(df['High'].iloc[-2])
            low = float(df['Low'].iloc[-2])
            close = float(df['Close'].iloc[-2])
            pivot = (high + low + close) / 3.0
            r1 = (2.0 * pivot) - low
            s1 = (2.0 * pivot) - high
            return {'s1': round(s1, 2), 'r1': round(r1, 2)}
    except Exception as e:
        print(f"Daily Wrap-up: Tech levels error for {symbol}: {e}")
    return {}

async def generate_daily_wrapup_text(persona_override: str = None, is_weekly_override: bool = False) -> str:
    """
    Assembles data from all components, invokes LLM to compile commentary based on selected persona,
    and returns a formatted WhatsApp text payload.
    """
    # 1. Fetch settings to determine AI persona and checkboxes
    persona = persona_override or "institutional"
    include_events = True
    include_deals = True
    include_sentiment = True
    include_breakouts = True
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT key, value FROM alert_settings 
               WHERE key IN ('daily_wrapup_persona', 'daily_wrapup_include_events', 'daily_wrapup_include_deals',
                             'daily_wrapup_include_sentiment', 'daily_wrapup_include_breakouts')"""
        )
        for row in cursor.fetchall():
            if not persona_override and row["key"] == "daily_wrapup_persona":
                persona = row["value"]
            elif row["key"] == "daily_wrapup_include_events":
                include_events = (row["value"] == "true")
            elif row["key"] == "daily_wrapup_include_deals":
                include_deals = (row["value"] == "true")
            elif row["key"] == "daily_wrapup_include_sentiment":
                include_sentiment = (row["value"] == "true")
            elif row["key"] == "daily_wrapup_include_breakouts":
                include_breakouts = (row["value"] == "true")

    # 1.5 Sentiment Header
    sentiment_header = ""
    if include_sentiment:
        sentiment_header = fetch_market_sentiment_header()

    # 2. Gather market indices
    indices_str = ""
    breadth_str = ""
    import backend.main as bmain
    cache = bmain._MARKET_MOVERS_CACHE
    if cache and cache.get("status") == "success":
        indices = cache.get("indices", [])
        for idx in indices[:4]:
            pts_val = idx.get("change_val")
            if pts_val is None:
                try:
                    price_val = float(idx['price'])
                    pct_val = float(idx['change_pct'])
                    prev_val = price_val / (1.0 + (pct_val / 100.0)) if pct_val != -100 else price_val
                    pts_val = price_val - prev_val
                except Exception:
                    pts_val = 0.0
            pts_sign = "+" if pts_val >= 0 else ""
            indices_str += f"• {idx['name']}:   `{idx['price']:.2f} ({pts_sign}{pts_val:,.2f} pts, {idx['change_pct']:+.2f}%)`\n"
        
        # Extract Gold and Silver prices if present
        comm_items = []
        for idx in indices:
            if idx["symbol"] in ["SPOTGOLD", "SPOTSILVER"]:
                chg_pct = idx.get("change_pct")
                chg_str = f" ({chg_pct:+.2f}%)" if chg_pct is not None else ""
                try:
                    price_val = float(idx['price'])
                    comm_items.append(f"  - {idx['name']}: `{price_val:,.2f}{chg_str}`")
                except Exception:
                    comm_items.append(f"  - {idx['name']}: `{idx['price']}{chg_str}`")
        if comm_items:
            indices_str += "✨ *Commodities Spot Rates:*\n" + "\n".join(comm_items) + "\n"

        adv = cache.get("advances", 0)
        dec = cache.get("declines", 0)
        breadth_str = f"📈 _Breadth: {adv} Advances | {dec} Declines_"
    else:
        # Robust fallback fetching multiple indices & spot commodities
        try:
            # 1. Fetch Nifty 50 and Sensex from yfinance in batch
            ticks = yf.download(["^NSEI", "^BSESN"], period="2d", interval="1d", progress=False)
            if not ticks.empty:
                for sym, name in [("^NSEI", "Nifty 50"), ("^BSESN", "BSE Sensex")]:
                    try:
                        if isinstance(ticks.columns, pd.MultiIndex):
                            curr = float(ticks["Close"][sym].iloc[-1])
                            prev = float(ticks["Close"][sym].iloc[-2])
                        else:
                            curr = float(ticks["Close"].iloc[-1])
                            prev = float(ticks["Close"].iloc[-2])
                        pct = (curr - prev) / prev * 100.0
                        pts_val = curr - prev
                        pts_sign = "+" if pts_val >= 0 else ""
                        indices_str += f"• {name}:   `{curr:.2f} ({pts_sign}{pts_val:,.2f} pts, {pct:+.2f}%)`\n"
                    except Exception:
                        pass
            if not indices_str:
                indices_str = "• Nifty 50: N/A\n"
        except Exception as e:
            print(f"Daily Wrap-up: Fallback index download error: {e}")
            indices_str = "• Nifty 50: N/A\n"
            
        # 2. Fetch Spot Gold & Silver from GoodReturns scraper
        try:
            from backend.commodity_scraper import CommodityScraper
            spots = await CommodityScraper.get_prices()
            comm_items = []
            if "gold_24k" in spots:
                g = spots["gold_24k"]
                comm_items.append(f"  - Gold 24K 10g (Spot): `{float(g['price']):,.2f} ({g['change_pct']:+.2f}%)`")
            if "silver_1kg" in spots:
                s = spots["silver_1kg"]
                comm_items.append(f"  - Silver 1kg (Spot): `{float(s['price']):,.2f} ({s['change_pct']:+.2f}%)`")
            if comm_items:
                indices_str += "✨ *Commodities Spot Rates:*\n" + "\n".join(comm_items) + "\n"
        except Exception as e:
            print(f"Daily Wrap-up: Fallback commodity scrape error: {e}")

    # 3. Gather Portfolio stats
    port = fetch_portfolio_summary()
    port_str = ""
    if port.get("active"):
        sign = "+" if port['total_daily_change_val'] >= 0 else ""
        port_str += f"• Daily Change:  `{sign}Rs. {port['total_daily_change_val']:,.2f} ({port['total_daily_change_pct']:+.2f}%)`\n"
        port_str += f"• Current Value: `Rs. {port['total_value']:,.2f}`\n"
        sign_ret = "+" if port['total_return_val'] >= 0 else ""
        port_str += f"• Total Return:  `{sign_ret}Rs. {port['total_return_val']:,.2f} ({port['total_return_pct']:+.2f}%)`\n"
        if port.get("top_gainer"):
            g_sym = port['top_gainer']['symbol'].replace('.NS','')
            g_tech = fetch_tech_levels(port['top_gainer']['symbol'])
            g_levels = f" (Supp: `₹{g_tech['s1']:,.2f}` | Res: `₹{g_tech['r1']:,.2f}`)" if g_tech.get("s1") else ""
            if g_sym in port.get("distressed_symbols", []):
                g_sym = f"⚠️ {g_sym} (Solvency Warning)"
            port_str += f"  ├─ 🏆 *Top Gainer:* {g_sym} (`{port['top_gainer']['day_change_pct']:+.2f}%`){g_levels}\n"
        if port.get("top_loser"):
            l_sym = port['top_loser']['symbol'].replace('.NS','')
            l_tech = fetch_tech_levels(port['top_loser']['symbol'])
            l_levels = f" (Supp: `₹{l_tech['s1']:,.2f}` | Res: `₹{l_tech['r1']:,.2f}`)" if l_tech.get("s1") else ""
            if l_sym in port.get("distressed_symbols", []):
                l_sym = f"⚠️ {l_sym} (Solvency Warning)"
            port_str += f"  ├─ ⚠️ *Top Loser:*  {l_sym} (`{port['top_loser']['day_change_pct']:+.2f}%`){l_levels}\n"
        if port.get("distressed_symbols"):
            port_str += f"  └─ ⚠️ *Solvency Warnings:* {', '.join(port['distressed_symbols'])} flagged distressed\n"
        else:
            # Fix final branch bracket line
            if port.get("top_loser"):
                # replace last branch character with corner character
                port_str = port_str.replace("├─ ⚠️ *Top Loser:*", "└─ ⚠️ *Top Loser:*")
    else:
        port_str = "_No active holdings in portfolio ledger._\n"

    # 4. Gather Sector stats
    sectors = fetch_sector_momentum()
    sectors_str = ""
    if sectors.get("active"):
        sectors_str += "• 🔥 *Strongest Sectors:*\n"
        for s in sectors["strongest"]:
            sectors_str += f"  - {s['name']} (`{s['return_1d']:+.2f}%`)\n"
            if s.get("leader"):
                sectors_str += f"    ├─ 🏆 Leader: {s['leader']['symbol'].replace('.NS','')} (`{s['leader']['return_1d']:+.2f}%`)\n"
            if s.get("laggard"):
                sectors_str += f"    └─ ⚠️ Laggard: {s['laggard']['symbol'].replace('.NS','')} (`{s['laggard']['return_1d']:+.2f}%`)\n"
        
        sectors_str += "• ❄️ *Weakest Sectors:*\n"
        for s in sectors["weakest"]:
            sectors_str += f"  - {s['name']} (`{s['return_1d']:+.2f}%`)\n"
            if s.get("leader"):
                sectors_str += f"    ├─ 🏆 Leader: {s['leader']['symbol'].replace('.NS','')} (`{s['leader']['return_1d']:+.2f}%`)\n"
            if s.get("laggard"):
                sectors_str += f"    └─ ⚠️ Laggard: {s['laggard']['symbol'].replace('.NS','')} (`{s['laggard']['return_1d']:+.2f}%`)\n"
    else:
        sectors_str = "_No sector momentum stats compiled._\n"

    # 5. Gather Watchlist highlights
    watchlist = fetch_watchlist_summary()
    watchlist_str = ""
    if watchlist.get("active"):
        if watchlist.get("gainers"):
            watchlist_str += "• 🟢 *Watchlist Gainers:*\n"
            for w in watchlist["gainers"]:
                watchlist_str += f"  - {w['symbol'].replace('.NS','')}: `{w['price']:.2f} ({w['change_pct']:+.2f}%)`\n"
        if watchlist.get("losers"):
            watchlist_str += "• 🔴 *Watchlist Losers:*\n"
            for w in watchlist["losers"]:
                watchlist_str += f"  - {w['symbol'].replace('.NS','')}: `{w['price']:.2f} ({w['change_pct']:+.2f}%)`\n"
    else:
        watchlist_str = "_No items in watchlists or markets are closed._\n"

    # 6. Gather Global News
    news = await fetch_global_news_summary()
    news_str = ""
    if news:
        for n in news:
            news_str += f"• {n['emoji']} _{n['source']}_: {n['title']}\n"
    else:
        news_str = "_No significant market news cached._\n"

    # Gather Portfolio and Watchlist symbols for details & breakouts
    port_symbols = []
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, symbol, name, sector, quantity, purchase_price, purchase_date, transaction_type FROM portfolio_items")
            all_txs = [dict(row) for row in cursor.fetchall()]
        active_holdings = compute_active_holdings(all_txs)
        port_symbols = [h["symbol"] for h in active_holdings]
    except Exception as e:
        print(f"Daily Wrap-up symbols query error: {e}")

    watchlist_symbols = []
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol FROM watchlist_items")
            watchlist_symbols = [row["symbol"] for row in cursor.fetchall()]
    except Exception as e:
        print(f"Daily Wrap-up watchlist query error: {e}")

    # 52W Breakouts & Smart Money Delivery Radar
    breakouts_block = ""
    if include_breakouts:
        breakouts_block = fetch_52w_breakouts(port_symbols, watchlist_symbols)
        
    smart_money_block = fetch_smart_money_delivery_radar(port_symbols, watchlist_symbols)

    # 7. Gather Events and Deals blocks
    events_block = ""
    events_summary = {}
    if include_events:
        events_summary = fetch_upcoming_events_summary(port_symbols, watchlist_symbols)
        events_block += f"📅 *6. UPCOMING PORTFOLIO EVENTS*\n"
        events_block += f"{events_summary['portfolio_text']}\n"
        if events_summary['watchlist_count'] > 0:
            events_block += f"• _Watchlist summary: {events_summary['watchlist_count']} upcoming events scheduled._\n"
        events_block += "\n"

    deals_block = ""
    deals_summary = {}
    if include_deals:
        deals_summary = fetch_recent_deals_summary(port_symbols, watchlist_symbols)
        deals_block += f"🤝 *7. PORTFOLIO INSIDER FLOWS*\n"
        deals_block += f"{deals_summary['portfolio_text']}\n"
        if deals_summary['watchlist_count'] > 0:
            deals_block += f"• _Watchlist summary: {deals_summary['watchlist_count']} recent promoter deals detected._\n"
        deals_block += "\n"

    # 8. Generate AI commentary
    system_prompts = {
        "institutional": (
            "You are an institutional portfolio manager. "
            "Based on the today's market performance metrics, write a sober, professional, 2-3 sentence market commentary (max 60 words) "
            "focusing on main indices, sector relative strength, and institutional flow catalysts. "
            "Keep it factual and direct. Do not include introductory remarks or emojis."
        ),
        "momentum": (
            "You are a momentum trading specialist. "
            "Based on the today's market metrics, write an action-oriented, technical 2-3 sentence swing analysis (max 60 words) "
            "focusing on volume breakouts, technical support/resistances, and breakout sectors/stocks on the watchlist. "
            "Keep it sharp and trading-focused. Do not include introductory remarks or emojis."
        ),
        "macro": (
            "You are a macro economist and commodities strategist. "
            "Based on the today's market metrics, write a macro-focused 2-3 sentence briefing (max 60 words) "
            "linking commodity movements, currency changes, global news stories, and underlying sector moves. "
            "Keep it strategic and high-level. Do not include introductory remarks or emojis."
        )
    }
    
    events_commentary_context = ""
    if include_events and events_summary.get("portfolio_text") and "_No upcoming portfolio" not in events_summary["portfolio_text"]:
        events_commentary_context = f"\nUpcoming Portfolio Events:\n{events_summary['portfolio_text']}"

    deals_commentary_context = ""
    if include_deals and deals_summary.get("portfolio_text") and "_No recent promoter" not in deals_summary["portfolio_text"]:
        deals_commentary_context = f"\nRecent Insider Deals:\n{deals_summary['portfolio_text']}"

    sys_prompt = system_prompts.get(persona, system_prompts["institutional"])
    user_prompt = (
        f"TODAY'S MARKET STATS:\n"
        f"Indices:\n{indices_str}\n"
        f"Portfolio P&L:\n{port_str}\n"
        f"Strongest Sectors:\n{sectors_str}\n"
        f"Global News Headlines:\n{news_str}\n"
        f"{events_commentary_context}"
        f"{deals_commentary_context}\n"
        f"Output only the 2-3 sentence summary."
    )
    
    ai_commentary = ""
    try:
        ai_commentary = await asyncio.to_thread(call_llm, TASK_FAST, sys_prompt, user_prompt)
        ai_commentary = ai_commentary.strip().strip('"').strip("'").strip()
    except Exception as ai_err:
        print(f"Daily Wrap-up AI commentary failed: {ai_err}")
        ai_commentary = "Market closed with standard distributions. Rebalancing and sector rotation remained active within structural bands."

    # 9. Assemble final WhatsApp payload
    today_date = datetime.now().strftime("%B %d, %Y")
    is_saturday = (datetime.now().weekday() == 5) or is_weekly_override
    report_title = "📅 Weekly Close Retrospective" if is_saturday else "📅 Daily Close Wrap-Up"
    
    msg = (
        f"════════════════════════\n"
        f"📈 *APEX EQUITIES WORKSTATION*\n"
        f"{report_title} | {today_date}\n"
        f"════════════════════════\n\n"
        
        f"{sentiment_header}"
        
        f"📊 *1. KEY MARKET INDICES*\n"
        f"{indices_str}"
        f"{breadth_str}\n\n"
        
        f"💼 *2. PORTFOLIO DAILY STATUS*\n"
        f"{port_str}\n"
        
        f"⚡ *3. SECTOR MOMENTUM RADAR*\n"
        f"{sectors_str}\n"
        
        f"👀 *4. WATCHLIST HIGHLIGHTS*\n"
        f"{watchlist_str}\n"
        
        f"{breakouts_block}"
        f"{smart_money_block}"
        
        f"📰 *5. MARKET CATALYST HEADLINES*\n"
        f"{news_str}\n"
        
        f"{events_block}"
        f"{deals_block}"
        
        f"🤖 *AI COPILOT BRIEFING* (_{persona.title()}_)\n"
        f"_{ai_commentary}_\n\n"
        f"────────────────────────\n"
        f"_APEX AI Workstation Client Portal_"
    )
    
    return msg

async def send_whatsapp_wrapup(msg_body: str) -> dict:
    """
    Dispatches a generated message body using the configured Meta WhatsApp Cloud API credentials.
    Splits messages into chunks of <= 3800 characters if body exceeds WhatsApp's 4096 limit.
    """
    wa_token = os.environ.get("WHATSAPP_TOKEN", "")
    wa_phone_id = os.environ.get("WHATSAPP_PHONE_ID", "")
    wa_recipient = os.environ.get("WHATSAPP_RECIPIENT", "")
    
    if not wa_token or not wa_phone_id or not wa_recipient:
        return {"status": "error", "message": "WhatsApp credentials not configured in .env file."}
        
    url = f"https://graph.facebook.com/v21.0/{wa_phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {wa_token}",
        "Content-Type": "application/json"
    }

    # Split message into chunks if it exceeds 3800 chars to avoid Meta WhatsApp Cloud API 4096 char limit
    MAX_LEN = 3800
    chunks = []
    
    if len(msg_body) <= MAX_LEN:
        chunks = [msg_body]
    else:
        # Split by paragraphs, keeping them together if possible
        raw_paragraphs = msg_body.split("\n\n")
        current_chunk = ""
        for p in raw_paragraphs:
            if len(current_chunk) + len(p) + 2 <= MAX_LEN:
                current_chunk += (p + "\n\n")
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                # If a single paragraph is still too long, split by line
                if len(p) > MAX_LEN:
                    lines = p.split("\n")
                    sub_chunk = ""
                    for line in lines:
                        if len(sub_chunk) + len(line) + 1 <= MAX_LEN:
                            sub_chunk += (line + "\n")
                        else:
                            chunks.append(sub_chunk.strip())
                            sub_chunk = line + "\n"
                    current_chunk = sub_chunk
                else:
                    current_chunk = p + "\n\n"
        if current_chunk:
            chunks.append(current_chunk.strip())

    last_msg_id = ""
    for idx, chunk in enumerate(chunks):
        final_text = chunk
        if len(chunks) > 1:
            final_text = f"*[Part {idx+1}/{len(chunks)}]*\n" + chunk

        payload = {
            "messaging_product": "whatsapp",
            "to": wa_recipient,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": final_text
            }
        }
        
        try:
            resp = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=10)
            resp_data = resp.json()
            if resp.status_code == 200 and "messages" in resp_data:
                last_msg_id = resp_data["messages"][0].get("id", "")
                if idx < len(chunks) - 1:
                    await asyncio.sleep(0.5)
            else:
                error_msg = resp_data.get("error", {}).get("message", "Unknown error")
                return {"status": "error", "message": f"WhatsApp Cloud API error (part {idx+1}/{len(chunks)}): {error_msg}"}
        except Exception as e:
            return {"status": "error", "message": f"Network error sending WhatsApp (part {idx+1}/{len(chunks)}): {str(e)}"}
            
    return {"status": "success", "message_id": last_msg_id}
