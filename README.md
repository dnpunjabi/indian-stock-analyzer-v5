# 📊 High-Fidelity Indian Stock Analyzer & Screener
A multi-agent, profile-aware investment analyzer and quantitative stock screener designed for the Indian equity market (NSE). Powered by a hierarchical LLM coordinator (Groq/Llama-3), a persistent SQLite caching database, and a highly responsive, premium interactive glassmorphism UI.

---

## 🏗️ System Architecture

The application operates as a hierarchical, multi-agent financial research analyst network. Below is the system flow showing how requests are processed:

```mermaid
graph TD
    UI[HTML5 Premium Glassmorphism UI] <--> |JSON API| Server[FastAPI Application Backend]
    
    subgraph Data Layer
        DB[(SQLite Persistent Database)]
        CacheWarmer[Background Cache Warmer Loop] --> |Write-Through Caching| DB
        NSE[NSE India Archives] --> |Index Constituent Sync| DB
    end

    subgraph Analytical Core
        Server <--> |Read / Write| DB
        Server --> |Launch Multi-Agent Pipeline| CIO[Chief Investment Officer Parent Agent]
        
        CIO --> |Sub-Delegation 1| CFA[CFA Chartist - Technical/RSI Analyst]
        CIO --> |Sub-Delegation 2| Auditor[Risk & Governance Auditor]
        CIO --> |Sub-Delegation 3| Chartist[Valuation Specialist - DCF Modeling]
        
        CFA --> |Collate Ratios| CIO
        Auditor --> |Audit Risk| CIO
        Chartist --> |Run DCF Valuation| CIO
    end

    Server --> |yfinance & Screener.in| Scrapers[Real-Time Hybrid Data Scrapers]
    Scrapers --> |Dynamic Overlay| CIO
```

---

## 💎 Core Feature Matrix

| Feature Section | 🔍 Data Source | 🧮 Mathematical Calculation | ⚡ Investor Impact | 🔄 Refresh Frequency |
| :--- | :--- | :--- | :--- | :--- |
| **Multi-Agent Research Suite** | `yfinance` & `Screener.in` | Blends structural fundamentals, technical momentum, and intrinsic value indicators into a dynamic **AI Advisory Score (0-100)**. | Delivers a hyper-personalized investment prospectus custom-tailored to the user's active investor profile. | **Real-time on-demand** (Write-through caching updates database instantly). |
| **Historical P/E Bands (3-5Y)** | `yfinance` 5-year monthly prices & TTM Consolidated EPS | Sorts 60 months of historical P/E multiples ($Price_t / EPS_t$) to extract the absolute Min, Max, and chronological Median. | Prevents Standalone vs. Consolidated mismatches; isolates true premium or discount relative to historical norms. | **24-hour cache lifespan** (Incremental background refreshes). |
| **Self-Healing Valuation Engine** | `yfinance` Trailing EPS & Scraped Screener Cards | Cross-validates scraped P/E against real-time derived P/E: $\text{Price} / \text{TTM\_EPS}$. Triggers overrides on anomalies (discrepancy $> 50$ or P/E $> 300$). | Bypasses corrupted external datasets automatically (e.g. self-heals `GVT&D.NS` / GE Vernova T&D P/E from outdated `706` to true `106.4`). | **Automatic on-load** (Self-heals cached profiles during cache-misses). |
| **AI Stock Screener** | Persistent SQLite `screener_universe` and `cached_profiles` | Filters active index constituents against **dynamic quality gates** (Debt/Equity, ROE%, promoter pledge, EPS growth). | Customizes universe scans instantly; Conservative profile tightens gates while Aggressive profile rewards high growth. | **Sub-millisecond execution** (Leverages persistent SQLite cache). |
| **Fully Real-Time Alert Engine** | SQLite active triggers & real-time scanner | Constant silent background sweeps auditing conditions ($Price > SMA_{200}$ or $RSI_{14} \le 30$) in the background. | Emits Web Audio API synthesized double-beeps (`880Hz` -> `1200Hz`) and increments header bell badge counts in real-time. | **Continuous background loop** (Active polling every 30 seconds). |
| **Index Explorer** | NSE India official CSV constituent listings | Direct fetch & download of official Nifty 100, Midcap 150, and Smallcap 250 baskets. | Provides complete visibility over index caching status (`WARMED 🟢` or `COLD ⚪`) with 1-click deep research. | **Manual Sync** or **On-Start Auto-Rebalance** (10-second initial boot delay). |
| **Bloomberg-Style Sub-Tabs** | Dynamic client DOM controller | Groups 21 dashboard cards into 6 sub-tabs, firing window resize events on toggles to trigger synchronous Chart.js redraws. | Maximizes visual hierarchy, saving vertical scroll space; keeps charts responsive and scaled correctly to their containers. | **Instantaneous** (Client-side interactive toggles). |

---

## 🛠️ Feature Deep Dive & Calculations

### 1. Unified Multi-Agent Research Engine
When a stock is searched in the **Single Stock Workspace**, the `Chief Investment Officer (CIO) Agent` coordinates a parallel analytical pipeline:
*   **CFA Chartist (Technicals)**: Evaluates the Relative Strength Index ($RSI_{14}$) and the 200-day Simple Moving Average ($SMA_{200}$).
*   **Risk Auditor (Governance)**: Scrutinizes leverage limits (Debt-to-Equity), working capital safety (Current Ratio), cash flow durability ($\text{CFO-to-PAT} \ge 0.8$), promoter pledge percentages, and auditor qualifications.
*   **Valuation Specialist (DCF Model)**: Calculates intrinsic value using a two-stage **Discounted Cash Flow** formula:
    $$PV = \sum_{t=1}^{5} \frac{FCF_0 \cdot (1 + g)^t}{(1 + WACC)^t} + \frac{FCF_5 \cdot (1 + g_n)}{(WACC - g_n) \cdot (1 + WACC)^5}$$
    *Where $g$ is the 5-year revenue growth projection, $WACC$ is the weighted average cost of capital, and $g_n$ is the terminal growth rate (capped at 4.5% to represent long-term GDP constraints).*

### 2. Look-Ahead Bias-Free P/E Bands
Traditional historical P/E calculations often suffer from *Look-Ahead Bias* (dividing historical stock prices by today's high EPS) or fail completely due to `NaN` annual report entries. 

Our engine resolves this by:
1.  **Chronological EPS Mapping**: Dropping `NaN` filings and chronological sorting of valid historical EPS points.
2.  **Bridging the Gap**: Appending `yfinance` `trailingEps` to represent the most recent rolling 12-month period.
3.  **CAGR Discounting Fallback**: If no historical EPS is found, the engine reconstructs the previous 5 years by discounting today's trailing EPS backward using a realistic 12% annual equity growth rate ($\text{historical\_eps} = \text{trailing\_eps} \times 0.88^i$).
4.  **Consolidated Value Lock**: The main stock P/E is overridden with the latest P/E in the consolidated history list, preventing Standalone vs. Consolidated mismatches (e.g., for JSW Energy).

### 3. Dynamic Self-Healing Valuation Engine
To prevent external data corruption or lag (for instance, **Screener.in** listing an outdated Standalone P/E of **706** for `GVT&D.NS` / GE Vernova T&D India Ltd), the backend applies an automated self-healing validation gate:
$$\text{Derived P/E} = \frac{\text{Current Price}}{\text{TTM Trailing EPS}}$$
*   **Discrepancy Check**: If $|\text{Scraped P/E} - \text{yfinance Trailing P/E}| > 50$, the system automatically overrides the P/E with the verified yfinance trailing multiple.
*   **Outlier Cap**: If $\text{Scraped P/E} > 300$ and $\text{Derived P/E} < 150$, the scraped outlier is flagged as corrupted and healed instantly to the derived P/E.

### 4. Fully Real-Time Alert Engine & Audio Cues
Alert rule auditing operates as a real-time background loop:
*   **Silent Background Polling**: A client-side worker polls `/api/alerts/check` every 30 seconds.
*   **Audible Alerts**: Breached thresholds trigger a synthesized dual-tone double-beep (`880Hz` for 150ms -> `1200Hz` for 150ms) using the native browser **Web Audio API** (avoiding external audio asset files and respecting the user's settings menu toggle).
*   **Dynamic Notification Sync**: Breached alerts automatically increment the sticky header's notifications count badge, inject red-badged (`TRIGGERED`) alert summaries into the header dropdown panel, and refresh the active logs table in real-time.

### 5. Bloomberg-Style Sub-Tabs & Accordion Scaling
To maximize layout efficiency, the single-stock dashboard divides its 21 analysis cards into 6 sub-tabs:
*   **Layout Compression**: Below the sticky header, a premium glassmorphic accordion toggle (**`⚙️ CONFIGURE PDF REPORT SECTIONS ▼`**) collapses the 11-checkbox print filter panel smoothly using CSS transitions (`max-height 0.3s ease-out`), saving vertical workspace space by default.
*   **Chart.js Active-Scaling Hook**: Switching tabs strips `.card-hidden` from active elements and triggers a global `window.dispatchEvent(new Event('resize'))` alongside synchronous Chart.js `.resize()` and `.update()` calls. This forces all hidden price curves, Fibonacci ranges, and drawdown indicators to instantly scale and draw pixel-perfect layouts when brought into view.

---

## 🗄️ Database Schema (SQLite)

The application uses an optimized, persistent SQLite database located at `backend/data/watchlist_database.db`.

```sql
-- 1. Persistent Screener Universe
CREATE TABLE IF NOT EXISTS screener_universe (
    symbol TEXT PRIMARY KEY,
    base_symbol TEXT NOT NULL,
    company_name TEXT NOT NULL,
    sector TEXT NOT NULL,
    cap_type TEXT NOT NULL,         -- 'large', 'mid', or 'small'
    last_rebalanced TEXT NOT NULL
);

-- 2. Persistent Cached Financial Profiles
CREATE TABLE IF NOT EXISTS cached_profiles (
    symbol TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,     -- Complete analytical payload
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Persistent Alerts Schema
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    condition_type TEXT NOT NULL,   -- 'PRICE', 'RSI', 'SMA'
    operator TEXT NOT NULL,         -- '>', '<', '<='
    value TEXT NOT NULL,
    status TEXT DEFAULT 'Active',   -- 'Active' or 'Triggered'
    triggered INTEGER DEFAULT 0,
    trigger_date TEXT DEFAULT ''
);

-- 4. Watchlist Tables
CREATE TABLE IF NOT EXISTS watchlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watchlist_id INTEGER,
    symbol TEXT NOT NULL,
    name TEXT,
    sector TEXT,
    FOREIGN KEY(watchlist_id) REFERENCES watchlists(id) ON DELETE CASCADE,
    UNIQUE(watchlist_id, symbol)
);
```

---

## ⚡ Background Tasks & Caching Policies

### 🔄 The Background Cache Warmer
Calculates and updates stock profiles incrementally without triggering third-party scraping rate limits or API blocks.
*   **Checking Frequency**: Runs once **every hour**.
*   **Initial Boot Delay**: **10 seconds** to allow core services to initialize cleanly.
*   **Refreshes**: Only targets entries older than **24 hours**.
*   **Throttling Delay**: Waits **4 seconds** between each stock update (and **10 seconds** on failure fallbacks) to respect rate limits.

### ⚡ Nightly 13-Screener Quant Prewarm Job
The background daemon automatically runs the 13-screener prewarm sweep every night at **01:30 AM IST**. To manually trigger or inspect the sweep status:
*   **Trigger Full Prewarm Sweep On-Demand**:
    ```bash
    curl -X POST http://127.0.0.1:8000/api/system/trigger-prewarm-sweep
    ```
*   **Check Prewarm Status & Caching Timestamps**:
    ```bash
    curl -s http://127.0.0.1:8000/api/system/cron-status
    ```

---

## 🚀 Setup & Execution

### 1. Environment Configurations
Create a `.env` file in the root directory:
```env
GROQ_API_KEY=your_groq_api_key_here
PORT=8000
DATABASE_DIR=backend/data
```

### 2. Install Dependencies
```bash
pip install -r backend/requirements.txt
```

### 3. Run the Development Server
```bash
python -m uvicorn backend.main:app --port 8000 --reload
```

### 4. Run the Analytical Test Suite
Ensure database integrity and system calculations are durable by running the automated unit test suite:
```bash
python -m backend.test_models
```
*(All 10 comprehensive unit tests pass with `OK` status).*

---

## 🌐 API Endpoint Reference

The backend exposes a highly optimized, environment-gated REST API built on FastAPI.

| Method | Endpoint | Description | Request Payload / Params |
| :--- | :--- | :--- | :--- |
| **GET** | `/api/analyze` | Triggers real-time Multi-Agent consensus research. | `query` (symbol), `horizon` (optional), `risk` (optional) |
| **POST** | `/api/analyze-custom` | Recalculates DCF sandbox intrinsic value using custom overrides. | `query`, `horizon`, `risk_profile`, `revenue_growth`, `opm`, `wacc`, `terminal_growth` |
| **GET** | `/api/discover` | Runs AI Screener Engine across Strategy & Universe. | `strategy` (hybrid/bottom_up/top_down), `universe` (all/large/mid/small), `horizon`, `risk` |
| **GET** | `/api/universe` | Retrieves persistent NSE index constituent listings. | `cap_type` (optional: large/mid/small) |
| **GET** | `/api/admin/rebalance-status` | Returns rebalance sync timestamps & cache coverage. | None |
| **POST** | `/api/admin/rebalance` | Manually triggers fresh official NSE index downloads. | None |
| **POST** | `/api/alerts/set` | Registers a persistent condition-based indicator alert. | `ticker`, `condition_type` (PRICE/RSI/SMA), `operator`, `value` |
| **GET** | `/api/alerts/check` | Runs manual background sweeping check of active alerts. | None |
| **GET** | `/api/system/cron-status` | Returns 13-screener prewarm status, timestamps, and leader counts. | None |
| **POST** | `/api/system/trigger-prewarm-sweep` | Triggers background 13-screener prewarm recalculation sweep on-demand. | None |
| **GET** | `/api/watchlists` | Lists all user watchlists and constituent items. | None |

---

## 🖥️ Interactive Workspace Tour

The premium glassmorphic user interface is divided into dedicated workspaces:

### 1. Unified Control Dashboard
*   **Index Universe Monitor**: Displays the current database synchronization status, indicating the exact size of your large, mid, and small-cap constituent databases and the current warm cache coverage.
*   **Manual Index Sync Trigger**: Initiates a background download of official NSE list updates with an animated progress container.
*   **Alert Tracker Panel**: View active alerts, trigger timestamps, and indicators.

### 2. Single Stock Workspace
*   **Bloomberg-Style Sub-Tabs Navigation**: Divides the 21+ comprehensive analytics cards into 6 logical sub-tabs, completely replacing vertical scrolling with structured, active-scaling workspaces:
    1.  `📋 Executive Summary`: Business profiles, CIO prospectus checklist, growth catalysts, and risk indicators.
    2.  `📊 Valuation & DCF`: DCF sandbox, cost of capital sliders, sensitivity matrices, consensus targets, and historical PE bands.
    3.  `📉 Technical Timing`: SMA price chart curves, RSI momentum listings, Fibonacci retracements, capturing ratios, and drawdowns.
    4.  `🩺 Ratios & Earnings`: Altman Z-Score, Piotroski F-Score logs, and dynamic compounding return calculators.
    5.  `👥 Peers & Ownership`: Competitive side-by-side matrices, rival pricing trendlines, and promoter/FII shareholdings.
    6.  `🔬 Agent Strategy Audit`: Multi-agent operational Diagnostics audit matrix displaying gate-by-gate pass/fail results.
*   **Collapsible Configure PDF Sections Panel**: A glassmorphic accordion panel (**`⚙️ CONFIGURE PDF REPORT SECTIONS`**) equipped with a granular **11-checkbox matrix**. Saves valuable screen space by remaining collapsed by default, sliding open smoothly with rotating arrow chevrons (`▼` to `▲`).
*   **Q&A Co-Pilot Prospectus Drawer**: Features a dynamic side-drawer triggered by the conviction badge pill. Supports interactive conversational chatbot prospectus queries, soft-red circular hover-closing triggers, click-outside-to-close listeners, and a **Print Prospectus** exporter button (`#print-prospectus-btn`) compiling Llama-3 synthesis into custom A4 PDF page briefs.
*   **Dynamic Chart.js Auto-Scaler**: Bypasses browser thread suspensions on hidden elements by automatically firing window resize triggers and `.resize()` / `.update()` routines when switching sub-tabs, securing crisp, correctly scaled pricing and Fibonacci curves.

### 3. AI Stock Screener
*   **Quantitative Strategy Selector**: Choose between Top-Down, Bottom-Up, or Hybrid screenings.
*   **Segment Selector & Style Overlays**: Scan Nifty baskets or isolate targets against investment overlays (Value, Growth, Contra). Supports custom A4 print formatting and dynamic CSV ledger downloads.
*   **Global Investor Profile Configurator**: Adjusts quality gate criteria and blended scoring algorithms dynamically in the background based on Horizon and Risk boundaries.

### 4. Index Universe Registry
*   **Index Constituent Monitor**: Complete database oversight over large, mid, and small cap NSE listings.
*   **Sync Engine**: Supports manual constituent updates from the live exchange, displaying progress bars and caching status (`WARMED 🟢` or `COLD ⚪`).

### 5. Peer Benchmarking Arena
*   **Tactical Battleground Matrix**: Direct, side-by-side comparison grids plotting valuation, returns, and momentum indicators.
*   **Sector Battleground Exporter**: Features a `#print-battleground-btn` button compiling peer statistics and custom Llama-3 competitive advantage theses into formal A4 report popup sheets.

### 6. Watchlist Registry Workspace
*   **SQLite Watchlist Managers**: Supports customized watchlists (Add, Delete, Rename) synced directly to SQLite.
*   **AI Batch Scorecard Exporter**: Computes batch constituents lists, generating a Groq Llama-3 portfolio summary report (**`Generate AI Watchlist Summary`**) and launches a unified popup printer (`#print-watchlist-report-btn`) mapping the constituent table and AI risk logs.

### 7. Portfolio Optimization Doctor
*   **Holdings Allocation Ledger**: Formats and audits current holdings (tickers, cost, committed capital, unrealized net P&L).
*   **Optimization Prescription Exporter**: Evaluates asset concentrations, computing health scores and diagnostics. Features a **Print Diagnostics Exporter** (`#print-portfolio-report-btn`) launching A4 print sheets decorated with soft green/red asset allocation meters.

---

## 💬 Developer Chat Slash Commands

When working with this codebase inside your agentic IDE, you can invoke the following shortcuts:

*   `/goal` — Use this when triggering long-running quantitative sweeps, automated database migrations, or system audits. The agent will execute sequentially, validating every phase, and will not stop until the goal is fully achieved.
*   `/schedule` — Use this to configure cron expressions or timers for background sweeps (e.g. running daily alerts verification sweeps at market close).
*   `/grill-me` — Use this to align on major database design changes or system upgrades through an interactive architecture interview.

---

## 🛠️ Diagnostics & Troubleshooting

> [!NOTE]
> All analytical database connections leverage connection context managers with foreign key constraints enabled by default.

### 1. Standalone vs. Consolidated Mismatch
If a stock's current P/E appears abnormally high (e.g., JSW Energy showing standalone P/E 115x) while its historical bands indicate a consolidated median (42x), the backend automatically overrides the displayed P/E using the latest calculated entry from the yfinance historical P/E list. This guarantees that current and historical metrics remain perfectly consistent on a consolidated basis.

### 2. Self-Healing Valuation Anomalies (The GVT&D P/E Fix)
Due to occasional delayed data updates on external Indian stock portals, **Screener.in** may publish corrupted P/E multiples (for instance, showing an outdated P/E of **706** for `GVT&D.NS` / GE Vernova T&D India Ltd). 
The backend resolves this automatically:
- During database mapping, it calculates a **Derived P/E** ($\text{Price} / \text{Trailing\_EPS}$ from yfinance real-time values).
- If it detects a discrepancy $> 50$ or an outlier ($PE > 300$ while derived P/E $< 150$), it flags the data as corrupted and **self-heals the profile** using the correct trailing P/E multiple (rebuilding the valuation bands to a correct, clean multiple of **106.38**).

### 3. Purging Stale Database Cache
To force-refresh an equity's profile or clear database write lock anomalies, execute this simple SQLite purge command from the root directory:
```bash
python -c "import sqlite3; conn = sqlite3.connect('backend/data/watchlist_database.db'); c = conn.cursor(); c.execute('DELETE FROM cached_profiles WHERE symbol = \'YOUR_TICKER.NS\''); conn.commit()"
```
Upon the next query or background warming loop, the system will rebuild and cache the profile using the latest real-time scraping structures.

---

## 🤖 AI / LLM Capabilities Mapping

For full technical specifications on all integrated AI capabilities and endpoints, please refer to the dedicated [AI_LLM_CAPABILITIES.md](file:///c:/Users/dheer/Desktop/AI/indian-stock-analyzer/AI_LLM_CAPABILITIES.md) catalog.

A high-level summary of AI features mapped by subfeature:

### 1. Portfolio Management & Optimization
*   **AI Rebalancing Advisory**: `POST /api/portfolio/stress-test` (TASK_FAST) - Sharpe optimization commentary.
*   **AI Portfolio Doctor**: `backend/agent.py` (TASK_HEAVY) - Diagnostics & trade triggers.
*   **AI Backtest Performance Synthesis**: `backend/agent.py` (TASK_HEAVY) - Returns and drawdown attribution.

### 2. Equity Research Terminal
*   **CIO Strategic Investment Thesis**: `backend/agent.py` (TASK_HEAVY) - Intrinsic value and ranges.
*   **CFA & Technical Prospectus**: `backend/agent.py` (TASK_HEAVY) - Multi-agent governance and charts review.
*   **Investment Committee Memo (Pitchbook)**: `GET /api/analyze/pitchbook` (TASK_FAST) - Institutional deck generator.

### 3. Market Regime & News Feed
*   **AI Sector Rotational Commentary**: `backend/main.py` (TASK_FAST) - Sector relative strength regimes.
*   **AI News Sentiment & Price Anomaly Audit**: `backend/main.py` (TASK_FAST) - Corporate catalysts and sentiment auditing.

### 4. Technical Indicators & Charting
*   **Custom Indicator AI Insights**: `GET /api/chart/indicator-synthesis` (TASK_FAST) - LuxAlgo, SMC, Maxwell charting channels.

### 5. Smart Scanner & Rule Builder
*   **AI Natural Language Scan Command Station**: `POST /api/screener/parse-nl-scan` (TASK_FAST) - Plain English to scanner rules.
*   **AI Screener Scan Synthesis**: `POST /api/screener/scan-synthesis` (TASK_FAST) - Scanner cluster analysis.
*   **AI Natural Language Alert Builder**: `POST /api/alerts/parse-nl` (TASK_FAST) - Plain English to alert settings.

