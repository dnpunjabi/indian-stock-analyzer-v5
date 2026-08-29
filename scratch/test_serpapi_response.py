import os
import sys
import json
import urllib.parse
import urllib.request

# Ensure UTF-8 output encoding for Windows terminal
sys.stdout.reconfigure(encoding='utf-8')

def test_serpapi(symbol="POLYCAB", api_key=""):
    """
    Test script to query SerpApi for Google AI Overview (SGE) data
    and inspect the response JSON structure for UI mapping.
    """
    print(f"=== Testing SerpApi Google AI Overview for {symbol} ===")
    
    # 1. Resolve SerpApi key from env or DB
    if not api_key:
        api_key = os.environ.get("SERPAPI_API_KEY", "")
        
    if not api_key:
        try:
            import sqlite3
            sys.path.insert(0, os.getcwd())
            from backend.main import get_db, decode_key
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM alert_settings WHERE key = 'serpapi_api_key'")
                row = cursor.fetchone()
                if row:
                    decoded = decode_key(row["value"])
                    if decoded.startswith("["):
                        api_key = json.loads(decoded)[0]
                    else:
                        api_key = decoded.split(",")[0].strip()
        except Exception as e:
            pass

    query = f"What is the latest market news, financial performance, and catalysts for {symbol} stock in India?"
    print(f"Query: '{query}'")
    print(f"SerpApi Key Configured: {'YES (' + api_key[:6] + '...)' if api_key else 'NO (Key Required)'}\n")

    if not api_key:
        print("----------------------------------------------------------------------")
        print("NO SERPAPI KEY DETECTED YET IN DB OR ENV.")
        print("Here is the EXPECTED SerpApi SGE AI Overview JSON schema & mapping:")
        print("----------------------------------------------------------------------")
        sample_expected_response = {
            "ai_overview": {
                "text": f"{symbol} stock trades near ₹9,040–₹9,140 range, driven by record Q1 FY27 results, robust infrastructure demand, and profit-booking pressures.",
                "sections": [
                    {
                        "title": "Market News and Stock Movement",
                        "bullet_points": [
                            "Recent Trading: Share price trades around ₹9,040–₹9,140 range (hovering near 52-week high ₹10,126).",
                            "Post-Earnings Reaction: Shares experienced a 3% to 4% profit-booking pullback post Q1 results. Major brokerages Jefferies and HSBC maintained 'Buy'."
                        ],
                        "sources": ["The Economic Times", "LevelBlue"]
                    },
                    {
                        "title": "Financial Performance (Q1 FY27)",
                        "bullet_points": [
                            "Revenue: Consolidated revenue surged 39.01% YoY to ₹8,209.73 crore.",
                            "Profitability: Net profit (PAT) rose 32-33% YoY to ₹784–₹797 crore.",
                            "Segment Breakdown: Wires & Cables up 38-39% YoY; FMEG recorded 71% YoY growth with 8% EBIT margin.",
                            "Margins: EBITDA stood at ₹1,136–₹1,241 crore (13.8% margin)."
                        ],
                        "sources": ["Investing.com", "Business Today", "CSBA"]
                    },
                    {
                        "title": "Growth Catalysts",
                        "bullet_points": [
                            "Project Spring: 5-year strategic roadmap targeting Wires & Cables growth at 1.5x industry rate with ₹6,000–₹8,000 crore capex.",
                            "Strong Balance Sheet: Debt-free balance sheet with net cash position of ~₹3,990 crore."
                        ],
                        "sources": ["MarketSmith India", "Screener", "Perplexity"]
                    }
                ]
            },
            "organic_results_count": 10
        }
        print(json.dumps(sample_expected_response, indent=2, ensure_ascii=False))
        return sample_expected_response

    # 2. Call SerpApi if key is present
    encoded_query = urllib.parse.quote(query)
    url = f"https://serpapi.com/search.json?engine=google&q={encoded_query}&api_key={api_key}&gl=in&hl=en"
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            
            print("SerpApi HTTP 200 OK Response Received!")
            print(f"Top-level Keys: {list(data.keys())}")
            
            ai_overview = data.get("ai_overview", {})
            print(f"\nHas 'ai_overview' block?: {bool(ai_overview)}")
            if ai_overview:
                print("--- AI OVERVIEW CONTENT ---")
                print("Text:", ai_overview.get("text", "")[:200] + "...")
                print("Bullet Points Count:", len(ai_overview.get("bullet_points", [])))
                print("Sources/References:", [ref.get("title") for ref in ai_overview.get("references", [])[:5]])
            
            organic = data.get("organic_results", [])
            print(f"\nOrganic Results Count: {len(organic)}")
            for item in organic[:3]:
                print(f" - [{item.get('source', 'Web')}] {item.get('title')} ({item.get('link')})")
                
            return data
    except Exception as err:
        print(f"SerpApi Request Failed: {err}")
        return {}

if __name__ == "__main__":
    test_serpapi()
