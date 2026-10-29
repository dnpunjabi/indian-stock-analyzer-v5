"""
backend/whatsapp_alerts.py — Real-Time Smart Price & Stop-Loss Alerts Engine

Provides chat-based price alert setup, active alert tracking, and automated
market-hours price trigger evaluation with instant WhatsApp push notifications.
"""

import os
import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import yfinance as yf

logger = logging.getLogger("whatsapp_alerts")

# Database connection helper
def _get_db():
    from backend.main import get_db
    return get_db()


def init_whatsapp_alerts_db() -> None:
    """Creates the whatsapp_price_alerts table if it does not already exist."""
    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS whatsapp_price_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_phone TEXT,
                    symbol TEXT NOT NULL,
                    company_name TEXT,
                    condition TEXT NOT NULL,
                    target_price REAL NOT NULL,
                    initial_price REAL NOT NULL,
                    note TEXT,
                    is_active INTEGER DEFAULT 1,
                    is_triggered INTEGER DEFAULT 0,
                    triggered_at TEXT,
                    triggered_price REAL,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_whatsapp_alerts_active 
                ON whatsapp_price_alerts(is_active, is_triggered)
            """)
            conn.commit()
            logger.info("Initialized whatsapp_price_alerts SQLite table successfully.")
    except Exception as e:
        logger.error(f"Error initializing whatsapp_price_alerts table: {e}", exc_info=True)


def parse_price_alert_command(cmd_text: str) -> Optional[Dict[str, Any]]:
    """
    Parses user natural language or structured commands:
    - ALERT INFY > 1950 (or ABOVE 1950)
    - ALERT INFY < 1850 (or BELOW 1850)
    - SL TCS 3900 (or STOPLOSS TCS 3900)
    - TARGET TATAMOTORS 1100 (or TGT TATAMOTORS 1100)
    - Optional note trailing: 'note: Breakout entry' or 'trailing SL'
    """
    raw = (cmd_text or "").strip()
    upper = raw.upper()

    # Pattern 1: SL / STOPLOSS <SYM> [AT/<=/<] <PRICE> [NOTE]
    m_sl = re.match(
        r"^(?:SL|STOPLOSS|STOP\s+LOSS)\s+([A-Za-z0-9\.\-_]+)(?:\s+(?:AT|<=|<))?\s+([0-9]+(?:\.[0-9]+)?)(?:\s+(?:NOTE:?|MSG:?|REASON:?)?\s*(.*))?$",
        raw, re.IGNORECASE
    )
    if m_sl:
        sym = m_sl.group(1).upper()
        price = float(m_sl.group(2))
        note = (m_sl.group(3) or "").strip() or "Stop-Loss Level"
        return {"symbol": sym, "condition": "BELOW", "target_price": price, "note": note}

    # Pattern 2: TARGET / TGT <SYM> [AT/>=/>] <PRICE> [NOTE]
    m_tgt = re.match(
        r"^(?:TARGET|TGT)\s+([A-Za-z0-9\.\-_]+)(?:\s+(?:AT|>=|>))?\s+([0-9]+(?:\.[0-9]+)?)(?:\s+(?:NOTE:?|MSG:?|REASON:?)?\s*(.*))?$",
        raw, re.IGNORECASE
    )
    if m_tgt:
        sym = m_tgt.group(1).upper()
        price = float(m_tgt.group(2))
        note = (m_tgt.group(3) or "").strip() or "Profit Target"
        return {"symbol": sym, "condition": "ABOVE", "target_price": price, "note": note}

    # Pattern 3: ALERT <SYM> (>|>=|ABOVE|<|<=|BELOW) <PRICE> [NOTE]
    m_alert = re.match(
        r"^(?:ALERT\s+)?([A-Za-z0-9\.\-_]+)\s*(>|>=|ABOVE|<|<=|BELOW)\s*([0-9]+(?:\.[0-9]+)?)(?:\s+(?:NOTE:?|MSG:?|REASON:?)?\s*(.*))?$",
        raw, re.IGNORECASE
    )
    if m_alert:
        sym = m_alert.group(1).upper()
        op = m_alert.group(2).upper()
        price = float(m_alert.group(3))
        note = (m_alert.group(4) or "").strip()
        cond = "ABOVE" if op in [">", ">=", "ABOVE"] else "BELOW"
        return {"symbol": sym, "condition": cond, "target_price": price, "note": note}

    return None


def create_price_alert(
    symbol_input: str,
    condition: str,
    target_price: float,
    note: str = "",
    user_phone: Optional[str] = None
) -> Tuple[bool, str, Optional[int]]:
    """
    Validates and stores a new price alert in the database.
    Returns (success, user_friendly_message, alert_id).
    """
    init_whatsapp_alerts_db()
    from backend.whatsapp_bot import resolve_company_ticker, get_stock_ground_truth

    resolved = resolve_company_ticker(symbol_input)
    if isinstance(resolved, dict):
        clean_sym = (resolved.get("base_symbol") or resolved.get("symbol") or symbol_input).strip().upper().replace(".NS", "").replace(".BO", "")
        comp_name = resolved.get("name") or clean_sym
    elif isinstance(resolved, str):
        clean_sym = resolved.strip().upper().replace(".NS", "").replace(".BO", "")
        comp_name = clean_sym
    else:
        clean_sym = symbol_input.strip().upper().replace(".NS", "").replace(".BO", "")
        comp_name = clean_sym

    # Fetch verified ground truth
    stock_info = get_stock_ground_truth(clean_sym)
    comp_name = stock_info.get("name", comp_name)
    curr_ltp = float(stock_info.get("ltp", 0.0))

    if curr_ltp <= 0:
        return False, f"⚠️ Unable to fetch live price for *{clean_sym}*. Please verify the ticker symbol.", None

    cond_upper = "ABOVE" if condition.upper() in [">", ">=", "ABOVE"] else "BELOW"

    # Sanity checks on target vs current price
    if cond_upper == "ABOVE" and target_price <= curr_ltp:
        pct_diff = ((curr_ltp - target_price) / target_price) * 100
        return False, (
            f"⚠️ *Target already reached!*\n"
            f"*{clean_sym}* is currently trading at *₹ {curr_ltp:,.2f}*, which is already above your target *₹ {target_price:,.2f}* (+{pct_diff:.2f}%)."
        ), None

    if cond_upper == "BELOW" and target_price >= curr_ltp:
        pct_diff = ((target_price - curr_ltp) / curr_ltp) * 100
        return False, (
            f"⚠️ *Stop-loss already breached!*\n"
            f"*{clean_sym}* is currently trading at *₹ {curr_ltp:,.2f}*, which is already below your stop *₹ {target_price:,.2f}* (-{pct_diff:.2f}%)."
        ), None

    phone = user_phone or os.environ.get("WHATSAPP_RECIPIENT", "")
    alert_id = None

    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO whatsapp_price_alerts 
                (user_phone, symbol, company_name, condition, target_price, initial_price, note, is_active, is_triggered)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)
            """, (phone, clean_sym, comp_name, cond_upper, target_price, curr_ltp, note))
            conn.commit()
            alert_id = cursor.lastrowid
    except Exception as e:
        logger.error(f"Error creating price alert: {e}", exc_info=True)
        return False, f"⚠️ Database error creating alert: {e}", None

    cond_icon = "🟢" if cond_upper == "ABOVE" else "🛑"
    cond_desc = "Take-Profit Target" if cond_upper == "ABOVE" else "Stop-Loss Floor"
    
    if cond_upper == "ABOVE":
        move_pct = ((target_price - curr_ltp) / curr_ltp) * 100.0
        move_desc = f"+{move_pct:.2f}% move required"
    else:
        buffer_pct = ((curr_ltp - target_price) / curr_ltp) * 100.0
        move_desc = f"{buffer_pct:.2f}% downside buffer"

    note_line = f"📝 *Note*: _{note}_\n" if note else ""

    confirm_msg = (
        f"🔔 *PRICE ALERT ARMED* (Alert #{alert_id})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 *{comp_name}* (`{clean_sym}`)\n"
        f"{cond_icon} *Condition*: {cond_desc} *{cond_upper} ₹ {target_price:,.2f}*\n"
        f"⚡ *Current LTP*: ₹ {curr_ltp:,.2f} ({move_desc})\n"
        f"{note_line}"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_ApexQuant will push an instant WhatsApp alert the second price crosses ₹ {target_price:,.2f}!_"
    )

    return True, confirm_msg, alert_id


def list_active_price_alerts(user_phone: Optional[str] = None) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Returns a formatted summary of all pending active price alerts,
    along with the raw alert dicts for interactive button generation.
    """
    init_whatsapp_alerts_db()
    from backend.whatsapp_bot import get_stock_ground_truth

    phone = user_phone or os.environ.get("WHATSAPP_RECIPIENT", "")
    alerts = []

    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, symbol, company_name, condition, target_price, initial_price, note, created_at
                FROM whatsapp_price_alerts
                WHERE is_active = 1 AND is_triggered = 0
                ORDER BY created_at DESC
            """)
            alerts = [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error listing alerts: {e}", exc_info=True)
        return f"⚠️ Error fetching alerts: {e}", []

    if not alerts:
        msg = (
            "🔔 *PRICE ALERTS HUB*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "You have *no active price alerts* right now.\n\n"
            "💡 *How to set an alert in chat:*\n"
            "• `ALERT INFY > 1950` (Target)\n"
            "• `SL TCS 3900` (Stop-Loss)\n"
            "• `TARGET TATAMOTORS 1100`\n"
            "• `ALERT BOSCHLTD < 34000 note: Key Support`\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "_Real-time monitoring active 24/7._"
        )
        return msg, []

    # Format list with live LTP and distance %
    lines = [
        "🔔 *ACTIVE PRICE ALERTS*",
        f"Total Active Triggers: *{len(alerts)}*",
        "━━━━━━━━━━━━━━━━━━━━"
    ]

    for a in alerts:
        sym = a["symbol"]
        cond = a["condition"]
        tgt = a["target_price"]
        aid = a["id"]
        note = a.get("note") or ""

        info = get_stock_ground_truth(sym)
        ltp = float(info.get("ltp", 0.0))

        icon = "🟢" if cond == "ABOVE" else "🛑"
        if ltp > 0:
            if cond == "ABOVE":
                dist_pct = ((tgt - ltp) / ltp) * 100.0
                dist_str = f"LTP ₹{ltp:,.1f} • {dist_pct:+.1f}% to hit"
            else:
                dist_pct = ((ltp - tgt) / ltp) * 100.0
                dist_str = f"LTP ₹{ltp:,.1f} • {dist_pct:.1f}% buffer"
        else:
            dist_str = f"Target: ₹{tgt:,.2f}"

        note_tag = f" — _{note}_" if note else ""
        lines.append(f"{icon} *#{aid}* *{sym}*: {cond} *₹ {tgt:,.1f}* ({dist_str}){note_tag}")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("🗑️ _To cancel an alert, text `CANCEL ALERT <ID>` (e.g. `CANCEL ALERT 1`)_")

    return "\n".join(lines), alerts


def cancel_price_alert(alert_id: int, user_phone: Optional[str] = None) -> Tuple[bool, str]:
    """Deactivates a price alert by ID."""
    init_whatsapp_alerts_db()
    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, target_price, condition FROM whatsapp_price_alerts WHERE id = ? AND is_active = 1", (alert_id,))
            row = cursor.fetchone()
            if not row:
                return False, f"⚠️ Active Alert *#{alert_id}* not found or already cancelled."

            sym = row["symbol"]
            tgt = row["target_price"]
            cond = row["condition"]

            cursor.execute("UPDATE whatsapp_price_alerts SET is_active = 0 WHERE id = ?", (alert_id,))
            conn.commit()

            return True, f"✅ Cancelled Alert *#{alert_id}*: *{sym}* ({cond} ₹ {tgt:,.2f})."
    except Exception as e:
        logger.error(f"Error cancelling alert #{alert_id}: {e}", exc_info=True)
        return False, f"⚠️ Database error cancelling alert: {e}"


def evaluate_price_alerts_sweep() -> List[Dict[str, Any]]:
    """
    Evaluates all active price alerts against live quotes.
    Triggered alerts dispatch high-visibility WhatsApp notifications and are marked triggered.
    Returns list of triggered alert dictionaries.
    """
    init_whatsapp_alerts_db()
    from backend.whatsapp_bot import send_whatsapp_interactive_buttons, get_stock_ground_truth

    triggered = []
    alerts = []

    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, user_phone, symbol, company_name, condition, target_price, initial_price, note
                FROM whatsapp_price_alerts
                WHERE is_active = 1 AND is_triggered = 0
            """)
            alerts = [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching active alerts for sweep: {e}", exc_info=True)
        return []

    if not alerts:
        return []

    # Distinct symbols to check
    sym_set = {a["symbol"] for a in alerts}
    prices: Dict[str, float] = {}

    for s in sym_set:
        try:
            info = get_stock_ground_truth(s)
            p = float(info.get("ltp", 0.0))
            if p > 0:
                prices[s] = p
        except Exception as e:
            logger.warning(f"Error getting price for {s} in alert sweep: {e}")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for a in alerts:
        sym = a["symbol"]
        if sym not in prices:
            continue

        curr_p = prices[sym]
        cond = a["condition"]
        tgt = a["target_price"]
        aid = a["id"]
        init_p = a["initial_price"]
        note = a.get("note") or ""
        phone = a.get("user_phone") or os.environ.get("WHATSAPP_RECIPIENT", "")

        is_hit = False
        if cond == "ABOVE" and curr_p >= tgt:
            is_hit = True
        elif cond == "BELOW" and curr_p <= tgt:
            is_hit = True

        if is_hit:
            # Mark triggered in DB
            try:
                with _get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE whatsapp_price_alerts
                        SET is_triggered = 1, triggered_at = ?, triggered_price = ?
                        WHERE id = ?
                    """, (now_str, curr_p, aid))
                    conn.commit()
            except Exception as up_err:
                logger.error(f"Error marking alert #{aid} triggered: {up_err}")

            # Send high-urgency push
            c_name = a.get("company_name", sym)
            icon = "🎯 [TARGET HIT]" if cond == "ABOVE" else "🚨 [STOP-LOSS BREACHED]"
            header_color = "🟢" if cond == "ABOVE" else "🔴"
            move_from_init = ((curr_p - init_p) / init_p) * 100.0 if init_p > 0 else 0.0
            sign = "+" if move_from_init >= 0 else ""

            note_block = f"📝 *Note*: _{note}_\n" if note else ""

            body = (
                f"{header_color} *PRICE ALERT TRIGGERED!* {icon}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 *{c_name}* (`{sym}`)\n"
                f"⚡ *Current Price*: *₹ {curr_p:,.2f}*\n"
                f"🎯 *Trigger Condition*: {cond} *₹ {tgt:,.2f}*\n"
                f"📊 *Net Move from Setup*: {sign}{move_from_init:.2f}%\n"
                f"{note_block}"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"_Triggered at {datetime.now().strftime('%d %b • %H:%M IST')}_"
            )

            buttons = [
                (f"view:stock:{sym}", "📊 View Stock"),
                (f"act:chart:{sym}", "📈 Live Chart"),
                ("view:alerts", "📋 My Alerts")
            ]

            send_whatsapp_interactive_buttons(body, buttons=buttons, recipient=phone)
            logger.info(f"Triggered and dispatched WhatsApp alert #{aid} for {sym} at {curr_p}")
            triggered.append({**a, "triggered_price": curr_p, "triggered_at": now_str})

    return triggered


async def run_background_price_alert_checker():
    """
    Background worker sweeping every 60 seconds during market hours
    to evaluate pending price alerts and dispatch push notifications.
    """
    import asyncio
    logger.info("Starting background WhatsApp price alert evaluator loop...")
    while True:
        try:
            # Run alert sweep in worker thread
            await asyncio.to_thread(evaluate_price_alerts_sweep)
        except Exception as e:
            logger.error(f"Error in price alert checker loop: {e}", exc_info=True)
        await asyncio.sleep(60)
