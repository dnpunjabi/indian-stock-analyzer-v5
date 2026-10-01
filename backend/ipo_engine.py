import os
import re
import json
import time
import sqlite3
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
import yfinance as yf

# Database path setup
DB_DIR = os.environ.get("DATABASE_DIR", os.path.join(os.path.dirname(__file__), "data"))
os.makedirs(DB_DIR, exist_ok=True)
IPO_DB_PATH = os.path.join(DB_DIR, "ipo_cache.db")
IPO_PROCESSED_CACHE_PATH = os.path.join(DB_DIR, "ipo_processed_cache.json")

def save_processed_ipo_cache(data: dict):
    """Save processed IPO dataset with timestamp to disk JSON cache."""
    try:
        data["last_cron_run_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(IPO_PROCESSED_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(clean_nans(data), f, indent=2)
    except Exception as e:
        print(f"[IPO Engine] Failed to write cache: {e}")

def load_processed_ipo_cache(max_age_hours: float = 4.0) -> dict:
    """Load cached IPO dataset from disk if present and not expired."""
    if os.path.exists(IPO_PROCESSED_CACHE_PATH):
        try:
            mtime = os.path.getmtime(IPO_PROCESSED_CACHE_PATH)
            age_hours = (datetime.now().timestamp() - mtime) / 3600.0
            if age_hours > max_age_hours:
                print(f"[IPO Engine] Disk cache expired ({age_hours:.1f}h old > {max_age_hours}h max). Auto-refreshing dataset.")
                return None

            with open(IPO_PROCESSED_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data and isinstance(data, dict) and "ipos" in data:
                    return data
        except Exception as e:
            print(f"[IPO Engine] Failed to read cache: {e}")
    return None

# Known Name-to-NSE Ticker Mapping for recent mainboard IPOs
KNOWN_SYMBOL_MAP = {
    "national stock exchange": "NSE",
    "nse of india": "NSE",
    "national securities depository": "NSDL",
    "nsdl": "NSDL",
    "manipal payment": "MPIMANIPAL",
    "manipal payment & identity": "MPIMANIPAL",
    "asset reconstruction": "ARCIL",
    "asset reconstruction co": "ARCIL",
    "caliber mining": "CMLL",
    "caliber mining & logistics": "CMLL",
    "citius transnet": "CITIUSINVT-IV",
    "citius transnet investment": "CITIUSINVT-IV",
    "raajmarg infra": "RIIT-IV",
    "raajmarg infra investment": "RIIT-IV",
    "dr agarwal": "AGARWALEYE",
    "dr.agarwal": "AGARWALEYE",
    "dr agarwals health care": "AGARWALEYE",
    "dr.agarwal's health care": "AGARWALEYE",
    "dr. agarwal's eye hospital": "AGARWALEYE",
    "agarwal eye": "AGARWALEYE",
    "a-one steels": "AONESTEELS",
    "a one steels": "AONESTEELS",
    "aonesteels": "AONESTEELS",
    "adroit industries": "ADROITIND",
    "adroit": "ADROITIND",
    "swastika infra": "SWASTIKAIN",
    "armlee infotech": "ARMEE",
    "elevate campuses": "ELEVATE",
    "varmora granito": "VARMORA",
    "sonaselection": "SONA",
    "sonaselection india": "SONA",
    "manika plastech": "MANIKA",
    "manika plastics": "MANIKA",
    "annu projects": "ANNU",
    "hy-tech engineers": "HTEL",
    "hy-tech": "HTEL",
    "hte": "HTEL",
    "symbiotec": "SYMBIOTEC",
    "symbiotec pharmalab": "SYMBIOTEC",
    "skyways air": "SKYWAYS",
    "skyways air services": "SKYWAYS",
    "augmont enterprises": "AUGMONT",
    "augmont": "AUGMONT",
    "gaja alternative": "GAJA",
    "gaja alternative asset": "GAJA",
    "sunshine pictures": "SUNSHINE",
    "shankesh jewellers": "SHANKESH",
    "lalithaa jewellery": "LALITHAA",
    "horizon industrial": "HORIZONIND",
    "horizon industrial parks": "HORIZONIND",
    "milky mist": "MILKYMIST",
    "milky mist dairy": "MILKYMIST",
    "dhoot transmission": "DHOOTTRANS",
    "pine labs": "PINELABS",
    "groww": "GROWW",
    "lenskart": "LENSKART",
    "lenskart solutions": "LENSKART",
    "tata capital": "TATACAP",
    "lg electronics": "LGEINDIA",
    "hexaware technologies": "HEXT",
    "hexaware": "HEXT",
    "urban company": "URBANCO",
    "wework india": "WEWORK",
    "wework": "WEWORK",
    "behari lal engineering": "BLEL",
    "behari lal": "BLEL",
    "bajaj housing finance": "BAJAJHFL",
    "hyundai motor": "HYUNDAI",
    "swiggy": "SWIGGY",
    "waaree energies": "WAAREERTL",
    "waaree": "WAAREERTL",
    "premiere energies": "PREMIERENE",
    "ola electric": "OLAELEC",
    "krn heat exchanger": "KRN",
    "blackbuck": "BLACKBUCK",
    "zinka logistics": "BLACKBUCK",
    "hero motors": "HEROMOTORS",
    "ss retail": "SSRETAIL",
    "jindal supreme": "JSIPL",
    "jindal supreme india": "JSIPL",
    "jindal": "JSIPL",
    "cube highways": "CUBEINVIT",
    "cube highways trust": "CUBEINVIT",
    "cube highways invit": "CUBEINVIT",
    "ixigo": "IXIGO",
    "exicom": "EXICOM",
    "awfis": "AWFIS",
    "sanstar": "SANSTAR",
    "veegaland developers": "VEEGALAND",
    "veegaland": "VEEGALAND",
    "tempsens instruments": "TEMPSENS",
    "tempsens": "TEMPSENS",
    "esds software": "ESDS",
    "glottis": "GLOTTIS",
    "moneyview": "MONEYVIEW",
    "rentomojo": "RENTOMOJO",
    "shiprocket": "SHIPROCKET",
    "lumino industries": "LUMINO",
    "lumino": "LUMINO"
}

def init_ipo_db():
    """Ensure the SQLite caching table exists."""
    with sqlite3.connect(IPO_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ipo_master (
                symbol TEXT PRIMARY KEY,
                company_name TEXT NOT NULL,
                sector TEXT,
                issue_price REAL,
                listing_price REAL,
                issue_size_cr REAL,
                subscription_times REAL,
                listing_date TEXT,
                open_date TEXT,
                close_date TEXT,
                registrar TEXT,
                segment TEXT DEFAULT 'mainboard',
                anchor_lockin_30d TEXT,
                anchor_lockin_90d TEXT,
                updated_at TEXT
            )
        """)
        conn.commit()

def clean_str(s: str) -> str:
    if not s:
        return ""
    return s.encode('ascii', 'ignore').decode('ascii').strip()

def derive_ticker_from_name(name: str) -> str:
    """Helper to convert company title into standard NSE Ticker symbol."""
    clean_name = clean_str(name).lower()
    for key, sym in KNOWN_SYMBOL_MAP.items():
        if key in clean_name:
            return sym
    
    # Generic extraction: remove suffixes like IPO, Limited, Ltd, Pvt, India & scraped noise words
    cleaned = re.sub(r'\b(ipo|limited|ltd|pvt|private|india|industries|corp|corporation|listed|mainboard|upcoming|ongoing|closed|bidding|equity|services)\b', '', clean_name, flags=re.IGNORECASE)
    words = [w.upper() for w in re.findall(r'[A-Za-z0-9]+', cleaned) if len(w) >= 2]
    if not words:
        return "UNKNOWN"
    
    if len(words) == 1:
        return words[0][:10]
    elif len(words) == 2:
        return (words[0][:5] + words[1][:5])
    else:
        return "".join([w[0] for w in words])[:10]

def parse_date(date_str: str) -> str:
    """Normalize messy date strings to YYYY-MM-DD."""
    if not date_str or date_str in ['-', '--', 'N/A']:
        return ""
    clean = clean_str(date_str)
    
    # Try parsing formats like "24 Sep 2026", "24 Sep", "2026-09-24"
    for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(clean, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
            
    # Try parsing format like "24 Sep" assuming current/recent year
    for fmt in ("%d %b", "%d %B"):
        try:
            dt = datetime.strptime(clean, fmt)
            current_year = datetime.now().year
            dt = dt.replace(year=current_year)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
            
    return clean

def parse_price_band(val_str: str) -> tuple:
    """Parse messy price string or concatenated string into (lower_price, upper_price)."""
    if not val_str:
        return (0.0, 0.0)
    clean = clean_str(str(val_str)).replace(',', '').replace('Cr', '').replace('%', '').replace('+', '').strip()
    
    matches = re.findall(r'\d+\.?\d*', clean)
    if len(matches) >= 2:
        try:
            nums = [float(n) for n in matches]
            return (min(nums), max(nums))
        except ValueError:
            pass
            
    if len(matches) == 1:
        raw_num_str = str(int(float(matches[0])))
        num_val = float(raw_num_str)
        if num_val > 1000 and len(raw_num_str) % 2 == 0:
            half = len(raw_num_str) // 2
            p1 = float(raw_num_str[:half])
            p2 = float(raw_num_str[half:])
            if p1 > 0 and p2 > 0 and abs(p1 - p2) / max(p1, p2) < 0.4:
                return (min(p1, p2), max(p1, p2))
        return (num_val, num_val)
        
    return (0.0, 0.0)

KNOWN_SECTORS = {
    'SWIGGY': 'E-Commerce / Food Delivery',
    'HYUNDAI': 'Automobiles & Components',
    'BAJAJHFL': 'Housing Finance',
    'WAAREERTL': 'Solar & Renewable Energy',
    'PREMIERENE': 'Solar Cells & Modules',
    'OLAELEC': 'Electric Vehicles',
    'KRN': 'HVAC & Industrial Equipment',
    'BLACKBUCK': 'Logistics Tech',
    'SANSTAR': 'Plant-based Ingredients',
    'IXIGO': 'Travel Tech & OTA',
    'EXICOM': 'EV Chargers & Power Systems',
    'AWFIS': 'Flexible Workspace',
    'VEEGALAND': 'Real Estate',
    'TEMPSENS': 'Thermal Engineering',
    'ESDS': 'Cloud Computing & Data Centers',
    'GLOTTIS': 'Logistics & Supply Chain',
    'NSEOFSLM': 'Financial Markets / Exchange',
    'HEROMOTORS': 'Automobiles & Components',
    'SSRETAIL': 'Consumer Goods & Retail',
    'JINDASUPRE': 'Pipes & Infrastructure',
    'MANIKPLAST': 'Packaging & Plastics',
    'STEAMHOUSE': 'Thermal Energy & Power',
    'KARAMENGIN': 'Electrical Transmission',
    'PRANACONST': 'Infrastructure & Construction',
    'DEEPAJEWEL': 'Gems & Jewellery Retail',
    'ROB': 'Solar & Renewable Energy',
    'PSL': 'Fashion & Retail',
    'PRIORJEWEL': 'Gems & Jewellery Retail',
    'LUMINO': 'Electrical Equipment & Wires',
    'ANNUPROJE': 'Infrastructure & Engineering',
    'HTE': 'Precision Engineering',
    'SYMBIPHARM': 'Healthcare & Pharma',
    'SAS': 'Aviation & Airport Services',
    'AUGMOENTER': 'Metal & Gold Trading',
    'GAAM': 'Alternative Asset Management',
    'SUNSHPICTU': 'Media & Entertainment',
    'SHANKJEWEL': 'Gems & Jewellery Retail',
    'LJM': 'Gems & Jewellery Retail',
    'HIP': 'Industrial Real Estate & Warehousing',
    'BLE': 'Engineering & Machinery',
    'SHIPROCKET': 'Logistics & E-Commerce Tech',
    'HMDF': 'Dairy & Food Products'
}

def resolve_ipo_sector(symbol: str, company_name: str, raw_sector: str = "") -> str:
    """Intelligently resolves and normalizes IPO company sector."""
    s_sym = (symbol or "").upper().strip()
    if s_sym and s_sym in KNOWN_SECTORS:
        return KNOWN_SECTORS[s_sym]
        
    raw = (raw_sector or "").strip()
    if raw and raw.lower() not in ['recently listed', 'mainboard equity', 'mainboard', 'listed', 'equity', 'n/a', 'none', '']:
        return raw

    comb = f"{company_name} {s_sym}".lower()

    if any(k in comb for k in ['jewel', 'gold', 'diamond', 'gem']):
        return 'Gems & Jewellery'
    if any(k in comb for k in ['bank', 'finance', 'capital', 'housing fin', 'securities', 'wealth', 'fintech', 'invest', 'exchange', 'nifty', 'credit', 'fund', 'asset', 'reconstruction']):
        return 'Financial Services'
    if any(k in comb for k in ['solar', 'wind', 'renew', 'clean energy', 'green energy', 'power', 'battery', 'ev ']):
        return 'Renewable Energy & Power'
    if any(k in comb for k in ['pharma', 'health', 'lab ', 'med', 'bio', 'life science', 'hospital', 'clinic', 'drug', 'diagnostics', 'medical']):
        return 'Healthcare & Pharma'
    if any(k in comb for k in ['auto', 'motor', 'vehicle', 'mobility', 'tyre', 'tire', 'wheel', 'engine']):
        return 'Automobiles & Components'
    if any(k in comb for k in ['fashion', 'retail', 'apparel', 'footwear', 'textile', 'store', 'garment', 'wear', 'beauty', 'mart']):
        return 'Consumer Goods & Retail'
    if any(k in comb for k in ['build', 'const', 'infra', 'estate', 'realty', 'home', 'developer', 'housing', 'project', 'structure', 'pipe', 'cement', 'tiles', 'wall', 'glass wall']):
        return 'Infrastructure & Real Estate'
    if any(k in comb for k in ['food', 'beverage', 'snack', 'agri', 'dairy', 'brew', 'restaurant', 'hotel', 'resort', 'kitchen', 'bakery', 'milk', 'agro', 'grain']):
        return 'Food, FMCG & Agriculture'
    if any(k in comb for k in ['chem', 'polymer', 'fertilizer', 'petro', 'plastic', 'resin', 'organic', 'material']):
        return 'Chemicals & Materials'
    if any(k in comb for k in ['logistics', 'express', 'transport', 'shipping', 'port', 'freight', 'supply chain', 'cargo']):
        return 'Logistics & Transportation'
    if any(k in comb for k in ['tech', 'soft', 'cloud', 'data', 'infotech', 'digital', 'cyber', 'system', 'solution', 'telecom', 'ai ', 'payment', 'identity']):
        return 'IT & Technology'
    if any(k in comb for k in ['packag', 'paper', 'container', 'box', 'carton', 'film']):
        return 'Packaging & Containers'
    if any(k in comb for k in ['heat', 'engineer', 'machin', 'tool', 'metal', 'steel', 'industrial', 'equipment', 'cable', 'wire', 'valve', 'pump', 'foundry', 'gear', 'electric', 'electron']):
        return 'Industrial & Capital Goods'
    if any(k in comb for k in ['defense', 'defence', 'aerospace', 'space']):
        return 'Defence & Aerospace'
    if any(k in comb for k in ['media', 'entertainment', 'film', 'broadcasting', 'ad', 'multiplex', 'cinema']):
        return 'Media & Entertainment'

    return 'Industrial & Capital Goods'

def parse_num(val_str: str, default: float = 0.0) -> float:
    """Clean numeric values from string with Cr, %, commas, etc. returning upper band value."""
    if not val_str:
        return default
    low_p, high_p = parse_price_band(str(val_str))
    return high_p if high_p > 0 else default

def scrape_iporise_mainboard() -> list:
    """Primary Scraper for Mainboard IPOs from iporise.com (scrapes listed-ipo page window.__LISTED__)."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }
    records = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # Primary Source: https://www.iporise.com/listed-ipo?segment=mainboard
    url = "https://www.iporise.com/listed-ipo?segment=mainboard"
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code == 200:
            match = re.search(r'window\.__LISTED__\s*=\s*(\[.*?\]);', resp.text, re.DOTALL)
            if match:
                raw_items = json.loads(match.group(1))
                for item in raw_items:
                    segment_key = str(item.get('segmentKey') or item.get('segment') or '').lower()
                    if 'mainboard' not in segment_key:
                        continue
                        
                    raw_name = item.get('name', '')
                    name_clean = re.sub(r'IPO.*$', '', raw_name, flags=re.IGNORECASE).strip()
                    symbol = derive_ticker_from_name(name_clean or raw_name)
                    
                    raw_issue = str(item.get('issuePrice') or '')
                    raw_list = str(item.get('listPrice') or '')
                    raw_cur = str(item.get('curPrice') or '')
                    
                    _, issue_price = parse_price_band(raw_issue)
                    _, list_price = parse_price_band(raw_list)
                    _, cur_price = parse_price_band(raw_cur)
                    
                    cur_price = cur_price or list_price or issue_price
                    issue_size = float(item.get('issueSize') or 0.0)
                    sub_times = float(item.get('sub') or 0.0)
                    list_date_str = item.get('listDate', '')
                    list_date = parse_date(list_date_str)
                    
                    # EXCLUDE UNLISTED / FUTURE LISTING DATES from Listed 12M Radar
                    if list_date and list_date > today_str:
                        continue
                    if 'upcoming' in raw_name.lower() or 'ongoing' in raw_name.lower():
                        continue
                    
                    lockin_30d, lockin_90d = "", ""
                    if list_date:
                        try:
                            ld = datetime.strptime(list_date, "%Y-%m-%d")
                            lockin_30d = (ld + timedelta(days=30)).strftime("%Y-%m-%d")
                            lockin_90d = (ld + timedelta(days=90)).strftime("%Y-%m-%d")
                        except Exception:
                            pass
                            
                    records.append({
                        "symbol": symbol,
                        "company_name": name_clean or raw_name,
                        "sector": resolve_ipo_sector(symbol, name_clean or raw_name, item.get('sector')),
                        "issue_price": issue_price,
                        "listing_price": list_price,
                        "current_price": cur_price,
                        "issue_size_cr": issue_size,
                        "subscription_times": sub_times,
                        "listing_date": list_date,
                        "open_date": "",
                        "close_date": "",
                        "registrar": "KFintech / LinkIntime",
                        "segment": "mainboard",
                        "anchor_lockin_30d": lockin_30d,
                        "anchor_lockin_90d": lockin_90d,
                        "updated_at": datetime.now().isoformat()
                    })
    except Exception as e:
        print(f"[IPO Scraper] Error scraping iporise listed-ipo: {e}")
        
    if records:
        return records

    # Secondary Fallback: HTML table scraper on ipo-mainboard
    url_fallback = "https://www.iporise.com/ipo-mainboard"
    try:
        resp = requests.get(url_fallback, headers=headers, timeout=12)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            tables = soup.find_all('table')
            if tables:
                main_table = tables[0]
                rows = main_table.find_all('tr')
                if len(rows) > 1:
                    for row in rows[1:]:
                        tds = row.find_all(['td', 'th'])
                        if len(tds) >= 8:
                            raw_name = clean_str(tds[0].get_text(separator=' ', strip=True))
                            issue_price_str = clean_str(tds[2].get_text(separator=' ', strip=True))
                            issue_size_str = clean_str(tds[3].get_text(separator=' ', strip=True))
                            sub_str = clean_str(tds[5].get_text(separator=' ', strip=True)) if len(tds) > 5 else "0"
                            open_dt_str = clean_str(tds[6].get_text(separator=' ', strip=True)) if len(tds) > 6 else ""
                            close_dt_str = clean_str(tds[7].get_text(separator=' ', strip=True)) if len(tds) > 7 else ""
                            list_dt_str = clean_str(tds[8].get_text(separator=' ', strip=True)) if len(tds) > 8 else ""
                            
                            list_date = parse_date(list_dt_str)
                            row_text = clean_str(row.get_text()).lower()
                            if 'upcoming' in row_text or 'ongoing' in row_text:
                                continue
                            if list_date and list_date > today_str:
                                continue
                                
                            name_clean = re.sub(r'IPO.*$', '', raw_name, flags=re.IGNORECASE).strip()
                            symbol = derive_ticker_from_name(name_clean)
                            _, issue_price = parse_price_band(issue_price_str)
                            issue_size = parse_num(issue_size_str)
                            sub_times = parse_num(sub_str)
                            
                            lockin_30d, lockin_90d = "", ""
                            if list_date:
                                try:
                                    ld = datetime.strptime(list_date, "%Y-%m-%d")
                                    lockin_30d = (ld + timedelta(days=30)).strftime("%Y-%m-%d")
                                    lockin_90d = (ld + timedelta(days=90)).strftime("%Y-%m-%d")
                                except Exception:
                                    pass
                                    
                            records.append({
                                "symbol": symbol,
                                "company_name": name_clean or raw_name,
                                "sector": resolve_ipo_sector(symbol, name_clean or raw_name),
                                "issue_price": issue_price,
                                "listing_price": issue_price * 1.15 if issue_price else 0.0,
                                "issue_size_cr": issue_size,
                                "subscription_times": sub_times,
                                "listing_date": list_date,
                                "open_date": parse_date(open_dt_str),
                                "close_date": parse_date(close_dt_str),
                                "registrar": "KFintech / LinkIntime",
                                "segment": "mainboard",
                                "anchor_lockin_30d": lockin_30d,
                                "anchor_lockin_90d": lockin_90d,
                                "updated_at": datetime.now().isoformat()
                            })
    except Exception as e:
        print(f"[IPO Scraper] Error scraping iporise mainboard fallback: {e}")
        
    return records

def scrape_upcoming_pipeline() -> list:
    """Scrapes active pipeline, upcoming, ongoing, and allotment-pending IPOs from iporise.com."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0'}
    url = "https://www.iporise.com/ipo-mainboard"
    pipeline = []
    
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            tables = soup.find_all('table')
            if tables:
                table_0 = tables[0]
                rows = table_0.find_all('tr')
                for row in rows[1:]:
                    tds = row.find_all(['td', 'th'])
                    cols = [clean_str(td.get_text(separator=' ', strip=True)) for td in tds]
                    if len(cols) >= 8:
                        # Extract cell 0 strings to get company name & raw sector subtitle
                        cell0_strings = [clean_str(s) for s in tds[0].stripped_strings if clean_str(s)]
                        raw_name_cell = cell0_strings[0] if cell0_strings else cols[0]
                        raw_sector = ""
                        if len(cell0_strings) > 1:
                            potential = cell0_strings[1]
                            if potential.lower() not in ['upcoming', 'ongoing', 'closed', 'listed', 'mainboard', 'sme']:
                                raw_sector = potential

                        gmp_cell = cols[1]
                        issue_price_cell = cols[2]
                        issue_size_cell = cols[3]
                        lot_size_cell = cols[4]
                        sub_cell = cols[5]
                        open_cell = cols[6]
                        close_cell = cols[7]
                        listing_cell = cols[8] if len(cols) > 8 else ""
                        
                        row_lower = clean_str(row.get_text()).lower()
                        if 'listed' in row_lower and not any(k in row_lower for k in ['upcoming', 'ongoing', 'closed']):
                            continue
                            
                        if 'upcoming' in row_lower:
                            status = "Upcoming"
                            status_badge = "📅 Upcoming"
                            status_color = "#38bdf8"
                        elif 'ongoing' in row_lower:
                            status = "Ongoing"
                            status_badge = "🟢 Bidding Open"
                            status_color = "#10b981"
                        elif 'closed' in row_lower:
                            status = "Closed"
                            status_badge = "🟡 Allotment Pending"
                            status_color = "#f59e0b"
                        else:
                            status = "Pipeline"
                            status_badge = "⚡ Pipeline"
                            status_color = "#94a3b8"
                            
                        clean_name = re.sub(r'IPO.*$', '', raw_name_cell, flags=re.IGNORECASE).strip()
                        clean_name = re.sub(r'\b(Upcoming|Ongoing|Closed|Listed|MAINBOARD)\b', '', clean_name, flags=re.IGNORECASE).strip()
                        
                        low_p, high_p = parse_price_band(issue_price_cell)
                        
                        # Fix comma in issue size (e.g. "₹1,092 Cr" -> 1092.0)
                        size_clean = issue_size_cell.replace(',', '')
                        size_match = re.search(r'([\d\.]+)', size_clean)
                        issue_sz = float(size_match.group(1)) if size_match else 0.0
                        
                        lot_sz = int(re.search(r'\d+', lot_size_cell).group(0)) if re.search(r'\d+', lot_size_cell) else 0
                        
                        # Fix comma in subscription (e.g. "36.21x")
                        sub_clean = sub_cell.replace(',', '')
                        sub_match = re.search(r'([\d\.]+)', sub_clean)
                        sub_times = float(sub_match.group(1)) if sub_match else 0.0
                        
                        gmp_rs, gmp_pct = 0.0, 0.0
                        gmp_match = re.search(r'(\d+)\s*\(([\d\.]+)\%\)', gmp_cell)
                        if gmp_match:
                            gmp_rs = float(gmp_match.group(1))
                            gmp_pct = float(gmp_match.group(2))
                            
                        sym = derive_ticker_from_name(clean_name or raw_name_cell)
                        pipeline.append({
                            "company_name": clean_name or raw_name_cell,
                            "symbol": sym,
                            "sector": resolve_ipo_sector(sym, clean_name or raw_name_cell, raw_sector),
                            "status": status,
                            "status_badge": status_badge,
                            "status_color": status_color,
                            "min_price": low_p,
                            "max_price": high_p,
                            "price_band_str": f"₹{int(low_p)} - ₹{int(high_p)}" if low_p != high_p else f"₹{int(high_p)}",
                            "gmp_rs": gmp_rs,
                            "gmp_pct": gmp_pct,
                            "issue_size_cr": issue_sz,
                            "lot_size": lot_sz,
                            "subscription_times": sub_times,
                            "open_date": parse_date(open_cell),
                            "close_date": parse_date(close_cell),
                            "listing_date": parse_date(listing_cell),
                            "segment": "Mainboard"
                        })
    except Exception as e:
        print(f"[IPO Engine] Error scraping upcoming pipeline: {e}")
        
    return pipeline

SEED_MAINBOARD_IPOS = [
    {"symbol": "SWIGGY", "company_name": "Swiggy Limited", "sector": "E-Commerce / Food Delivery", "issue_price": 390.0, "listing_price": 420.0, "issue_size_cr": 11327.0, "subscription_times": 3.59, "listing_date": "2024-11-13", "open_date": "2024-11-06", "close_date": "2024-11-08", "registrar": "LinkIntime", "segment": "mainboard", "anchor_lockin_30d": "2024-12-13", "anchor_lockin_90d": "2025-02-13", "updated_at": datetime.now().isoformat()},
    {"symbol": "HYUNDAI", "company_name": "Hyundai Motor India Ltd", "sector": "Automobiles", "issue_price": 1960.0, "listing_price": 1934.0, "issue_size_cr": 27870.0, "subscription_times": 2.37, "listing_date": "2024-10-22", "open_date": "2024-10-15", "close_date": "2024-10-17", "registrar": "KFintech", "segment": "mainboard", "anchor_lockin_30d": "2024-11-22", "anchor_lockin_90d": "2025-01-22", "updated_at": datetime.now().isoformat()},
    {"symbol": "BAJAJHFL", "company_name": "Bajaj Housing Finance Ltd", "sector": "Housing Finance", "issue_price": 70.0, "listing_price": 150.0, "issue_size_cr": 6560.0, "subscription_times": 63.6, "listing_date": "2024-09-16", "open_date": "2024-09-09", "close_date": "2024-09-11", "registrar": "KFintech", "segment": "mainboard", "anchor_lockin_30d": "2024-10-16", "anchor_lockin_90d": "2024-12-16", "updated_at": datetime.now().isoformat()},
    {"symbol": "WAAREERTL", "company_name": "Waaree Energies Ltd", "sector": "Solar Energy Equipment", "issue_price": 1503.0, "listing_price": 2500.0, "issue_size_cr": 4321.0, "subscription_times": 76.34, "listing_date": "2024-10-28", "open_date": "2024-10-21", "close_date": "2024-10-23", "registrar": "LinkIntime", "segment": "mainboard", "anchor_lockin_30d": "2024-11-28", "anchor_lockin_90d": "2025-01-28", "updated_at": datetime.now().isoformat()},
    {"symbol": "PREMIERENE", "company_name": "Premiere Energies Ltd", "sector": "Solar Cells & Modules", "issue_price": 450.0, "listing_price": 990.0, "issue_size_cr": 2830.0, "subscription_times": 74.38, "listing_date": "2024-09-03", "open_date": "2024-08-27", "close_date": "2024-08-29", "registrar": "KFintech", "segment": "mainboard", "anchor_lockin_30d": "2024-10-03", "anchor_lockin_90d": "2024-12-03", "updated_at": datetime.now().isoformat()},
    {"symbol": "OLAELEC", "company_name": "Ola Electric Mobility Ltd", "sector": "Electric Vehicles", "issue_price": 76.0, "listing_price": 76.0, "issue_size_cr": 6145.0, "subscription_times": 4.45, "listing_date": "2024-08-09", "open_date": "2024-08-02", "close_date": "2024-08-06", "registrar": "LinkIntime", "segment": "mainboard", "anchor_lockin_30d": "2024-09-09", "anchor_lockin_90d": "2024-11-09", "updated_at": datetime.now().isoformat()},
    {"symbol": "KRN", "company_name": "KRN Heat Exchanger Ltd", "sector": "HVAC / Industrial Equipment", "issue_price": 220.0, "listing_price": 470.0, "issue_size_cr": 341.0, "subscription_times": 214.4, "listing_date": "2024-10-03", "open_date": "2024-09-25", "close_date": "2024-09-27", "registrar": "Bigshare", "segment": "mainboard", "anchor_lockin_30d": "2024-11-03", "anchor_lockin_90d": "2025-01-03", "updated_at": datetime.now().isoformat()},
    {"symbol": "BLACKBUCK", "company_name": "Zinka Logistics Solution (BlackBuck)", "sector": "Logistics Tech", "issue_price": 273.0, "listing_price": 279.0, "issue_size_cr": 1114.0, "subscription_times": 1.86, "listing_date": "2024-11-22", "open_date": "2024-11-13", "close_date": "2024-11-18", "registrar": "KFintech", "segment": "mainboard", "anchor_lockin_30d": "2024-12-22", "anchor_lockin_90d": "2025-02-22", "updated_at": datetime.now().isoformat()},
    {"symbol": "SANSTAR", "company_name": "Sanstar Limited", "sector": "Plant-based Ingredients", "issue_price": 95.0, "listing_price": 109.0, "issue_size_cr": 510.0, "subscription_times": 82.9, "listing_date": "2024-07-26", "open_date": "2024-07-19", "close_date": "2024-07-23", "registrar": "LinkIntime", "segment": "mainboard", "anchor_lockin_30d": "2024-08-26", "anchor_lockin_90d": "2024-10-26", "updated_at": datetime.now().isoformat()},
    {"symbol": "IXIGO", "company_name": "Le Travenues Technology (ixigo)", "sector": "Travel Tech / OTA", "issue_price": 93.0, "listing_price": 138.0, "issue_size_cr": 740.0, "subscription_times": 98.3, "listing_date": "2024-06-18", "open_date": "2024-06-10", "close_date": "2024-06-12", "registrar": "LinkIntime", "segment": "mainboard", "anchor_lockin_30d": "2024-07-18", "anchor_lockin_90d": "2024-09-18", "updated_at": datetime.now().isoformat()},
    {"symbol": "EXICOM", "company_name": "Exicom Tele-Systems Ltd", "sector": "EV Chargers & Power Systems", "issue_price": 142.0, "listing_price": 265.0, "issue_size_cr": 429.0, "subscription_times": 129.5, "listing_date": "2024-03-05", "open_date": "2024-02-27", "close_date": "2024-02-29", "registrar": "LinkIntime", "segment": "mainboard", "anchor_lockin_30d": "2024-04-05", "anchor_lockin_90d": "2024-06-05", "updated_at": datetime.now().isoformat()},
    {"symbol": "AWFIS", "company_name": "Awfis Space Solutions Ltd", "sector": "Flexible Workspace", "issue_price": 383.0, "listing_price": 435.0, "issue_size_cr": 599.0, "subscription_times": 108.6, "listing_date": "2024-05-30", "open_date": "2024-05-22", "close_date": "2024-05-27", "registrar": "Bigshare", "segment": "mainboard", "anchor_lockin_30d": "2024-06-30", "anchor_lockin_90d": "2024-08-30", "updated_at": datetime.now().isoformat()},
    {"symbol": "VEEGALAND", "company_name": "Veegaland Developers Ltd", "sector": "Real Estate", "issue_price": 140.0, "listing_price": 154.0, "issue_size_cr": 180.0, "subscription_times": 12.4, "listing_date": "2024-08-14", "open_date": "2024-08-05", "close_date": "2024-08-08", "registrar": "LinkIntime", "segment": "mainboard", "anchor_lockin_30d": "2024-09-14", "anchor_lockin_90d": "2024-11-14", "updated_at": datetime.now().isoformat()},
    {"symbol": "TEMPSENS", "company_name": "Tempsens Instruments Ltd", "sector": "Thermal Engineering", "issue_price": 300.0, "listing_price": 634.0, "issue_size_cr": 220.0, "subscription_times": 45.2, "listing_date": "2024-08-20", "open_date": "2024-08-12", "close_date": "2024-08-14", "registrar": "KFintech", "segment": "mainboard", "anchor_lockin_30d": "2024-09-20", "anchor_lockin_90d": "2024-11-20", "updated_at": datetime.now().isoformat()},
    {"symbol": "ESDS", "company_name": "ESDS Software Solution Ltd", "sector": "Cloud Computing & Data Centers", "issue_price": 429.0, "listing_price": 757.0, "issue_size_cr": 320.0, "subscription_times": 38.6, "listing_date": "2024-08-12", "open_date": "2024-08-02", "close_date": "2024-08-06", "registrar": "KFintech", "segment": "mainboard", "anchor_lockin_30d": "2024-09-12", "anchor_lockin_90d": "2024-11-12", "updated_at": datetime.now().isoformat()},
    {"symbol": "GLOTTIS", "company_name": "Glottis Limited", "sector": "Logistics & Supply Chain", "issue_price": 129.0, "listing_price": 84.0, "issue_size_cr": 250.0, "subscription_times": 8.5, "listing_date": "2024-08-05", "open_date": "2024-07-26", "close_date": "2024-07-30", "registrar": "Bigshare", "segment": "mainboard", "anchor_lockin_30d": "2024-09-05", "anchor_lockin_90d": "2024-11-05", "updated_at": datetime.now().isoformat()}
]

def fetch_investorgain_fallback() -> list:
    """Fallback Scraper for IPO Performance Tracker."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0'}
    url = 'https://www.investorgain.com/report/ipo-performance-tracker/331/'
    records = list(SEED_MAINBOARD_IPOS)
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'utf-8'
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            table = soup.find('table')
            if table:
                rows = table.find_all('tr')
                for row in rows[1:]:
                    cols = [clean_str(td.get_text(strip=True)) for td in row.find_all(['td', 'th'])]
                    if len(cols) >= 6:
                        raw_name = cols[0]
                        if 'MAINBOARD' in raw_name or 'IPO' in raw_name:
                            name_clean = re.sub(r'IPO.*$', '', raw_name, flags=re.IGNORECASE).strip()
                            symbol = derive_ticker_from_name(name_clean)
                            if symbol != "UNKNOWN":
                                issue_px = parse_num(cols[4])
                                issue_sz = parse_num(cols[5])
                                records.append({
                                    "symbol": symbol,
                                    "company_name": name_clean,
                                    "sector": "Mainboard Equity",
                                    "issue_price": issue_px,
                                    "listing_price": issue_px * 1.1,
                                    "issue_size_cr": issue_sz,
                                    "subscription_times": 10.0,
                                    "listing_date": (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d"),
                                    "open_date": "",
                                    "close_date": "",
                                    "registrar": "LinkIntime",
                                    "segment": "mainboard",
                                    "anchor_lockin_30d": "",
                                    "anchor_lockin_90d": "",
                                    "updated_at": datetime.now().isoformat()
                                })
    except Exception as e:
        print(f"[IPO Scraper] Fallback investorgain error: {e}")
    return records

def sync_ipo_master_db(force_refresh: bool = False) -> list:
    """Sync IPO list with SQLite local database."""
    init_ipo_db()
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    with sqlite3.connect(IPO_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Purge unlisted, future-dated, or corrupt items from DB cache
        cursor.execute("DELETE FROM ipo_master WHERE listing_date > ? OR listing_date IS NULL OR listing_date = ''", (today_str,))
        cursor.execute("DELETE FROM ipo_master WHERE issue_price > 10000")
        conn.commit()
        
        # Check cache age
        if not force_refresh:
            rows = cursor.execute("SELECT * FROM ipo_master WHERE listing_date <= ? ORDER BY listing_date DESC", (today_str,)).fetchall()
            if rows and len(rows) >= 5:
                first_row = dict(rows[0])
                updated_at = first_row.get("updated_at", "")
                if updated_at:
                    try:
                        updated_dt = datetime.fromisoformat(updated_at)
                        if datetime.now() - updated_dt < timedelta(hours=12):
                            return [dict(r) for r in rows]
                    except Exception:
                        pass
                        
        # Fetch fresh data from primary scraper and flush stale DB records
        print("[IPO Engine] Flushing stale DB table & refreshing IPO master data from scrapers...")
        cursor.execute("DELETE FROM ipo_master")
        conn.commit()
        
        fresh_records = scrape_iporise_mainboard()
        if not fresh_records:
            fresh_records = fetch_investorgain_fallback()
            
        # Combine scraped records with curated seed list of top 12M mainboard IPOs
        combined_map = {rec["symbol"]: rec for rec in SEED_MAINBOARD_IPOS if not rec.get("listing_date") or rec["listing_date"] <= today_str}
        for rec in fresh_records:
            list_dt = rec.get("listing_date", "")
            if list_dt and list_dt > today_str:
                continue
            combined_map[rec["symbol"]] = rec
            
        all_to_sync = list(combined_map.values())
        
        if all_to_sync:
            for rec in all_to_sync:
                cursor.execute("""
                    INSERT INTO ipo_master (
                        symbol, company_name, sector, issue_price, listing_price,
                        issue_size_cr, subscription_times, listing_date, open_date,
                        close_date, registrar, segment, anchor_lockin_30d, anchor_lockin_90d, updated_at
                    ) VALUES (
                        :symbol, :company_name, :sector, :issue_price, :listing_price,
                        :issue_size_cr, :subscription_times, :listing_date, :open_date,
                        :close_date, :registrar, :segment, :anchor_lockin_30d, :anchor_lockin_90d, :updated_at
                    ) ON CONFLICT(symbol) DO UPDATE SET
                        company_name=excluded.company_name,
                        sector=excluded.sector,
                        issue_price=excluded.issue_price,
                        listing_price=excluded.listing_price,
                        issue_size_cr=excluded.issue_size_cr,
                        subscription_times=excluded.subscription_times,
                        listing_date=excluded.listing_date,
                        updated_at=excluded.updated_at
                """, rec)
            conn.commit()
            
        rows = cursor.execute("SELECT * FROM ipo_master WHERE listing_date <= ? ORDER BY listing_date DESC", (today_str,)).fetchall()
        return [dict(r) for r in rows]

def resolve_true_ticker_symbol(company_name: str, fallback_symbol: str) -> str:
    """
    Automatically verifies and resolves the official NSE ticker symbol for any new IPO company name
    using Screener API and Yahoo Finance Search API if the fallback derived symbol fails yfinance lookup.
    Result is cached in KNOWN_SYMBOL_MAP & SQLite DB for ultra-fast future resolution.
    """
    if not company_name:
        return fallback_symbol
        
    import urllib.parse
    clean_name = clean_str(company_name).lower()
    for k, sym in KNOWN_SYMBOL_MAP.items():
        if k in clean_name:
            return sym

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0'}
    
    # Method 1: Screener API Search
    try:
        url = f"https://www.screener.in/api/company/search/?q={urllib.parse.quote(company_name)}"
        resp = requests.get(url, headers=headers, timeout=3)
        if resp.status_code == 200:
            results = resp.json()
            if results and isinstance(results, list) and len(results) > 0:
                match_url = results[0].get("url", "")
                m = re.search(r'/company/([A-Z0-9]+)', match_url)
                if m:
                    actual_ticker = m.group(1).upper()
                    KNOWN_SYMBOL_MAP[clean_name] = actual_ticker
                    KNOWN_SYMBOL_MAP[fallback_symbol.lower()] = actual_ticker
                    print(f"[IPO Engine] Auto-resolved symbol via Screener for '{company_name}': {fallback_symbol} -> {actual_ticker}")
                    
                    try:
                        with sqlite3.connect(IPO_DB_PATH) as conn:
                            conn.execute("UPDATE ipo_master SET symbol=? WHERE company_name=? OR symbol=?", (actual_ticker, company_name, fallback_symbol))
                            conn.commit()
                    except Exception:
                        pass
                        
                    return actual_ticker
    except Exception:
        pass

    # Method 2: Yahoo Finance Search API Fallback
    try:
        yf_search_url = f"https://query2.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(company_name)}&quotesCount=5"
        resp = requests.get(yf_search_url, headers=headers, timeout=3)
        if resp.status_code == 200:
            quotes = resp.json().get("quotes", [])
            for q in quotes:
                raw_sym = q.get("symbol", "")
                if raw_sym and (".NS" in raw_sym or ".BO" in raw_sym):
                    clean_sym = raw_sym.replace(".NS", "").replace(".BO", "").strip().upper()
                    KNOWN_SYMBOL_MAP[clean_name] = clean_sym
                    KNOWN_SYMBOL_MAP[fallback_symbol.lower()] = clean_sym
                    print(f"[IPO Engine] Auto-resolved symbol via Yahoo Search for '{company_name}': {fallback_symbol} -> {clean_sym}")
                    return clean_sym
    except Exception:
        pass
        
    return fallback_symbol

def fetch_yf_history_safe(symbol: str, company_name: str = "", retries: int = 2) -> tuple:
    """
    Safely fetches 1y history from Yahoo Finance with retry & backoff on rate limits.
    Tries resolved true ticker mapping first (.NS / .BO), then fallback symbol (.NS / .BO).
    Returns (df, resolved_symbol).
    """
    if not symbol:
        return pd.DataFrame(), ""
        
    clean = symbol.replace('.NS', '').replace('.BO', '').strip()
    symbols_to_try = []
    
    if company_name:
        resolved = resolve_true_ticker_symbol(company_name, clean)
        if resolved:
            symbols_to_try.append(resolved)
            
    if clean not in symbols_to_try:
        symbols_to_try.append(clean)
            
    for sym in symbols_to_try:
        for suffix in [".NS", ".BO"]:
            cand = f"{sym}{suffix}" if not sym.endswith(suffix) else sym
            for attempt in range(retries):
                try:
                    tk = yf.Ticker(cand)
                    df = tk.history(period="1y")
                    if not df.empty and len(df) >= 1:
                        return df, sym
                except Exception as e:
                    err_str = str(e).lower()
                    if "too many requests" in err_str or "rate limit" in err_str or "429" in err_str:
                        time.sleep(1.0 * (attempt + 1))
                    else:
                        break
                        
    return pd.DataFrame(), clean

def get_ipo_technical_analysis(symbol: str, listing_date: str, issue_price: float, listing_price: float, current_price_scraped: float = 0.0, company_name: str = "") -> dict:
    """Fetch daily OHLCV candles via yfinance and compute technical setup & metrics."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    if listing_date and listing_date > today_str:
        return {"is_valid_listed": False}
        
    # Compute exact days since listing
    days_listed = 30
    if listing_date:
        try:
            ld = datetime.strptime(listing_date, "%Y-%m-%d")
            days_listed = max(0, (datetime.now() - ld).days)
        except Exception:
            pass
            
    # Default fallback metrics when historical candles are unavailable
    fallback_cmp = current_price_scraped if current_price_scraped > 0 else (listing_price or issue_price or 100.0)
    baseline_high = max(fallback_cmp, listing_price, issue_price) if (listing_price or issue_price) else fallback_cmp
    fallback_drawdown = None
    if baseline_high > 0 and fallback_cmp < baseline_high:
        fallback_drawdown = round(((fallback_cmp - baseline_high) / baseline_high) * 100, 2)
        
    res = {
        "is_valid_listed": True if (issue_price > 0 or listing_price > 0) else False,
        "has_historical_candles": False,
        "current_price": fallback_cmp,
        "day_change_pct": 0.0,
        "listing_gain_pct": round(((listing_price - issue_price) / issue_price * 100), 2) if issue_price else 0.0,
        "current_gain_from_issue_pct": round(((fallback_cmp - issue_price) / issue_price * 100), 2) if issue_price else 0.0,
        "current_gain_from_listing_pct": round(((fallback_cmp - listing_price) / listing_price * 100), 2) if listing_price else 0.0,
        "ath": baseline_high,
        "atl": min(fallback_cmp, listing_price, issue_price, 100.0) if (listing_price or issue_price) else 100.0,
        "drawdown_from_ath_pct": fallback_drawdown,
        "days_since_listing": days_listed,
        "ma_20": None,
        "ma_50": None,
        "rsi_14": None,
        "vol_20_sma": None,
        "volume_dryup_ratio": None,
        "sparkline_prices": []
    }
    
    try:
        df, actual_sym = fetch_yf_history_safe(symbol, company_name=company_name)
        if df.empty or len(df) < 1:
            res["resolved_symbol"] = symbol
            return res
            
        prices = df['Close'].tolist()
        volumes = df['Volume'].tolist()
        curr_px = float(prices[-1])
        
        # Check if Angel One SmartWebSocket live tick_store has a real-time CMP tick
        try:
            from backend.websocket_server import tick_store
            clean_sym = symbol.replace('.NS', '').replace('.BO', '').strip().upper()
            live_tick = tick_store.get(clean_sym) or tick_store.get(f"{clean_sym}.NS")
            if live_tick:
                ltp = live_tick.get("last_price") or live_tick.get("ltp") or live_tick.get("c") or live_tick.get("price")
                if ltp and float(ltp) > 0:
                    curr_px = float(ltp)
        except Exception as ws_err:
            pass

        ath_px = max(float(df['High'].max()), curr_px)
        atl_px = float(df['Low'].min())
        
        # Calculate returns
        issue_px = issue_price if (issue_price > 0 and issue_price < 20000) else float(df['Open'].iloc[0])
        list_px = listing_price if (listing_price > 0 and listing_price < 20000) else float(df['Open'].iloc[0])
        
        gain_from_issue = round(((curr_px - issue_px) / issue_px) * 100, 2)
        gain_from_listing = round(((curr_px - list_px) / list_px) * 100, 2)
        drawdown_ath = round(((curr_px - ath_px) / ath_px) * 100, 2)
        
        # Calculate moving averages & indicators
        ma20 = float(df['Close'].ewm(span=20).mean().iloc[-1]) if len(df) >= 10 else None
        ma50 = float(df['Close'].rolling(window=50).mean().iloc[-1]) if len(df) >= 30 else None
        
        # RSI 14
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        rsi = float(100 - (100 / (1 + rs)).iloc[-1]) if len(df) >= 14 else 50.0
        
        # Volume dry up ratio (last 5-day avg vol / 20-day avg vol)
        vol_20_raw = df['Volume'].rolling(window=20).mean().iloc[-1] if len(df) >= 10 else df['Volume'].mean()
        vol_20 = float(vol_20_raw) if (pd.notna(vol_20_raw) and not np.isnan(vol_20_raw)) else 100000.0
        
        vol_5_raw = df['Volume'].tail(5).mean() if len(df) >= 5 else vol_20
        vol_5 = float(vol_5_raw) if (pd.notna(vol_5_raw) and not np.isnan(vol_5_raw)) else vol_20
        vol_dryup = round(vol_5 / (vol_20 + 1e-9), 2)
        
        # Sparkline (last 20 prices)
        sparkline = [round(float(p), 2) for p in prices[-20:] if pd.notna(p)]

        # Daily Change % relative to previous close
        prev_close = float(prices[-2]) if len(prices) >= 2 else curr_px
        day_change_pct = round(((curr_px - prev_close) / prev_close) * 100, 2) if prev_close > 0 else 0.0

        res.update({
            "is_valid_listed": True,
            "has_historical_candles": True,
            "current_price": round(curr_px, 2),
            "day_change_pct": day_change_pct,
            "listing_gain_pct": round(((list_px - issue_px) / issue_px * 100), 2),
            "current_gain_from_issue_pct": gain_from_issue,
            "current_gain_from_listing_pct": gain_from_listing,
            "ath": round(ath_px, 2),
            "atl": round(atl_px, 2),
            "drawdown_from_ath_pct": drawdown_ath,
            "days_since_listing": days_listed,
            "ma_20": round(ma20, 2) if ma20 else None,
            "ma_50": round(ma50, 2) if ma50 else None,
            "rsi_14": round(rsi, 1),
            "vol_20_sma": int(vol_20) if pd.notna(vol_20) else 100000,
            "volume_dryup_ratio": vol_dryup,
            "sparkline_prices": sparkline,
            "resolved_symbol": actual_sym
        })
    except Exception as e:
        print(f"[IPO Engine] YFinance analysis failed for {symbol}: {e}")
        
    return res

def evaluate_ipo_buy_opportunity(ipo: dict, tech: dict) -> dict:
    """
    Quantitative Algorithmic Scoring (0 - 100) for recent IPOs.
    Categorizes into Setups: IPO Base Breakout, Pullback to 20 EMA, Lock-in Reversal, Initial Price Discovery.
    """
    has_candles = tech.get("has_historical_candles", False)
    days_listed = tech.get("days_since_listing", 0)
    issue_gain = tech.get("current_gain_from_issue_pct", 0.0)
    list_gain = tech.get("current_gain_from_listing_pct", 0.0)
    drawdown_ath = tech.get("drawdown_from_ath_pct", 0.0)
    curr_px = tech.get("current_price", 0.0)
    
    reasons = []
    
    # -------------------------------------------------------------
    # Scenario 1: Newly Listed Stock (< 30 calendar days)
    # -------------------------------------------------------------
    if days_listed < 30:
        setup_type = "🌱 Initial Price Discovery"
        if issue_gain >= 15.0:
            score = 65
            badge = "Watchlist - Initial Rally"
            color = "#38bdf8" # Cyan
        elif issue_gain >= 0.0:
            score = 55
            badge = "Watchlist - Building Base"
            color = "#f59e0b" # Yellow
        else:
            score = 40
            badge = "Avoid - Below Issue Price"
            color = "#ef4444" # Red
            
        reasons.append(f"Listed {days_listed} days ago (in initial price discovery phase)")
        reasons.append(f"Current price return from issue price is {issue_gain}%")
        reasons.append("Requires at least 30 calendar days to establish technical IPO base")
        
        return {
            "opportunity_score": score,
            "signal_badge": badge,
            "badge_color": color,
            "setup_type": setup_type,
            "key_reasons": reasons
        }

    # -------------------------------------------------------------
    # Scenario 1b: Stock >= 30 days without full candles
    # -------------------------------------------------------------
    if not has_candles:
        if issue_gain < -5.0:
            setup_type = "📉 Below Issue Price"
            score = 40
            badge = "Avoid - Below Issue Price"
            color = "#ef4444"
        elif issue_gain >= 15.0:
            setup_type = "📦 IPO Base Consolidation"
            score = 65
            badge = "Watchlist - Building Base"
            color = "#f59e0b"
        else:
            setup_type = "Consolidating Base"
            score = 55
            badge = "Watchlist - Building Base"
            color = "#f59e0b"
            
        reasons.append(f"Listed {days_listed} days ago")
        reasons.append(f"Current price return from issue price is {issue_gain}%")
        
        return {
            "opportunity_score": score,
            "signal_badge": badge,
            "badge_color": color,
            "setup_type": setup_type,
            "key_reasons": reasons
        }

    # -------------------------------------------------------------
    # Scenario 2: Established IPO Stock (>= 15 trading days with OHLC candles)
    # -------------------------------------------------------------
    score = 50 # Base neutral score
    setup_type = "Consolidating Base"
    
    # 1. Negative Return Penalties
    if issue_gain < -5.0:
        score -= 20
        reasons.append(f"Trading below issue price ({issue_gain}% since IPO)")
    elif list_gain < -5.0:
        score -= 10
        reasons.append(f"Trading below listing day open price ({list_gain}%)")

    # 2. ATH Drawdown Evaluation (IPO Base Breakout / Consolidation)
    dist_from_ath = abs(drawdown_ath)
    if dist_from_ath <= 4.0 and issue_gain >= 0:
        score += 25
        setup_type = "🚀 IPO Base Breakout"
        reasons.append("Trading within 4% of All-Time High in an IPO Base breakout zone")
    elif dist_from_ath <= 10.0 and issue_gain >= 0:
        score += 12
        setup_type = "📦 IPO Base Consolidation"
        reasons.append("Forming tight upper consolidation within 10% of ATH")
    elif drawdown_ath < -20.0:
        score -= 15
        setup_type = "📉 Pullback / Correction"
        reasons.append(f"Stock in correction (-{dist_from_ath}% off All-Time High peak)")

    # 3. Moving Average Support
    ma20 = tech.get("ma_20")
    ma50 = tech.get("ma_50")
    if ma20 and abs(curr_px - ma20) / ma20 <= 0.025:
        score += 15
        if setup_type == "Consolidating Base":
            setup_type = "📉 Pullback to 20 EMA"
        reasons.append("Supported strongly at 20-day Exponential Moving Average")
    elif ma50 and abs(curr_px - ma50) / ma50 <= 0.03:
        score += 10
        reasons.append("Finding institutional support at 50-day Moving Average")

    # 4. Volume Contraction (VCP / Dry-up)
    vol_dryup = tech.get("volume_dryup_ratio")
    if vol_dryup is not None:
        if vol_dryup <= 0.65:
            score += 15
            reasons.append(f"Volume dried up significantly ({int((1 - vol_dryup)*100)}% lower than 20-day avg)")
        elif vol_dryup <= 0.85:
            score += 8
            reasons.append("Supply drying up on tight price contractions")

    # 5. RSI & Momentum Scenarios
    rsi = tech.get("rsi_14")
    if rsi is not None:
        if 50.0 <= rsi <= 68.0:
            score += 10
            reasons.append(f"RSI ({rsi}) is in bullish accumulation territory")
        elif rsi > 75.0:
            score -= 15
            reasons.append(f"RSI ({rsi}) is short-term overextended")

    # 6. Lock-in Expiry Timeline Assessment
    lockin_30d = ipo.get("anchor_lockin_30d", "")
    if lockin_30d:
        try:
            lockin_dt = datetime.strptime(lockin_30d, "%Y-%m-%d")
            now = datetime.now()
            diff_days = (lockin_dt - now).days
            if 0 <= diff_days <= 7:
                score -= 10
                reasons.append(f"⚠️ 30-day Anchor Lock-in expires in {diff_days} days")
            elif -14 <= diff_days < 0:
                score += 12
                if setup_type == "Consolidating Base":
                    setup_type = "🔓 Post-Lockin Reversal"
                reasons.append("30-day Anchor Lock-in expired recently and market absorbed supply")
        except Exception:
            pass

    # Bound final score between 5 and 98
    final_score = max(5, min(98, score))
    
    # Classification Badge
    if final_score >= 80:
        badge = "Strong Buy Opportunity"
        color = "#10b981" # Green
    elif final_score >= 60:
        badge = "Watchlist - Building Base"
        color = "#f59e0b" # Yellow
    elif final_score >= 40:
        badge = "Overextended / Wait"
        color = "#f97316" # Orange
    else:
        badge = "Avoid / Weak Trend"
        color = "#ef4444" # Red
        
    return {
        "opportunity_score": final_score,
        "signal_badge": badge,
        "badge_color": color,
        "setup_type": setup_type,
        "key_reasons": reasons[:3] if reasons else ["Consolidating in post-listing price range"]
    }

def deduplicate_ipo_dataset(ipos_list: list) -> list:
    """Ensure each stock symbol / company name appears only once in the dataset."""
    if not ipos_list:
        return []
    seen_symbols = set()
    seen_companies = set()
    deduped = []
    
    for item in ipos_list:
        sym = (item.get("symbol") or "").strip().upper()
        raw_comp = (item.get("company_name") or "").strip()
        comp = clean_str(raw_comp).lower()
        
        if not sym or sym == "UNKNOWN":
            continue
            
        if sym in seen_symbols:
            continue
            
        if comp and len(comp) > 4 and comp in seen_companies:
            continue
            
        seen_symbols.add(sym)
        if comp and len(comp) > 4:
            seen_companies.add(comp)
            
        deduped.append(item)
        
    return deduped

def apply_live_ticks_to_ipo_dataset(data: dict) -> dict:
    """
    Dynamically updates cached IPO items with live streaming LTP from WebSocket tick_store,
    deduplicates stock records, and automatically triggers registration of IPO symbols to AngelOne WebSocket.
    """
    if not data or "ipos" not in data or not isinstance(data.get("ipos"), list):
        return data
        
    try:
        from backend.websocket_server import tick_store, subscribe_symbols
        # Deduplicate dataset records
        ipos = deduplicate_ipo_dataset(data.get("ipos", []))
        data["ipos"] = ipos
        if "summary" in data and isinstance(data["summary"], dict):
            data["summary"]["total_ipos_12m"] = len(ipos)

        symbols_to_subscribe = []
        
        for item in ipos:
            sym = item.get("symbol", "").strip().upper()
            if not sym or sym == "UNKNOWN":
                continue
            clean_sym = sym.replace('.NS', '').replace('.BO', '').strip()
            symbols_to_subscribe.append(clean_sym)
            symbols_to_subscribe.append(f"{clean_sym}.NS")
            symbols_to_subscribe.append(f"{clean_sym}-EQ")
            
            # Check live WebSocket tick store
            live_tick = None
            if tick_store:
                live_tick = (
                    tick_store.get(clean_sym)
                    or tick_store.get(f"{clean_sym}.NS")
                    or tick_store.get(f"{clean_sym}-EQ")
                    or tick_store.get(f"{clean_sym}-NSE")
                    or tick_store.get(sym)
                )
                
            if live_tick:
                ltp = live_tick.get("last_price") or live_tick.get("ltp") or live_tick.get("c") or live_tick.get("price")
                if ltp and float(ltp) > 0:
                    live_cmp = round(float(ltp), 2)
                    item["current_price"] = live_cmp
                    live_change_pct = live_tick.get("change_pct")
                    if live_change_pct is not None:
                        item["day_change_pct"] = round(float(live_change_pct), 2)

                    issue_px = item.get("issue_price", 0.0)
                    list_px = item.get("listing_price", 0.0)
                    ath = item.get("ath", live_cmp)
                    
                    if issue_px and issue_px > 0:
                        item["current_gain_from_issue_pct"] = round(((live_cmp - issue_px) / issue_px) * 100, 2)
                    if list_px and list_px > 0:
                        item["current_gain_from_listing_pct"] = round(((live_cmp - list_px) / list_px) * 100, 2)
                    if ath and ath > 0:
                        if live_cmp > ath:
                            item["ath"] = live_cmp
                            item["drawdown_from_ath_pct"] = 0.0
                        else:
                            item["drawdown_from_ath_pct"] = round(((live_cmp - ath) / ath) * 100, 2)
                            
        # Asynchronously request AngelOne WebSocket subscription for all 12-month IPO tickers
        if symbols_to_subscribe:
            try:
                subscribe_symbols(list(set(symbols_to_subscribe)))
            except Exception:
                pass
    except Exception as e:
        pass
        
    return data

def get_ipo_tracker_dataset(force_refresh: bool = False, sector_filter: str = None, signal_filter: str = None) -> dict:
    """
    Main Entrypoint: Returns complete 12-Month IPO dataset with technical metrics,
    opportunity scores, and summary KPI analytics. Parallelized for speed.
    Uses disk JSON caching by default unless force_refresh=True.
    Dynamically overlays live streaming WebSocket ticks on returned data.
    """
    if force_refresh and os.path.exists(IPO_PROCESSED_CACHE_PATH):
        try:
            os.remove(IPO_PROCESSED_CACHE_PATH)
            print("[IPO Engine] Flushed old JSON cache file on force_refresh.")
        except Exception:
            pass

    if not force_refresh and not sector_filter and not signal_filter:
        cached = load_processed_ipo_cache()
        if cached:
            return apply_live_ticks_to_ipo_dataset(cached)

    master_list = sync_ipo_master_db(force_refresh=force_refresh)
    
    dataset = []
    total_listing_gain = 0.0
    active_buy_count = 0
    sector_counts = {}
    
    def process_single_ipo(ipo):
        symbol = ipo.get("symbol", "UNKNOWN")
        company = ipo.get("company_name", symbol)
        listing_date = ipo.get("listing_date", "")
        issue_px = ipo.get("issue_price", 0.0)
        list_px = ipo.get("listing_price", 0.0)
        sector = resolve_ipo_sector(symbol, company, ipo.get("sector"))
        
        today_str = datetime.now().strftime("%Y-%m-%d")
        if listing_date and listing_date > today_str:
            return None
            
        cur_px = ipo.get("current_price", 0.0)
        tech = get_ipo_technical_analysis(symbol, listing_date, issue_px, list_px, cur_px, company_name=company)
        if not tech.get("is_valid_listed", False):
            return None
            
        opportunity = evaluate_ipo_buy_opportunity(ipo, tech)
        
        item = {
            "symbol": tech.get("resolved_symbol", symbol),
            "company_name": company,
            "sector": sector,
            "issue_price": issue_px,
            "listing_price": list_px,
            "current_price": tech["current_price"],
            "day_change_pct": tech.get("day_change_pct", 0.0),
            "listing_date": listing_date,
            "open_date": ipo.get("open_date", ""),
            "close_date": ipo.get("close_date", ""),
            "issue_size_cr": ipo.get("issue_size_cr", 0.0),
            "subscription_times": ipo.get("subscription_times", 0.0),
            "anchor_lockin_30d": ipo.get("anchor_lockin_30d", ""),
            "anchor_lockin_90d": ipo.get("anchor_lockin_90d", ""),
            "listing_gain_pct": tech["listing_gain_pct"],
            "current_gain_from_issue_pct": tech["current_gain_from_issue_pct"],
            "current_gain_from_listing_pct": tech["current_gain_from_listing_pct"],
            "ath": tech["ath"],
            "atl": tech["atl"],
            "drawdown_from_ath_pct": tech["drawdown_from_ath_pct"],
            "has_historical_candles": tech["has_historical_candles"],
            "days_since_listing": tech["days_since_listing"],
            "ma_20": tech["ma_20"],
            "ma_50": tech["ma_50"],
            "rsi_14": tech["rsi_14"],
            "sparkline_prices": tech["sparkline_prices"],
            "opportunity_score": opportunity["opportunity_score"],
            "signal_badge": opportunity["signal_badge"],
            "badge_color": opportunity["badge_color"],
            "setup_type": opportunity["setup_type"],
            "key_reasons": opportunity["key_reasons"]
        }
        return item

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(process_single_ipo, ipo) for ipo in master_list]
        for future in as_completed(futures):
            try:
                res = future.result()
                if res:
                    if res["opportunity_score"] >= 80:
                        active_buy_count += 1
                    total_listing_gain += res["listing_gain_pct"]
                    sector_counts[res["sector"]] = sector_counts.get(res["sector"], 0) + 1
                    
                    # Apply filters if specified
                    if sector_filter and sector_filter.lower() not in res["sector"].lower():
                        continue
                    if signal_filter:
                        sf = signal_filter.lower()
                        if sf == "buy" and res["opportunity_score"] < 80:
                            continue
                        elif sf == "watchlist" and not (60 <= res["opportunity_score"] < 80):
                            continue
                        elif sf == "overextended" and not (40 <= res["opportunity_score"] < 60):
                            continue
                            
                    dataset.append(res)
            except Exception as e:
                print(f"[IPO Engine] Error processing item: {e}")
        
    # Fetch active upcoming & pipeline IPOs
    upcoming_pipeline = scrape_upcoming_pipeline()
    
    # Deduplicate entries by symbol and company name
    dataset = deduplicate_ipo_dataset(dataset)
    
    # Sort dataset by listing_date descending or opportunity_score descending
    dataset.sort(key=lambda x: (x.get("listing_date") or "", x["opportunity_score"]), reverse=True)
    
    # Clean sector selection logic
    def is_generic_sector(s):
        if not s or len(s) > 35: return True
        sl = s.lower()
        for bad in ["recently listed", "mainboard equity", "mainboard", "listed", "national stock exchange"]:
            if bad in sl:
                return True
        return False

    # Calculate true outperforming sector by average current return (% from issue price)
    sector_gains = {}
    for i in dataset:
        sec = i.get("sector", "")
        if sec and not is_generic_sector(sec):
            gain = i.get("current_gain_from_issue_pct", 0.0)
            if sec not in sector_gains:
                sector_gains[sec] = []
            sector_gains[sec].append(gain)
            
    top_sector = "Solar & Renewable Tech"
    top_sector_avg = 0.0
    if sector_gains:
        ranked = sorted(
            [(sec, round(sum(gains) / len(gains), 1), len(gains)) for sec, gains in sector_gains.items()],
            key=lambda x: (x[1], x[2]),
            reverse=True
        )
        if ranked:
            top_sector = ranked[0][0]
            top_sector_avg = ranked[0][1]

    avg_list_gain = round(total_listing_gain / len(dataset), 1) if dataset else 0.0

    gainers = len([i for i in dataset if i.get("current_gain_from_issue_pct", 0) > 0])
    losers = len([i for i in dataset if i.get("current_gain_from_issue_pct", 0) < 0])
    avg_current_gain = round(sum(i.get("current_gain_from_issue_pct", 0) for i in dataset) / len(dataset), 1) if dataset else 0.0
    watchlist_count = len([i for i in dataset if 60 <= i.get("opportunity_score", 0) < 80 and i.get("days_since_listing", 999) >= 30])
    discovery_count = len([i for i in dataset if i.get("days_since_listing", 999) < 30])
    below_issue_count = losers
    near_ath_count = len([i for i in dataset if i.get("has_historical_candles") and i.get("drawdown_from_ath_pct") is not None and abs(i.get("drawdown_from_ath_pct")) <= 5.0 and i.get("days_since_listing", 0) >= 15])
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    raw_res = {
        "summary": {
            "total_ipos_12m": len(dataset),
            "gainers_count": gainers,
            "losers_count": losers,
            "total_upcoming_pipeline": len(upcoming_pipeline),
            "avg_listing_gain_pct": avg_list_gain,
            "avg_current_gain_pct": avg_current_gain,
            "active_buy_opportunities": active_buy_count,
            "watchlist_count": watchlist_count,
            "discovery_count": discovery_count,
            "below_issue_count": below_issue_count,
            "near_ath_count": near_ath_count,
            "top_sector": top_sector,
            "top_sector_avg_gain": top_sector_avg,
            "last_updated": now_str,
            "last_cron_run_at": now_str
        },
        "ipos": dataset,
        "upcoming_pipeline": upcoming_pipeline
    }
    
    cleaned = clean_nans(raw_res)
    if not sector_filter and not signal_filter:
        save_processed_ipo_cache(cleaned)
    return apply_live_ticks_to_ipo_dataset(cleaned)

def generate_ipo_whatsapp_summary(dataset: list, upcoming_pipeline: list) -> str:
    """
    Generates a publication-grade WhatsApp alert payload summarizing top 2-3 listed IPO opportunities
    and top 2-3 high-demand upcoming/unlisted pipeline IPOs.
    """
    today_str = datetime.now().strftime("%d %b %Y")
    
    # Filter & rank top listed IPO opportunities
    listed_candidates = [
        item for item in dataset 
        if item.get("opportunity_score", 0) >= 60 and item.get("current_gain_from_issue_pct") is not None
    ]
    listed_candidates.sort(key=lambda x: (x.get("opportunity_score", 0), x.get("current_gain_from_issue_pct", 0)), reverse=True)
    top_listed = listed_candidates[:3]

    # Filter & rank top upcoming / pipeline IPOs
    def pipeline_score(item):
        gmp_pct = float(item.get("gmp_pct", 0.0) or 0.0)
        sub_times = float(item.get("subscription_times", 0.0) or 0.0)
        status = (item.get("status") or "").lower()
        # Active bidding or allotment pending gets priority
        status_boost = 1.2 if any(s in status for s in ["ongoing", "closed", "bidding open", "allotment"]) else 1.0
        return ((gmp_pct * 2.0) + (sub_times * 0.8)) * status_boost

    pipeline_candidates = sorted(upcoming_pipeline or [], key=pipeline_score, reverse=True)
    top_pipeline = pipeline_candidates[:3]

    lines = [
        f"🚀 *DAILY IPO RADAR SUMMARY* ({today_str})",
        "=====================================",
        "",
        "📈 *TOP LISTED IPO OPPORTUNITIES*",
    ]

    if top_listed:
        for idx, item in enumerate(top_listed, 1):
            sym = item.get("symbol", "IPO")
            score = item.get("opportunity_score", 0)
            setup = item.get("setup_type", "Consolidating")
            issue_px = item.get("issue_price", 0)
            cur_px = item.get("current_price", 0)
            gain = item.get("current_gain_from_issue_pct", 0.0)
            gain_str = f"+{gain:.1f}%" if gain >= 0 else f"{gain:.1f}%"
            reasons = item.get("key_reasons", [])
            lead_reason = reasons[0] if reasons else "Strong relative strength"

            lines.append(f"{idx}. *{sym}* - Score {score}/100 ({setup})")
            lines.append(f"   • Issue: ₹{issue_px:.0f} | CMP: ₹{cur_px:.1f} ({gain_str})")
            lines.append(f"   • Key Factor: {lead_reason}")
            lines.append("")
    else:
        lines.append("• No high-conviction breakout setups detected today.")
        lines.append("")

    lines.append("🔥 *HIGH DEMAND UNLISTED / PIPELINE IPOs*")
    if top_pipeline:
        for idx, item in enumerate(top_pipeline, 1):
            company = item.get("company_name", "Upcoming IPO")
            low_p = item.get("min_price", 0)
            high_p = item.get("max_price", 0)
            price_band = item.get("price_band_str") or (f"₹{int(low_p)} - ₹{int(high_p)}" if low_p > 0 else "TBD")
            
            gmp_pct = float(item.get("gmp_pct", 0.0) or 0.0)
            gmp_rs = float(item.get("gmp_rs", 0.0) or 0.0)
            if gmp_pct > 0 or gmp_rs > 0:
                gmp_str = f"+{gmp_pct:.1f}% (+₹{int(gmp_rs)})"
            else:
                gmp_str = "N/A"

            status = item.get("status_badge") or item.get("status") or "Upcoming"
            sub_times = item.get("subscription_times")
            sub_str = f" | Sub: {sub_times:.2f}x" if sub_times and float(sub_times) > 0 else ""

            lines.append(f"{idx}. *{company}* ({status})")
            lines.append(f"   • Price Band: {price_band} | Est. GMP: {gmp_str}{sub_str}")
            lines.append("")
    else:
        lines.append("• No active pipeline IPOs matching criteria.")
        lines.append("")

    lines.append("=====================================")
    lines.append("🔗 *APEX AI Workstation Client Portal*")

    return "\n".join(lines)

async def dispatch_ipo_whatsapp_summary(dataset: list, upcoming_pipeline: list) -> dict:
    """Dispatches WhatsApp alert using Meta WhatsApp Cloud API."""
    try:
        from backend.daily_wrapup import send_whatsapp_wrapup
        msg = generate_ipo_whatsapp_summary(dataset, upcoming_pipeline)
        res = await send_whatsapp_wrapup(msg)
        return res
    except Exception as e:
        print(f"[IPO Engine] Failed to dispatch WhatsApp summary: {e}")
        return {"status": "error", "message": str(e)}

def clean_nans(obj):
    import math
    if isinstance(obj, dict):
        return {k: clean_nans(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nans(v) for v in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    elif type(obj).__module__ == 'numpy' and np.isnan(obj):
        return 0.0
    return obj


IPO_AI_INSIGHTS_DB_PATH = os.path.join(DB_DIR, "ipo_ai_insights.db")

def init_ipo_ai_insights_db():
    try:
        conn = sqlite3.connect(IPO_AI_INSIGHTS_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ipo_ai_insights (
                symbol TEXT PRIMARY KEY,
                company_name TEXT,
                insight_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[IPO Engine] Error initializing AI insights DB: {e}")

def get_cached_ipo_ai_insight(symbol: str) -> dict:
    init_ipo_ai_insights_db()
    try:
        conn = sqlite3.connect(IPO_AI_INSIGHTS_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT insight_json FROM ipo_ai_insights WHERE UPPER(symbol) = UPPER(?)", (symbol,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as e:
        print(f"[IPO Engine] Error reading AI insight cache for {symbol}: {e}")
    return None

def save_ipo_ai_insight(symbol: str, company_name: str, insight_dict: dict):
    init_ipo_ai_insights_db()
    try:
        conn = sqlite3.connect(IPO_AI_INSIGHTS_DB_PATH)
        cursor = conn.cursor()
        insight_json = json.dumps(insight_dict)
        cursor.execute("""
            INSERT OR REPLACE INTO ipo_ai_insights (symbol, company_name, insight_json, created_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """, (symbol.upper(), company_name, insight_json))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[IPO Engine] Error saving AI insight cache for {symbol}: {e}")

def generate_ipo_ai_prospectus_insight(symbol_or_name: str) -> dict:
    """
    Generates or retrieves cached AI Prospectus Summary & Risk Breakdown for an upcoming/pipeline IPO.
    """
    symbol_clean = symbol_or_name.strip().upper()
    cached = get_cached_ipo_ai_insight(symbol_clean)
    if cached:
        print(f"[IPO AI Insight] Cache hit for {symbol_clean}")
        return cached

    # Find item in pipeline dataset
    pipeline = scrape_upcoming_pipeline()
    target_item = None
    for item in pipeline:
        item_sym = (item.get("symbol") or "").upper()
        item_name = (item.get("company_name") or "").upper()
        if symbol_clean in item_sym or symbol_clean in item_name or item_sym in symbol_clean or item_name in symbol_clean:
            target_item = item
            break

    if not target_item:
        target_item = {
            "company_name": symbol_or_name,
            "symbol": symbol_clean,
            "sector": "Mainboard Industrial / Tech",
            "price_band_str": "TBD",
            "issue_size_cr": 0,
            "status": "Upcoming",
            "gmp_rs": 0,
            "gmp_pct": 0.0,
            "subscription_times": 0.0
        }

    company = target_item.get("company_name", symbol_or_name)
    sector = target_item.get("sector", "General Enterprise")
    price_band = target_item.get("price_band_str", "TBD")
    issue_size = target_item.get("issue_size_cr") or target_item.get("issue_size") or "TBD"
    gmp_rs = target_item.get("gmp_rs", 0)
    gmp_pct = target_item.get("gmp_pct", 0)
    sub = target_item.get("subscription_times", 0)
    status = target_item.get("status", "Upcoming")

    user_prompt = f"""
    Please generate an institutional prospectus summary and risk breakdown for the following IPO:

    Company Name: {company}
    Ticker/Symbol: {symbol_clean}
    Sector/Industry: {sector}
    Price Band: {price_band}
    Issue Size: {issue_size}
    Current GMP: ₹{gmp_rs} ({gmp_pct:.1f}%)
    Subscription Demand: {sub}x
    Current Status: {status}
    """

    system_prompt = """
    You are a senior SEBI-registered Lead Manager and Institutional IPO Analyst.
    Analyze the provided IPO metadata and generate an executive prospectus analysis adhering strictly to JSON format.
    Return ONLY a valid JSON object matching this exact structure:

    {
      "symbol": "SYMBOL",
      "company_name": "Company Name",
      "business_summary": "2-sentence executive summary of company's core business model and products.",
      "use_of_proceeds": {
        "fresh_issue_ratio": "70% Fresh Issue / 30% OFS",
        "primary_allocation": "Expansion of manufacturing facility and working capital requirements"
      },
      "peer_valuation": {
        "issue_pe": "24.5x",
        "peer_avg_pe": "38.2x",
        "verdict": "Attractive valuation relative to listed industry peers."
      },
      "critical_risk_factors": [
        "Customer concentration: Top 5 clients account for over 50% of revenue.",
        "Raw material volatility: Sensitive to key commodity input price swings.",
        "Capacity utilization: Rapid expansion requires sustained order inflows."
      ],
      "conviction_grade": "HIGH_CONVICTION",
      "key_takeaway": "High-growth enterprise play with strong market positioning."
    }
    """

    try:
        from backend.llm_config import call_llm, TASK_FAST
        response = call_llm(
            task_type=TASK_FAST,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=1500
        )

        clean_json_str = response.strip()
        if clean_json_str.startswith("```json"):
            clean_json_str = clean_json_str.split("```json")[1].split("```")[0].strip()
        elif clean_json_str.startswith("```"):
            clean_json_str = clean_json_str.split("```")[1].split("```")[0].strip()

        data = json.loads(clean_json_str)
        data["symbol"] = symbol_clean
        data["company_name"] = company
        save_ipo_ai_insight(symbol_clean, company, data)
        return data
    except Exception as e:
        print(f"[IPO Engine] Failed to generate AI insight for {symbol_clean}: {e}")
        fallback_data = {
            "symbol": symbol_clean,
            "company_name": company,
            "business_summary": f"{company} is an upcoming IPO in the {sector} sector.",
            "use_of_proceeds": {
                "fresh_issue_ratio": "Fresh Issue & OFS mix",
                "primary_allocation": "Capital expansion, debt reduction, and general corporate purposes."
            },
            "peer_valuation": {
                "issue_pe": "N/A",
                "peer_avg_pe": "N/A",
                "verdict": "Valuation details pending final price band confirmation."
            },
            "critical_risk_factors": [
                "Market & Macroeconomic risks associated with sector cyclicality.",
                "Execution risk on proposed capital deployment timelines.",
                "Regulatory compliance requirements under SEBI guidelines."
            ],
            "conviction_grade": "MODERATE_CONVICTION",
            "key_takeaway": "Pipeline tracking active. Monitor GMP and subscription trends near issue closing date."
        }
        return fallback_data


