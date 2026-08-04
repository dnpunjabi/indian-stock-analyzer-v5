import os
import requests
import urllib.parse
from bs4 import BeautifulSoup

def fetch_latest_news_for_query(
    query: str, 
    timeframe: str = "7d", 
    use_tavily: bool = False, 
    use_serpapi: bool = False,
    use_brave: bool = False,
    serpapi_api_key: str = "",
    tavily_api_key: str = ""
) -> tuple[list[str], str]:
    """
    Fetch news snippets from multiple search endpoints in priority order,
    complying with user authorization toggles.
    
    Returns a tuple of (snippets_list, provider_name).
    """
    timeframe_map_qdr = {
        "1d": "d",
        "5d": "d5",
        "7d": "w",
        "14d": "w2",
        "30d": "m",
        "1m": "m",
        "3m": "m3",
        "6m": "m6",
        "1y": "y",
        "5y": "y5",
        "ytd": "ytd"
    }
    qdr = timeframe_map_qdr.get(timeframe.lower().strip(), "w")
    
    # Get all configured API keys
    serpapi_keys = []
    if isinstance(serpapi_api_key, list):
        serpapi_keys = serpapi_api_key
    elif isinstance(serpapi_api_key, str) and serpapi_api_key:
        serpapi_keys = [k.strip() for k in serpapi_api_key.split(",") if k and k.strip()]
    else:
        for k, v in os.environ.items():
            if k.startswith("SERPAPI_API_KEY"):
                val = v.strip()
                if val and val not in serpapi_keys:
                    serpapi_keys.append(val)
            
    tavily_keys = []
    if isinstance(tavily_api_key, list):
        tavily_keys = tavily_api_key
    elif isinstance(tavily_api_key, str) and tavily_api_key:
        tavily_keys = [k.strip() for k in tavily_api_key.split(",") if k and k.strip()]
    else:
        for k, v in os.environ.items():
            if k.startswith("TAVILY_API_KEY"):
                val = v.strip()
                if val and val not in tavily_keys:
                    tavily_keys.append(val)
            
    brave_key = os.environ.get("BRAVE_API_KEY", "")

    # 1. TIER 1: SerpApi (If toggled ON and Key configured)
    if use_serpapi and serpapi_keys:
        for sk in serpapi_keys:
            if not sk:
                continue
            try:
                masked_sk = f"{sk[:6]}...{sk[-4:]}" if len(sk) > 10 else sk
                print(f"[Catalyst Scraper] Querying SerpApi with key {masked_sk} for: {query}")
                encoded_query = urllib.parse.quote(query)
                tbs = f"qdr:{qdr}"
                url = f"https://serpapi.com/search.json?engine=google&q={encoded_query}&api_key={sk}&tbs={tbs}"
                r = requests.get(url, timeout=20.0)
                if r.status_code == 200:
                    data = r.json()
                    ai_overview = data.get("ai_overview", {})
                    if ai_overview:
                        text = ai_overview.get("text", "")
                        if text:
                            print("[Catalyst Scraper] SerpApi SGE successfully returned AI Overview.")
                            return [f"Google AI Overview: {text}"], "SerpApi AI Overview"
                    
                    organic_results = data.get("organic_results", [])
                    snippets = []
                    for item in organic_results[:6]:
                        title = item.get("title", "")
                        snippet = item.get("snippet", "")
                        if title or snippet:
                            snippets.append(f"Title: {title}\nSnippet: {snippet}")
                    if snippets:
                        print(f"[Catalyst Scraper] SerpApi successfully returned {len(snippets)} organic snippets.")
                        return snippets, "SerpApi Search"
                else:
                    print(f"[Catalyst Scraper] SerpApi key {masked_sk} returned status {r.status_code}. Rotating key.")
                    continue
            except Exception as e:
                print(f"[Catalyst Scraper] SerpApi query failed for key {masked_sk}: {e}. Rotating key.")
                continue

    # 2. TIER 2: Brave Search API (If toggled ON and Key configured)
    if use_brave and brave_key:
        try:
            print(f"[Catalyst Scraper] Querying Brave Search for: {query}")
            headers = {
                "Accept": "application/json",
                "X-Subscription-Token": brave_key
            }
            # Map timeframe to freshness codes
            freshness_map = {
                "1d": "pd",
                "5d": "pw",
                "7d": "pw",
                "14d": "pw",
                "30d": "pm",
                "1m": "pm"
            }
            freshness = freshness_map.get(timeframe.lower().strip(), "pw")
            params = {
                "q": query,
                "count": 8,
                "freshness": freshness,
                "extra_snippets": 1,
                "summary": 1
            }
            r = requests.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params=params, timeout=8.0)
            if r.status_code == 200:
                data = r.json()
                snippets = []
                
                # Check for Brave AI Answer/Summarizer
                summarizer = data.get("summarizer", {})
                if summarizer:
                    answer = summarizer.get("answer") or summarizer.get("text") or ""
                    if answer:
                        snippets.append(f"Brave AI Summary: {answer}")
                
                # Parse organic results
                web = data.get("web", {})
                results = web.get("results", [])
                for item in results:
                    title = item.get("title", "")
                    description = item.get("description", "")
                    url = item.get("url", "")
                    extra = " ".join(item.get("extra_snippets", []) or [])
                    full_desc = f"{description} {extra}".strip()
                    if title or full_desc:
                        snippets.append(f"Title: {title}\nSnippet: {full_desc}\nLink: {url}")
                
                if snippets:
                    print(f"[Catalyst Scraper] Brave Search successfully returned {len(snippets)} snippets.")
                    return snippets, "Brave Search"
        except Exception as e:
            print(f"[Catalyst Scraper] Brave Search failed: {e}. Moving to next tier.")

    # 3. TIER 3: Tavily Search API (If toggled ON and Key configured)
    if use_tavily and tavily_keys:
        for tk in tavily_keys:
            if not tk:
                continue
            try:
                masked_tk = f"{tk[:6]}...{tk[-4:]}" if len(tk) > 10 else tk
                print(f"[Catalyst Scraper] Querying Tavily with key {masked_tk} for: {query}")
                payload = {
                    "api_key": tk,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 5
                }
                r = requests.post("https://api.tavily.com/search", json=payload, timeout=6.0)
                if r.status_code == 200:
                    data = r.json()
                    snippets = []
                    for item in data.get("results", []):
                        title = item.get("title", "")
                        content = item.get("content", "")
                        if title or content:
                            snippets.append(f"Title: {title}\nSnippet: {content}")
                    if snippets:
                        print(f"[Catalyst Scraper] Tavily successfully returned {len(snippets)} snippets.")
                        return snippets, "Tavily Search"
                else:
                    print(f"[Catalyst Scraper] Tavily key {masked_tk} returned status {r.status_code}. Rotating key.")
                    continue
            except Exception as e:
                print(f"[Catalyst Scraper] Tavily search failed for key {masked_tk}: {e}. Rotating key.")
                continue

    # 3. TIER 3: Free Google News RSS feed (Fallback)
    try:
        # Translate timeframe to Google News 'when' parameter
        rss_query = f"{query} when:{timeframe}"
        encoded_query = urllib.parse.quote(rss_query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
        print(f"[Catalyst Scraper] Querying free Google News RSS for: {rss_query}")
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }
        r = requests.get(rss_url, headers=headers, timeout=6.0)
        if r.status_code == 200:
            soup = BeautifulSoup(r.content, "html.parser")
            items = soup.find_all("item")
            snippets = []
            for item in items[:8]:
                title = item.find("title").text if item.find("title") else ""
                description = item.find("description").text if item.find("description") else ""
                clean_desc = ""
                if description:
                    clean_desc = BeautifulSoup(description, "html.parser").get_text()
                pub_date = item.find("pubdate").text if item.find("pubdate") else ""
                
                if title:
                    snippets.append(f"Title: {title}\nDate: {pub_date}\nSnippet: {clean_desc}")
            if snippets:
                print(f"[Catalyst Scraper] Google News RSS successfully returned {len(snippets)} snippets.")
                return snippets, "Google News RSS"
    except Exception as e:
        print(f"[Catalyst Scraper] Google News RSS failed: {e}")
        
    return [], "None"


def fetch_serpapi_google_ai_overview(query: str, serpapi_keys: list) -> dict:
    """
    Queries SerpApi with Google AI Overview (SGE) engine and extracts
    structured sections, bullet points, source citation badges, and
    Google AI generated follow-up prompts.
    """
    if not serpapi_keys:
        return {}

    for sk in serpapi_keys:
        if not sk:
            continue
        try:
            masked_sk = f"{sk[:6]}...{sk[-4:]}" if len(sk) > 10 else sk
            print(f"[Catalyst Scraper] Querying SerpApi SGE for Google AI Overview with key {masked_sk}: '{query}'")
            encoded_query = urllib.parse.quote(query)
            url = f"https://serpapi.com/search.json?engine=google&q={encoded_query}&api_key={sk}&gl=in&hl=en"
            r = requests.get(url, timeout=15.0)
            if r.status_code == 200:
                data = r.json()
                ai_overview = data.get("ai_overview", {})
                if ai_overview:
                    text = ai_overview.get("text", "")
                    
                    # 1. Extract sections
                    sections = []
                    raw_sections = ai_overview.get("sections", [])
                    if isinstance(raw_sections, list):
                        for sec in raw_sections:
                            if isinstance(sec, dict):
                                title = sec.get("title", "Market Update")
                                bullets = sec.get("bullet_points", [])
                                if isinstance(bullets, list):
                                    clean_bullets = [str(b.get("text", b)) if isinstance(b, dict) else str(b) for b in bullets]
                                else:
                                    clean_bullets = [str(bullets)] if bullets else []
                                sources = [str(s.get("name", s.get("title", s))) if isinstance(s, dict) else str(s) for s in sec.get("sources", sec.get("references", []))]
                                sections.append({
                                    "title": title,
                                    "bullet_points": clean_bullets,
                                    "sources": sources
                                })
                    
                    # 2. Extract references/citations at top-level
                    top_sources = []
                    for ref in ai_overview.get("references", []):
                        if isinstance(ref, dict):
                            src_name = ref.get("source", ref.get("title", "Web"))
                            if src_name and src_name not in top_sources:
                                top_sources.append(src_name)

                    # 3. Extract Google AI generated follow-up prompts
                    suggested_followups = []
                    for followup in ai_overview.get("suggested_questions", ai_overview.get("follow_ups", [])):
                        if isinstance(followup, dict):
                            txt = followup.get("question", followup.get("text", ""))
                        else:
                            txt = str(followup)
                        if txt:
                            suggested_followups.append(txt)
                            
                    print(f"[Catalyst Scraper] SerpApi SGE successfully returned AI Overview ({len(sections)} sections, {len(suggested_followups)} followups).")
                    return {
                        "text": text,
                        "sections": sections,
                        "sources": top_sources,
                        "suggested_followups": suggested_followups,
                        "data_source": "SerpApi SGE"
                    }
                else:
                    print(f"[Catalyst Scraper] SerpApi returned HTTP 200 but no 'ai_overview' block for this query.")
        except Exception as e:
            print(f"[Catalyst Scraper] SerpApi SGE query failed: {e}")
            continue

    return {}

