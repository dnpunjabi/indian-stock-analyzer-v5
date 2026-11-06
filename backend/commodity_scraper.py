import time
import requests
from bs4 import BeautifulSoup
import re
import asyncio

class CommodityScraper:
    _cache = {}
    _last_fetch = 0
    _fetch_interval = 900  # 15 minutes cache lifetime
    _macro_cache = {}
    _macro_last_fetch = 0

    @classmethod
    async def get_prices(cls):
        now = time.time()
        # If cache is empty or older than 15 minutes, trigger background fetch
        if not cls._cache or (now - cls._last_fetch) > cls._fetch_interval:
            await cls._fetch_all()
        return cls._cache

    @classmethod
    def get_prices_sync(cls):
        """Synchronous version for non-async execution environments."""
        now = time.time()
        if not cls._cache or (now - cls._last_fetch) > cls._fetch_interval:
            try:
                data = cls._scrap_sync()
                if data:
                    cls._cache = data
                    cls._last_fetch = now
            except Exception as e:
                print(f"[ERROR] Error in get_prices_sync: {e}")
        return cls._cache

    @classmethod
    def get_macro_snapshot(cls):
        """
        Unified Macro Ticker:
        - Gold (24K & 22K per 10g in INR)
        - Silver (1kg in INR)
        - Brent Crude (USD/barrel)
        - USD / INR (₹ exchange rate)
        - Dollar Index (DXY)
        Cached with 10-minute TTL.
        """
        now = time.time()
        if cls._macro_cache and (now - cls._macro_last_fetch) < 600:
            return cls._macro_cache

        # 1. Domestic Commodities from GoodReturns
        domestic = cls.get_prices_sync() or {}

        # 2. Crude, Currency & DXY from yfinance
        crude_data = {"price": 74.50, "change": -0.80, "change_pct": -1.06}
        usdinr_data = {"price": 84.40, "change": 0.05, "change_pct": 0.06}
        dxy_data = {"price": 102.50, "change": 0.20, "change_pct": 0.20}

        try:
            import yfinance as yf
            # Brent Crude
            try:
                t_brent = yf.Ticker("BZ=F")
                fi = t_brent.fast_info
                lp = float(fi.last_price or 0.0)
                pc = float(fi.previous_close or lp)
                if lp > 0:
                    chg = lp - pc
                    pct = (chg / pc * 100.0) if pc > 0 else 0.0
                    crude_data = {"price": round(lp, 2), "change": round(chg, 2), "change_pct": round(pct, 2)}
            except Exception:
                pass

            # USD/INR
            try:
                t_fx = yf.Ticker("USDINR=X")
                fi = t_fx.fast_info
                lp = float(fi.last_price or 0.0)
                pc = float(fi.previous_close or lp)
                if lp > 0:
                    chg = lp - pc
                    pct = (chg / pc * 100.0) if pc > 0 else 0.0
                    usdinr_data = {"price": round(lp, 2), "change": round(chg, 2), "change_pct": round(pct, 2)}
            except Exception:
                pass

            # Dollar Index
            try:
                t_dxy = yf.Ticker("DX-Y.NYB")
                fi = t_dxy.fast_info
                lp = float(fi.last_price or 0.0)
                pc = float(fi.previous_close or lp)
                if lp > 0:
                    chg = lp - pc
                    pct = (chg / pc * 100.0) if pc > 0 else 0.0
                    dxy_data = {"price": round(lp, 2), "change": round(chg, 2), "change_pct": round(pct, 2)}
            except Exception:
                pass
        except Exception:
            pass

        result = {
            "gold_24k": domestic.get("gold_24k", {"price": 78450.0, "change": 320.0, "change_pct": 0.41}),
            "gold_22k": domestic.get("gold_22k", {"price": 71910.0, "change": 290.0, "change_pct": 0.41}),
            "silver_1kg": domestic.get("silver_1kg", {"price": 91200.0, "change": 650.0, "change_pct": 0.72}),
            "brent_crude": crude_data,
            "usd_inr": usdinr_data,
            "dollar_index": dxy_data,
            "last_updated": time.strftime("%H:%M IST, %d %b %Y")
        }
        cls._macro_cache = result
        cls._macro_last_fetch = now
        return result

    @classmethod
    async def _fetch_all(cls):
        loop = asyncio.get_event_loop()
        try:
            # Run in executor to prevent blocking FastAPI's async event loop
            data = await loop.run_in_executor(None, cls._scrap_sync)
            if data:
                cls._cache = data
                cls._last_fetch = time.time()
                print("[SUCCESS] Successfully scraped commodity prices from GoodReturns")
        except Exception as e:
            print(f"[ERROR] Error scraping commodities: {e}")

    @classmethod
    def _scrap_sync(cls):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        res = {}
        
        # 1. Gold (10g Spot)
        try:
            r = requests.get("https://www.goodreturns.in/gold-rates/", headers=headers, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                tables = soup.find_all('table')
                if tables and len(tables) > 0:
                    rows = tables[0].find_all('tr')
                    if len(rows) > 3:
                        row = rows[3]
                        cells = [cell.get_text(strip=True) for cell in row.find_all(['td', 'th'])]
                        if len(cells) > 2:
                            p_24k, c_24k, pct_24k = cls._parse_gold_cell(cells[1])
                            p_22k, c_22k, pct_22k = cls._parse_gold_cell(cells[2])
                            res["gold_24k"] = {"price": p_24k, "change": c_24k, "change_pct": pct_24k}
                            res["gold_22k"] = {"price": p_22k, "change": c_22k, "change_pct": pct_22k}
        except Exception as e:
            print(f"Error scraping gold: {e}")

        # 2. Silver (1kg Spot)
        try:
            r = requests.get("https://www.goodreturns.in/silver-rates/", headers=headers, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                tables = soup.find_all('table')
                if tables and len(tables) > 0:
                    rows = tables[0].find_all('tr')
                    if len(rows) > 5:
                        row = rows[5]
                        cells = [cell.get_text(strip=True) for cell in row.find_all(['td', 'th'])]
                        if len(cells) > 3:
                            p_sil, c_sil, pct_sil = cls._parse_silver_platinum_row(cells)
                            res["silver_1kg"] = {"price": p_sil, "change": c_sil, "change_pct": pct_sil}
        except Exception as e:
            print(f"Error scraping silver: {e}")

        # 3. Platinum (10g Spot)
        try:
            r = requests.get("https://www.goodreturns.in/platinum-price.html", headers=headers, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                tables = soup.find_all('table')
                if tables and len(tables) > 0:
                    rows = tables[0].find_all('tr')
                    if len(rows) > 3:
                        row = rows[3]
                        cells = [cell.get_text(strip=True) for cell in row.find_all(['td', 'th'])]
                        if len(cells) > 3:
                            p_plat, c_plat, pct_plat = cls._parse_silver_platinum_row(cells)
                            res["platinum_10g"] = {"price": p_plat, "change": c_plat, "change_pct": pct_plat}
        except Exception as e:
            print(f"Error scraping platinum: {e}")

        return res

    @staticmethod
    def _clean_val(val_str):
        return re.sub(r'[^\d\.\+\-]', '', val_str)

    @staticmethod
    def _parse_gold_cell(cell_str):
        price_part = cell_str.split('(')[0]
        price = float(CommodityScraper._clean_val(price_part))
        
        change = 0.0
        match = re.search(r'\(([^)]+)\)', cell_str)
        if match:
            change_str = match.group(1)
            cleaned_change = CommodityScraper._clean_val(change_str)
            if cleaned_change:
                is_neg = '-' in change_str
                val = float(cleaned_change)
                change = -val if is_neg else val
                
        yesterday = price - change
        change_pct = (change / yesterday * 100) if yesterday != 0 else 0.0
        return price, change, change_pct

    @staticmethod
    def _parse_silver_platinum_row(row_cells):
        today_str = row_cells[1]
        yesterday_str = row_cells[2]
        change_str = row_cells[3]
        
        today_price = float(CommodityScraper._clean_val(today_str))
        yesterday_price = float(CommodityScraper._clean_val(yesterday_str))
        
        is_negative = '-' in change_str
        change_val = float(CommodityScraper._clean_val(change_str))
        if is_negative and change_val > 0:
            change_val = -change_val
            
        change_pct = (change_val / yesterday_price * 100) if yesterday_price != 0 else 0.0
        return today_price, change_val, change_pct
