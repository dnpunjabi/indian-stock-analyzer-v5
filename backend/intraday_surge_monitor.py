"""
backend/intraday_surge_monitor.py — Real-Time Intraday Volatility & Volume Breakout Radar

Monitors user portfolio holdings and active watchlists during market hours (09:15 to 15:30 IST).
Detects sudden intraday price spikes (>= +/-3.5%), volume shockers (> 2.0x avg vol),
and dispatches high-priority WhatsApp alerts with position-aware P&L context.
"""

import os
import logging
from datetime import datetime, date, time
from typing import Optional, Dict, Any, List, Set, Tuple
import pytz
import pandas as pd
import yfinance as yf

logger = logging.getLogger("intraday_surge_monitor")

IST = pytz.timezone("Asia/Kolkata")

def _get_db():
    from backend.main import get_db
    return get_db()


def init_intraday_surge_db() -> None:
    """Initializes the intraday surge alert history table."""
    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS intraday_surge_alert_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    day_change_pct REAL NOT NULL,
                    volume_ratio REAL,
                    dispatched_at TEXT DEFAULT (datetime('now', 'localtime')),
                    UNIQUE(symbol, trade_date, alert_type)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_surge_lookup 
                ON intraday_surge_alert_history(trade_date, symbol, alert_type)
            """)
            conn.commit()
    except Exception as e:
        logger.error(f"Error initializing intraday_surge_alert_history: {e}", exc_info=True)


def is_indian_market_open() -> bool:
    """Checks whether the Indian stock market (NSE/BSE) is currently open."""
    now_ist = datetime.now(IST)
    # Check weekday (0=Mon, 4=Fri)
    if now_ist.weekday() >= 5:
        return False
    current_time = now_ist.time()
    market_open = time(9, 15)
    market_close = time(15, 30)
    return market_open <= current_time <= market_close


def get_monitored_universe() -> Dict[str, Dict[str, Any]]:
    """
    Gathers active portfolio holdings and primary watchlist items.
    Focuses strictly on user's high-stakes positions to ensure high signal & fast scans (<2s).
    """
    universe: Dict[str, Dict[str, Any]] = {}
    from backend.daily_wrapup import compute_active_holdings, normalize_symbol
    from backend.whatsapp_bot import get_primary_watchlist_id

    # 1. Active Portfolio Holdings
    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, symbol, name, quantity, purchase_price, transaction_type
                FROM portfolio_items
            """)
            txs = [dict(r) for r in cursor.fetchall()]
            active = compute_active_holdings(txs)
            for h in active:
                clean = normalize_symbol(h["symbol"]).replace(".NS", "").replace(".BO", "")
                universe[clean] = {
                    "is_portfolio": True,
                    "qty": float(h.get("quantity") or 0.0),
                    "avg_price": float(h.get("purchase_price") or 0.0),
                    "name": h.get("name", clean),
                    "is_watchlist": False
                }
    except Exception as e:
        logger.error(f"Error loading portfolio holdings for surge monitor: {e}")

    # 2. Primary Watchlist Items
    try:
        primary_wl_id = get_primary_watchlist_id()
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT symbol FROM watchlist_items 
                WHERE watchlist_id = ?
            """, (primary_wl_id,))
            for r in cursor.fetchall():
                clean = normalize_symbol(r["symbol"]).replace(".NS", "").replace(".BO", "")
                if clean not in universe:
                    universe[clean] = {
                        "is_portfolio": False,
                        "qty": 0,
                        "avg_price": 0.0,
                        "name": clean,
                        "is_watchlist": True
                    }
                else:
                    universe[clean]["is_watchlist"] = True
    except Exception as e:
        logger.error(f"Error loading primary watchlist for surge monitor: {e}")

    return universe


def has_alerted_today(symbol: str, alert_type: str, today_str: Optional[str] = None) -> bool:
    """Checks whether an alert of this type was already sent today for this symbol."""
    t_date = today_str or datetime.now(IST).strftime("%Y-%m-%d")
    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id FROM intraday_surge_alert_history
                WHERE symbol = ? AND trade_date = ? AND alert_type = ?
            """, (symbol, t_date, alert_type))
            return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Error checking alert history: {e}")
        return False


def record_surge_alert(symbol: str, alert_type: str, day_change_pct: float, volume_ratio: float) -> None:
    """Records that an alert was dispatched to prevent duplicates."""
    t_date = datetime.now(IST).strftime("%Y-%m-%d")
    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO intraday_surge_alert_history 
                (symbol, trade_date, alert_type, day_change_pct, volume_ratio)
                VALUES (?, ?, ?, ?, ?)
            """, (symbol, t_date, alert_type, day_change_pct, volume_ratio))
            conn.commit()
    except Exception as e:
        logger.error(f"Error recording surge alert: {e}")


def scan_intraday_volatility(force: bool = False) -> List[Dict[str, Any]]:
    """
    Scans portfolio and watchlist universe for abnormal intraday moves or volume surges.
    Dispatches WhatsApp notifications for newly triggered events.
    """
    init_intraday_surge_db()
    from backend.whatsapp_bot import send_whatsapp_interactive_buttons

    if not force and not is_indian_market_open():
        logger.info("Market is closed. Skipping intraday surge scan.")
        return []

    universe = get_monitored_universe()
    if not universe:
        logger.info("No active holdings or watchlist items to monitor.")
        return []

    symbols = list(universe.keys())
    yf_tickers = [f"{s}.NS" for s in symbols]
    triggered = []
    today_str = datetime.now(IST).strftime("%Y-%m-%d")

    try:
        # Fetch 5-day daily bars to calculate current move and 10-day volume average
        df = yf.download(yf_tickers, period="15d", interval="1d", progress=False)
        if df.empty:
            return []

        is_multi = isinstance(df.columns, pd.MultiIndex)

        for sym in symbols:
            yf_sym = f"{sym}.NS"
            try:
                if is_multi:
                    closes = df['Close'][yf_sym].dropna()
                    vols = df['Volume'][yf_sym].dropna()
                else:
                    closes = df['Close'].dropna()
                    vols = df['Volume'].dropna()

                if len(closes) < 2:
                    continue

                curr_p = float(closes.iloc[-1])
                prev_p = float(closes.iloc[-2])
                if prev_p <= 0:
                    continue

                day_chg_pct = ((curr_p - prev_p) / prev_p) * 100.0
                day_chg_pts = curr_p - prev_p

                # Volume Surge calculation
                curr_vol = float(vols.iloc[-1]) if len(vols) >= 1 else 0.0
                hist_vol_slice = vols.iloc[:-1]
                avg_vol = float(hist_vol_slice.tail(10).mean()) if len(hist_vol_slice) > 0 else 0.0
                vol_ratio = (curr_vol / avg_vol) if avg_vol > 0 else 1.0

                # Determine trigger conditions:
                # 1. Strong Bullish Surge: >= +3.5%
                # 2. Heavy Bearish Drop: <= -3.5%
                # 3. Volume Breakout: vol >= 2.2x avg AND abs(day_chg_pct) >= 1.5%
                alert_type = None
                if day_chg_pct >= 3.5:
                    alert_type = "SURGE_GAIN"
                elif day_chg_pct <= -3.5:
                    alert_type = "SURGE_DROP"
                elif vol_ratio >= 2.2 and abs(day_chg_pct) >= 1.5:
                    alert_type = "VOLUME_BREAKOUT"

                if not alert_type:
                    continue

                if has_alerted_today(sym, alert_type, today_str):
                    continue

                # Prepare rich notification
                u_info = universe[sym]
                is_port = u_info["is_portfolio"]
                qty = u_info.get("qty", 0)
                avg_p = u_info.get("avg_price", 0.0)
                name = u_info.get("name", sym)

                tag = "💼 *[PORTFOLIO]*" if is_port else "👀 *[WATCHLIST]*"
                pnl_line = ""
                if is_port and qty > 0 and avg_p > 0:
                    unrealized_pnl = (curr_p - avg_p) * qty
                    unrealized_pct = ((curr_p - avg_p) / avg_p) * 100.0
                    pnl_sign = "+" if unrealized_pnl >= 0 else "-"
                    pnl_color = "🟢" if unrealized_pnl >= 0 else "🔴"
                    pnl_line = (
                        f"💼 *Position*: {qty} Qty @ ₹{avg_p:,.1f}\n"
                        f"{pnl_color} *Total P&L*: {pnl_sign}₹{abs(unrealized_pnl):,.0f} ({'+' if unrealized_pct >= 0 else ''}{unrealized_pct:.2f}%)\n"
                    )

                if alert_type == "SURGE_GAIN":
                    headline = f"🚀 *INTRADAY SURGE ALERT* (+{day_chg_pct:.2f}%)"
                    tone_desc = f"Surging *+{day_chg_pct:.2f}%* (+₹{day_chg_pts:,.2f}) with heavy intraday demand!"
                elif alert_type == "SURGE_DROP":
                    headline = f"⚠️ *INTRADAY DROP ALERT* ({day_chg_pct:.2f}%)"
                    tone_desc = f"Slipping *{day_chg_pct:.2f}%* (-₹{abs(day_chg_pts):,.2f}). Watch key support levels."
                else:
                    headline = f"📦 *UNUSUAL VOLUME BREAKOUT* ({vol_ratio:.1f}x Avg)"
                    sign = "+" if day_chg_pct >= 0 else ""
                    tone_desc = f"Trading at *{vol_ratio:.1f}x* 10-day average volume ({sign}{day_chg_pct:.2f}% intraday move)!"

                body = (
                    f"{headline}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"{tag} *{name}* (`{sym}`)\n"
                    f"⚡ *Live Price*: *₹ {curr_p:,.2f}* ({'+' if day_chg_pct >= 0 else ''}{day_chg_pct:.2f}%)\n"
                    f"📊 *Volume*: *{vol_ratio:.1f}x* 10-day avg volume\n"
                    f"{pnl_line}"
                    f"💡 *Update*: {tone_desc}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"_ApexQuant Real-Time Market Sentinel • {datetime.now(IST).strftime('%H:%M IST')}_"
                )

                buttons = [
                    (f"act:chart:{sym}", "📈 Live Chart"),
                    (f"view:stock:{sym}", "📊 Stock Dossier"),
                    ("view:portfolio", "💼 Portfolio")
                ]

                send_whatsapp_interactive_buttons(body, buttons=buttons)
                record_surge_alert(sym, alert_type, day_chg_pct, vol_ratio)
                logger.info(f"Dispatched {alert_type} WhatsApp alert for {sym} ({day_chg_pct:.2f}%)")

                triggered.append({
                    "symbol": sym,
                    "name": name,
                    "alert_type": alert_type,
                    "price": curr_p,
                    "change_pct": day_chg_pct,
                    "volume_ratio": vol_ratio,
                    "is_portfolio": is_port
                })

            except Exception as item_err:
                logger.warning(f"Error evaluating intraday surge for {sym}: {item_err}")

    except Exception as e:
        logger.error(f"Error running intraday volatility scan: {e}", exc_info=True)

    return triggered


async def run_background_intraday_surge_scheduler():
    """
    Runs every 10 minutes during market hours (09:20 - 15:30 IST) on weekdays.
    Sweeps active portfolio and watchlist items for abnormal volatility.
    """
    import asyncio
    logger.info("Starting background Intraday Surge & Volatility Monitor...")
    while True:
        try:
            if is_indian_market_open():
                await asyncio.to_thread(scan_intraday_volatility, False)
        except Exception as e:
            logger.error(f"Error in background intraday surge loop: {e}", exc_info=True)
        await asyncio.sleep(600)  # Sweep every 10 minutes
