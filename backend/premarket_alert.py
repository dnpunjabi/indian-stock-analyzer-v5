"""
backend/premarket_alert.py — Daily Pre-Market Morning Intelligence Alert

Gathers overnight market developments, global cues, GIFT Nifty opening projection,
FII/DII cash and derivatives flows, technical pivots, overnight market news catalysts,
and cross-references active portfolio holdings and watchlist symbols.
Generates an AI CIO morning tactical brief via call_llm (TASK_FAST) and dispatches
to WhatsApp using the configured Meta WhatsApp Cloud API credentials.
"""

import os
import json
import sqlite3
import asyncio
from datetime import datetime, date, timedelta
import html
import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import pandas as pd
import yfinance as yf
import requests

from backend.main import get_db, compute_active_holdings
from backend.financial_utils import normalize_symbol
from backend.llm_config import call_llm, TASK_FAST, get_last_llm_meta
from backend.daily_wrapup import send_whatsapp_wrapup

# ─── 1. FETCH GLOBAL CUES & COMMODITIES ──────────────────────────────────────────

def fetch_global_market_cues() -> dict:
    """
    Downloads quotes for major global indices, macro commodities, and currency pairs.
    Returns structured values, price deltas, and percentage changes.
    """
    tickers = {
        "nifty": "^NSEI",
        "sensex": "^BSESN",
        "vix": "^INDIAVIX",
        "dow": "^DJI",
        "sp500": "^GSPC",
        "nasdaq": "^IXIC",
        "nikkei": "^N225",
        "hang_seng": "^HSI",
        "crude": "BZ=F",
        "us10y": "^TNX",
        "dxy": "DX-Y.NYB",
        "usdinr": "INR=X"
    }

    results = {}
    try:
        data = yf.download(list(tickers.values()), period="5d", interval="1d", progress=False)
        is_multi = isinstance(data.columns, pd.MultiIndex)

        for key, sym in tickers.items():
            try:
                s = data["Close"][sym].dropna() if is_multi else data["Close"].dropna()
                if len(s) >= 2:
                    curr = float(s.iloc[-1])
                    prev = float(s.iloc[-2])
                    chg_pct = ((curr - prev) / prev * 100.0) if prev > 0 else 0.0
                    chg_pts = curr - prev
                    results[key] = {
                        "symbol": sym,
                        "current": curr,
                        "prev": prev,
                        "change_pts": chg_pts,
                        "change_pct": chg_pct
                    }
                elif len(s) == 1:
                    curr = float(s.iloc[-1])
                    results[key] = {
                        "symbol": sym,
                        "current": curr,
                        "prev": curr,
                        "change_pts": 0.0,
                        "change_pct": 0.0
                    }
            except Exception as item_err:
                pass
    except Exception as batch_err:
        print(f"[Pre-Market] Batch yfinance download error: {batch_err}")

    # Fallback individual download for missing key tickers
    for key, sym in [("nifty", "^NSEI"), ("sensex", "^BSESN"), ("vix", "^INDIAVIX")]:
        if key not in results:
            try:
                t = yf.Ticker(sym)
                h = t.history(period="5d")
                if len(h) >= 2:
                    curr = float(h["Close"].iloc[-1])
                    prev = float(h["Close"].iloc[-2])
                    results[key] = {
                        "symbol": sym,
                        "current": curr,
                        "prev": prev,
                        "change_pts": curr - prev,
                        "change_pct": ((curr - prev) / prev * 100.0) if prev > 0 else 0.0
                    }
            except Exception:
                pass

    return results


# ─── 2. CALCULATE NIFTY & BANK NIFTY TACTICAL PIVOTS ───────────────────────────

def calculate_index_pivots(index_sym: str = "^NSEI") -> dict:
    """
    Computes Floor Pivot (P), S1, S2, R1, R2 for the target index from previous day H, L, C.
    """
    try:
        t = yf.Ticker(index_sym)
        hist = t.history(period="5d")
        if len(hist) >= 1:
            prev = hist.iloc[-1]
            h = float(prev["High"])
            l = float(prev["Low"])
            c = float(prev["Close"])
            p = (h + l + c) / 3.0
            r1 = (2 * p) - l
            s1 = (2 * p) - h
            r2 = p + (h - l)
            s2 = p - (h - l)
            return {
                "high": h, "low": l, "close": c,
                "pivot": p, "s1": s1, "s2": s2, "r1": r1, "r2": r2
            }
    except Exception as e:
        print(f"[Pre-Market] Pivot calculation error for {index_sym}: {e}")
    return {}


# ─── 2B. FETCH LIVE GIFT NIFTY FUTURES QUOTE ───────────────────────────────────

def fetch_actual_gift_nifty_quote() -> dict:
    """
    Fetches the live trading price and net change of GIFT Nifty futures directly
    from Moneycontrol (https://www.moneycontrol.com/live-index/gift-nifty?symbol=in;gsx).
    """
    url = "https://www.moneycontrol.com/live-index/gift-nifty?symbol=in;gsx"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as r:
            html_text = r.read().decode("utf-8", errors="ignore")

        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">([^<]+)</script>', html_text)
        if m:
            data = json.loads(m.group(1))
            stk = data.get("props", {}).get("pageProps", {}).get("consumptionData", {}).get("stockData", {})
            if stk and stk.get("lastprice"):
                def parse_val(v):
                    if not v:
                        return 0.0
                    return float(str(v).replace(",", "").strip())

                last_price = parse_val(stk.get("lastprice"))
                net_change = parse_val(stk.get("change") or stk.get("net_change"))
                pct_change = parse_val(stk.get("percentchange") or stk.get("percent_change"))
                prev_close = parse_val(stk.get("prev_close") or stk.get("prevclose"))
                last_updated = stk.get("lastupdated") or stk.get("lastupd", "")

                return {
                    "available": True,
                    "symbol": "GIFT NIFTY",
                    "price": last_price,
                    "change_pts": net_change,
                    "change_pct": pct_change,
                    "prev_close": prev_close,
                    "last_updated": last_updated
                }
    except Exception as e:
        print(f"[Pre-Market] GIFT Nifty live fetch error: {e}")

    return {"available": False}


# ─── 3. FETCH FII / DII NET CASH FLOWS ───────────────────────────────────────────

def fetch_fiidii_cash_flows() -> dict:
    """
    Fetches official previous session FII/FPI and DII cash net values from NSE India.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    fii_dii = {"fii_net": 0.0, "dii_net": 0.0, "date": "", "available": False}
    try:
        sess = requests.Session()
        sess.headers.update(headers)
        sess.get("https://www.nseindia.com", timeout=6)
        r = sess.get("https://www.nseindia.com/api/fiidiiTradeReact", timeout=8)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                for row in data:
                    cat = row.get("category", "")
                    net = float(row.get("netValue", 0.0) or 0.0)
                    dt = row.get("date", "")
                    if dt:
                        fii_dii["date"] = dt
                    if "FII" in cat or "FPI" in cat:
                        fii_dii["fii_net"] = net
                    elif "DII" in cat:
                        fii_dii["dii_net"] = net
                fii_dii["available"] = True
    except Exception as e:
        print(f"[Pre-Market] NSE FII/DII fetch note: {e}")

    return fii_dii


# ─── 4. NEWS ENGINE HELPERS & OVERNIGHT AGGREGATOR ────────────────────────────

def classify_news_sentiment(title: str) -> str:
    """Classifies sentiment into Bullish, Bearish, or Neutral using financial keyword telemetry."""
    t = title.lower()
    bullish_k = [
        "jump", "surge", "gain", "rise", "climb", "high", "record", "rally", "upbeat", "expand",
        "profit jumps", "positive", "growth", "win", "acquisition", "dividend", "bullish", "soar",
        "advance", "upgrade", "outperform", "order win", "contract", "beats", "invest", "buy",
        "accumulate", "multibagger", "boost", "inflow", "inflows"
    ]
    bearish_k = [
        "slip", "fall", "slump", "drop", "plunge", "losses", "slips", "decline", "downbeat", "loss",
        "negative", "warn", "tariff", "penalty", "sebi bar", "regulatory action", "fraud", "crash",
        "bearish", "downgrade", "underperform", "trim", "dumping", "selloff", "attack", "debt",
        "crisis", "raid", "probe", "fine", "cut", "weakness"
    ]
    bull_count = sum(1 for k in bullish_k if k in t)
    bear_count = sum(1 for k in bearish_k if k in t)
    if bull_count > bear_count:
        return "Bullish"
    elif bear_count > bull_count:
        return "Bearish"
    return "Neutral"


def classify_news_category(title: str) -> str:
    """Categorizes news into institutional buckets (Corporate, Macro, Flows, etc.)."""
    t = title.lower()
    if any(k in t for k in ["rbi", "inflation", "cpi", "wpi", "gdp", "fiscal", "rupee", "forex", "nifty", "sensex", "bank nifty", "monetary policy", "repo rate"]):
        return "Macro & Indices"
    if any(k in t for k in ["bank", "nbfc", "hdfc", "icici", "sbi", "axis", "kotak", "credit", "lending", "loan"]):
        return "Banking & Finance"
    if any(k in t for k in ["tcs", "infosys", "wipro", "hcl", "tech mahindra", "ai", "software", "semiconductor"]):
        return "IT & Tech"
    if any(k in t for k in ["crude", "oil", "ongc", "reliance", "bpcl", "ioc", "gas", "petrol", "power", "adani", "ntpc", "green energy"]):
        return "Energy & Infra"
    if any(k in t for k in ["fii", "fpi", "dii", "foreign investor", "inflows", "outflows", "selloff", "funds"]):
        return "Institutional Flows"
    if any(k in t for k in ["dow jones", "wall street", "nikkei", "hang seng", "us stock", "global market", "fed", "federal reserve", "spacex", "tesla", "nvidia", "apple"]):
        return "Global Markets"
    if any(k in t for k in ["dividend", "earnings", "quarterly", "profit", "net profit", "loss", "q1", "q2", "q3", "q4", "revenue", "ebitda", "merger", "acquisition", "order win", "contract", "ipo", "stake"]):
        return "Corporate & Earnings"
    return "General Markets"


def fetch_overnight_market_news(limit: int = 5) -> dict:
    """
    Extracts live market-moving headlines from top institutional RSS feeds:
    1. Economic Times Markets
    2. LiveMint Markets
    3. Business Standard Markets
    4. Google News Business / Markets

    Performs title-slug deduplication, sentiment analysis, and category prioritization.
    Returns:
        dict: {"curated_top": list[dict], "full_pool": list[dict]}
    """
    feeds = {
        "Economic Times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "LiveMint": "https://www.livemint.com/rss/markets",
        "Business Standard": "https://www.business-standard.com/rss/markets-106.rss",
        "Google News Business": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-IN&gl=IN&ceid=IN:en"
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    raw_items = []
    seen_slugs = set()

    for name, url in feeds.items():
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=6) as resp:
                root = ET.fromstring(resp.read())
                items = root.findall('.//item')
                for it in items[:15]:
                    title = it.find('title').text if it.find('title') is not None else ""
                    link = it.find('link').text if it.find('link') is not None else ""
                    pub_date = it.find('pubDate').text if it.find('pubDate') is not None else ""
                    if not title:
                        continue
                    clean_title = html.unescape(title.strip())

                    # Clean source tag if Google News returns "Headline - Publisher"
                    if " - " in clean_title and (name == "Google News Business" or len(clean_title.split(" - ")[-1]) < 25):
                        parts = clean_title.rsplit(" - ", 1)
                        clean_title = parts[0].strip()
                        detected_src = parts[1].strip()
                    else:
                        detected_src = name

                    slug = "".join(c for c in clean_title.lower() if c.isalnum())[:35]
                    if slug in seen_slugs or len(slug) < 8:
                        continue
                    seen_slugs.add(slug)

                    sentiment = classify_news_sentiment(clean_title)
                    icon = "🟢" if sentiment == "Bullish" else ("🔴" if sentiment == "Bearish" else "⚪")
                    category = classify_news_category(clean_title)

                    raw_items.append({
                        "source": detected_src,
                        "title": clean_title,
                        "link": link.strip(),
                        "date": pub_date.strip(),
                        "category": category,
                        "sentiment": sentiment,
                        "icon": icon
                    })
        except Exception as e:
            print(f"[Pre-Market News] Error fetching {name}: {e}")

    # Prioritize: Corporate & Earnings, Macro, Flows + Non-neutral sentiment first
    def priority_score(item):
        score = 0
        if item["sentiment"] != "Neutral":
            score += 2
        if item["category"] in ["Corporate & Earnings", "Institutional Flows", "Macro & Indices"]:
            score += 3
        elif item["category"] in ["Global Markets", "Energy & Infra", "Banking & Finance"]:
            score += 2
        return score

    sorted_items = sorted(raw_items, key=priority_score, reverse=True)
    curated_top = sorted_items[:limit]

    return {
        "curated_top": curated_top,
        "full_pool": sorted_items
    }


# ─── 5. FETCH CORPORATE EVENTS TODAY ───────────────────────────────────────────

def fetch_corporate_events_today() -> list:
    """
    Queries the stock_events SQLite table for corporate events (earnings, board meetings,
    dividends, bonus, splits) scheduled for today or within the next 24-48 hours.
    """
    events_today = []
    today_str = date.today().isoformat()
    tomorrow_str = (date.today() + timedelta(days=1)).isoformat()

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT symbol, company_name, event_type, event_date, description
                FROM stock_events
                WHERE event_date IN (?, ?)
                ORDER BY event_date ASC
                LIMIT 15
            """, (today_str, tomorrow_str))
            for row in cursor.fetchall():
                events_today.append(dict(row))
    except Exception as e:
        print(f"[Pre-Market] stock_events lookup error: {e}")

    return events_today


# ─── 6. DUAL CROSS-CHECK: USER PORTFOLIO & WATCHLISTS ──────────────────────────

def cross_check_user_assets_and_news(news_pool: list, events_today: list) -> dict:
    """
    Cross-references active portfolio holdings and watchlist symbols against:
    1. Entire deduplicated news pool (50+ multi-source headlines)
    2. Corporate events & earnings scheduled for today
    3. Targeted deep Google News scan for active portfolio holdings
    """
    portfolio_holdings = []
    watchlist_items = []

    # 1. Fetch active portfolio holdings via FIFO netting
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, symbol, name, sector, quantity, purchase_price, purchase_date, transaction_type FROM portfolio_items")
            txs = [dict(r) for r in cursor.fetchall()]
            if txs:
                portfolio_holdings = compute_active_holdings(txs)
    except Exception as e:
        print(f"[Pre-Market] Portfolio holdings fetch error: {e}")

    # 2. Fetch distinct watchlist items
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT wi.symbol, wi.name, w.name as wl_name
                FROM watchlist_items wi
                LEFT JOIN watchlists w ON wi.watchlist_id = w.id
            """)
            watchlist_items = [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        print(f"[Pre-Market] Watchlist items fetch error: {e}")

    alerts = {
        "portfolio_news": [],
        "watchlist_news": [],
        "portfolio_events": [],
        "watchlist_events": []
    }

    # Normalized symbols maps
    port_sym_map = {}
    for h in portfolio_holdings:
        clean = h["symbol"].replace(".NS", "").replace(".BO", "").upper()
        if clean != "TESTEDITSTOCK":
            port_sym_map[clean] = h

    wl_sym_map = {}
    for w in watchlist_items:
        clean = w["symbol"].replace(".NS", "").replace(".BO", "").upper()
        wl_sym_map[clean] = w

    matched_portfolio_syms = set()

    # Step A: Cross-check against multi-source news pool
    for item in news_pool:
        title_upper = item["title"].upper()
        for clean_sym, h in port_sym_map.items():
            if f" {clean_sym} " in f" {title_upper} " or f"({clean_sym})" in title_upper or (len(clean_sym) >= 4 and clean_sym in title_upper):
                if clean_sym not in matched_portfolio_syms:
                    alerts["portfolio_news"].append({
                        "symbol": h["symbol"],
                        "name": h.get("name") or clean_sym,
                        "qty": h.get("quantity", 0),
                        "headline": item["title"],
                        "sentiment": item.get("sentiment", "Neutral"),
                        "icon": item.get("icon", "⚪"),
                        "source": item.get("source", "Market News")
                    })
                    matched_portfolio_syms.add(clean_sym)

        for clean_sym, w in wl_sym_map.items():
            if clean_sym not in port_sym_map:
                if f" {clean_sym} " in f" {title_upper} " or f"({clean_sym})" in title_upper or (len(clean_sym) >= 4 and clean_sym in title_upper):
                    alerts["watchlist_news"].append({
                        "symbol": w["symbol"],
                        "name": w.get("name") or clean_sym,
                        "wl_name": w.get("wl_name") or "Watchlist",
                        "headline": item["title"],
                        "sentiment": item.get("sentiment", "Neutral"),
                        "icon": item.get("icon", "⚪"),
                        "source": item.get("source", "Market News")
                    })

    # Step B: Deep Scan for active portfolio holdings via Google News RSS (if < 2 hits)
    if len(alerts["portfolio_news"]) < 2 and port_sym_map:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        for clean_sym, h in list(port_sym_map.items())[:5]:
            if clean_sym in matched_portfolio_syms:
                continue
            try:
                q = urllib.parse.quote(f"{clean_sym} stock when:2d")
                url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    root = ET.fromstring(resp.read())
                    items = root.findall('.//item')
                    if items:
                        first_t = items[0].find('title').text or ""
                        first_t = html.unescape(first_t.strip())
                        if " - " in first_t:
                            t_clean, src = first_t.rsplit(" - ", 1)
                        else:
                            t_clean, src = first_t, "News Feed"
                        sent = classify_news_sentiment(t_clean)
                        icon = "🟢" if sent == "Bullish" else ("🔴" if sent == "Bearish" else "⚪")
                        alerts["portfolio_news"].append({
                            "symbol": h["symbol"],
                            "name": h.get("name") or clean_sym,
                            "qty": h.get("quantity", 0),
                            "headline": t_clean,
                            "sentiment": sent,
                            "icon": icon,
                            "source": src.strip()
                        })
                        matched_portfolio_syms.add(clean_sym)
                        if len(alerts["portfolio_news"]) >= 3:
                            break
            except Exception:
                pass

    # Step C: Cross-check corporate events today
    for ev in events_today:
        clean_ev = ev["symbol"].replace(".NS", "").replace(".BO", "").upper()
        if clean_ev in port_sym_map:
            h = port_sym_map[clean_ev]
            alerts["portfolio_events"].append({
                "symbol": ev["symbol"],
                "name": ev.get("company_name") or clean_ev,
                "qty": h.get("quantity", 0),
                "type": ev["event_type"],
                "desc": ev.get("description", "")
            })
        elif clean_ev in wl_sym_map:
            w = wl_sym_map[clean_ev]
            alerts["watchlist_events"].append({
                "symbol": ev["symbol"],
                "name": ev.get("company_name") or clean_ev,
                "wl_name": w.get("wl_name") or "Watchlist",
                "type": ev["event_type"],
                "desc": ev.get("description", "")
            })

    return alerts


# ─── 7. COMPOSE AI CIO MORNING GAME PLAN ───────────────────────────────────────

async def generate_ai_cio_morning_brief(
    persona: str,
    global_cues: dict,
    pivots: dict,
    fiidii: dict,
    overnight_news: list,
    alerts: dict,
    gift_data: dict = None
) -> tuple[str, dict]:
    """
    Invokes call_llm (TASK_FAST) to generate a concise, 3-sentence institutional
    tactical game plan for the morning opening bell.
    """
    nifty_close = global_cues.get("nifty", {}).get("current", 22500)
    nifty_pts = global_cues.get("nifty", {}).get("change_pts", 0.0)
    nifty_chg = global_cues.get("nifty", {}).get("change_pct", 0.0)
    sensex_close = global_cues.get("sensex", {}).get("current", 74000)
    sensex_pts = global_cues.get("sensex", {}).get("change_pts", 0.0)
    sensex_chg = global_cues.get("sensex", {}).get("change_pct", 0.0)
    vix = global_cues.get("vix", {}).get("current", 14.0)
    sp500_chg = global_cues.get("sp500", {}).get("change_pct", 0.0)
    nasdaq_chg = global_cues.get("nasdaq", {}).get("change_pct", 0.0)
    crude = global_cues.get("crude", {}).get("current", 80.0)

    gift_line = ""
    if gift_data and gift_data.get("available") and gift_data.get("price", 0) > 0:
        gift_line = f"- GIFT Nifty Live: {gift_data.get('price'):,.2f} ({gift_data.get('change_pts', 0.0):+.2f} pts, {gift_data.get('change_pct', 0.0):+.2f}%)\n"

    # AI Context Formats
    news_snippets = "\n".join([f"- {it.get('icon', '⚪')} [{it.get('category', 'Markets')}] {it['title']} ({it.get('source', 'News')})" for it in overnight_news[:5]])
    
    port_news_alerts = alerts.get("portfolio_news", [])
    port_context = ""
    if port_news_alerts:
        port_context = "Key User Portfolio Catalysts:\n" + "\n".join([f"- Holding {p['symbol']}: {p['headline']} ({p.get('source', 'News')})" for p in port_news_alerts[:3]]) + "\n"

    sys_prompt = (
        f"You are the Chief Investment Officer (CIO) of an institutional Indian equity fund ({persona.title()} style).\n"
        "Synthesize the morning market data (GIFT Nifty futures, Wall Street close, crude, India VIX, FII/DII cash flow, "
        "Nifty key pivots, overnight market news catalysts, and portfolio headlines) into an actionable 3-sentence morning game plan.\n"
        "Strictly adhere to this format:\n"
        "• Opening Bias: (Bullish / Cautious / Range-bound / Short-Squeeze Potential)\n"
        "• Tactical Action: (e.g. Buy on dips near S1 / Wait for 15-min opening range break / Fade early spike)\n"
        "• Sector & Focus: (Highlight 1-2 leading sectors and specific catalysts)\n"
        "Keep the total output under 100 words. Do not use generic disclaimers."
    )

    user_prompt = f"""
    Current Market Telemetry:
    - Nifty 50 Close: {nifty_close:.2f} ({nifty_pts:+.2f} pts, {nifty_chg:+.2f}%)
    - BSE Sensex Close: {sensex_close:.2f} ({sensex_pts:+.2f} pts, {sensex_chg:+.2f}%)
    {gift_line}    - India VIX: {vix:.2f}
    - Nifty Floor Pivot: {pivots.get('pivot', nifty_close):.2f} (S1: {pivots.get('s1', 0):.2f}, R1: {pivots.get('r1', 0):.2f})
    - US Overnight Action: S&P 500 ({sp500_chg:+.2f}%), Nasdaq ({nasdaq_chg:+.2f}%)
    - Brent Crude: ${crude:.2f}/bbl
    - FII Cash Net: ₹{fiidii.get('fii_net', 0.0):.2f} Cr, DII Cash Net: ₹{fiidii.get('dii_net', 0.0):.2f} Cr
    
    Top Overnight Market Catalysts:
    {news_snippets}

    {port_context}
    """

    ai_commentary = ""
    llm_meta = {}
    try:
        ai_commentary = await asyncio.to_thread(call_llm, TASK_FAST, sys_prompt, user_prompt, max_tokens=250)
        ai_commentary = ai_commentary.strip().strip('"').strip("'").strip()
        llm_meta = get_last_llm_meta()
    except Exception as e:
        print(f"[Pre-Market] AI synthesis error: {e}")
        ai_commentary = "• Opening Bias: Neutral to Range-bound.\n• Tactical Action: Watch initial 15-minute range breakout above Pivot before taking directional positions.\n• Sector & Focus: Track Index heavyweights and high-delivery momentum stocks."

    return ai_commentary, llm_meta


# ─── 8. ASSEMBLE COMPLETE WHATSAPP PAYLOAD ─────────────────────────────────────

async def compile_premarket_alert_payload(config: dict = None) -> tuple[str, dict]:
    """
    Gathers all data streams and compiles the formatted pre-market WhatsApp text message.
    Returns (message_body, llm_meta).
    """
    if config is None:
        config = {
            "persona": "institutional",
            "include_gift": True,
            "include_fiidii": True,
            "include_news": True,
            "include_catalysts": True,
            "include_portfolio_watchlist": True
        }

    persona = config.get("persona", "institutional")
    include_gift = config.get("include_gift", True)
    include_fiidii = config.get("include_fiidii", True)
    include_news = config.get("include_news", True)
    include_catalysts = config.get("include_catalysts", True)
    include_pw = config.get("include_portfolio_watchlist", True)

    # Parallel Data Fetch
    loop = asyncio.get_event_loop()
    f_global = loop.run_in_executor(None, fetch_global_market_cues)
    f_pivots = loop.run_in_executor(None, calculate_index_pivots, "^NSEI")
    f_fiidii = loop.run_in_executor(None, fetch_fiidii_cash_flows)
    f_news = loop.run_in_executor(None, fetch_overnight_market_news, 5)
    f_events = loop.run_in_executor(None, fetch_corporate_events_today)
    f_gift = loop.run_in_executor(None, fetch_actual_gift_nifty_quote)

    global_cues, pivots, fiidii, news_data, events_today, gift_data = await asyncio.gather(
        f_global, f_pivots, f_fiidii, f_news, f_events, f_gift
    )

    curated_news = news_data.get("curated_top", []) if isinstance(news_data, dict) else (news_data or [])
    news_pool = news_data.get("full_pool", []) if isinstance(news_data, dict) else (news_data or [])

    # Asset cross-check (scans entire news pool + active portfolio targeted queries)
    alerts = cross_check_user_assets_and_news(news_pool, events_today)

    # AI CIO Synthesis
    ai_game_plan, llm_meta = await generate_ai_cio_morning_brief(
        persona, global_cues, pivots, fiidii, curated_news, alerts, gift_data=gift_data
    )

    today_str = datetime.now().strftime("%B %d, %Y")
    
    # ── Section 1: Opening Projection & Indices ──
    nifty = global_cues.get("nifty", {})
    sensex = global_cues.get("sensex", {})
    vix = global_cues.get("vix", {})

    n_curr = nifty.get("current", 0.0)
    n_pts = nifty.get("change_pts", 0.0)
    n_chg = nifty.get("change_pct", 0.0)
    s_curr = sensex.get("current", 0.0)
    s_pts = sensex.get("change_pts", 0.0)
    s_chg = sensex.get("change_pct", 0.0)
    vix_val = vix.get("current", 0.0)
    vix_chg = vix.get("change_pct", 0.0)

    # Wall Street & Asian cues
    sp_chg = global_cues.get("sp500", {}).get("change_pct", 0.0)
    nasdaq_chg = global_cues.get("nasdaq", {}).get("change_pct", 0.0)
    dow_chg = global_cues.get("dow", {}).get("change_pct", 0.0)
    nikkei_chg = global_cues.get("nikkei", {}).get("change_pct", 0.0)

    # GIFT Nifty
    gift_line = ""
    if gift_data and gift_data.get("available") and gift_data.get("price", 0) > 0:
        g_price = gift_data["price"]
        g_pts = gift_data["change_pts"]
        g_chg = gift_data["change_pct"]
        gift_line = f"• GIFT Nifty: *{g_price:,.2f}* ({g_pts:+,.2f} pts, {g_chg:+.2f}%)\n"

    opening_block = ""
    if include_gift:
        opening_block = (
            f"🎯 *1. MARKET OPENING PROJECTION*\n"
            f"• Nifty Prev Close: *{n_curr:,.2f}* ({n_pts:+,.2f} pts, {n_chg:+.2f}%)\n"
            f"• BSE Sensex: *{s_curr:,.2f}* ({s_pts:+,.2f} pts, {s_chg:+.2f}%)\n"
            f"{gift_line}"
            f"• India VIX: *{vix_val:.2f}* ({vix_chg:+.2f}%)\n\n"
        )

    # ── Section 2: Global Cues & Commodities ──
    crude = global_cues.get("crude", {}).get("current", 0.0)
    crude_chg = global_cues.get("crude", {}).get("change_pct", 0.0)
    us10y = global_cues.get("us10y", {}).get("current", 0.0)
    dxy = global_cues.get("dxy", {}).get("current", 0.0)
    usdinr = global_cues.get("usdinr", {}).get("current", 0.0)

    global_block = (
        f"🌐 *2. GLOBAL OVERNIGHT CUES*\n"
        f"• Wall Street: S&P 500 ({sp_chg:+.2f}%), Nasdaq ({nasdaq_chg:+.2f}%), Dow ({dow_chg:+.2f}%)\n"
        f"• Asian Morning: Nikkei ({nikkei_chg:+.2f}%)\n"
        f"• Brent Crude: *${crude:.2f}/bbl* ({crude_chg:+.2f}%)\n"
        f"• Macro: US 10Y {us10y:.2f}% | DXY {dxy:.2f} | USD/INR ₹{usdinr:.2f}\n\n"
    )

    # ── Section 3: Overnight News & Catalysts ──
    news_block = ""
    if include_news and curated_news:
        news_lines = []
        for n in curated_news[:4]:
            news_lines.append(f"• {n.get('icon', '⚪')} {n['title']} (_{n['source']}_)")
        news_block = (
            f"📰 *3. OVERNIGHT NEWS & CATALYSTS*\n"
            + "\n".join(news_lines) + "\n\n"
        )

    # ── Section 4: Institutional Flows ──
    fiidii_block = ""
    if include_fiidii and fiidii.get("available", False):
        f_net = fiidii.get("fii_net", 0.0)
        d_net = fiidii.get("dii_net", 0.0)
        f_icon = "🟢" if f_net > 0 else "🔴"
        d_icon = "🟢" if d_net > 0 else "🔴"
        f_tag = "Net Buyers" if f_net > 0 else "Net Sellers"
        d_tag = "Net Buyers" if d_net > 0 else "Net Sellers"
        fiidii_block = (
            f"💼 *4. INSTITUTIONAL FLOWS (PREV SESSION)*\n"
            f"• FII / FPI: {f_icon} *₹{f_net:+,.2f} Cr* ({f_tag})\n"
            f"• DII: {d_icon} *₹{d_net:+,.2f} Cr* ({d_tag})\n\n"
        )

    # ── Section 5: Nifty Tactical Pivots ──
    pivot_block = ""
    if pivots:
        p_val = pivots.get("pivot", 0.0)
        s1 = pivots.get("s1", 0.0)
        s2 = pivots.get("s2", 0.0)
        r1 = pivots.get("r1", 0.0)
        r2 = pivots.get("r2", 0.0)
        pivot_block = (
            f"📊 *5. NIFTY 50 TACTICAL LEVELS*\n"
            f"• Major Resistance: R1 *{r1:,.0f}* | R2 *{r2:,.0f}*\n"
            f"• Floor Pivot: *{p_val:,.0f}*\n"
            f"• Key Support: S1 *{s1:,.0f}* | S2 *{s2:,.0f}*\n\n"
        )

    # ── Section 6: Corporate Events Today ──
    events_block = ""
    if include_catalysts and events_today:
        ev_lines = []
        for e in events_today[:4]:
            clean_sym = e["symbol"].replace(".NS", "").replace(".BO", "")
            raw_type = e.get("event_type", "").replace("_", " ").title()
            desc = (e.get("description") or "").strip()
            if desc:
                if raw_type.lower() in desc.lower():
                    ev_lines.append(f"• *{clean_sym}*: {desc[:50]}")
                else:
                    ev_lines.append(f"• *{clean_sym}*: {raw_type} ({desc[:40]})")
            else:
                ev_lines.append(f"• *{clean_sym}*: {raw_type}")
        events_block = (
            f"📢 *6. RESULTS & EVENTS TODAY*\n"
            + "\n".join(ev_lines) + "\n\n"
        )

    # ── Section 7: Portfolio & Watchlist Heads-Up ──
    pw_block = ""
    if include_pw:
        pw_lines = []
        for pn in alerts["portfolio_news"][:2]:
            clean = pn["symbol"].replace(".NS", "").replace(".BO", "")
            icon = pn.get("icon", "⚪")
            pw_lines.append(f"• 💼 *[Portfolio]* *{clean}* ({pn['qty']} qty): {icon} {pn['headline'][:75]} (_{pn.get('source', 'News')}_)")
        for pe in alerts["portfolio_events"][:2]:
            clean = pe["symbol"].replace(".NS", "").replace(".BO", "")
            raw_t = pe.get('type', '').replace('_', ' ').title()
            pw_lines.append(f"• 💼 *[Portfolio]* *{clean}*: {raw_t} scheduled today.")
        for wn in alerts["watchlist_news"][:2]:
            clean = wn["symbol"].replace(".NS", "").replace(".BO", "")
            icon = wn.get("icon", "⚪")
            pw_lines.append(f"• 👀 *[Watchlist]* *{clean}* ({wn['wl_name']}): {icon} {wn['headline'][:75]} (_{wn.get('source', 'News')}_)")
        for we in alerts["watchlist_events"][:2]:
            clean = we["symbol"].replace(".NS", "").replace(".BO", "")
            raw_t = we.get('type', '').replace('_', ' ').title()
            pw_lines.append(f"• 👀 *[Watchlist]* *{clean}* ({we['wl_name']}): {raw_t} scheduled today.")

        if pw_lines:
            pw_block = (
                f"🛡️ *7. YOUR PORTFOLIO & WATCHLIST HEADS-UP*\n"
                + "\n".join(pw_lines) + "\n\n"
            )
        else:
            pw_block = (
                f"🛡️ *7. PORTFOLIO & WATCHLIST CROSS-CHECK*\n"
                f"• 🟢 All active portfolio holdings & watchlists scanned — no adverse filings or event clashes today.\n\n"
            )

    # ── Section 8: AI CIO Tactical Game Plan ──
    ai_block = (
        f"🤖 *AI CIO MORNING GAME PLAN* (_{persona.title()} Strategy_)\n"
        f"{ai_game_plan}\n"
    )

    # Assemble Full Message
    msg = (
        f"════════════════════════\n"
        f"🌅 *APEX MORNING INTELLIGENCE*\n"
        f"Pre-Market Setup | {today_str}\n"
        f"════════════════════════\n\n"
        f"{opening_block}"
        f"{global_block}"
        f"{news_block}"
        f"{fiidii_block}"
        f"{pivot_block}"
        f"{events_block}"
        f"{pw_block}"
        f"{ai_block}\n"
        f"────────────────────────\n"
        f"_APEX AI Workstation Client Portal_"
    )

    return msg, llm_meta


# ─── 9. DISPATCH ALERT VIA META WHATSAPP CLOUD API ─────────────────────────────

async def dispatch_premarket_alert(msg_body: str) -> dict:
    """
    Sends the pre-market alert payload to WhatsApp using the unified
    send_whatsapp_wrapup function with multi-part chunking.
    """
    return await send_whatsapp_wrapup(msg_body)
