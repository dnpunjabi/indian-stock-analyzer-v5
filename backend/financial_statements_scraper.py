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
from bs4 import BeautifulSoup
import re
from backend.financial_utils import make_screener_request

def clean_label(label: str) -> str:
    # Remove trailing plus and whitespace
    label = re.sub(r'\s*\+\s*$', '', label)
    # Replace multiple spaces with single space
    label = re.sub(r'\s+', ' ', label)
    return label.strip()

def clean_value(val_str: str):
    val_str = val_str.strip().replace(",", "")
    if not val_str or val_str == "" or val_str == "--" or val_str == "N/A":
        return None
    try:
        # Check if percentage
        if "%" in val_str:
            val_str = val_str.replace("%", "")
            return float(val_str)
        if "." in val_str:
            return float(val_str)
        return int(val_str)
    except ValueError:
        return val_str

def parse_screener_table(table_el) -> dict:
    if not table_el:
        return {"headers": [], "rows": []}
        
    headers_cells = table_el.find_all("th")
    headers = [th.text.strip() for th in headers_cells]
    
    rows = []
    tbody = table_el.find("tbody")
    tr_elements = tbody.find_all("tr") if tbody else table_el.find_all("tr")[1:]
    
    for tr in tr_elements:
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        label = clean_label(cells[0].text)
        if not label:
            continue
            
        values = [clean_value(c.text) for c in cells[1:]]
        # Skip empty rows (e.g. divider rows)
        if all(v is None for v in values) and len(values) > 0:
            continue
            
        rows.append({
            "label": label,
            "values": values
        })
        
    return {
        "headers": headers,
        "rows": rows
    }

def parse_screener_peers_table(table_el) -> dict:
    if not table_el:
        return {"headers": [], "rows": []}
        
    headers_cells = table_el.find_all("th")
    headers = [clean_label(th.text) for th in headers_cells]
    
    # Clean headers: remove S.No or blank first column
    if len(headers) > 1 and (headers[0] == "" or "s.no" in headers[0].lower()):
        headers = headers[1:]
        
    rows = []
    tbody = table_el.find("tbody")
    tr_elements = tbody.find_all("tr") if tbody else table_el.find_all("tr")[1:]
    
    for tr in tr_elements:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
            
        # Skip header rows nested inside tbody (e.g. rows containing "Name")
        if len(cells) > 1 and "name" in cells[1].text.lower():
            continue
            
        # If cells[0] is just a digit (serial number), then cells[1] is the company name
        c0_text = cells[0].text.strip().rstrip(".")
        if len(cells) > 2 and c0_text.isdigit():
            label = clean_label(cells[1].text)
            values = [clean_value(c.text) for c in cells[2:]]
        else:
            label = clean_label(cells[0].text)
            values = [clean_value(c.text) for c in cells[1:]]
            
        if not label:
            continue
            
        rows.append({
            "label": label,
            "values": values
        })
        
    return {
        "headers": headers,
        "rows": rows
    }


def scrape_financial_statements(symbol: str, view: str = "consolidated", session_cookie: str = None) -> dict:
    """
    Scrapes the Quarterly Results, annual Profit & Loss, and Balance Sheet statements
    from Screener.in with optional session cookie support for customized peer metrics.
    
    If 'view' is 'consolidated', it will target the /consolidated/ path on Screener.
    If it's 'standalone', it will target the default path.
    If the requested view is not available, it fallbacks automatically.
    """
    cookies = {}
    if session_cookie:
        cookie_val = session_cookie
        if "sessionid=" in cookie_val:
            cookie_val = cookie_val.split("sessionid=")[-1].split(";")[0].strip()
        cookies = {"sessionid": cookie_val}
    # 1. Resolve ticker symbol and name using our offline database first
    base_symbol = symbol.split(".")[0].strip().upper()
    company_name = None
    
    try:
        from backend.financial_utils import resolve_company_ticker
        resolution = resolve_company_ticker(symbol)
        if resolution:
            base_symbol = resolution.get("base_symbol") or base_symbol
            company_name = resolution.get("name")
    except Exception as e:
        print(f"Local ticker resolution failed in financial_statements_scraper: {e}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        # 2. Resolve URL path using Screener's API search suggestion
        resolved_path = None
        search_queries = [base_symbol]
        if company_name:
            clean_name = company_name.replace("Limited", "").replace("Ltd.", "").replace("Ltd", "").strip()
            if clean_name and clean_name not in search_queries:
                search_queries.append(clean_name)
                
        for q in search_queries:
            search_url = f"https://www.screener.in/api/company/search/?q={requests.utils.quote(q)}"
            # Propagate connection errors/timeouts up so we proceed directly to yfinance fallback
            search_res = make_screener_request(search_url, headers=headers, cookies=cookies, timeout=3)
            if search_res.status_code == 200:
                results = search_res.json()
                if results and len(results) > 0:
                    for item in results:
                        url_val = item.get("url", "").lower()
                        name_val = item.get("name", "").lower()
                        q_lower = q.lower()
                        if q_lower in url_val or q_lower in name_val:
                            resolved_path = item.get("url")
                            break
                    if not resolved_path:
                        resolved_path = results[0].get("url")
                    if resolved_path:
                        break

        # Remove trailing slash if present to make URL construction clean
        if resolved_path:
            base_path = resolved_path.rstrip("/")
            # If search suggest returned a consolidated path, extract the base slug
            if "/consolidated" in base_path:
                base_path = base_path.replace("/consolidated", "")
        else:
            base_path = f"/company/{base_symbol}"

        # Build URLs
        if view == "consolidated":
            url = f"https://www.screener.in{base_path}/consolidated/"
        else:
            url = f"https://www.screener.in{base_path}/"

        response = make_screener_request(url, headers=headers, cookies=cookies, timeout=4)
        
        # Fallback if consolidated returns 404 or redirects back to the main standalone profile page
        if view == "consolidated" and (response.status_code != 200 or len(response.history) > 0):
            fallback_url = f"https://www.screener.in{base_path}/"
            response = make_screener_request(fallback_url, headers=headers, cookies=cookies, timeout=4)
            
        if response.status_code != 200:
            raise Exception(f"Failed to retrieve Screener financials. Status: {response.status_code}")
            
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Check actual consolidated state of the page we parsed
        p_text = ""
        quarters_sec = soup.find("section", id="quarters")
        if quarters_sec:
            p_el = quarters_sec.find("p")
            if p_el:
                p_text = p_el.text.strip()
        actual_is_consolidated = ("consolidated" in p_text.lower() or "/consolidated" in response.url.lower())
        
        # Parse the warehouse_id (or company_id as fallback) from main page to call peers API
        warehouse_id_match = re.search(r'data-warehouse-id=["\'](\d+)["\']', response.text)
        if not warehouse_id_match:
            warehouse_id_match = re.search(r'data-company-id=["\'](\d+)["\']', response.text)
        warehouse_id = warehouse_id_match.group(1) if warehouse_id_match else None
        
        peers_table_el = None
        if warehouse_id:
            try:
                peers_url = f"https://www.screener.in/api/company/{warehouse_id}/peers/"
                peers_res = make_screener_request(peers_url, headers=headers, cookies=cookies, timeout=3)
                if peers_res.status_code == 200:
                    peers_soup = BeautifulSoup(peers_res.text, "html.parser")
                    peers_table_el = peers_soup.find("table")
            except Exception as e:
                print(f"Error fetching peers API: {e}")
                
        return {
            "symbol": symbol,
            "resolved_symbol": base_symbol,
            "is_consolidated": actual_is_consolidated,
            "source": "screener",
            "is_fallback": False,
            "quarters": parse_screener_table(soup.find("section", id="quarters").find("table") if soup.find("section", id="quarters") else None),
            "profit_loss": parse_screener_table(soup.find("section", id="profit-loss").find("table") if soup.find("section", id="profit-loss") else None),
            "balance_sheet": parse_screener_table(soup.find("section", id="balance-sheet").find("table") if soup.find("section", id="balance-sheet") else None),
            "cash_flow": parse_screener_table(soup.find("section", id="cash-flow").find("table") if soup.find("section", id="cash-flow") else None),
            "ratios": parse_screener_table(soup.find("section", id="ratios").find("table") if soup.find("section", id="ratios") else None),
            "peers": parse_screener_peers_table(peers_table_el)
        }
    except Exception as err:
        print(f"Screener connection/scrape failed: {err}. Proceeding to yfinance fallback.")
        try:
            return scrape_yfinance_financials_fallback(symbol, view)
        except Exception as yf_err:
            print(f"yfinance fallback also failed: {yf_err}")
            return {"error": f"Exception occurred: {str(err)} (yfinance fallback error: {str(yf_err)})"}


def scrape_yfinance_financials_fallback(symbol: str, view: str = "consolidated") -> dict:
    """
    Fallback data resolver using yfinance when Screener.in blocks connections or is down.
    Converts and maps standard Yahoo Finance keys to match Screener's data schema.
    """
    import yfinance as yf
    import pandas as pd
    from datetime import datetime
    
    base_symbol = symbol.split(".")[0].strip().upper()
    yf_ticker = symbol.upper()
    if not (yf_ticker.endswith(".NS") or yf_ticker.endswith(".BO")):
        yf_ticker = f"{base_symbol}.NS"
        
    stock = yf.Ticker(yf_ticker)
    
    def format_yf_date(col):
        try:
            if isinstance(col, str):
                dt = datetime.strptime(col.split(" ")[0], "%Y-%m-%d")
            else:
                dt = col
            return dt.strftime("%b %Y")
        except Exception:
            return str(col)
            
    def build_table(df, mappings):
        if df is None or df.empty:
            return {"headers": [], "rows": []}
            
        headers = [format_yf_date(col) for col in reversed(df.columns)]
        
        rows = []
        for label, keys in mappings.items():
            found_key = None
            for key in keys:
                matches = [idx for idx in df.index if str(idx).strip().lower() == key.strip().lower()]
                if matches:
                    found_key = matches[0]
                    break
                    
            if found_key is not None:
                vals = []
                is_eps = label in ["Basic EPS", "Diluted EPS", "EPS in Rs"]
                for val in df.loc[found_key]:
                    if pd.isna(val) or val is None:
                        vals.append(None)
                    else:
                        try:
                            if is_eps:
                                vals.append(round(float(val), 2))
                            else:
                                vals.append(round(float(val) / 10000000.0, 2))
                        except Exception:
                            vals.append(val)
                rows.append({
                    "label": label,
                    "values": list(reversed(vals))
                })
            else:
                rows.append({
                    "label": label,
                    "values": [None] * len(headers)
                })
                
        return {"headers": headers, "rows": rows}

    def postprocess_income_table(table):
        headers = table["headers"]
        rows = table["rows"]
        
        def get_vals(label):
            for r in rows:
                if r["label"] == label:
                    return r["values"]
            return [None] * len(headers)
            
        sales = get_vals("Sales")
        op_profit = get_vals("Operating Profit")
        pbt = get_vals("Profit before tax")
        tax_prov = get_vals("Tax Provision")
        
        opm_pct = []
        tax_pct = []
        
        for i in range(len(headers)):
            s_val = sales[i]
            op_val = op_profit[i]
            if s_val and op_val and s_val > 0:
                opm_pct.append(round((op_val / s_val) * 100.0, 2))
            else:
                opm_pct.append(None)
                
            pbt_val = pbt[i]
            tax_val = tax_prov[i]
            if pbt_val and tax_val and pbt_val > 0:
                tax_pct.append(round((tax_val / pbt_val) * 100.0, 2))
            else:
                tax_pct.append(None)
                
        op_idx = next((i for i, r in enumerate(rows) if r["label"] == "Operating Profit"), -1)
        if op_idx != -1:
            rows.insert(op_idx + 1, {"label": "OPM %", "values": opm_pct})
            
        pbt_idx = next((i for i, r in enumerate(rows) if r["label"] == "Profit before tax"), -1)
        if pbt_idx != -1:
            rows.insert(pbt_idx + 1, {"label": "Tax %", "values": tax_pct})
            
        for r in rows:
            if r["label"] == "Basic EPS":
                r["label"] = "EPS in Rs"
                
        return {"headers": headers, "rows": [r for r in rows if r["label"] != "Tax Provision"]}

    def postprocess_balance_sheet(table, df):
        headers = table["headers"]
        rows = table["rows"]
        
        def get_vals(label):
            for r in rows:
                if r["label"] == label:
                    return r["values"]
            return [None] * len(headers)
            
        total_assets = get_vals("Total Assets")
        fixed_assets = get_vals("Fixed Assets")
        investments = get_vals("Investments")
        cwip = get_vals("CWIP")
        share_cap = get_vals("Share Capital")
        borrowings = get_vals("Borrowings")
        
        stockholders_equity = [None] * len(headers)
        if df is not None and not df.empty:
            for key in ["Stockholders Equity", "Total Equity Gross Minority Interest"]:
                matches = [idx for idx in df.index if str(idx).strip().lower() == key.strip().lower()]
                if matches:
                    vals = [round(float(v) / 10000000.0, 2) if not pd.isna(v) else 0.0 for v in df.loc[matches[0]]]
                    stockholders_equity = list(reversed(vals))
                    break
                    
        reserves = []
        for i in range(len(headers)):
            se_val = stockholders_equity[i]
            sc_val = share_cap[i] or 0.0
            if se_val is not None:
                reserves.append(round(se_val - sc_val, 2))
            else:
                reserves.append(None)
                
        for r in rows:
            if r["label"] == "Reserves":
                r["values"] = reserves
                
        other_liabs_calc = []
        for i in range(len(headers)):
            ta_val = total_assets[i] or 0.0
            sc_val = share_cap[i] or 0.0
            res_val = reserves[i] or 0.0
            b_val = borrowings[i] or 0.0
            other_liabs_calc.append(round(max(0.0, ta_val - sc_val - res_val - b_val), 2))
            
        for r in rows:
            if r["label"] == "Other Liabilities":
                r["values"] = other_liabs_calc
                
        other_assets_calc = []
        for i in range(len(headers)):
            ta_val = total_assets[i] or 0.0
            fa_val = fixed_assets[i] or 0.0
            inv_val = investments[i] or 0.0
            cwip_val = cwip[i] or 0.0
            other_assets_calc.append(round(max(0.0, ta_val - fa_val - inv_val - cwip_val), 2))
            
        for r in rows:
            if r["label"] == "Other Assets":
                r["values"] = other_assets_calc

    # Income stmt mappings
    income_mappings = {
        "Sales": ["Total Revenue", "Operating Revenue", "Revenue"],
        "Expenses": ["Total Expenses"],
        "Operating Profit": ["Operating Income"],
        "Other Income": ["Other Income Expense", "Net Non Operating Interest Income Expense", "Other Non Operating Income Expenses"],
        "Interest": ["Interest Expense", "Interest Paid Cff"],
        "Depreciation": ["Depreciation And Amortization In Income Statement", "Depreciation Income Statement", "Depreciation"],
        "Profit before tax": ["Pretax Income"],
        "Tax Provision": ["Tax Provision", "Income Tax Expense"],
        "Net Profit": ["Net Income"],
        "Basic EPS": ["Basic EPS", "Diluted EPS"]
    }

    balance_mappings = {
        "Share Capital": ["Common Stock", "Common Stock Equity", "Capital Stock"],
        "Reserves": ["Retained Earnings"],
        "Borrowings": ["Long Term Debt", "Total Debt"],
        "Other Liabilities": ["Total Liabilities Net Minority Interest"],
        "Fixed Assets": ["Net PPE", "Property Plant And Equipment Net"],
        "CWIP": ["Construction In Progress"],
        "Investments": ["Investmentin Financial Assets", "Long Term Equity Investment", "Held To Maturity Securities"],
        "Other Assets": ["Total Assets"],
        "Total Assets": ["Total Assets"]
    }

    cashflow_mappings = {
        "Cash from Operating Activity": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
        "Cash from Investing Activity": ["Investing Cash Flow", "Cash Flow From Continuing Investing Activities"],
        "Cash from Financing Activity": ["Financing Cash Flow", "Cash Flow From Continuing Financing Activities"],
        "Net Cash Flow": ["Changes In Cash", "Net Change In Cash"]
    }

    # Fetch DataFrames from yfinance
    q_inc = stock.quarterly_income_stmt if not stock.quarterly_income_stmt.empty else stock.quarterly_financials
    ann_inc = stock.income_stmt if not stock.income_stmt.empty else stock.financials
    bal = stock.balance_sheet
    cf = stock.cashflow

    quarters_table = build_table(q_inc, income_mappings)
    quarters_table = postprocess_income_table(quarters_table)

    pl_table = build_table(ann_inc, income_mappings)
    pl_table = postprocess_income_table(pl_table)

    bs_table = build_table(bal, balance_mappings)
    postprocess_balance_sheet(bs_table, bal)

    cf_table = build_table(cf, cashflow_mappings)

    # Prepend empty header to all fallback tables to align with the frontend renderer
    if quarters_table and quarters_table.get("headers"):
        quarters_table["headers"] = [""] + quarters_table["headers"]
    if pl_table and pl_table.get("headers"):
        pl_table["headers"] = [""] + pl_table["headers"]
    if bs_table and bs_table.get("headers"):
        bs_table["headers"] = [""] + bs_table["headers"]
    if cf_table and cf_table.get("headers"):
        cf_table["headers"] = [""] + cf_table["headers"]

    return {
        "symbol": symbol,
        "resolved_symbol": base_symbol,
        "is_consolidated": (view == "consolidated"),
        "source": "yfinance_fallback",
        "is_fallback": True,
        "quarters": quarters_table,
        "profit_loss": pl_table,
        "balance_sheet": bs_table,
        "cash_flow": cf_table,
        "peers": {"headers": [], "rows": []}
    }
