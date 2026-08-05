# Implementation Plan — UI/UX & Mobile Edge-to-Edge Enhancements for ✨ Google AI Overview

Upgrade the **✨ Google AI Overview** subtab into a state-of-the-art equity intelligence terminal with a **Bull/Bear AI Sentiment Gauge**, **Key Metric KPI Summary Banner**, **3-Column Visual Card Grid**, **Clickable Publisher Citations**, **Interactive Follow-Up Slide-Over Modal**, and **100% Mobile Edge-to-Edge Responsiveness & Typography Scaling**.

---

## User Review Required

> [!IMPORTANT]
> **Complete Package of Approved Features & Mobile Specifications:**
> 1. **📱 Mobile Edge-to-Edge & Typography Alignment**:
>    - Matches container margins, padding (`12px 14px`), and corner radius (`border-radius: 12px`) with existing Executive Summary & DCF Valuation sections.
>    - Scaled typography: `15px` Outfit title, `13px` section headers, `12px` bullet body (`line-height: 1.55`), `10.5px` citation link pills.
>    - 1-column mobile auto-collapse under `@media (max-width: 768px)` for zero horizontal scroll and pixel-perfect portrait viewing on Android/iOS Capacitor webview.
> 2. **Recommendation A — Bull/Bear AI Sentiment Gauge Meter**: Gradient progress gauge (e.g. `🟢 88% Bullish | Strongly Positive`) based on SGE catalyst analysis.
> 3. **Option 1 — KPI Summary Banner & Multi-Card Grid**: 4 top KPI summary badges (Revenue, PAT, EBITDA Margin, Analyst Consensus) + 3 visual category cards (`Financial Performance`, `Market News`, `Growth Catalysts`).
> 4. **Option 2 — Clickable Publisher Citations**: Makes all citation chips (`🌐 The Economic Times ↗`, `🌐 Screener ↗`, `🌐 Moneycontrol ↗`) interactive links that open original source articles in a new tab.
> 5. **Option 3 — Interactive Follow-Up Slide-Over Modal**: Clicking follow-up prompt chips (`🌐 Peer Comparison (KEI & Havells)`, `📊 Quarterly Profit Trend`) opens a slide-over modal powered by live backend follow-up resolution.

---

## Proposed Changes

### Frontend Components & DOM Architecture

#### [MODIFY] [index.html](file:///c:/Users/dheer/Desktop/AI/indian-stock-analyzer%20-%205.0/backend/static/index.html)
- Add `#google-ai-followup-modal` backdrop and slide-over container for Option 3 follow-up prompt execution.

#### [MODIFY] [styles.css](file:///c:/Users/dheer/Desktop/AI/indian-stock-analyzer%20-%205.0/backend/static/styles.css)
- **Mobile Edge-to-Edge Container**: Match `#google-ai-overview-card-container` padding (`0 12px` / `0 14px`) and width (`100%`) with `.executive-summary-section` and `.dcf-section`.
- **Mobile Typography System**:
  - Main Title: `font-size: 15px`, `font-family: 'Outfit', sans-serif`, `font-weight: 600`.
  - Section Headers: `font-size: 13px`, `font-weight: 600`, color `var(--text-primary)`.
  - Bullet Points: `font-size: 12px`, `line-height: 1.55`, `color: var(--text-secondary)`.
  - Citation Link Pills: `font-size: 10.5px`, `padding: 2px 7px`, `border-radius: 6px`.
- **Bull/Bear Sentiment Gauge**: `.sentiment-gauge-bar` gradient progress container with percentage text badge and sentiment pill (`Strongly Positive`).
- **Top KPI Summary Banner**: `.google-ai-kpi-banner` grid with 4 glowing metric badges (Revenue, Profit, Margins, Consensus).
- **3-Column Grid Layout & Mobile Auto-Collapse**:
  - Desktop: `grid-template-columns: repeat(auto-fit, minmax(320px, 1fr))`
  - Mobile `@media (max-width: 768px)`: Collapses to `grid-template-columns: 1fr`, `gap: 10px`, zero horizontal overflow.
- **Interactive Citation Link Pills**: `.citation-chip-link` with hover animations, glowing borders, and external link arrow (`↗`).
- **Follow-Up Slide-Over Modal**: `.google-ai-modal` overlay with smooth transition and backdrop blur.

#### [MODIFY] [app.js](file:///c:/Users/dheer/Desktop/AI/indian-stock-analyzer%20-%205.0/backend/static/app.js)
- Update `renderGoogleAIOverviewCard(data)` to:
  1. Render **Bull/Bear Sentiment Gauge** bar (`sentiment_score`, `sentiment_label`).
  2. Extract and display top KPI summary badges in `.google-ai-kpi-banner`.
  3. Map `references` URLs into clickable `<a>` citation tags.
  4. Render 3 distinct category cards in a grid layout.
- Implement `handleGoogleAIFollowup(symbol, promptText)` to open `#google-ai-followup-modal` and fetch follow-up answers.

---

### Backend Endpoint & Follow-Up Engine

#### [MODIFY] [main.py](file:///c:/Users/dheer/Desktop/AI/indian-stock-analyzer%20-%205.0/backend/main.py)
- **Sentiment Score Calculator**: Analyze SGE `text_blocks` and organic catalysts to compute a numerical sentiment score (0–100%) and label (`Bullish`, `Neutral`, `Bearish`).
- **KPI Extraction**: Parse SGE `text_blocks` to automatically compute top KPI summary metrics (`kpi_metrics`: revenue growth, profit growth, EBITDA margin, analyst rating).
- **Clickable Reference Map**: Map `snippet_links` and `references` into direct external target URLs.
- **Follow-Up Endpoint**: Add `@app.get("/api/google-ai-followup")` to resolve follow-up prompt queries dynamically.

---

## Verification Plan

### Automated Tests & Lint Checks
- Compile backend server: `python -m py_compile backend/main.py`
- Validate frontend syntax: `node -c backend/static/app.js`
- Test API endpoints: `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/google-ai-overview/POLYCAB.NS?force_refresh=true')"`

### Manual Verification & Mobile Sync
1. Open local web app at `http://localhost:8000` and navigate to **✨ GOOGLE AI OVERVIEW** tab.
2. Verify edge-to-edge mobile alignment and typography scaling on desktop and mobile viewport (`375px` / `412px`).
3. Verify **Bull/Bear Sentiment Score Gauge** displays gradient progress bar (`🟢 88% Bullish | Strongly Positive`).
4. Verify top **KPI Summary Banner** displays 4 key metric pills at a glance.
5. Verify 3-column card grid on desktop and 1-column auto-collapse on mobile screens.
6. Click citation link chips (`🌐 The Economic Times ↗`) to confirm source article opens in a new tab.
7. Click **`🌐 Peer Comparison (KEI & Havells)`** chip to verify slide-over modal opens with quick peer comparison.
8. Synchronize mobile assets using `python scratch/sync_assets.py`.
