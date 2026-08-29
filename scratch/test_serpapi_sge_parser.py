import os
import requests
import urllib.parse
import json
from dotenv import load_dotenv

load_dotenv()

def fetch_real_google_ai_overview(symbol: str, company_name: str = ""):
    clean_sym = symbol.replace('.NS', '').replace('.BO', '').strip().upper()
    comp_name = company_name if company_name else clean_sym
    
    # 1. Collect all SerpApi keys
    serpapi_keys = [v.strip() for k, v in os.environ.items() if k.startswith("SERPAPI") and v.strip()]
    if not serpapi_keys:
        return None, "No SerpApi keys configured"
        
    query = f"What is the latest market news and financial performance for {comp_name} ({clean_sym}) stock in India?"
    encoded_query = urllib.parse.quote(query)
    
    for key in serpapi_keys:
        try:
            # Step A: Query engine=google to get SGE page_token or direct ai_overview
            url1 = f"https://serpapi.com/search.json?engine=google&q={encoded_query}&api_key={key}"
            r1 = requests.get(url1, timeout=15)
            if r1.status_code != 200:
                continue
            data1 = r1.json()
            
            ai_ov = data1.get("ai_overview", {})
            page_token = ai_ov.get("page_token")
            
            blocks = []
            references = []
            
            # Step B: If page_token present, resolve via engine=google_ai_overview
            if page_token:
                url2 = f"https://serpapi.com/search.json?engine=google_ai_overview&page_token={page_token}&api_key={key}"
                r2 = requests.get(url2, timeout=15)
                if r2.status_code == 200:
                    data2 = r2.json()
                    res_ov = data2.get("ai_overview", {})
                    blocks = res_ov.get("text_blocks", [])
                    references = res_ov.get("references", [])
            elif "text_blocks" in ai_ov:
                blocks = ai_ov.get("text_blocks", [])
                references = ai_ov.get("references", [])
                
            if not blocks:
                # Fallback to organic snippets if SGE is quiet
                organic = data1.get("organic_results", [])
                if organic:
                    sections = [
                        {
                            "title": "Recent Market & Corporate Catalysts",
                            "bullet_points": [item.get("snippet", "") for item in organic[:3] if item.get("snippet")],
                            "sources": list(set([item.get("source", "Google Search") for item in organic[:3]]))
                        }
                    ]
                    return {
                        "symbol": clean_sym,
                        "company_name": comp_name,
                        "data_source": "SerpApi Organic Intelligence",
                        "text": f"Latest web intelligence summary for {comp_name} ({clean_sym}).",
                        "sections": sections,
                        "references": [item.get("link") for item in organic[:3]]
                    }, "SerpApi Organic"
                continue

            # Step C: Parse text_blocks into structured sections
            intro_text = ""
            sections = []
            current_section = None
            
            # Extract references domain/source count map
            source_counts = {}
            for ref in references:
                src_name = ref.get("source") or ref.get("title") or "Web"
                source_counts[src_name] = source_counts.get(src_name, 0) + 1
            
            top_sources = [f"{k} +{v}" if v > 1 else k for k, v in list(source_counts.items())[:3]]

            for block in blocks:
                b_type = block.get("type")
                snippet = block.get("snippet", "").strip()
                if not snippet:
                    continue
                    
                if b_type == "paragraph" and not intro_text:
                    intro_text = snippet
                elif b_type == "heading":
                    if current_section and current_section["bullet_points"]:
                        sections.append(current_section)
                    current_section = {
                        "title": snippet,
                        "bullet_points": [],
                        "sources": top_sources
                    }
                elif b_type in ["paragraph", "list_item", "bullet"]:
                    if current_section:
                        current_section["bullet_points"].append(snippet)
                    elif not intro_text:
                        intro_text = snippet
                    else:
                        if not sections:
                            current_section = {
                                "title": "Market Overview & Key Highlights",
                                "bullet_points": [snippet],
                                "sources": top_sources
                            }
                        else:
                            sections[-1]["bullet_points"].append(snippet)
                            
            if current_section and current_section["bullet_points"]:
                sections.append(current_section)
                
            if not intro_text:
                intro_text = f"Google SGE AI Overview for {comp_name} ({clean_sym})."

            return {
                "symbol": clean_sym,
                "company_name": comp_name,
                "data_source": "⚡ SerpApi Google SGE (AI Overview)",
                "text": intro_text,
                "sections": sections,
                "references": [ref.get("link") for ref in references[:5] if ref.get("link")]
            }, "SerpApi SGE"

        except Exception as err:
            print(f"Key {key[:8]} failed: {err}")
            continue

    return None, "All SerpApi keys exhausted"

if __name__ == "__main__":
    res, src = fetch_real_google_ai_overview("POLYCAB.NS", "Polycab India Ltd.")
    print("SOURCE:", src)
    print(json.dumps(res, indent=2))
