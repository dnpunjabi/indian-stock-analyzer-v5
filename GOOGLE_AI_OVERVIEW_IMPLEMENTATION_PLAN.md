# Implementation Plan: Embedded ✨ Google AI Overview Card (SerpApi SGE Powered)

Build an **Embedded ✨ Google AI Overview Card** inside the Stock Analysis Executive Summary view that mirrors the exact Google Search SGE AI Overview layout (executive summary, financial performance breakdown, growth catalysts, inline publisher citation chips, and suggested follow-up chips).

---

## User Review Required

> [!IMPORTANT]
> **SerpApi SGE Integration Strategy**:
> 1. **Natural Question Query**: Formulates natural prompt queries (`What is the latest market news, financial performance, and catalysts for {SYMBOL} stock in India?`) to trigger Google's AI Overview SGE engine via SerpApi.
> 2. **Structured AI Parsing & Citation Badges**: Parses SerpApi `ai_overview` sections and inline publisher citations (e.g. `Angel One +4`, `The Economic Times +2`, `Investing.com +2`, `Screener +2`).
> 3. **Gemini Fallback Synthesizer**: If SerpApi SGE is quiet for a specific ticker or key limits are hit, Gemini 1.5 Flash formats web search results into the exact 3-part Google AI Overview template.
> 4. **100% Google AI Extracted Follow-Up Prompts**: The **Peer Comparison chip** is extracted **directly from Google AI Search SGE response prompts** (e.g. *"A peer comparison with KEI Industries or Havells"*), NOT hardcoded or pulled from local DB tables.
> 5. **100% On-Demand & 15-Min SQLite Cache**: Cached in SQLite table `cached_google_ai_overview` with 15-minute TTL and manual **`🔄 Force Refresh`** button.

> [!NOTE]
> **Dedicated Navigation Subtab Design**:
> - **Dedicated Subtab Button**: Added `<button class="subtab-btn" data-subtab="ai-overview">✨ Google AI Overview</button>` right next to `📋 Executive Summary` in the Equity Research Terminal bar.
> - **Zero Vertical Clutter**: Selecting the subtab opens the **✨ Google AI Overview** view cleanly at full width without competing for vertical scroll real estate with 6 other heavy summary cards.
> - **100% Mobile Responsiveness**: Works seamlessly across desktop and native Android mobile view (Capacitor APK compatible).
> - **Auto 1-Column Collapse**: Uses `@media (max-width: 768px)` rules to collapse side-by-side desktop grids into a sleek 1-column mobile card.
> - **Zero Horizontal Scrolling**: Citation pills (`Angel One +4`, `LevelBlue +2`) use `flex-wrap: wrap` so they wrap into clean multi-line rows on mobile screens.
> - **Capacitor Mobile Sync**: Fully synchronized with the Android native APK bundle via `npx cap sync`.

---

## Key Features & UI Component Design

### 1. Header & Source Badge
- ✨ **Google AI Overview** title with active ticker symbol (e.g. `POLYCAB`).
- Source indicator: `⚡ SERPAPI SGE (GOOGLE AI)` or `💾 CACHED INTEL`.
- Action controls: **`🔄 Force Refresh`** and **`🔊 Read Audio Briefing`** (linked to existing `#speech-controller-panel`).

### 2. Category 1: Executive Overview & Market News
- **Recent Trading**: Stock trading range, distance from 52-week high, with publisher citation chips.
- **Post-Earnings Reaction**: Profit-booking pullback %, brokerage recommendations (Jefferies, HSBC 'Buy' ratings).
- **Sector Dynamics**: Industrial & cable sector performance, macro drivers.

### 3. Category 2: Financial Performance (Q1 Results)
- **Revenue**: Consolidated revenue figures and YoY growth %.
- **Profitability**: Net profit (PAT) figures and YoY growth.
- **Segment Breakdown**: Core Wires & Cables YoY growth vs Fast-Moving Electrical Goods (FMEG) YoY growth.
- **Margins**: EBITDA figures and margin compression/expansion bps.

### 4. Category 3: Strategic Growth Catalysts
- **Strategic Roadmap**: 5-year strategic targets (Project Spring), capex allocation (`₹6,000–₹8,000 crore`).
- **Macro Tailwinds**: Public/private capex, power transmission, electrification.
- **Balance Sheet Strength**: Debt-free status, net cash position (`₹3,990 crore`).

### 5. Google AI Extracted Follow-Up Prompts
- `📊 Analyst Target Prices and Forecasts` (Extracted from Google AI response)
- `🌐 Peer Comparison ({EXTRACTED_GOOGLE_AI_PEERS})` (Extracted directly from Google AI response, e.g. *KEI Industries or Havells*)
- `🔊 Read Audio Briefing`

---

## Proposed Changes

### Backend Layer

#### [main.py](file:///c:/Users/dheer/Desktop/AI/indian-stock-analyzer%20-%205.0/backend/main.py)
- Create SQLite cache table `cached_google_ai_overview` (columns: `symbol`, `overview_json`, `updated_at`).
- Add endpoint `@app.get("/api/google-ai-overview/{symbol}")`:
  - Accepts `symbol: str` and `force_refresh: bool = False`.
  - Queries SerpApi with natural question query:  
    `"What is the latest market news, financial performance, and catalysts for {clean_symbol} stock in India?"`
  - Parses SerpApi `ai_overview` payload (extracts section titles, bullet points, source citations, and Google AI generated follow-up prompts).
  - Fallback: If `ai_overview` is missing, passes search snippets to Gemini 1.5 Flash with strict Google AI Overview prompt schema (including follow-up prompts).
  - Returns structured JSON payload containing `suggested_followups` extracted from Google AI Search.
- Add startup housekeeping purge:  
  `DELETE FROM cached_google_ai_overview WHERE updated_at < DATETIME('now', '-24 hours')`.

#### [catalyst_scraper.py](file:///c:/Users/dheer/Desktop/AI/indian-stock-analyzer%20-%205.0/backend/catalyst_scraper.py)
- Add `fetch_serpapi_google_ai_overview(query, serpapi_keys)` helper returning structured sections, citation chips, and suggested follow-up prompts.

---

### Frontend UI & Layout Layer

#### [index.html](file:///c:/Users/dheer/Desktop/AI/indian-stock-analyzer%20-%205.0/backend/static/index.html)
- Add `<div id="google-ai-overview-card" class="card">` inside the Stock Analysis Executive Summary view.
- Structure card with dark-theme glassmorphism, purple Google AI gradient accents, bullet list sections, citation pills, and follow-up prompt chips.

#### [styles.css](file:///c:/Users/dheer/Desktop/AI/indian-stock-analyzer%20-%205.0/backend/static/styles.css)
- Add mobile CSS rules (`@media (max-width: 768px)`):
  - `.google-ai-card`: 100% width, 1-column layout, touch padding.
  - `.citation-chip-row`: `flex-wrap: wrap`, gap 6px.
  - Dynamic font scaling (headers `15px–17px`, bullets `12.5px–13.5px`, pills `10px–11px`).

#### [app.js](file:///c:/Users/dheer/Desktop/AI/indian-stock-analyzer%20-%205.0/backend/static/app.js)
- Add `loadGoogleAIOverviewCard(symbol, forceRefresh)` function.
- Dynamically format follow-up chips using `data.suggested_followups` extracted directly from Google AI Search.
- Hook into main stock search loading pipeline (`updateMetaBannerDetails`).

---

## Verification & Mobile Testing Plan

### Automated / API Verification
- Test endpoint via python:  
  `http://localhost:8000/api/google-ai-overview/POLYCAB?force_refresh=true`.
- Verify response `suggested_followups` contains the exact Google AI prompts.

### Manual UI & Mobile Verification
- Open `http://localhost:8000` in browser.
- Search **POLYCAB** -> verify peer chip displays Google AI's extracted follow-up text (*KEI Industries or Havells*).
- Run `npx cap sync` to synchronize mobile Capacitor web assets with the Android native APK build folder.
