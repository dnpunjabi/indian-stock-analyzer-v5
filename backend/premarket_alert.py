"""
backend/premarket_alert.py — Daily Pre-Market Morning Intelligence Alert

Gathers overnight market developments, global cues, GIFT Nifty opening projection,
FII/DII cash and derivatives flows, technical pivots, overnight market news catalysts,
and cross-references active portfolio holdings and watchlist symbols.
Generates an AI CIO morning tactical brief via call_llm (TASK_FAST) in beginner-friendly,
layman-accessible terms and dispatches to WhatsApp using the configured Meta WhatsApp Cloud API credentials.
"""

import os
import json
import sqlite3
import asyncio
from datetime import datetime, date, timedelta
import html
import re
import csv
import io
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
            except Exception:
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


# ─── 2C. FETCH NIFTY DERIVATIVES TELEMETRY & TRANSLATE TO LAYMAN ────────────────

def fetch_nifty_derivatives_telemetry() -> dict:
    """
    Fetches live Nifty option chain data to extract:
    - Max Call Open Interest Strike (Institutional Ceiling)
    - Max Put Open Interest Strike (Institutional Safety Floor)
    - Put-Call Ratio (PCR) representing Market Temperature
    """
    url = "https://groww.in/v1/api/option_chain_service/v1/option_chain/derivatives/nifty"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            chains = data.get("optionChain", {}).get("optionChains", [])
            tot_call_oi = 0
            tot_put_oi = 0
            max_call_oi = 0
            max_call_strike = 0
            max_put_oi = 0
            max_put_strike = 0

            for row in chains:
                strike = (row.get("strikePrice") or 0) / 100.0
                c_oi = (row.get("callOption") or {}).get("openInterest") or 0
                p_oi = (row.get("putOption") or {}).get("openInterest") or 0
                tot_call_oi += c_oi
                tot_put_oi += p_oi
                if c_oi > max_call_oi:
                    max_call_oi = c_oi
                    max_call_strike = strike
                if p_oi > max_put_oi:
                    max_put_oi = p_oi
                    max_put_strike = strike

            pcr = (tot_put_oi / tot_call_oi) if tot_call_oi > 0 else 1.0
            return {
                "available": True,
                "pcr": round(pcr, 2),
                "max_call_strike": int(max_call_strike),
                "max_put_strike": int(max_put_strike),
                "max_call_oi": max_call_oi,
                "max_put_oi": max_put_oi
            }
    except Exception as e:
        print(f"[Pre-Market] Option chain telemetry fetch note: {e}")

    return {"available": False}


def fetch_fii_index_positioning() -> dict:
    """
    Fetches official previous session FII Index Futures Long vs Short contracts from NSE
    and calculates the FII Long/Short Ratio.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    for days_back in range(0, 5):
        target_date = date.today() - timedelta(days=days_back)
        dt_str = target_date.strftime("%d%m%Y")
        url = f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{dt_str}.csv"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=4) as r:
                text = r.read().decode("utf-8", errors="ignore")
                reader = csv.reader(io.StringIO(text))
                header = None
                for row in reader:
                    if not row:
                        continue
                    if "Client Type" in row[0]:
                        header = [c.strip() for c in row]
                        continue
                    if header and len(row) > 2 and row[0].strip() == "FII":
                        f_idx_long = float(row[header.index("Future Index Long")].strip())
                        f_idx_short = float(row[header.index("Future Index Short")].strip())
                        tot = f_idx_long + f_idx_short
                        long_ratio = (f_idx_long / tot * 100.0) if tot > 0 else 50.0
                        return {
                            "available": True,
                            "date": target_date.strftime("%d %b"),
                            "long_contracts": int(f_idx_long),
                            "short_contracts": int(f_idx_short),
                            "long_pct": round(long_ratio, 1),
                            "short_pct": round(100.0 - long_ratio, 1)
                        }
        except Exception:
            continue

    return {"available": False}


def interpret_derivatives_layman(telemetry: dict, nifty_pivots: dict = None) -> dict:
    """
    Translates raw options & derivatives data into crystal-clear beginner terms:
    - Safety Floor (Where big buyers are waiting)
    - Upper Ceiling (Where big sellers are waiting)
    - Market Mood (Plain-English sentiment)
    - In Simple Words (Practical trading behavior)
    """
    pcr = telemetry.get("pcr", 1.0)
    max_call = telemetry.get("max_call_strike")
    max_put = telemetry.get("max_put_strike")

    # If option chain not available, use mathematical pivots as fallback
    if not max_call or not max_put:
        if nifty_pivots:
            max_call = int(nifty_pivots.get("r1", 0))
            max_put = int(nifty_pivots.get("s1", 0))
        else:
            max_call = 0
            max_put = 0

    if pcr < 0.75:
        mood = "🛒 Heavily Oversold (Selling power is exhausting; high odds of a sharp bounce)"
        advice = f"Avoid aggressive panic-selling; market is primed for a sudden bounce off {max_put:,}."
    elif pcr < 0.95:
        mood = "🟡 Cautious with high sell bets (Dips likely to find buyers near support)"
        advice = f"Safe zone to look for buying is near {max_put:,}; avoid chasing longs near {max_call:,}."
    elif pcr > 1.35:
        mood = "⚠️ Overheated / Greedy (Risk of sudden profit-booking)"
        advice = f"Consider booking profits closer to {max_call:,}; market is vulnerable to a sharp pullback."
    elif pcr > 1.10:
        mood = "🟢 Confident & Bullish (Buyers in control; buy on minor pullbacks)"
        advice = f"Trend is strongly supportive; look to buy on minor pullbacks towards {max_put:,}."
    else:
        mood = "⚪ Balanced & Range-bound (Consolidation expected)"
        advice = f"Market expected to oscillate between {max_put:,} and {max_call:,}."

    return {
        "floor": max_put,
        "ceiling": max_call,
        "mood": mood,
        "pcr": pcr,
        "advice": advice
    }


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

def clean_headline_text(text: str) -> str:
    """Removes HTML entities and trailing clickbait suffixes like '; here', ' - details here'."""
    t = html.unescape(text.strip())
    t = re.sub(r";\s*here\s*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*-\s*details here\s*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*-\s*read more\s*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r";\s*check details\s*$", "", t, flags=re.IGNORECASE)
    return t.strip()


def is_clickbait_headline(title: str) -> bool:
    """Detects retail engagement clickbait to ensure only high-signal institutional catalysts surface."""
    t = title.lower()
    patterns = [
        r"bonus issue.*dividend alert",
        r"last day to buy",
        r"do you own any",
        r"stocks to buy (?:or sell )?today",
        r"top \d+ stocks to buy",
        r"hot stocks",
        r"trade setup for today",
        r"multibagger",
        r"penny stock",
        r"can .* deliver long-term growth",
        r"should you buy",
        r"buy, sell or hold",
        r"technical pick",
        r"expert view",
        r"stock to buy:",
        r"stocks to watch:"
    ]
    for p in patterns:
        if re.search(p, t):
            return True
    return False


def classify_news_sentiment(title: str) -> str:
    """
    Classifies sentiment into Bullish, Bearish, or Neutral using phrase-level
    context and financial keyword telemetry. Prevents mislabeling cases like
    'slower revenue growth' as bullish.
    """
    t = title.lower()

    # 1. Bearish Multi-word phrases
    bearish_phrases = [
        "slower growth", "slower revenue", "weaker trading", "weak demand",
        "profit drops", "profit falls", "profit slumps", "revenue falls",
        "revenue drops", "misses estimates", "below expectations", "cuts target",
        "market falls", "shares drop", "shares fall", "shares tumble", "slump",
        "losses widen", "revenue de-grows", "downgrades"
    ]
    if any(p in t for p in bearish_phrases):
        return "Bearish"

    # 2. Bullish Multi-word phrases
    bullish_phrases = [
        "profit jumps", "profit surges", "profit rises", "revenue jumps",
        "revenue surges", "beats estimates", "above expectations", "record high",
        "order win", "secures contract", "upgrades target", "shares surge", "shares rally",
        "all-time high", "multifold jump"
    ]
    if any(p in t for p in bullish_phrases):
        return "Bullish"

    # 3. Keyword Scoring
    bullish_k = [
        "jump", "surge", "gain", "rise", "climb", "rally", "upbeat",
        "positive", "expansion", "acquisition", "bullish", "soar",
        "advance", "upgrade", "outperform", "beats", "inflow", "inflows"
    ]
    bearish_k = [
        "slip", "fall", "slump", "drop", "plunge", "losses", "decline",
        "downbeat", "loss", "negative", "warn", "warning", "tariff", "penalty",
        "sebi bar", "fraud", "crash", "bearish", "downgrade", "underperform",
        "trim", "dumping", "selloff", "crisis", "raid", "probe", "fine", "cut",
        "weakness", "weaker", "slower", "slowdown", "subdued", "drag"
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

    Performs title-slug deduplication, clickbait filtering, and sentiment analysis.
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
                    clean_title = clean_headline_text(title)

                    # Clean source tag if Google News returns "Headline - Publisher"
                    if " - " in clean_title and (name == "Google News Business" or len(clean_title.split(" - ")[-1]) < 25):
                        parts = clean_title.rsplit(" - ", 1)
                        clean_title = clean_headline_text(parts[0])
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
                    clickbait = is_clickbait_headline(clean_title)

                    raw_items.append({
                        "source": detected_src,
                        "title": clean_title,
                        "link": link.strip(),
                        "date": pub_date.strip(),
                        "category": category,
                        "sentiment": sentiment,
                        "icon": icon,
                        "is_clickbait": clickbait
                    })
        except Exception as e:
            print(f"[Pre-Market News] Error fetching {name}: {e}")

    # Prioritize: non-clickbait, corporate earnings/macro, non-neutral sentiment
    def priority_score(item):
        if item.get("is_clickbait"):
            return -10
        score = 0
        if item["sentiment"] != "Neutral":
            score += 2
        if item["category"] in ["Corporate & Earnings", "Institutional Flows", "Macro & Indices"]:
            score += 3
        elif item["category"] in ["Global Markets", "Energy & Infra", "Banking & Finance"]:
            score += 2
        return score

    sorted_items = sorted(raw_items, key=priority_score, reverse=True)
    curated_top = [it for it in sorted_items if not it.get("is_clickbait")][:limit]
    if len(curated_top) < limit:
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

def is_ticker_mentioned_in_headline(clean_sym: str, title: str) -> bool:
    """
    Checks if a ticker symbol is authentically mentioned in the headline, with strict
    context disambiguation for ambiguous symbols (like BSE, NSE, IT, ALL, BEL, LT).
    """
    t_upper = title.upper()

    # 1. Specialized handling for BSE (BSE Ltd stock vs Bombay Stock Exchange)
    if clean_sym == "BSE":
        exchange_phrases = [
            "NSE AND BSE", "BSE AND NSE", "BSE SENSEX", "BSE INDEX",
            "BSE HOLIDAY", "BSE CLOSED", "LISTED ON BSE", "ON BSE AND NSE",
            "BSE, NSE", "NSE, BSE", "BSE NOTIFIES", "CLOSURE ON BSE"
        ]
        if any(phrase in t_upper for phrase in exchange_phrases):
            company_phrases = ["BSE SHARE", "BSE STOCK", "BSE LTD", "BSE Q1", "BSE Q2", "BSE Q3", "BSE Q4", "BSE PROFIT", "SHARES OF BSE"]
            return any(cp in t_upper for cp in company_phrases)
        return bool(re.search(r"\bBSE\b", t_upper))

    # 2. Skip generic short words without explicit stock context
    if clean_sym in ["IT", "ALL", "NEW", "AT", "ON", "OR", "BE"]:
        return False

    # 3. Explicit symbol format: (TICKER) or [TICKER]
    if f"({clean_sym})" in t_upper or f"[{clean_sym}]" in t_upper:
        return True

    # 4. Strict word boundary matching
    pattern = rf"\b{re.escape(clean_sym)}\b"
    return bool(re.search(pattern, t_upper))


def check_asset_match(sym: str, name: str, title: str) -> bool:
    """Matches an asset against a headline using both ticker symbol and company name."""
    clean_sym = sym.replace(".NS", "").replace(".BO", "").upper()
    if is_ticker_mentioned_in_headline(clean_sym, title):
        return True
    if name and len(name) >= 4:
        clean_name = re.sub(r"\b(LTD|LIMITED|INDS|INDUSTRIES|CORP|CORPORATION|INDIA)\b", "", name.upper()).strip()
        if len(clean_name) >= 4 and clean_name in title.upper():
            return True
    return False


def cross_check_user_assets_and_news(news_pool: list, events_today: list) -> dict:
    """
    Cross-references active portfolio holdings and watchlist symbols against:
    1. Entire deduplicated news pool (filtered for false positives)
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
        "watchlist_events": [],
        "port_sym_map": {},
        "wl_sym_map": {}
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

    alerts["port_sym_map"] = port_sym_map
    alerts["wl_sym_map"] = wl_sym_map

    matched_portfolio_syms = set()

    # Step A: Cross-check against multi-source news pool
    for item in news_pool:
        title = item["title"]
        for clean_sym, h in port_sym_map.items():
            if check_asset_match(clean_sym, h.get("name", ""), title):
                if clean_sym not in matched_portfolio_syms:
                    alerts["portfolio_news"].append({
                        "symbol": h["symbol"],
                        "name": h.get("name") or clean_sym,
                        "qty": h.get("quantity", 0),
                        "headline": clean_headline_text(title),
                        "sentiment": item.get("sentiment", "Neutral"),
                        "icon": item.get("icon", "⚪"),
                        "source": item.get("source", "Market News")
                    })
                    matched_portfolio_syms.add(clean_sym)

        for clean_sym, w in wl_sym_map.items():
            if clean_sym not in port_sym_map:
                if check_asset_match(clean_sym, w.get("name", ""), title):
                    alerts["watchlist_news"].append({
                        "symbol": w["symbol"],
                        "name": w.get("name") or clean_sym,
                        "wl_name": w.get("wl_name") or "Watchlist",
                        "headline": clean_headline_text(title),
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
                company_query = h.get("name") or clean_sym
                q = urllib.parse.quote(f"{company_query} share stock when:2d")
                url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    root = ET.fromstring(resp.read())
                    items = root.findall('.//item')
                    if items:
                        first_t = items[0].find('title').text or ""
                        first_t = clean_headline_text(first_t)
                        if " - " in first_t:
                            t_clean, src = first_t.rsplit(" - ", 1)
                        else:
                            t_clean, src = first_t, "News Feed"
                        t_clean = clean_headline_text(t_clean)

                        if check_asset_match(clean_sym, h.get("name", ""), t_clean):
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
    gift_data: dict = None,
    derivatives_layman: dict = None,
    fii_positioning: dict = None,
    open_sentiment: dict = None
) -> tuple[str, dict]:
    """
    Invokes call_llm (TASK_FAST) to generate a concise, beginner-friendly 3-bullet
    game plan for the opening bell. Ensures opening bias strictly aligns with GIFT Nifty spread.
    """
    nifty_close = global_cues.get("nifty", {}).get("current", 22500)
    nifty_pts = global_cues.get("nifty", {}).get("change_pts", 0.0)
    nifty_chg = global_cues.get("nifty", {}).get("change_pct", 0.0)
    sensex_close = global_cues.get("sensex", {}).get("current", 74000)
    vix = global_cues.get("vix", {}).get("current", 14.0)
    sp500_chg = global_cues.get("sp500", {}).get("change_pct", 0.0)
    nasdaq_chg = global_cues.get("nasdaq", {}).get("change_pct", 0.0)
    crude = global_cues.get("crude", {}).get("current", 80.0)

    # Implied open info
    open_dir = open_sentiment.get("direction", "Flat / Neutral") if open_sentiment else "Flat / Neutral"
    spread_pts = open_sentiment.get("spread_pts", 0.0) if open_sentiment else 0.0
    open_desc = open_sentiment.get("desc", "Flat / Neutral") if open_sentiment else "Flat / Neutral"

    floor_val = derivatives_layman.get("floor", 22000) if derivatives_layman else int(pivots.get("s1", 22400))
    ceil_val = derivatives_layman.get("ceiling", 23000) if derivatives_layman else int(pivots.get("r1", 22800))
    inst_mood = derivatives_layman.get("mood", "Cautious") if derivatives_layman else "Cautious"
    pcr_val = derivatives_layman.get("pcr", 1.0) if derivatives_layman else 1.0

    fii_fno_desc = ""
    if fii_positioning and fii_positioning.get("available"):
        fii_fno_desc = f"FII Index Futures Stance: {fii_positioning['long_pct']}% Long / {fii_positioning['short_pct']}% Short (Heavy short base)"

    # AI Context Formats
    news_snippets = "\n".join([f"- {it.get('icon', '⚪')} [{it.get('category', 'Markets')}] {it['title']} ({it.get('source', 'News')})" for it in overnight_news[:4]])
    
    port_news_alerts = alerts.get("portfolio_news", [])
    port_context = ""
    if port_news_alerts:
        port_context = "Key User Portfolio Catalysts:\n" + "\n".join([f"- Holding {p['symbol']}: {p['headline']} ({p.get('source', 'News')})" for p in port_news_alerts[:3]]) + "\n"

    sys_prompt = (
        f"You are the Chief Investment Officer (CIO) of an institutional Indian equity fund ({persona.title()} style).\n"
        "Synthesize the morning market setup for everyday retail investors in crystal-clear, beginner-friendly layman terms.\n"
        "CRITICAL RULES:\n"
        f"1. Opening Bias MUST strictly reflect the true GIFT Nifty implied opening direction: {open_dir} (Spread: {spread_pts:+.2f} pts vs Nifty cash close). "
        "If the implied spread is positive, describe it as Mild Gap-Up / Positive open. If negative, describe as Mild Gap-Down / Soft open. Never contradict this direction!\n"
        "2. Do NOT use complicated technical jargon. Use plain English terms like 'Safety Floor', 'Upper Ceiling', and 'Short Squeeze'.\n"
        "Strictly adhere to this 3-bullet format:\n"
        f"• *Opening Bias*: ({open_dir} — explain the opening setup simply in 1 sentence)\n"
        "• *Tactical Action*: (Clear advice for today in simple words — e.g. avoid early rush, look for buying support near the safety floor with disciplined stop-loss)\n"
        "• *Sector & Focus*: (1-2 clear sectors to watch and why, highlighting specific user holdings if relevant)\n"
        "Keep the total output under 100 words. Do not use generic disclaimers."
    )

    user_prompt = f"""
    Current Market Telemetry:
    - Nifty 50 Cash Close: {nifty_close:,.2f} ({nifty_pts:+.2f} pts, {nifty_chg:+.2f}%)
    - BSE Sensex Close: {sensex_close:,.2f}
    - GIFT Nifty Futures: {gift_data.get('price', 0):,.2f} (Implied Opening Spread vs Nifty Cash: {spread_pts:+.2f} pts | Direction: {open_desc})
    - India VIX: {vix:.2f}
    - Derivatives OI Range: Safety Floor {floor_val:,} to Upper Ceiling {ceil_val:,} (Options PCR: {pcr_val:.2f})
    - Institutional Stance: FII Cash Net ₹{fiidii.get('fii_net', 0.0):,.2f} Cr, DII Cash Net ₹{fiidii.get('dii_net', 0.0):,.2f} Cr | {fii_fno_desc}
    - US Overnight: S&P 500 ({sp500_chg:+.2f}%), Nasdaq ({nasdaq_chg:+.2f}%)
    - Brent Crude: ${crude:.2f}/bbl

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
        ai_commentary = (
            f"• *Opening Bias*: {open_dir} (Opening with GIFT Nifty spread at {spread_pts:+.1f} pts).\n"
            f"• *Tactical Action*: Avoid chasing early euphoria at the open; look to buy on dips holding above {floor_val:,} with strict stop-losses.\n"
            "• *Sector & Focus*: Focus on leaders in IT and Steel, while staying cautious on crude-sensitive consumption."
        )

    return ai_commentary, llm_meta


# ─── 8. ASSEMBLE COMPLETE WHATSAPP PAYLOAD ─────────────────────────────────────

async def compile_premarket_alert_payload(config: dict = None) -> tuple[str, dict]:
    """
    Gathers all data streams and compiles the formatted pre-market WhatsApp text message.
    Translates complex institutional telemetry into intuitive, beginner-friendly terms.
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

    # Parallel Data Fetch (Zero extra latency)
    loop = asyncio.get_event_loop()
    f_global = loop.run_in_executor(None, fetch_global_market_cues)
    f_pivots = loop.run_in_executor(None, calculate_index_pivots, "^NSEI")
    f_bank_pivots = loop.run_in_executor(None, calculate_index_pivots, "^NSEBANK")
    f_derivatives = loop.run_in_executor(None, fetch_nifty_derivatives_telemetry)
    f_fii_pos = loop.run_in_executor(None, fetch_fii_index_positioning)
    f_fiidii = loop.run_in_executor(None, fetch_fiidii_cash_flows)
    f_news = loop.run_in_executor(None, fetch_overnight_market_news, 5)
    f_events = loop.run_in_executor(None, fetch_corporate_events_today)
    f_gift = loop.run_in_executor(None, fetch_actual_gift_nifty_quote)

    global_cues, pivots, bank_pivots, derivatives_data, fii_positioning, fiidii, news_data, events_today, gift_data = await asyncio.gather(
        f_global, f_pivots, f_bank_pivots, f_derivatives, f_fii_pos, f_fiidii, f_news, f_events, f_gift
    )

    curated_news = news_data.get("curated_top", []) if isinstance(news_data, dict) else (news_data or [])
    news_pool = news_data.get("full_pool", []) if isinstance(news_data, dict) else (news_data or [])

    # Asset cross-check (scans entire news pool + active portfolio targeted queries)
    alerts = cross_check_user_assets_and_news(news_pool, events_today)
    port_sym_map = alerts.get("port_sym_map", {})
    wl_sym_map = alerts.get("wl_sym_map", {})

    # Translate options/derivatives data into Layman terms
    derivatives_layman = interpret_derivatives_layman(derivatives_data, pivots)

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

    # Implied Opening Gap (GIFT Nifty vs Nifty Spot Close)
    gift_line = ""
    indicated_open_line = ""
    open_sentiment_tag = "Flat / Neutral"
    spread_pts = 0.0
    open_desc = "Flat / Neutral Open"

    if gift_data and gift_data.get("available") and gift_data.get("price", 0) > 0:
        g_price = gift_data["price"]
        
        if n_curr > 0:
            spread_pts = g_price - n_curr
            spread_pct = (spread_pts / n_curr) * 100.0
            
            if spread_pts >= 18.0:
                open_sentiment_tag = "Gap-Up"
                open_icon = "🟢"
                open_desc = f"Mild Gap-Up (~{abs(spread_pts):,.0f} pts / {spread_pct:+.2f}% vs Spot)"
            elif spread_pts <= -18.0:
                open_sentiment_tag = "Gap-Down"
                open_icon = "🔴"
                open_desc = f"Mild Gap-Down (~{abs(spread_pts):,.0f} pts / {spread_pct:+.2f}% vs Spot)"
            else:
                open_sentiment_tag = "Flat / Neutral"
                open_icon = "⚪"
                open_desc = f"Flat / Neutral Open ({spread_pts:+,.1f} pts vs Spot)"
            
            gift_line = f"• GIFT Nifty Live: *{g_price:,.2f}* (Spread: *{spread_pts:+,.2f} pts*)\n"
            indicated_open_line = f"• Indicated Open: {open_icon} *{open_desc}*\n"
        else:
            gift_line = f"• GIFT Nifty Live: *{g_price:,.2f}*\n"

    # VIX Layman Tag
    vix_tag = "Moderate Volatility"
    if vix_val > 18:
        vix_tag = "High Volatility (Expect sharp swings)"
    elif vix_val < 13:
        vix_tag = "Low Volatility (Calm market)"

    opening_block = ""
    if include_gift:
        opening_block = (
            f"🎯 *1. MARKET OPENING PROJECTION*\n"
            f"• Nifty Prev Close: *{n_curr:,.2f}* ({n_pts:+,.2f} pts, {n_chg:+.2f}%)\n"
            f"• BSE Sensex: *{s_curr:,.2f}* ({s_pts:+,.2f} pts, {s_chg:+.2f}%)\n"
            f"{gift_line}"
            f"{indicated_open_line}"
            f"• India VIX: *{vix_val:.2f}* ({vix_chg:+.2f}% | {vix_tag})\n\n"
        )

    # ── Section 2: Global Cues & Commodities ──
    sp_chg = global_cues.get("sp500", {}).get("change_pct", 0.0)
    nasdaq_chg = global_cues.get("nasdaq", {}).get("change_pct", 0.0)
    dow_chg = global_cues.get("dow", {}).get("change_pct", 0.0)
    nikkei_chg = global_cues.get("nikkei", {}).get("change_pct", 0.0)

    crude = global_cues.get("crude", {}).get("current", 0.0)
    crude_chg = global_cues.get("crude", {}).get("change_pct", 0.0)
    us10y = global_cues.get("us10y", {}).get("current", 0.0)
    dxy = global_cues.get("dxy", {}).get("current", 0.0)
    usdinr = global_cues.get("usdinr", {}).get("current", 0.0)

    crude_tag = "Elevated — Headwind for Paints & OMCs" if crude > 85 else "Stable"

    global_block = (
        f"🌐 *2. GLOBAL OVERNIGHT CUES*\n"
        f"• Wall Street: S&P 500 ({sp_chg:+.2f}%), Nasdaq ({nasdaq_chg:+.2f}%), Dow ({dow_chg:+.2f}%)\n"
        f"• Asian Morning: Nikkei ({nikkei_chg:+.2f}%)\n"
        f"• Brent Crude: *${crude:.2f}/bbl* ({crude_chg:+.2f}% | {crude_tag})\n"
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

    # ── Section 4: Big Institutional Money & Derivatives ──
    fiidii_block = ""
    if include_fiidii and fiidii.get("available", False):
        f_net = fiidii.get("fii_net", 0.0)
        d_net = fiidii.get("dii_net", 0.0)
        f_icon = "🟢" if f_net > 0 else "🔴"
        d_icon = "🟢" if d_net > 0 else "🔴"

        f_action = f"Bought ₹{abs(f_net):,.2f} Cr" if f_net > 0 else f"Sold ₹{abs(f_net):,.2f} Cr"
        d_action = f"Bought ₹{abs(d_net):,.2f} Cr" if d_net > 0 else f"Sold ₹{abs(d_net):,.2f} Cr"

        f_desc = "(Cash Market)"
        d_desc = "(Cash Market)"

        fii_pos_line = ""
        if fii_positioning and fii_positioning.get("available"):
            l_pct = fii_positioning["long_pct"]
            s_pct = fii_positioning["short_pct"]
            if l_pct < 20:
                pos_tag = "Extreme Short Base ⚠️ (High Squeeze Risk)"
            elif l_pct < 40:
                pos_tag = "Cautious / Short-Heavy"
            elif l_pct > 65:
                pos_tag = "Bullish / Long-Heavy"
            else:
                pos_tag = "Neutral / Balanced"
            fii_pos_line = f"• FII Index Futures Stance: *{l_pct:.1f}% Long / {s_pct:.1f}% Short* ({pos_tag})\n"

        # Layman Institutional Mood
        if fii_positioning and fii_positioning.get("available") and fii_positioning["long_pct"] < 25:
            inst_mood_line = "• Big Money Mood: 🟡 Foreign funds are heavily short (90%+). Any positive trigger can trap these shorts and spark a sharp short-covering bounce!"
        elif f_net < 0 and d_net > 0:
            inst_mood_line = "• Big Money Mood: 🟡 Foreign funds cautious, but domestic funds absorbing selling. Trapped shorts could spark a sudden squeeze on positive triggers."
        elif f_net > 0 and d_net > 0:
            inst_mood_line = "• Big Money Mood: 🟢 Both Foreign & Domestic institutions buying aggressively. Strong tailwind."
        elif f_net < 0 and d_net < 0:
            inst_mood_line = "• Big Money Mood: 🔴 Dual institutional selling pressure. Exercise caution and avoid aggressive longs."
        else:
            inst_mood_line = "• Big Money Mood: ⚪ Institutional activity balanced."

        fiidii_block = (
            f"💼 *4. BIG INSTITUTIONAL MONEY & DERIVATIVES (PREV SESSION)*\n"
            f"• Foreign Investors (FIIs): {f_icon} Net {f_action} {f_desc}\n"
            f"• Domestic Funds (DIIs): {d_icon} Net {d_action} {d_desc}\n"
            f"{fii_pos_line}"
            f"{inst_mood_line}\n\n"
        )

    # ── Section 5: Nifty 50: Key Levels & Derivatives Map ──
    pivot_block = ""
    floor_val = derivatives_layman.get("floor") or int(pivots.get("s1", 0.0))
    ceil_val = derivatives_layman.get("ceiling") or int(pivots.get("r1", 0.0))
    advice = derivatives_layman.get("advice", "")
    pcr_val = derivatives_layman.get("pcr", 1.0)

    # Format OI contracts nicely (e.g. 1.74L or 117K)
    def fmt_oi(contracts):
        if not contracts:
            return ""
        if contracts >= 100000:
            return f"{contracts / 100000.0:.2f}L contracts"
        return f"{contracts / 1000.0:.1f}K contracts"

    c_oi_str = fmt_oi(derivatives_data.get("max_call_oi", 0))
    p_oi_str = fmt_oi(derivatives_data.get("max_put_oi", 0))

    floor_desc = f"Max Put OI: {p_oi_str} | Big buyers defending" if p_oi_str else "Strong institutional support floor"
    ceil_desc = f"Max Call OI: {c_oi_str} | Heavy seller wall" if c_oi_str else "Major resistance ceiling"

    # PCR interpretation in layman terms
    if pcr_val < 0.75:
        pcr_tag = "Heavily Oversold (Prime bounce zone)"
    elif pcr_val < 0.95:
        pcr_tag = "Oversold Zone (Dips likely to find buyers)"
    elif pcr_val > 1.35:
        pcr_tag = "Overheated (Risk of sudden pullback)"
    elif pcr_val > 1.10:
        pcr_tag = "Bullish / Strong Put Support"
    else:
        pcr_tag = "Balanced / Range-bound"

    bn_line = ""
    if bank_pivots:
        bn_floor = int(bank_pivots.get("s1", 0.0))
        bn_ceil = int(bank_pivots.get("r1", 0.0))
        bn_line = f"• Bank Nifty Levels: Safety Floor *{bn_floor:,}* | Upper Ceiling *{bn_ceil:,}*\n"

    pivot_block = (
        f"📊 *5. NIFTY 50: KEY LEVELS & DERIVATIVES MAP*\n"
        f"• Derivatives OI Range: *{floor_val:,} to {ceil_val:,}*\n"
        f"• 🛡️ Safety Floor (Support): *{floor_val:,}* ({floor_desc})\n"
        f"• 🧱 Upper Ceiling (Resistance): *{ceil_val:,}* ({ceil_desc})\n"
        f"• Market Temperature (PCR): *{pcr_val:.2f}* ({pcr_tag})\n"
        f"{bn_line}"
        f"• 💡 In Simple Words: {advice}\n\n"
    )

    # ── Section 6: Results & Corporate Events Today (With Portfolio Badging) ──
    events_block = ""
    if include_catalysts and events_today:
        ev_lines = []
        for e in events_today[:4]:
            clean_sym = e["symbol"].replace(".NS", "").replace(".BO", "")
            raw_type = e.get("event_type", "").replace("_", " ").title()
            desc = (e.get("description") or "").strip()

            badge = ""
            if clean_sym in port_sym_map:
                badge = " ⚡ *[In Your Portfolio]*"
            elif clean_sym in wl_sym_map:
                badge = " 👀 *[In Watchlist]*"

            event_label = f"{raw_type} ({desc[:40]})" if desc and raw_type.lower() not in desc.lower() else (desc[:50] if desc else raw_type)
            ev_lines.append(f"• *{clean_sym}*{badge}: {event_label}")

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
    open_sentiment_data = {
        "direction": open_sentiment_tag,
        "spread_pts": spread_pts,
        "desc": open_desc
    }
    ai_game_plan, llm_meta = await generate_ai_cio_morning_brief(
        persona, global_cues, pivots, fiidii, curated_news, alerts,
        gift_data=gift_data, derivatives_layman=derivatives_layman,
        fii_positioning=fii_positioning,
        open_sentiment=open_sentiment_data
    )

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
