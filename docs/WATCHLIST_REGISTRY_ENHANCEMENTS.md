# Watchlist Registry — Enhancement Roadmap & Feature Backlog

> **Document ID**: WR-ENHANCE-2026-07-28  
> **Created**: 28 Jul, 2026  
> **Status**: Approved for Implementation  
> **Author**: AI Workstation Dev Team

---

## ✅ Current Feature Inventory (Already Built)

| # | Feature | Status |
|---|---|---|
| 1 | Create / Delete / Rename Watchlists (max 10) | ✅ Live |
| 2 | Add / Remove Stocks (max 100 per watchlist) | ✅ Live |
| 3 | Import from Screener.in | ✅ Live |
| 4 | 3-Dot DVM Traffic Light Signals (Valuation → Momentum → Health) | ✅ Live |
| 5 | Overview View (LTP, Added Price, Added On, Chg Since Added, Day Chg, 52W Range) | ✅ Live |
| 6 | Returns Matrix View (1W, 1M, 3M, 6M, 1Y) | ✅ Live |
| 7 | Quick Filter Chips (All, Top Gainers, 3-Dots Green, Dip Alerts) | ✅ Live |
| 8 | Telemetry Grid (Avg Conviction, Sector Dispersion, Avg P/E / ROE / MOS) | ✅ Live |
| 9 | Batch Analysis Scorecard (Score, Action, MOS, RSI, Trend) | ✅ Live |
| 10 | Risk-Return Scatter Plot & Consensus Verdict Thermometer | ✅ Live |
| 11 | AI Watchlist Portfolio Summary (LLM-generated) | ✅ Live |
| 12 | Print Batch Report | ✅ Live |
| 13 | Pagination & Column Sorting | ✅ Live |
| 14 | Sticky Left Column (Mobile) | ✅ Live |
| 15 | Live Price Refresh (WebSocket + HTTP fallback) | ✅ Live |
| 16 | Fuzzy Score Badge per stock | ✅ Live |

---

## 🚦 3-Dot DVM Traffic Light — Multi-Parameter Composite Rules

### Dot 1: Valuation 💎
- **Parameters**: `P/E Ratio`, `PEG Ratio`, `P/B Ratio`, `Sector P/E (Industry PE)`, `EV/EBITDA`
- 🟢 **Green (Undervalued)**: `P/E < 25` OR `P/E < Sector P/E` OR `PEG < 1.0` OR `EV/EBITDA < 12`
- 🟡 **Yellow (Fairly Valued)**: `25 ≤ P/E ≤ 45` OR `1.0 ≤ PEG ≤ 2.0` OR `12 ≤ EV/EBITDA ≤ 20`
- 🔴 **Red (Expensive)**: `P/E > 45` OR `PEG > 2.0` OR `EV/EBITDA > 25`

### Dot 2: Technical Momentum 🚀
- **Parameters**: `RSI (14-day)`, `50-Day MA vs 200-Day MA`, `Breakout/Breakdown Status`
- 🟢 **Green (Bullish)**: `RSI > 55` AND `50MA ≥ 200MA` AND no Bearish Breakdown
- 🟡 **Yellow (Consolidating)**: `40 ≤ RSI ≤ 55` OR (`RSI > 55` but `50MA < 200MA`)
- 🔴 **Red (Bearish)**: `RSI < 40` OR (`RSI < 45` and `50MA < 200MA`) OR Bearish Breakdown

### Dot 3: Financial Health & Quality 🛡️
- **Parameters**: `Debt-to-Equity (D/E)`, `ROE %`, `ROCE %`, `Promoter Pledge %`, `Interest Coverage`
- 🔴 **Red (Critical Override)**: `Promoter Pledge > 15%` — immediate red regardless of other metrics
- 🟢 **Green (Strong)**: `D/E < 0.5` AND (`ROE > 15%` OR `ROCE > 15%` OR `Interest Cov > 4.0x`)
- 🟡 **Yellow (Moderate)**: `0.5 ≤ D/E ≤ 1.2` OR `8% ≤ ROE ≤ 15%`
- 🔴 **Red (Weak)**: `D/E > 1.2` OR `ROE < 8%`

---

## 🏆 Enhancement Backlog — Tier 1 (Quick Wins, P0)

### ENH-01: Target Price & Margin of Safety Column
- **Description**: Add a Target Price column showing DCF-derived intrinsic value alongside current LTP. Display Margin of Safety % as a colored pill (🟢 > 20% upside, 🟡 0-20%, 🔴 overvalued).
- **Data Source**: `dcf_model.margin_of_safety` from batch analysis endpoint
- **Impact**: Very High | **Effort**: Low

### ENH-02: Watchlist Export to CSV/Excel
- **Description**: Add an 📤 Export CSV button in the watchlist header. Export all visible columns (Symbol, LTP, Added Price, Chg Since Added, DVM dots, 52W position, Returns matrix). Include timestamp and watchlist name in filename.
- **Impact**: High | **Effort**: Low

### ENH-03: Drag-and-Drop Reorder Stocks
- **Description**: Allow manual reordering of stocks within a watchlist by drag-and-drop. Add `sort_order INTEGER` column to `watchlist_items` table. Persist custom order in SQLite.
- **Impact**: Medium | **Effort**: Medium

### ENH-04: Inline Notes / Investment Thesis per Stock
- **Description**: Add a small 📝 note icon per stock row that opens an inline text area. Users write a 1-2 line investment thesis (e.g., "Buy on dip below ₹2,800. Strong ROCE moat."). Store in `notes TEXT` column in `watchlist_items`.
- **Impact**: High | **Effort**: Low

### ENH-05: Additional Smart Filter Chips
- **Description**: Add more filter chips beyond the existing 4:
  - 📊 High Conviction (Score ≥ 75)
  - 🎯 Near 52W Low (within 10% of 52-week low)
  - 🚀 Near 52W High (within 5% of 52-week high)
  - 🔴 Red Flags (any red DVM dot)
- **Impact**: High | **Effort**: Low

---

## 🥈 Enhancement Backlog — Tier 2 (Medium Effort, P1)

### ENH-06: Price Alert / Target Notification System
- **Description**: Per-stock price alert targets (e.g., "Alert me when TCS drops below ₹3,500"). Store `alert_price_low REAL` and `alert_price_high REAL` in `watchlist_items`. Visual indicator on breached alerts. Optional WhatsApp notification (backend already has `check_fuzzy_watchlist_whatsapp_alerts` infrastructure).
- **Impact**: Very High | **Effort**: Medium

### ENH-07: Watchlist Comparison View (Side-by-Side)
- **Description**: Select 2-3 stocks from watchlist for side-by-side comparison. Compare P/E, ROE, ROCE, D/E, MOS, RSI, Returns (1W to 1Y). Display as comparison card or modal with radar chart.
- **Impact**: Medium | **Effort**: Medium

### ENH-08: Sector-Wise Interactive Heatmap
- **Description**: Replace or augment the sector dispersion bar with an interactive sector heatmap. Each sector tile shows avg day change % with color intensity (deep green = strong, deep red = weak). Click sector tile to filter table to that sector.
- **Impact**: High | **Effort**: Medium

### ENH-09: Bulk Actions Toolbar
- **Description**: When users select multiple stocks via checkboxes, show floating toolbar: 🗑️ Remove Selected, 📋 Move to Another Watchlist, 📊 Compare Selected, 🔄 Refresh Selected.
- **Impact**: High | **Effort**: Medium

### ENH-10: Historical Watchlist Performance Chart
- **Description**: Track overall watchlist performance over time. Calculate "watchlist index" (equal-weight avg of all constituent returns since added dates). Show sparkline/mini area chart in telemetry grid. Compare vs Nifty 50 benchmark.
- **Impact**: High | **Effort**: Medium

---

## 🥉 Enhancement Backlog — Tier 3 (Premium Features, P2/P3)

### ENH-11: AI "What to Buy Next" Recommendation Engine
- **Description**: Based on watchlist composition, suggest 3-5 complementary stocks using sector diversification gaps + DVM signal strengths. Display as "🤖 AI Suggests" card below watchlist table.
- **Impact**: High | **Effort**: High | **Priority**: P2

### ENH-12: Earnings Calendar Integration
- **Description**: Show next earnings/results date per watchlist stock. Add "📅 Upcoming Earnings" filter chip for stocks reporting in next 7-14 days. Visual badge (e.g., "Results in 3 days") on stock row.
- **Impact**: Medium | **Effort**: High | **Priority**: P2

### ENH-13: Peer Comparison Sparklines
- **Description**: In returns matrix view, add tiny inline sparklines (30-day price trend) next to each stock using Canvas/SVG-based lightweight rendering.
- **Impact**: Medium | **Effort**: Medium | **Priority**: P2

### ENH-14: Watchlist Sharing (URL / QR Code)
- **Description**: Generate shareable URL or QR code for a watchlist (read-only public view). Others can view without modifying.
- **Impact**: Low | **Effort**: High | **Priority**: P3

### ENH-15: Smart Watchlist Templates
- **Description**: Pre-built templates for one-click import: "🏦 Nifty 50 Bluechips", "💊 Pharma & Healthcare", "🏗️ Infrastructure Capex", "💰 High Dividend Yield", "🚀 Small-Cap Multibaggers".
- **Impact**: Medium | **Effort**: Low | **Priority**: P2

---

## 📊 Priority Matrix Summary

| Priority | Enhancement IDs | Description |
|---|---|---|
| **P0** (Do First) | ENH-01, ENH-02, ENH-04, ENH-05 | Target Price/MOS, CSV Export, Inline Notes, Extra Filters |
| **P1** (Next Sprint) | ENH-03, ENH-06, ENH-08, ENH-09, ENH-10 | Drag Reorder, Price Alerts, Sector Heatmap, Bulk Actions, Performance Chart |
| **P2** (Backlog) | ENH-07, ENH-11, ENH-12, ENH-13, ENH-15 | Comparison View, AI Suggestions, Earnings Calendar, Sparklines, Templates |
| **P3** (Future) | ENH-14 | Watchlist Sharing |

---

## 📐 Database Schema Changes Required

```sql
-- ENH-03: Drag Reorder
ALTER TABLE watchlist_items ADD COLUMN sort_order INTEGER DEFAULT 0;

-- ENH-04: Inline Notes
ALTER TABLE watchlist_items ADD COLUMN notes TEXT;

-- ENH-06: Price Alerts
ALTER TABLE watchlist_items ADD COLUMN alert_price_low REAL;
ALTER TABLE watchlist_items ADD COLUMN alert_price_high REAL;
ALTER TABLE watchlist_items ADD COLUMN alert_enabled INTEGER DEFAULT 0;
```

---

> **Last Updated**: 28 Jul, 2026 | **Version**: 1.0
