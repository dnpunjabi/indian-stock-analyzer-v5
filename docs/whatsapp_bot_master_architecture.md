# ApexQuant • 10-Pillar WhatsApp Terminal Architecture

The ApexQuant WhatsApp Bot has been upgraded from a static text terminal into an institutional **Interactive Mobile Terminal** using native Meta WhatsApp Cloud API components (Lists, Action Buttons, and Headless Technical Charts).

---

## 1. Master Navigation Hierarchy

```
┌────────────────────────────────────────────────────────┐
│ 📋 APEXQUANT MASTER TERMINAL                           │
├────────────────────────────────────────────────────────┤
│ 1. 🎯 Quant Screeners     (12+ Strategies in 3 Families)│
│ 2. ⚡ Technical Scans     (14 Scans in 3 Scan Clusters)│
│ 3. 🚀 Market Movers       (Large, Mid & Small Cap)     │
│ 4. 🧭 Sector Radar        (Relative Strength Rotation) │
│ 5. 🔔 Active Alerts       (52 Triggers & Alert Logs)   │
│ 6. 💼 Portfolio Health    (Valuation, P&L & Allocation)│
│ 7. 📰 Financial News      (Macro, Portfolio & Catalysts│
│ 8. 🌐 Market Pulse        (Nifty 50, VIX & Breadth)    │
│ 9. 📌 Stock Query & Chart (Dossier & 6M Dark Chart PNG)│
│ 10. 📝 Log Trade          (1-Tap BUY/SELL Order Journal│
└────────────────────────────────────────────────────────┘
```

---

## 2. Interactive Components & Payload Registry

### A. Level 0: Main Menu (`nav:menu:main`)
* **Trigger**: Reply `MENU`, `HELP`, `HI`, or tap `[ 🏠 Main Menu ]`.
* **Dispatches**: A native bottom-sheet drawer with all 9 core institutional domains.
* **Sticky Quick Buttons**: `[ 🚀 Instant VCP ]` `[ 💼 Portfolio ]` `[ 🌐 Market Pulse ]`.

---

### B. Level 1: Submenus & Clusters

| Submenu Key | Label | Items / Content |
| :--- | :--- | :--- |
| `nav:sub:screeners` | **Quant Screeners Vault** | • 🚀 Breakout Models (4)<br>• 📈 Stage & Trend (4)<br>• ⚡ Reversals & Volume (4) |
| `nav:sub:scans` | **14 Technical Scans** | • 🔥 Volume & Breakouts (5)<br>• 📉 Pullbacks & Supports (5)<br>• 🎯 RSI & Extremes (4) |
| `nav:sub:movers` | **Market Movers** | • 🐘 Large Cap Leaders<br>• 🐎 Mid Cap Leaders<br>• 🐇 Small Cap Leaders |
| `view:sector_radar`| **Sector Radar** | • Top 3 Leading Sectors (1M Return)<br>• Top 2 Lagging Sectors |
| `view:alerts` | **Active Alerts Hub** | • Active Triggers Count (52)<br>• Recently Triggered Breaches |
| `nav:sub:news` | **Financial News Feeds** | • 🌐 Macro Market News<br>• 💼 Portfolio News & Catalysts |
| `view:portfolio` | **Portfolio Health** | • Net Valuation, Today's P&L, Top Gainer & Laggard |
| `view:pulse` | **Market Pulse** | • Nifty 50, Bank Nifty, India VIX, Market Breadth |
| `nav:sub:trade` | **Log Trade Journal** | • Syntax guidance & 1-tap example order chips |

---

## 3. The 14 Technical Scans from UI

1. **Volume & Breakout Cluster**:
   * `run:scan:near_high`: Stocks within 3% of 52-Week High.
   * `run:scan:volume_shockers`: Volume > 2.5x 20-day Average.
   * `run:scan:delivery_shockers`: Institutional Delivery Volume > 65%.
   * `run:scan:gap_up`: Gap-up > 1.5% at open.
   * `run:scan:golden_crossover`: SMA 50 crossing above SMA 200.

2. **Pullback & Support Cluster**:
   * `run:scan:sma_50_pullback`: Testing rising 50-day SMA.
   * `run:scan:sma_100_pullback`: Support test at 100-day SMA.
   * `run:scan:sma_200_pullback`: Institutional 200-day baseline test.
   * `run:scan:fib_618_support`: Golden ratio 61.8% Fibonacci retracement.
   * `run:scan:fib_500_support`: Benchmark 50.0% Fibonacci retracement.

3. **RSI & Extremes Cluster**:
   * `run:scan:rsi_oversold`: RSI-14 < 35 (Oversold bounce setups).
   * `run:scan:rsi_overbought`: RSI-14 > 70 (Overextended momentum).
   * `run:scan:near_low`: Stocks within 3% of 52-Week Low.
   * `run:scan:gap_down`: Severe gap-down open.

---

## 4. Dual-Mode Flexibility (Touch + Fast-Path Text)

You can navigate 100% by tapping menus and buttons, OR type instant text shortcuts anytime:

| Shortcut | Description |
| :--- | :--- |
| `<SYMBOL>` (e.g. `BOSCH`, `TCS`, `INFY`) | Single-stock valuation dossier with `[ 📈 Chart ]` button. |
| `C <SYMBOL>` or `CHART <SYMBOL>` | Generates & delivers dark-mode 6M technical chart image. |
| `VCP` | Instant Minervini VCP breakout setups. |
| `PF` or `STATUS` | Live portfolio valuation & daily P&L. |
| `MOVERS` | Large, Mid & Small Cap leaders. |
| `SECTOR` | Sector relative strength rankings. |
| `ALERTS` | Active triggers and recent alert history. |
| `NEWS <SYMBOL>` | AI news sentiment & catalyst audit for a stock. |
| `BUY <SYMBOL> <QTY> <PRICE>` | Records purchase order into SQLite database. |

