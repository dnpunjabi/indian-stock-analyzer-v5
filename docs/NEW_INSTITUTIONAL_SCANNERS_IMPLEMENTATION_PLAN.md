# Implementation Plan: 3 New Institutional & Swing Scanners + 4 High-Impact Enhancements

Integrate 3 world-class institutional and swing trading screeners (**Kristjan Qullamaggie Episodic Pivot (EP)**, **Gil Morales & Chris Kacher Pocket Pivot Accumulation**, and **Oliver Kell EMA 10/20 Reversal**) into the **Quant Suite**, backend pre-warm cron engine, SQLite cache, and Watchlist Quant Matrix, complete with 4 user experience & automation enhancements.

---

## 🏛️ Screener Specifications & Quantitative Rules

### 1. 🚀 Kristjan Qullamaggie Episodic Pivot (EP / Catalyst Gap-Up)
- **Goal**: Detect massive fundamental gap-ups on institutional volume surges that signal multi-week re-ratings.
- **Rules**:
  - **Price Gap-Up**: Opening price gap $\ge +8.0\%$ to $+25.0\%$ above previous close.
  - **Institutional Volume Surge**: Relative Volume ($\text{RVOL}$) $\ge 3.0\times$ the 20-day average volume ($\text{Volume} \ge 3.0 \times \text{SMA}_{20}(\text{Volume})$).
  - **Moving Average Baseline**: $\text{Price} > 50\text{-day SMA}$ or $\text{Price} > 200\text{-day SMA}$.
  - **52-Week Range**: Within $35.0\%$ of 52-week High, or breaking out of a multi-month base ($+30\%+$ above 52-week Low).
  - **Status Classification**: `EP_GAP_LIVE` 🚀 (Day 1 Gap Surge), `EP_FLAG_FORMING` 🟡 (1-3 Day Tight Consolidation), `EP_ORB_BREAKOUT` 🟢 (Opening Range High Breakout).

### 2. 🎯 Gil Morales & Chris Kacher Pocket Pivot Accumulation
- **Goal**: Identify stealth institutional accumulation inside a base *before* standard resistance breakout.
- **Rules**:
  - **The Pocket Pivot Volume Signature**:
    $$\text{Volume}_{\text{UpDay}} > \max\left(\text{Volume}_{\text{DownDay, 10d}}\right)$$
    Volume on up-day strictly exceeds the single highest down-day volume over the previous 10 trading days.
  - **Moving Average Touch & Reclaim**: Price within $\le 2.0\%$ distance of $10\,\text{EMA}$, $21\,\text{EMA}$, or $50\,\text{SMA}$.
  - **Stage 2 Trend Alignment**: $\text{Price} > 50\,\text{SMA} \ge 150\,\text{SMA} \ge 200\,\text{SMA}$.
  - **Not Extended Cap**: Price is not extended $>10.0\%$ above its 50-day SMA.
  - **52-Week High Proximity**: Within $20.0\%$ of 52-week High.
  - **Status Classification**: `POCKET_PIVOT_LIVE` 🎯 (Volume Signature Met Today), `POCKET_PIVOT_FORMING` 🟡 (Resting at MA Support with VDU $\le 0.85\times$).

### 3. 📈 Oliver Kell EMA Trend Continuation & 10/20 EMA Reversal
- **Goal**: Capture low-risk trend continuation entries during active Stage 2 momentum runs.
- **Rules**:
  - **MA Stack**: $\text{Price} > 10\,\text{EMA} > 20\,\text{EMA} > 50\,\text{SMA} > 200\,\text{SMA}$ (all upward sloping over 10 days).
  - **Low-Volume Pullback**: Price pulls back to touch/undercut the $10\,\text{EMA}$ or $20\,\text{EMA}$ on low volume ($\text{VDU} \le 0.85\times$).
  - **Reversal Candle Signal**: Bullish reversal candle (close in top $35\%$ of daily range) or 10/20 EMA cross.
  - **52-Week Leadership**: Within $15.0\%$ of 52-week High and $\ge +40.0\%$ above 52-week Low.
  - **Status Classification**: `KELL_REVERSAL_LIVE` 📈 (Reversal Triggered off 10/20 EMA), `KELL_PULLBACK_TEST` 🟡 (Touching 10/20 EMA on Low Volume VDU).

---

## ⚡ 4 User Experience & System Enhancements

1. **Watchlist Quant Matrix Parity**: Add diagnostic badges (`EP GAP 🚀`, `POCKET 🎯`, `KELL 10/20 📈`) to the Watchlist Stage 1-4 Quant Matrix subtab.
2. **4-Layer Midnight Cron Pre-Warming**: Integrate all 3 new screeners into the 1:30 AM pre-warm sweep, `/api/system/cron-status` API, and Nightly Summary WhatsApp Alert.
3. **Collapsible Strategy Banners**: Add strategy guide cards above each screener table detailing the trader's philosophy, entry triggers, stop-loss rules, and target risk-reward ratios.
4. **Action Column Direct Links**: Add `Chart ↗` (TradingView live chart with 10/20 EMA overlays) and `Simulate ⚙️` (Stage Simulator) buttons to every row.

---

## 🛠️ Proposed Changes

### [Backend Component]

#### [MODIFY] [backend/swing_utils.py](file:///c:/Users/dheer/Desktop/AI/indian-stock-analyzer%20-%205.0/backend/swing_utils.py)
- Implement `detect_episodic_pivot(df)`
- Implement `detect_pocket_pivot(df)`
- Implement `detect_oliver_kell_reversal(df)`

#### [MODIFY] [backend/main.py](file:///c:/Users/dheer/Desktop/AI/indian-stock-analyzer%20-%205.0/backend/main.py)
- Update `screener_results_cache` SQLite table support for screener keys `'episodic_pivot'`, `'pocket_pivot'`, `'oliver_kell_reversal'`.
- Update `prewarm_screener_results()` and `_recalculate_vcp_universe()` to calculate all 3 screeners during the 1:30 AM midnight cron.
- Update `send_quant_cron_whatsapp_summary()` to include stock counts for the 3 new screeners.
- Add API endpoints:
  - `GET /api/screener/episodic-pivot`
  - `GET /api/screener/pocket-pivot`
  - `GET /api/screener/oliver-kell`

---

### [Frontend Component]

#### [MODIFY] [backend/static/index.html](file:///c:/Users/dheer/Desktop/AI/indian-stock-analyzer%20-%205.0/backend/static/index.html)
- Add subtab buttons in Quant Suite subnav (`tab-episodicpivot-btn`, `tab-pocketpivot-btn`, `tab-oliverkell-btn`).
- Add 3 strategy guide hero headers, KPI summary cards, and data tables in Quant Suite tab.
- Add diagnostic columns to Watchlist Quant Matrix table.

#### [MODIFY] [backend/static/app.js](file:///c:/Users/dheer/Desktop/AI/indian-stock-analyzer%20-%205.0/backend/static/app.js)
- Add table renderers: `renderEpisodicPivotTable()`, `renderPocketPivotTable()`, `renderOliverKellTable()`.
- Add API fetch handlers.
- Update Watchlist matrix renderer to display badges for the 3 new screeners.

#### [MODIFY] [backend/static/modernizer.css](file:///c:/Users/dheer/Desktop/AI/indian-stock-analyzer%20-%205.0/backend/static/modernizer.css)
- Add status badge styling (`badge-quant-purple`, `badge-quant-cyan`, `badge-quant-indigo`).
- Enforce responsive sticky symbol column alignment for mobile devices.

---

## 🧪 Verification Plan

### Automated Tests
- Create `tests/test_new_scanners.py` to verify detection logic, edge cases, and wave thresholds.

### Manual Verification
- Verify response times of all 3 API endpoints (<45ms from SQLite cache).
- Verify pre-warming via `/api/system/cron-status` endpoint.
- Verify mobile app layout alignment on screen sizes from 360px to 412px.
