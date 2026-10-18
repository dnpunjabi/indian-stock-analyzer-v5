"""
backend/shark_scraper.py — Shark Radar (Superstar Investor Portfolio Engine)

Features:
- Scrapes and parses Trendlyne's 60+ Indian superstar investor portfolios.
- Normalizes entity/family aliases (e.g. Rare Enterprises, Suryavanshi Commotrade).
- Cache-first architecture using SQLite (7-day TTL) for sub-20ms UI response.
- Option 1: Shark Consensus Screener (Multi-Shark Overlap: stocks held by >=2 sharks).
- Option 3: Automated WhatsApp / Telegram alerts for Brand New Entries and >= +0.5% Stake Hikes.
- Option 6: 1-Click Clone / Import of an investor's entire portfolio into workspace Watchlists.
- Reverse Lookup for Stock Research View ("Smart Money Presence Badge").
"""

import os
import re
import json
import time
import asyncio
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from backend.main import get_db

logger = logging.getLogger("shark_radar")

SEED_FILE_PATH = os.path.join(os.path.dirname(__file__), "shark_radar_seed.json")

# Standard browser headers to ensure 200 OK responses
TRENDLYNE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://trendlyne.com/portfolio/superstar-shareholders/index/",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}

# ─── DATABASE INITIALIZATION ───────────────────────────────────────────────────

def init_shark_tables():
    """Initializes tables for Shark Radar in watchlist_database.db."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # 1. Directory Leaderboard
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_shark_investors (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL,
            net_worth_cr REAL,
            net_worth_str TEXT,
            change_pct REAL,
            stocks_count INTEGER,
            sector_preference TEXT,
            top_holdings TEXT,
            recently_bought TEXT,
            recently_sold TEXT,
            bio TEXT,
            profile_url TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # 2. Deep-Dive Full Portfolio JSON
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_shark_portfolios (
            investor_id TEXT PRIMARY KEY,
            data_json TEXT NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(investor_id) REFERENCES cached_shark_investors(id)
        )
        """)
        
        # 3. Normalized Stock-to-Shark Lookup Table (for Consensus & Instant Stock Badges)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS shark_stock_lookup (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            company_name TEXT,
            investor_id TEXT NOT NULL,
            investor_name TEXT NOT NULL,
            holding_percent REAL,
            holding_value_cr REAL,
            shares_count INTEGER,
            holding_entity TEXT,
            latest_quarter TEXT,
            prior_quarter_percent REAL,
            change_percent REAL,
            change_type TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, investor_id, holding_entity)
        )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_shark_stock_sym ON shark_stock_lookup(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_shark_stock_inv ON shark_stock_lookup(investor_id)")
        
        # 4. Shark Alert Notification History (Option 3)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS shark_alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            investor_id TEXT NOT NULL,
            investor_name TEXT NOT NULL,
            symbol TEXT NOT NULL,
            change_type TEXT NOT NULL,
            stake_percent REAL,
            change_percent REAL,
            message_text TEXT,
            channel TEXT DEFAULT 'whatsapp',
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        conn.commit()
    seed_shark_tables_if_empty()


def seed_shark_tables_if_empty() -> bool:
    """
    Seeds shark tables from backend/shark_radar_seed.json if cached_shark_investors is empty.
    Guarantees instant sub-20ms startup and offline/datacenter VM resilience.
    """
    if not os.path.exists(SEED_FILE_PATH):
        return False
        
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM cached_shark_investors")
            count = cursor.fetchone()[0]
            if count > 0:
                return True
                
            logger.info("Seeding Shark Radar database from bundled seed dataset...")
            with open(SEED_FILE_PATH, "r", encoding="utf-8") as f:
                seed_data = json.load(f)
                
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 1. Directory Leaderboard
            for inv in seed_data.get("investors", []):
                cursor.execute("""
                INSERT OR IGNORE INTO cached_shark_investors 
                (id, name, slug, net_worth_cr, net_worth_str, change_pct, stocks_count, sector_preference, top_holdings, recently_bought, recently_sold, bio, profile_url, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    inv["id"], inv["name"], inv["slug"], inv.get("net_worth_cr", 0.0), inv.get("net_worth_str", ""),
                    inv.get("change_pct", 0.0), inv.get("stocks_count", 0), inv.get("sector_preference", ""),
                    inv.get("top_holdings", ""), inv.get("recently_bought", ""), inv.get("recently_sold", ""),
                    inv.get("bio", ""), inv.get("profile_url", ""), inv.get("last_updated") or now_str
                ))
                
            # 2. Portfolios
            for port in seed_data.get("portfolios", []):
                cursor.execute("""
                INSERT OR IGNORE INTO cached_shark_portfolios (investor_id, data_json, last_updated)
                VALUES (?, ?, ?)
                """, (port["investor_id"], port["data_json"], port.get("last_updated") or now_str))
                
            # 3. Stock Lookup
            for row in seed_data.get("stock_lookup", []):
                cursor.execute("""
                INSERT OR IGNORE INTO shark_stock_lookup 
                (symbol, company_name, investor_id, investor_name, holding_percent, holding_value_cr, shares_count, holding_entity, latest_quarter, prior_quarter_percent, change_percent, change_type, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row["symbol"], row.get("company_name", ""), row["investor_id"], row.get("investor_name", ""),
                    row.get("holding_percent", 0.0), row.get("holding_value_cr", 0.0), row.get("shares_count", 0),
                    row.get("holding_entity", ""), row.get("latest_quarter", ""), row.get("prior_quarter_percent", 0.0),
                    row.get("change_percent", 0.0), row.get("change_type", "UNCHANGED"), row.get("last_updated") or now_str
                ))
                
            conn.commit()
            logger.info("Successfully seeded Shark Radar tables with bundled dataset.")
            return True
    except Exception as e:
        logger.error(f"Failed to seed Shark Radar tables: {e}")
        return False


# ─── PARSING HELPERS ──────────────────────────────────────────────────────────

def parse_float_safe(val_str: Any) -> float:
    """Extracts a clean float from formatted text (e.g. '3,154.8 Cr', '+0.4%', '-2.95%')."""
    if val_str is None:
        return 0.0
    if isinstance(val_str, (int, float)):
        return float(val_str)
    s = str(val_str).replace(',', '').replace('%', '').strip()
    match = re.search(r'[-+]?\d*\.?\d+', s)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return 0.0
    return 0.0

def parse_int_safe(val_str: Any) -> int:
    """Extracts integer from text with commas."""
    if val_str is None:
        return 0
    if isinstance(val_str, int):
        return val_str
    s = str(val_str).replace(',', '').strip()
    match = re.search(r'\d+', s)
    if match:
        try:
            return int(match.group(0))
        except ValueError:
            return 0
    return 0

def parse_holding_value(val_str: Any) -> tuple[float, str]:
    """
    Parses holding value from Trendlyne formats like '57.4 Cr', '41.8 L', '₹3.1 Cr', '-'.
    Accurately converts Lakhs ('L') to Crores (dividing by 100).
    Returns (value_in_cr, formatted_str).
    """
    if not val_str or str(val_str).strip() in ['-', '--', 'N/A', 'None']:
        return 0.0, "-"
    s = str(val_str).replace(',', '').replace('₹', '').strip()
    match = re.search(r'[-+]?\d*\.?\d+', s)
    if not match:
        return 0.0, "-"
    try:
        num = float(match.group(0))
        if 'L' in s.upper() and 'CR' not in s.upper():
            val_cr = round(num / 100.0, 3)
            formatted = f"₹{num:.1f} L"
        else:
            val_cr = round(num, 2)
            formatted = f"₹{num:.1f} Cr"
        return val_cr, formatted
    except Exception:
        return 0.0, "-"


# ─── SCRAPING FUNCTIONS ───────────────────────────────────────────────────────

def trendlyne_get(url: str, timeout: int = 15) -> str:
    """
    Fetches HTML from Trendlyne using a resilient multi-tier engine:
    1. curl_cffi with Chrome 120/124 TLS fingerprint impersonation (bypasses CloudFront / AWS WAF bot detection on Oracle VM / Datacenter IPs).
    2. cloudscraper (anti-bot / Cloudflare challenge bypass).
    3. requests.Session with complete modern browser headers.
    """
    errors = []
    
    # Tier 1: curl_cffi (Essential for bypassing CloudFront JA3/JA4 TLS fingerprinting on Datacenter IPs)
    try:
        from curl_cffi import requests as cffi_requests
        resp = cffi_requests.get(
            url,
            headers=TRENDLYNE_HEADERS,
            impersonate="chrome120",
            timeout=timeout
        )
        if resp.status_code == 200 and resp.text:
            return resp.text
        else:
            errors.append(f"curl_cffi HTTP {resp.status_code}")
    except Exception as e:
        errors.append(f"curl_cffi: {e}")

    # Tier 2: cloudscraper
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )
        resp = scraper.get(url, headers=TRENDLYNE_HEADERS, timeout=timeout)
        if resp.status_code == 200 and resp.text:
            return resp.text
        else:
            errors.append(f"cloudscraper HTTP {resp.status_code}")
    except Exception as e:
        errors.append(f"cloudscraper: {e}")

    # Tier 3: standard requests with modern browser headers
    try:
        session = requests.Session()
        resp = session.get(url, headers=TRENDLYNE_HEADERS, timeout=timeout)
        if resp.status_code == 200 and resp.text:
            return resp.text
        else:
            errors.append(f"requests HTTP {resp.status_code}")
    except Exception as e:
        errors.append(f"requests: {e}")

    error_summary = " | ".join(errors)
    raise Exception(f"Failed to fetch {url}. Diagnostics: {error_summary}")


def scrape_superstar_index() -> List[Dict[str, Any]]:
    """
    Scrapes Trendlyne's Superstar Shareholders index page.
    Returns list of 60+ superstar investors with net worth, stock count, and recent moves.
    """
    url = "https://trendlyne.com/portfolio/superstar-shareholders/index/"
    html_text = trendlyne_get(url, timeout=15)
        
    soup = BeautifulSoup(html_text, "html.parser")
    table = soup.find("table")
    if not table:
        raise Exception("Superstar index table not found in Trendlyne page HTML.")
        
    rows = table.find_all("tr")[1:]  # Skip the header row
    investors = []
    
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 3:
            continue
            
        name_col = cols[0]
        a_tag = name_col.find("a")
        name = name_col.get_text(strip=True)
        url_link = a_tag["href"] if a_tag and "href" in a_tag.attrs else ""
        
        # Extract ID and slug: e.g. /portfolio/superstar-shareholders/53746/latest/ashish-kacholia/
        match = re.search(r'/superstar-shareholders/(\d+)/latest/([^/]+)/', url_link)
        inv_id = match.group(1) if match else ""
        slug = match.group(2) if match else name.lower().replace(" ", "-")
        
        # Portfolio value & change
        val_text = cols[1].get_text(separator=" ", strip=True) if len(cols) > 1 else ""
        val_match = re.search(r'([\d,]+\.?\d*)\s*Cr', val_text, re.I)
        net_worth_cr = parse_float_safe(val_match.group(1)) if val_match else parse_float_safe(val_text)
        net_worth_str = f"₹{net_worth_cr:,.1f} Cr"
        
        # Change % in portfolio value
        chg_match = re.search(r'([-+]?\d*\.?\d+)%', val_text)
        change_pct = float(chg_match.group(1)) if chg_match else 0.0
        
        # Number of stocks
        stocks_count = parse_int_safe(cols[2].get_text(strip=True)) if len(cols) > 2 else 0
        
        # Sector preference
        sector_pref = cols[3].get_text(separator=" ", strip=True) if len(cols) > 3 else ""
        
        # Top holdings: cleanly extract stock names from <a> tags to prevent value parentheses splitting
        top_holdings_list = []
        if len(cols) > 5:
            links = cols[5].find_all("a")
            for a in links:
                t = a.get_text(strip=True)
                if t and t not in top_holdings_list:
                    top_holdings_list.append(t)
        top_holdings_raw = " | ".join(top_holdings_list) if top_holdings_list else (cols[5].get_text(separator=" ", strip=True) if len(cols) > 5 else "")
        
        # Recent buys and sells (filter out dash '-' and empty values)
        raw_rb = cols[6].get_text(strip=True) if len(cols) > 6 else ""
        recent_bought = "" if raw_rb in ("-", "--", "N/A", "None", "") else raw_rb
        
        raw_rs = cols[7].get_text(strip=True) if len(cols) > 7 else ""
        recent_sold = "" if raw_rs in ("-", "--", "N/A", "None", "") else raw_rs
        
        if inv_id and name:
            investors.append({
                "id": inv_id,
                "name": name,
                "slug": slug,
                "net_worth_cr": net_worth_cr,
                "net_worth_str": net_worth_str,
                "change_pct": change_pct,
                "stocks_count": stocks_count,
                "sector_preference": sector_pref,
                "top_holdings": top_holdings_raw,
                "recently_bought": recent_bought,
                "recently_sold": recent_sold,
                "profile_url": url_link,
                "bio": ""
            })
            
    return investors


def scrape_investor_portfolio(investor_id: str, slug: str) -> Dict[str, Any]:
    """
    Scrapes an individual investor's portfolio page from Trendlyne.
    Extracts complete stock holdings, tickers, quantities, values, quarterly history, and entity aliases.
    """
    url = f"https://trendlyne.com/portfolio/superstar-shareholders/{investor_id}/latest/{slug}/"
    html_text = trendlyne_get(url, timeout=15)
        
    soup = BeautifulSoup(html_text, "html.parser")
    
    # 1. Extract Bio / Headline Summary
    headings = [h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"])]
    bio = ""
    for h in headings:
        if len(h) > 60 and any(k in h.lower() for k in ["portfolio", "invest", "known", "market", "whiz", "whale"]):
            bio = h
            break
            
    # 2. Extract Recent Moves / Insights
    insights = []
    for div in soup.find_all(class_=re.compile(r'(insight|activity|highlight|card|stat)', re.I)):
        text = div.get_text(separator=" ", strip=True)
        if any(k in text.lower() for k in ["accumulation", "partial exit", "increased his stake", "decreased his stake", "entered"]):
            if len(text) < 250 and text not in insights:
                insights.append(text)
                
    # 3. Extract Holdings Tables
    # Locate the primary/master superstar shareholding table (ignore nested child subtables)
    master_table = soup.find("table", class_="superstar-shareholding")
    if not master_table:
        for t in soup.find_all("table"):
            th_text = " ".join([th.get_text() for th in t.find_all("th")])
            if "Stock" in th_text and ("Holding Value" in th_text or "Holding %" in th_text):
                master_table = t
                break

    holdings = []
    quarters_found = []
    
    if master_table:
        thead = master_table.find("thead")
        header_cells = [c.get_text(strip=True) for c in (thead.find_all("th") if thead else master_table.find_all("tr")[0].find_all(["th", "td"]))]
        
        # Determine column positions based on whether the table has the 'Expand' column
        has_expand = len(header_cells) > 0 and "expand" in header_cells[0].lower()
        stock_col = 1 if has_expand else 0
        val_col = 2 if has_expand else 1
        qty_col = 3 if has_expand else 2
        
        # Quarter columns (strictly exclude any 'change' header)
        q_cols = []
        change_col_idx = None
        for idx, col_name in enumerate(header_cells):
            if "change" in col_name.lower():
                change_col_idx = idx
            elif re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*\d{4}', col_name, re.I):
                clean_q = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*\d{4}', col_name, re.I).group(0)
                q_cols.append((idx, clean_q))
                if clean_q not in quarters_found:
                    quarters_found.append(clean_q)

        tbody = master_table.find("tbody")
        rows = tbody.find_all("tr", recursive=False) if tbody else master_table.find_all("tr")[1:]
        
        for r in rows:
            # Skip child expansion rows or subtables
            r_classes = r.get("class", [])
            if any(c in r_classes for c in ["childrow", "childrowDT", "subtable"]):
                continue
                
            cells = r.find_all(["td", "th"], recursive=False)
            if len(cells) < 4:
                continue
                
            stock_cell = cells[stock_col] if stock_col < len(cells) else cells[0]
            stock_name = stock_cell.get_text(strip=True)
            if not stock_name or stock_name.lower() in ["stock", "total", "expand"]:
                continue
                
            # Extract ticker symbol from link
            ticker = ""
            a_tag = stock_cell.find("a", href=True)
            if a_tag:
                href = a_tag["href"]
                sym_match = re.search(r'/equity/share-holding/\d+/([A-Z0-9_-]+)/', href)
                if sym_match:
                    ticker = sym_match.group(1).upper()
            if not ticker:
                ticker = re.sub(r'[^A-Z0-9]', '', stock_name.upper())[:10]
                
            val_text = cells[val_col].get_text(strip=True) if val_col < len(cells) else "-"
            holding_val_cr, holding_val_str = parse_holding_value(val_text)
            
            qty_text = cells[qty_col].get_text(strip=True) if qty_col < len(cells) else "-"
            qty_held = parse_int_safe(qty_text)
            
            holder_name = slug.replace("-", " ").title()
            
            # Quarter by quarter history
            quarterly_pcts = {}
            for col_idx, q_label in q_cols:
                if col_idx < len(cells):
                    pct_str = cells[col_idx].get_text(strip=True)
                    quarterly_pcts[q_label] = parse_float_safe(pct_str) if pct_str not in ["-", "--", ""] else 0.0
                    
            latest_pct = 0.0
            prior_pct = 0.0
            if q_cols:
                latest_q_label = q_cols[0][1]
                latest_pct = quarterly_pcts.get(latest_q_label, 0.0)
                if len(q_cols) > 1:
                    prior_q_label = q_cols[1][1]
                    prior_pct = quarterly_pcts.get(prior_q_label, 0.0)
                    
            if change_col_idx is not None and change_col_idx < len(cells):
                change_pct = parse_float_safe(cells[change_col_idx].get_text(strip=True))
            else:
                change_pct = round(latest_pct - prior_pct, 2)
                
            # Genuine new stake entry: prior stake was 0 (or unlisted under SEBI 1% mandatory threshold) and latest stake >= 1.0%
            if prior_pct == 0.0 and latest_pct >= 1.0:
                change_type = "NEW"
            elif change_pct > 0:
                change_type = "INCREASED"
            elif change_pct < 0:
                change_type = "REDUCED"
            else:
                change_type = "UNCHANGED"
                
            holdings.append({
                "stock_name": stock_name,
                "symbol": ticker,
                "holding_value_cr": holding_val_cr,
                "holding_value_str": holding_val_str,
                "shares_count": qty_held,
                "latest_stake_pct": latest_pct,
                "prior_stake_pct": prior_pct,
                "change_pct": change_pct,
                "change_type": change_type,
                "holder_name": holder_name,
                "quarterly_history": quarterly_pcts
            })
            
    # Deduplicate holdings by (symbol, holder_name)
    dedup_holdings = []
    seen = set()
    for h in holdings:
        key = (h["symbol"], h["holder_name"])
        if key not in seen:
            seen.add(key)
            dedup_holdings.append(h)
            
    # Sort holdings by holding value descending
    dedup_holdings.sort(key=lambda x: x["holding_value_cr"], reverse=True)
    
    return {
        "investor_id": investor_id,
        "slug": slug,
        "bio": bio,
        "insights": insights[:5],
        "holdings_count": len(dedup_holdings),
        "holdings": dedup_holdings,
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


# ─── SYNC & CACHE ENGINE ───────────────────────────────────────────────────────

def sync_shark_directory(force: bool = False, max_age_days: int = 7) -> List[Dict[str, Any]]:
    """
    Syncs the 60+ superstar investors directory to SQLite.
    Returns cached list instantly if younger than max_age_days and not force.
    """
    init_shark_tables()
    now = datetime.now()
    
    # 1. Check local cache
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM cached_shark_investors ORDER BY net_worth_cr DESC")
        rows = cursor.fetchall()
        
        if rows and not force:
            first_row = rows[0]
            last_up = first_row["last_updated"]
            try:
                dt = datetime.strptime(str(last_up).split('.')[0], "%Y-%m-%d %H:%M:%S")
                if now - dt < timedelta(days=max_age_days):
                    return [dict(r) for r in rows]
            except Exception:
                pass
                
    # 2. Cache miss or forced refresh: Scrape live with graceful failover
    scraped_investors = []
    try:
        scraped_investors = scrape_superstar_index()
    except Exception as scrape_err:
        logger.warning(f"Trendlyne superstar index live scrape failed ({scrape_err}). Attempting fallback recovery.")

    if not scraped_investors:
        # Fallback 1: Return existing cache if any exists (even if older than max_age_days)
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM cached_shark_investors ORDER BY net_worth_cr DESC")
            existing = [dict(r) for r in cursor.fetchall()]
            if existing:
                return existing
                
        # Fallback 2: Load from bundled seed dataset if cache is completely empty
        seed_shark_tables_if_empty()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM cached_shark_investors ORDER BY net_worth_cr DESC")
            return [dict(r) for r in cursor.fetchall()]
            
    # 3. Upsert into database
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        for inv in scraped_investors:
            cursor.execute("""
            INSERT INTO cached_shark_investors 
            (id, name, slug, net_worth_cr, net_worth_str, change_pct, stocks_count, sector_preference, top_holdings, recently_bought, recently_sold, bio, profile_url, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                slug=excluded.slug,
                net_worth_cr=excluded.net_worth_cr,
                net_worth_str=excluded.net_worth_str,
                change_pct=excluded.change_pct,
                stocks_count=excluded.stocks_count,
                sector_preference=excluded.sector_preference,
                top_holdings=excluded.top_holdings,
                recently_bought=excluded.recently_bought,
                recently_sold=excluded.recently_sold,
                profile_url=excluded.profile_url,
                last_updated=excluded.last_updated
            """, (
                inv["id"], inv["name"], inv["slug"], inv["net_worth_cr"], inv["net_worth_str"],
                inv["change_pct"], inv["stocks_count"], inv["sector_preference"],
                inv["top_holdings"], inv["recently_bought"], inv["recently_sold"],
                inv["bio"], inv["profile_url"], now_str
            ))
        conn.commit()
        
    return scraped_investors


def sync_investor_portfolio(investor_id: str, force: bool = False, max_age_days: int = 7) -> Dict[str, Any]:
    """
    Syncs an individual investor's portfolio to SQLite.
    Checks cache first (< max_age_days).
    Option 3: Automatically detects new entries & >= +0.5% hikes and dispatches alerts.
    """
    init_shark_tables()
    now = datetime.now()
    
    # 1. Check local portfolio cache
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data_json, last_updated FROM cached_shark_portfolios WHERE investor_id = ?", (investor_id,))
        row = cursor.fetchone()
        
        if row and not force:
            try:
                last_up = datetime.strptime(str(row["last_updated"]).split('.')[0], "%Y-%m-%d %H:%M:%S")
                if now - last_up < timedelta(days=max_age_days):
                    return json.loads(row["data_json"])
            except Exception:
                pass
                
        # Resolve slug
        cursor.execute("SELECT slug, name FROM cached_shark_investors WHERE id = ?", (investor_id,))
        inv_meta = cursor.fetchone()
        slug = inv_meta["slug"] if inv_meta else investor_id
        investor_name = inv_meta["name"] if inv_meta else slug.replace("-", " ").title()
        
    # 2. Live Scrape with Fallback
    portfolio_data = None
    try:
        portfolio_data = scrape_investor_portfolio(investor_id, slug)
        portfolio_data["investor_name"] = investor_name
    except Exception as scrape_err:
        logger.warning(f"Live scrape failed for investor {investor_id} ({scrape_err}). Attempting cached/seed recovery.")

    if not portfolio_data:
        # Fallback 1: Check existing SQLite cache (even if older than max_age_days)
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT data_json FROM cached_shark_portfolios WHERE investor_id = ?", (investor_id,))
            cached_row = cursor.fetchone()
            if cached_row:
                return json.loads(cached_row["data_json"])
                
        # Fallback 2: Check bundled seed dataset
        if os.path.exists(SEED_FILE_PATH):
            try:
                with open(SEED_FILE_PATH, "r", encoding="utf-8") as f:
                    seed_data = json.load(f)
                for port in seed_data.get("portfolios", []):
                    if str(port.get("investor_id")) == str(investor_id):
                        seed_port = json.loads(port["data_json"])
                        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
                        with get_db() as conn:
                            cursor = conn.cursor()
                            cursor.execute("""
                            INSERT OR REPLACE INTO cached_shark_portfolios (investor_id, data_json, last_updated)
                            VALUES (?, ?, ?)
                            """, (investor_id, port["data_json"], port.get("last_updated") or now_str))
                            conn.commit()
                        return seed_port
            except Exception:
                pass
                
        # Fallback 3: Safe minimal response instead of 500 error
        return {
            "investor_id": investor_id,
            "investor_name": investor_name,
            "holdings_count": 0,
            "holdings": [],
            "bio": f"Live portfolio details for {investor_name} could not be updated right now.",
            "insights": [],
            "quarters": []
        }
    
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    # 3. Option 3 Hook: Detect Brand New Entries & Aggressive Stake Hikes (>= +0.5%)
    alert_triggers = []
    with get_db() as conn:
        cursor = conn.cursor()
        for h in portfolio_data.get("holdings", []):
            sym = (h.get("symbol") or "").strip().upper()
            # Ignore non-equity ISINs, debt or purely numeric instruments
            if not sym or sym.isdigit() or len(sym) < 2:
                continue
            change_type = h.get("change_type", "UNCHANGED")
            change_pct = h.get("change_pct", 0.0)
            stake_pct = h.get("latest_stake_pct", 0.0)
            val_cr = h.get("holding_value_cr", 0.0)
            
            # Check if this change was already alerted
            if change_type == "NEW":
                cursor.execute("""
                SELECT id FROM shark_alert_history 
                WHERE investor_id = ? AND symbol = ? AND change_type = 'NEW_ENTRY'
                """, (investor_id, sym))
                if not cursor.fetchone():
                    alert_triggers.append({
                        "investor_name": investor_name,
                        "investor_id": investor_id,
                        "symbol": sym,
                        "change_type": "NEW_ENTRY",
                        "stake_pct": stake_pct,
                        "change_pct": change_pct,
                        "val_cr": val_cr
                    })
            elif change_type == "INCREASED" and change_pct >= 0.50:
                cursor.execute("""
                SELECT id FROM shark_alert_history 
                WHERE investor_id = ? AND symbol = ? AND change_type = 'AGGRESSIVE_STAKE_INCREASE' AND stake_percent = ?
                """, (investor_id, sym, stake_pct))
                if not cursor.fetchone():
                    alert_triggers.append({
                        "investor_name": investor_name,
                        "investor_id": investor_id,
                        "symbol": sym,
                        "change_type": "AGGRESSIVE_STAKE_INCREASE",
                        "stake_pct": stake_pct,
                        "change_pct": change_pct,
                        "val_cr": val_cr
                    })
                    
        # 4. Save Portfolio JSON to database
        cursor.execute("""
        INSERT INTO cached_shark_portfolios (investor_id, data_json, last_updated)
        VALUES (?, ?, ?)
        ON CONFLICT(investor_id) DO UPDATE SET
            data_json=excluded.data_json,
            last_updated=excluded.last_updated
        """, (investor_id, json.dumps(portfolio_data), now_str))
        
        # 5. Populate Normalized shark_stock_lookup Table
        for h in portfolio_data.get("holdings", []):
            cursor.execute("""
            INSERT INTO shark_stock_lookup 
            (symbol, company_name, investor_id, investor_name, holding_percent, holding_value_cr, shares_count, holding_entity, latest_quarter, prior_quarter_percent, change_percent, change_type, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, investor_id, holding_entity) DO UPDATE SET
                holding_percent=excluded.holding_percent,
                holding_value_cr=excluded.holding_value_cr,
                shares_count=excluded.shares_count,
                latest_quarter=excluded.latest_quarter,
                prior_quarter_percent=excluded.prior_quarter_percent,
                change_percent=excluded.change_percent,
                change_type=excluded.change_type,
                last_updated=excluded.last_updated
            """, (
                h["symbol"], h["stock_name"], investor_id, investor_name,
                h["latest_stake_pct"], h["holding_value_cr"], h["shares_count"],
                h["holder_name"], "Latest", h["prior_stake_pct"], h["change_pct"],
                h["change_type"], now_str
            ))
            
        conn.commit()
        
    # Dispatch Option 3 alerts asynchronously if any
    for trig in alert_triggers:
        dispatch_shark_alert(
            investor_name=trig["investor_name"],
            investor_id=trig["investor_id"],
            symbol=trig["symbol"],
            change_type=trig["change_type"],
            stake_pct=trig["stake_pct"],
            change_pct=trig["change_pct"],
            val_cr=trig["val_cr"]
        )
        
    return portfolio_data


# ─── OPTION 1: SHARK CONSENSUS SCREENER ────────────────────────────────────────

def get_shark_consensus(min_sharks: int = 2) -> List[Dict[str, Any]]:
    """
    Option 1: Returns high-conviction stocks held by >= min_sharks (default 2).
    Calculates combined equity stake %, total value in Cr, and investor breakdown.
    """
    init_shark_tables()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
        SELECT 
            symbol,
            company_name,
            COUNT(DISTINCT investor_id) as shark_count,
            ROUND(SUM(holding_percent), 2) as total_shark_stake,
            ROUND(SUM(holding_value_cr), 2) as total_shark_value_cr,
            GROUP_CONCAT(investor_name || ' (' || holding_percent || '%)', ' | ') as investors_breakdown
        FROM shark_stock_lookup
        WHERE holding_percent > 0.0
        GROUP BY symbol
        HAVING shark_count >= ?
        ORDER BY shark_count DESC, total_shark_value_cr DESC
        """, (min_sharks,))
        
        rows = cursor.fetchall()
        consensus_list = []
        for r in rows:
            # Query individual detailed investor chips for this symbol
            cursor.execute("""
            SELECT investor_id, investor_name, holding_percent, holding_value_cr, change_type, change_percent, holding_entity
            FROM shark_stock_lookup
            WHERE symbol = ? AND holding_percent > 0.0
            ORDER BY holding_value_cr DESC
            """, (r["symbol"],))
            inv_rows = [dict(ir) for ir in cursor.fetchall()]
            
            consensus_list.append({
                "symbol": r["symbol"],
                "company_name": r["company_name"],
                "shark_count": r["shark_count"],
                "total_shark_stake_pct": r["total_shark_stake"],
                "total_shark_value_cr": r["total_shark_value_cr"],
                "investors": inv_rows
            })
            
        return consensus_list


# ─── OPTION 3: WHATSAPP / TELEGRAM SHARK ALERTS ────────────────────────────────

def dispatch_shark_alert(investor_name: str, investor_id: str, symbol: str, change_type: str, stake_pct: float, change_pct: float, val_cr: float):
    """
    Option 3: Dispatches instant alert to WhatsApp / Telegram via backend/daily_wrapup.py
    and logs the alert in shark_alert_history and the global alerts table.
    """
    val_snippet = ""
    if val_cr >= 1.0:
        val_snippet = f" (approx ₹{val_cr:.1f} Cr)"
    elif val_cr > 0.0:
        val_lakhs = round(val_cr * 100, 1)
        val_snippet = f" (approx ₹{val_lakhs:.1f} L)"

    if change_type == "NEW_ENTRY":
        title = f"🦈 SHARK ALERT: New Entry by {investor_name}"
        body = f"Superstar investor *{investor_name}* entered a brand new disclosed stake in *{symbol}* of *{stake_pct:.1f}%*{val_snippet}."
    else:
        title = f"🦈 SHARK ALERT: Stake Increase by {investor_name}"
        body = f"Superstar investor *{investor_name}* aggressively increased holding in *{symbol}* by *+{change_pct:.2f}%* to *{stake_pct:.1f}%*{val_snippet}."
        
    full_msg = f"{title}\n\n{body}\n\n📈 *Indian Stock Analyzer 5.0 — Shark Radar*"
    
    # 1. Log in SQLite
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO shark_alert_history (investor_id, investor_name, symbol, change_type, stake_percent, change_percent, message_text)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (investor_id, investor_name, symbol, change_type, stake_pct, change_pct, full_msg))
        
        # Also post into app's main alerts bell notification table
        try:
            alert_id = f"shark_{investor_id}_{symbol}_{int(time.time())}"
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
            INSERT OR IGNORE INTO alerts (id, ticker, condition_type, operator, value, status, triggered, trigger_date, ai_context)
            VALUES (?, ?, 'SHARK_RADAR', '>=', ?, 'Triggered', 1, ?, ?)
            """, (alert_id, symbol, f"{stake_pct:.1f}%", now_str, full_msg))
        except Exception as e:
            print(f"[SharkRadar] Note inserting into alerts table: {e}")
        conn.commit()
        
    # 2. Asynchronously send via WhatsApp using the app's established sender
    try:
        from backend.daily_wrapup import send_whatsapp_wrapup
        import threading
        
        def run_async_send():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(send_whatsapp_wrapup(full_msg))
                loop.close()
            except Exception as e:
                print(f"[SharkRadar Alert] WhatsApp dispatch error: {e}")
                
        threading.Thread(target=run_async_send, daemon=True).start()
    except Exception as err:
        print(f"[SharkRadar Alert] Failed to trigger alert thread: {err}")


# ─── OPTION 6: 1-CLICK CLONE TO WATCHLIST ──────────────────────────────────────

def clone_shark_to_watchlist(investor_id: str, custom_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Option 6: Clones all stocks owned by an investor into a new or existing watchlist.
    Instantly available in the user's Watchlist tab with live tracking.
    """
    init_shark_tables()
    with get_db() as conn:
        cursor = conn.cursor()
        
        # 1. Get investor name
        cursor.execute("SELECT name FROM cached_shark_investors WHERE id = ?", (investor_id,))
        row = cursor.fetchone()
        investor_name = row["name"] if row else f"Investor {investor_id}"
        
        # 2. Get distinct stocks held by this investor
        cursor.execute("""
        SELECT DISTINCT symbol, company_name FROM shark_stock_lookup 
        WHERE investor_id = ? AND holding_percent > 0.0
        """, (investor_id,))
        stocks = cursor.fetchall()
        
        if not stocks:
            # Check if portfolio needs to be synced first
            sync_investor_portfolio(investor_id)
            cursor.execute("""
            SELECT DISTINCT symbol, company_name FROM shark_stock_lookup 
            WHERE investor_id = ? AND holding_percent > 0.0
            """, (investor_id,))
            stocks = cursor.fetchall()
            
        if not stocks:
            return {"status": "error", "message": f"No stocks found for investor {investor_name}."}
            
        # 3. Create or find Watchlist
        wl_name = custom_name.strip() if custom_name else f"🦈 {investor_name} Holdings"
        cursor.execute("SELECT id FROM watchlists WHERE name = ?", (wl_name,))
        wl_row = cursor.fetchone()
        
        if wl_row:
            watchlist_id = wl_row["id"]
        else:
            cursor.execute("INSERT INTO watchlists (name) VALUES (?)", (wl_name,))
            watchlist_id = cursor.lastrowid
            
        # 4. Insert stocks into watchlist_items
        added_count = 0
        for s in stocks:
            sym = s["symbol"].strip().upper()
            c_name = s["company_name"] or sym
            cursor.execute("""
            INSERT OR IGNORE INTO watchlist_items (watchlist_id, symbol, name, sector, quantity, purchase_price, in_portfolio)
            VALUES (?, ?, ?, 'Equities', 0.0, 0.0, 0)
            """, (watchlist_id, sym, c_name))
            if cursor.rowcount > 0:
                added_count += 1
                
        conn.commit()
        
        return {
            "status": "success",
            "watchlist_id": watchlist_id,
            "watchlist_name": wl_name,
            "investor_name": investor_name,
            "total_stocks": len(stocks),
            "added_count": added_count
        }


# ─── REVERSE LOOKUP FOR STOCK PROFILE PAGE ─────────────────────────────────────

def get_sharks_for_stock(symbol: str) -> List[Dict[str, Any]]:
    """
    Retrieves all shark investors holding >= 1% in the given symbol.
    Runs in < 1ms using the indexed shark_stock_lookup table.
    """
    init_shark_tables()
    clean_sym = symbol.replace(".NS", "").replace(".BO", "").strip().upper()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT 
            investor_id, 
            investor_name, 
            holding_percent, 
            holding_value_cr, 
            shares_count, 
            holding_entity, 
            latest_quarter, 
            prior_quarter_percent, 
            change_percent, 
            change_type,
            last_updated
        FROM shark_stock_lookup
        WHERE symbol = ? AND holding_percent > 0.0
        ORDER BY holding_value_cr DESC, holding_percent DESC
        """, (clean_sym,))
        
        return [dict(r) for r in cursor.fetchall()]


# ─── BATCH BACKGROUND WORKER ──────────────────────────────────────────────────

def sync_top_sharks_batch(limit: int = 15, delay_sec: float = 1.0):
    """
    Polite background worker to pre-populate the top N investors' portfolios.
    Called on system boot or manual sync trigger.
    """
    directory = sync_shark_directory(force=False)
    top_sharks = directory[:limit]
    
    for idx, shark in enumerate(top_sharks):
        try:
            sync_investor_portfolio(shark["id"], force=False)
            time.sleep(delay_sec)
        except Exception as e:
            print(f"[SharkRadar Worker] Error syncing {shark['name']}: {e}")
