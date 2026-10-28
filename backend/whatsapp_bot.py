"""
backend/whatsapp_bot.py — Two-Way Interactive WhatsApp Command Terminal

Processes inbound WhatsApp messages and dispatches real-time, institutional-grade
financial intelligence bubbles back to the user's WhatsApp device.

Supported Commands:
- <STOCK_SYMBOL> (e.g. "BOSCH", "RELIANCE", "TCS", "INFY"): Full single-stock quant intelligence.
- "PORTFOLIO" or "STATUS": Active portfolio valuation, today's P&L, leaders & laggards.
- "NIFTY" or "MARKET": Benchmark indices, India VIX, leading & lagging sectors.
- "SHARK": Multi-shark consensus stocks & recent superstar investor entries.
- "HELP": Menu of available terminal commands.
"""

import os
import re
import json
import sqlite3
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

import yfinance as yf
import requests

from backend.main import get_db, compute_active_holdings, resolve_company_ticker
from backend.financial_utils import normalize_symbol
from backend.daily_wrapup import send_whatsapp_wrapup

logger = logging.getLogger("whatsapp_bot")


def format_currency_inr(val: float) -> str:
    """Formats numeric values into Indian Rupee strings with commas."""
    if abs(val) >= 10000000:
        return f"₹ {val / 10000000:.2f} Cr"
    elif abs(val) >= 100000:
        return f"₹ {val / 100000:.2f} L"
    else:
        return f"₹ {val:,.2f}"


def ensure_sandbox_registered(pin: str = "123456") -> Dict[str, Any]:
    """
    Registers the Meta WhatsApp sandbox test number to keep it continuously active.
    Prevents the test phone number from falling into deregistered state (Error 133010)
    or showing 'This person is no longer on WhatsApp' on the client device.
    """
    token = os.environ.get("WHATSAPP_TOKEN", "")
    phone_id = os.environ.get("WHATSAPP_PHONE_ID", "")
    if not token or not phone_id:
        return {"status": "error", "message": "Missing WhatsApp credentials"}

    url = f"https://graph.facebook.com/v21.0/{phone_id}/register"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "pin": pin
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        data = resp.json()
        if resp.status_code == 200 and data.get("success"):
            logger.info("[WHATSAPP SANDBOX] Number registered successfully.")
            return {"status": "success", "registered": True}
        else:
            logger.warning(f"[WHATSAPP SANDBOX] Register failed: {data}")
            return {"status": "error", "response": data}
    except Exception as e:
        logger.error(f"[WHATSAPP SANDBOX] Registration network error: {e}")
        return {"status": "error", "message": str(e)}


def send_sandbox_wake_template(
    template_name: str = "hello_world",
    language_code: str = "en_US",
    recipient: Optional[str] = None
) -> Dict[str, Any]:
    """
    Dispatches a pre-approved template message to the recipient to open
    or refresh the Meta 24-hour service conversation window.
    """
    token = os.environ.get("WHATSAPP_TOKEN", "")
    phone_id = os.environ.get("WHATSAPP_PHONE_ID", "")
    to_phone = recipient or os.environ.get("WHATSAPP_RECIPIENT", "")
    if not token or not phone_id or not to_phone:
        return {"status": "error", "message": "Missing WhatsApp credentials"}

    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": language_code
            }
        }
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        data = resp.json()
        if resp.status_code == 200 and "messages" in data:
            return {"status": "success", "message_id": data["messages"][0]["id"]}
        else:
            return {"status": "error", "response": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def wake_sandbox_session(recipient: Optional[str] = None) -> Dict[str, Any]:
    """
    Complete wake-up sequence for personal WhatsApp sandbox usage:
    1. Re-registers the test number.
    2. Sends 'hello_world' template to open/refresh the 24-hour window.
    3. Dispatches interactive action buttons to start interacting immediately.
    """
    reg_res = ensure_sandbox_registered()
    tmpl_res = send_sandbox_wake_template(recipient=recipient)
    btn_res = send_whatsapp_interactive_buttons(
        "🤖 *ApexQuant Personal Workstation Online*\n"
        "Your private WhatsApp sandbox session is active.\n"
        "Tap a button below or text any stock symbol (e.g. `BOSCH`, `TCS`):",
        buttons=[
            ("btn_portfolio", "💼 Portfolio"),
            ("btn_nifty", "🌐 Market Pulse"),
            ("btn_breakout", "🚀 Breakouts")
        ],
        recipient=recipient
    )
    return {
        "status": "success",
        "registration": reg_res,
        "template": tmpl_res,
        "buttons": btn_res
    }


async def run_background_whatsapp_sandbox_keepalive():
    """
    Background keep-alive loop running periodically to ensure the
    WhatsApp Sandbox test number never deregisters or expires.
    """
    # Immediate registration on startup
    try:
        await asyncio.to_thread(ensure_sandbox_registered)
    except Exception as e:
        logger.warning(f"[WHATSAPP SANDBOX CRON] Startup keep-alive error: {e}")

    while True:
        try:
            # Check every 6 hours
            await asyncio.sleep(21600)
            res = await asyncio.to_thread(ensure_sandbox_registered)
            logger.info(f"[WHATSAPP SANDBOX CRON] Periodic keep-alive status: {res.get('status')}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[WHATSAPP SANDBOX CRON] Keep-alive error: {e}")


def send_whatsapp_interactive_buttons(
    body_text: str,
    buttons: Optional[List[Tuple[str, str]]] = None,
    recipient: Optional[str] = None,
    retry_on_auth_err: bool = True
) -> Dict[str, Any]:
    """
    Dispatches a message with up to 3 clickable quick-reply action buttons via Meta Cloud API.
    buttons: List of (button_id, button_title) tuples. Max title length is 20 characters.
    """
    token = os.environ.get("WHATSAPP_TOKEN", "")
    phone_id = os.environ.get("WHATSAPP_PHONE_ID", "")
    to_phone = recipient or os.environ.get("WHATSAPP_RECIPIENT", "")

    if not token or not phone_id or not to_phone:
        return {"status": "error", "message": "Missing WhatsApp credentials."}

    if not buttons:
        buttons = [
            ("btn_portfolio", "💼 Portfolio"),
            ("btn_nifty", "🌐 Market Pulse"),
            ("btn_breakout", "🚀 Breakouts")
        ]

    action_buttons = []
    for btn_id, btn_title in buttons[:3]:
        action_buttons.append({
            "type": "reply",
            "reply": {
                "id": str(btn_id)[:256],
                "title": str(btn_title)[:20]
            }
        })

    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": body_text
            },
            "action": {
                "buttons": action_buttons
            }
        }
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=12)
        resp_data = resp.json()
        if resp.status_code == 200 and "messages" in resp_data:
            return {"status": "success", "message_id": resp_data["messages"][0]["id"]}
        else:
            err_code = resp_data.get("error", {}).get("code")
            # Auto-heal Error 133010 ("Account not registered")
            if err_code == 133010 and retry_on_auth_err:
                logger.warning("[WHATSAPP BOT] Number not registered (133010). Auto-registering and retrying...")
                ensure_sandbox_registered()
                return send_whatsapp_interactive_buttons(body_text, buttons, recipient, retry_on_auth_err=False)
            # Auto-heal Error 131047 (24h conversation window lapsed)
            elif err_code == 131047 and retry_on_auth_err:
                logger.warning("[WHATSAPP BOT] Conversation window lapsed (131047). Dispatching template wake-up...")
                send_sandbox_wake_template(recipient=to_phone)
                return send_whatsapp_interactive_buttons(body_text, buttons, recipient, retry_on_auth_err=False)

            err = resp_data.get("error", {}).get("message", "Interactive send failed")
            return {"status": "error", "message": f"Meta Button Error: {err}"}
    except Exception as e:
        return {"status": "error", "message": f"Network error sending buttons: {str(e)}"}




def handle_stock_query(symbol_input: str) -> str:
    """
    Handles single-stock queries (e.g. 'BOSCH', 'RELIANCE', 'TCS').
    Fetches fundamental valuation, technical momentum, and Shark Radar badge.
    """
    clean_sym = symbol_input.strip().upper().replace(" ", "")
    resolved = resolve_company_ticker(clean_sym)
    
    lookup_ticker = resolved.get("yf_ticker") if resolved else None
    if not lookup_ticker:
        if not clean_sym.endswith(".NS") and not clean_sym.endswith(".BO"):
            lookup_ticker = f"{clean_sym}.NS"
        else:
            lookup_ticker = clean_sym

    base_sym = resolved.get("base_symbol") if resolved else lookup_ticker.replace(".NS", "").replace(".BO", "")
    company_name = resolved.get("name") if resolved else base_sym

    # 1. Fetch quote and basic technicals via yfinance
    try:
        t = yf.Ticker(lookup_ticker)
        fast_info = t.fast_info
        curr_price = float(fast_info.last_price or 0.0)
        prev_close = float(fast_info.previous_close or curr_price)
        day_chg_pct = ((curr_price - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0
        day_chg_val = curr_price - prev_close
        mcap = float(fast_info.market_cap or 0.0)
        fifty_two_h = float(fast_info.year_high or 0.0)
        fifty_two_l = float(fast_info.year_low or 0.0)
    except Exception as e:
        logger.error(f"yfinance quote failed for {lookup_ticker}: {e}")
        return (
            f"⚠️ *Stock Not Found*: Could not find quote for `{clean_sym}`.\n"
            "Please check the ticker symbol (e.g. `BOSCH`, `RELIANCE`, `TCS`, `INFY`)."
        )

    # 2. Query local cache / Screener database for company name & fundamentals
    company_name = base_sym
    pe_ratio = "N/A"
    roce = "N/A"
    sector = "Equities"
    dcf_fair_val = None
    piotroski = "N/A"

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            # Try cached_profiles
            cursor.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ?", (lookup_ticker,))
            p_row = cursor.fetchone()
            if p_row:
                p_data = json.loads(p_row["profile_json"])
                company_name = p_data.get("company_name", company_name)
                sector = p_data.get("sector", sector)
                pe_ratio = p_data.get("fundamentals", {}).get("pe_ratio", "N/A")
                roce = p_data.get("fundamentals", {}).get("roce_pct", "N/A")
                dcf_fair_val = p_data.get("dcf_model", {}).get("intrinsic_value")
                piotroski = p_data.get("earnings_quality", {}).get("piotroski_score", "N/A")
            else:
                # Try screener_universe
                cursor.execute("SELECT company_name, sector, pe_ratio FROM screener_universe WHERE symbol LIKE ?", (f"{base_sym}%",))
                s_row = cursor.fetchone()
                if s_row:
                    company_name = s_row["company_name"] or company_name
                    sector = s_row["sector"] or sector
                    pe_ratio = f"{s_row['pe_ratio']:.1f}" if s_row["pe_ratio"] else "N/A"
    except Exception as db_err:
        logger.warning(f"DB lookup warning for {base_sym}: {db_err}")

    # 3. Check Shark Radar Presence (Superstar Investors holding this stock)
    shark_mentions = []
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT investor_name, holding_percent, holding_value_cr 
                FROM shark_stock_lookup 
                WHERE symbol = ? OR symbol LIKE ?
                ORDER BY holding_percent DESC LIMIT 3
            """, (base_sym, f"{base_sym}%"))
            shark_rows = cursor.fetchall()
            for sr in shark_rows:
                shark_mentions.append(f"{sr['investor_name']} ({sr['holding_percent']:.1f}%)")
    except Exception:
        pass

    shark_badge = f"🦈 *Superstar Sharks*: {', '.join(shark_mentions)}" if shark_mentions else "🦈 *Smart Money*: No major shark holdings (>1%)"

    # 4. Technical Trend & Sentiment Pill
    chg_emoji = "🟢" if day_chg_pct >= 0 else "🔴"
    chg_sign = "+" if day_chg_pct >= 0 else ""
    
    # Valuation headroom
    dcf_line = ""
    if dcf_fair_val and dcf_fair_val > 0:
        mos = ((dcf_fair_val - curr_price) / dcf_fair_val * 100.0)
        mos_sign = "+" if mos >= 0 else ""
        dcf_line = f"🎯 *DCF Fair Value*: ₹ {dcf_fair_val:,.1f} (MOS: {mos_sign}{mos:.1f}%)\n"

    # 5. Assemble formatted WhatsApp Intelligence Card
    msg = (
        f"📊 *{company_name.upper()}* (`{base_sym}`)\n"
        f"🏢 *Sector*: {sector}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{chg_emoji} *Price*: ₹ {curr_price:,.2f} ({chg_sign}{day_chg_pct:.2f}% | {chg_sign}₹ {abs(day_chg_val):.2f})\n"
        f"📏 *52W Range*: ₹ {fifty_two_l:,.1f} – ₹ {fifty_two_h:,.1f}\n"
        f"⚖️ *P/E*: {pe_ratio}  |  *ROCE*: {roce}%  |  *F-Score*: {piotroski}/9\n"
        f"{dcf_line}"
        f"{shark_badge}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"_Reply with another ticker or `PORTFOLIO` / `NIFTY` / `HELP`._"
    )
    return msg


def handle_portfolio_query() -> str:
    """
    Handles 'PORTFOLIO' or 'STATUS' queries.
    Aggregates active FIFO holdings and returns valuation + today's P&L.
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, symbol, name, sector, quantity, purchase_price, purchase_date, transaction_type FROM portfolio_items")
            all_txs = [dict(row) for row in cursor.fetchall()]
        
        active_holdings = compute_active_holdings(all_txs)
        # Filter out test holdings
        active_holdings = [h for h in active_holdings if not h.get("symbol", "").startswith("TEST")]
        
        if not active_holdings:
            return "💼 *Portfolio Status*: No active positions detected in your portfolio database."

        # Quick price lookup
        symbols = list(set(h["symbol"] for h in active_holdings))
        total_cost = 0.0
        total_val = 0.0
        total_day_pnl = 0.0
        
        holdings_summary = []
        for h in active_holdings:
            sym = h["symbol"]
            qty = h["quantity"]
            buy_price = h["purchase_price"]
            cost = qty * buy_price
            total_cost += cost
            
            # Fast price quote
            try:
                t = yf.Ticker(sym)
                fi = t.fast_info
                curr_p = float(fi.last_price or buy_price)
                prev_p = float(fi.previous_close or curr_p)
            except Exception:
                curr_p = buy_price
                prev_p = buy_price
                
            val = qty * curr_p
            total_val += val
            day_chg_val = qty * (curr_p - prev_p)
            total_day_pnl += day_chg_val
            day_chg_pct = ((curr_p - prev_p) / prev_p * 100.0) if prev_p > 0 else 0.0
            
            holdings_summary.append({
                "symbol": sym.replace(".NS", ""),
                "val": val,
                "pct": day_chg_pct
            })

        holdings_summary.sort(key=lambda x: x["pct"], reverse=True)
        top_gainer = holdings_summary[0] if holdings_summary else None
        top_loser = holdings_summary[-1] if holdings_summary else None
        
        day_pnl_sign = "+" if total_day_pnl >= 0 else "-"
        day_pnl_emoji = "🟢" if total_day_pnl >= 0 else "🔴"
        day_pnl_pct = (total_day_pnl / (total_val - total_day_pnl) * 100.0) if (total_val - total_day_pnl) > 0 else 0.0
        
        total_return = total_val - total_cost
        tot_ret_sign = "+" if total_return >= 0 else ""
        tot_ret_pct = (total_return / total_cost * 100.0) if total_cost > 0 else 0.0

        msg = (
            "💼 *PORTFOLIO INTELLIGENCE BRIEF*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 *Total Valuation*: ₹ {total_val:,.0f}\n"
            f"{day_pnl_emoji} *Today's Net P&L*: {day_pnl_sign}₹ {abs(total_day_pnl):,.0f} ({day_pnl_sign}{abs(day_pnl_pct):.2f}%)\n"
            f"📈 *Overall Return*: {tot_ret_sign}₹ {total_return:,.0f} ({tot_ret_sign}{tot_ret_pct:.2f}%)\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🚀 *Top Performer*: {top_gainer['symbol']} ({top_gainer['pct']:+.2f}%)\n"
            f"🔻 *Top Laggard*: {top_loser['symbol']} ({top_loser['pct']:+.2f}%)\n"
            f"📌 *Active Positions*: {len(active_holdings)} stocks\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "_Reply with any ticker (e.g. `BOSCH`, `TCS`) for deep drill-down._"
        )
        return msg
    except Exception as e:
        logger.error(f"Error computing portfolio query: {e}")
        return f"⚠️ *Error*: Failed to compute portfolio status: {str(e)}"


def handle_market_query() -> str:
    """
    Handles 'NIFTY' or 'MARKET' queries.
    Fetches Nifty 50, Sensex, India VIX, and global cues.
    """
    tickers = {"Nifty 50": "^NSEI", "Sensex": "^BSESN", "India VIX": "^INDIAVIX"}
    lines = []
    
    for name, sym in tickers.items():
        try:
            t = yf.Ticker(sym)
            fi = t.fast_info
            curr = float(fi.last_price or 0.0)
            prev = float(fi.previous_close or curr)
            pct = ((curr - prev) / prev * 100.0) if prev > 0 else 0.0
            sign = "+" if pct >= 0 else ""
            emoji = "🟢" if pct >= 0 else "🔴"
            if name == "India VIX":
                lines.append(f"⚡ *{name}*: {curr:.2f} ({sign}{pct:.2f}%)")
            else:
                lines.append(f"{emoji} *{name}*: {curr:,.1f} ({sign}{pct:.2f}%)")
        except Exception:
            pass

    msg = (
        "🌐 *MARKET BENCHMARK PULSE*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        + "\n".join(lines) + "\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "_Reply with a stock ticker or `PORTFOLIO` / `SHARK`._"
    )
    return msg


def handle_shark_query() -> str:
    """
    Handles 'SHARK' query.
    Surfaces superstar investor consensus holdings (stocks held by >=2 sharks).
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT symbol, company_name, COUNT(DISTINCT investor_id) as shark_count, 
                       GROUP_CONCAT(DISTINCT investor_name) as sharks,
                       SUM(holding_value_cr) as total_val_cr
                FROM shark_stock_lookup
                GROUP BY symbol
                HAVING shark_count >= 2
                ORDER BY shark_count DESC, total_val_cr DESC
                LIMIT 5
            """)
            rows = cursor.fetchall()
            
        if not rows:
            return "🦈 *Shark Radar*: Updating superstar investor portfolios. Check back shortly."
            
        lines = []
        for r in rows:
            sym = r["symbol"].replace(".NS", "").replace(".BO", "")
            lines.append(
                f"⭐ *{sym}* (Held by {r['shark_count']} Sharks)\n"
                f"   └ 🦈 _{r['sharks']}_\n"
                f"   └ 💰 Total Value: ₹ {r['total_val_cr']:.1f} Cr"
            )
            
        msg = (
            "🦈 *SHARK RADAR • CONSENSUS STOCKS*\n"
            "Stocks held simultaneously by 2+ Indian Superstar Investors:\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            + "\n\n".join(lines) + "\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "_Reply with any stock ticker (e.g. `BOSCH`, `TCS`) to inspect._"
        )
        return msg
    except Exception as e:
        logger.error(f"Error fetching shark consensus: {e}")
        return f"⚠️ *Error*: Failed to query Shark Radar: {str(e)}"


def handle_chart_query(symbol_input: str) -> str:
    """
    Handles 'CHART <SYMBOL>' queries (e.g. 'CHART BOSCH', 'CHART TCS').
    Generates a 6-month dark-mode technical chart and sends it directly to WhatsApp.
    """
    from backend.chart_generator import generate_stock_technical_chart, send_whatsapp_chart
    clean = symbol_input.strip().upper()
    if clean.startswith("CHART"):
        clean = clean[5:].strip()

    resolved = resolve_company_ticker(clean)
    ticker = resolved.get("yf_ticker") if resolved else f"{clean}.NS"
    disp_name = resolved.get("name") if resolved else clean
    base_sym = resolved.get("base_symbol") if resolved else clean.replace(".NS", "")

    try:
        img_bytes = generate_stock_technical_chart(ticker, disp_name)
        caption = (
            f"📈 *{disp_name.upper()}* (`{base_sym}`)\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📊 6-Month Technical Trend Analysis\n"
            "• Yellow Line: 50-day SMA\n"
            "• Purple Line: 200-day SMA\n"
            "• Subpanel: RSI-14 Oscillator\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "_Automated technical chart attached._"
        )
        res = send_whatsapp_chart(img_bytes, caption)
        if res.get("status") == "success":
            return f"✅ *Chart Delivered*: Dispatched 6-month technical chart for `{base_sym}` to your chat."
        else:
            return f"⚠️ *Chart Delivery Error*: {res.get('message')}"
    except Exception as e:
        logger.error(f"Error generating technical chart for {clean}: {e}")
        return f"⚠️ *Error*: Failed to generate chart for `{clean}`: {str(e)}"


def handle_breakout_query() -> str:
    """
    Handles 'BREAKOUT' or 'SCAN' query.
    Surfaces the top active VCP breakouts from the screener cache.
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT symbol, vcp_json, canslim_json, updated_at 
                FROM vcp_screener_cache 
                ORDER BY updated_at DESC LIMIT 5
            """)
            rows = cursor.fetchall()
            
        if not rows:
            return "🎯 *Breakout Radar*: Scanning NSE universe. No active VCP breakouts at this moment."

        cards = []
        for r in rows:
            try:
                vcp = json.loads(r["vcp_json"])
                sym = vcp.get("symbol", "").replace(".NS", "").replace(".BO", "")
                name = vcp.get("company_name", sym)
                status = vcp.get("vcp_status", "LIVE_BREAKOUT").replace("_", " ")
                pivot = vcp.get("pivot_price", 0.0)
                sl = vcp.get("stop_loss", 0.0)
                t1 = vcp.get("target_1", 0.0)
                rr = vcp.get("risk_reward_ratio", "1 : 3.0")
                grade = vcp.get("grade", "Grade A")

                cards.append(
                    f"🚀 *{sym}* — {name}\n"
                    f"   ├ ⚡ *Status*: {status} ({grade})\n"
                    f"   ├ 🎯 *Pivot*: ₹ {pivot:,.1f}  |  *SL*: ₹ {sl:,.1f}\n"
                    f"   ├ 🏁 *Target 1*: ₹ {t1:,.1f}  (R:R {rr})\n"
                    f"   └ 📊 _Contractions: {len(vcp.get('contractions', []))} stages_"
                )
            except Exception:
                pass

        msg = (
            "🎯 *VCP BREAKOUT RADAR • INSTITUTIONAL SETUPS*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            + "\n\n".join(cards) + "\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "_Reply with `CHART <SYMBOL>` to view setup chart._"
        )
        return msg
    except Exception as e:
        logger.error(f"Error querying breakouts: {e}")
        return f"⚠️ *Error*: Failed to query breakout radar: {str(e)}"


def handle_log_buy_query(cmd_text: str) -> str:
    """
    Handles 'BUY <SYMBOL> <QTY> <PRICE>' or 'LOG BUY ...'.
    Logs purchase transaction directly into portfolio_items database table.
    """
    pattern = r"^(?:LOG\s+)?BUY\s+([A-Za-z0-9.]+)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)"
    match = re.match(pattern, cmd_text.strip(), re.IGNORECASE)
    if not match:
        return (
            "⚠️ *Invalid Format*: To log a purchase, use:\n"
            "`BUY <SYMBOL> <QTY> <PRICE>`\n"
            "Example: `BUY BOSCH 5 44500` or `BUY RELIANCE 10 2950`"
        )

    raw_sym, qty_str, price_str = match.groups()
    qty = float(qty_str)
    price = float(price_str)

    resolved = resolve_company_ticker(raw_sym)
    ticker = resolved.get("yf_ticker") if resolved else f"{raw_sym.upper()}.NS"
    company_name = resolved.get("name") if resolved else raw_sym.upper()
    base_sym = resolved.get("base_symbol") if resolved else raw_sym.upper()

    # Query sector from screener_universe
    sector = "Equities"
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT sector FROM screener_universe WHERE symbol LIKE ?", (f"{base_sym}%",))
            s_row = cursor.fetchone()
            if s_row and s_row["sector"]:
                sector = s_row["sector"]
    except Exception:
        pass

    today_str = datetime.now().strftime("%Y-%m-%d")
    total_cost = qty * price

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO portfolio_items (symbol, name, sector, quantity, purchase_price, purchase_date, transaction_type)
                VALUES (?, ?, ?, ?, ?, ?, 'buy')
            """, (ticker, company_name, sector, qty, price, today_str))
            conn.commit()

        return (
            "✅ *TRADE JOURNAL ENTRY RECORDED*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 *Asset*: {company_name} (`{base_sym}`)\n"
            f"📥 *Type*: BUY\n"
            f"🔢 *Quantity*: {qty:,.0f} shares\n"
            f"💰 *Purchase Price*: ₹ {price:,.2f}\n"
            f"💵 *Total Outlay*: ₹ {total_cost:,.2f}\n"
            f"📅 *Date*: {today_str}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "_Synced with your workstation portfolio database._\n"
            "Reply `PORTFOLIO` to view updated valuation."
        )
    except Exception as e:
        logger.error(f"Error logging trade: {e}")
        return f"⚠️ *Error*: Failed to record trade: {str(e)}"


def handle_help_query() -> str:
    """Returns the interactive command terminal menu."""
    return (
        "🤖 *APEXQUANT INTELLIGENCE TERMINAL*\n"
        "Welcome! Reply with any of these instant commands:\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📌 *Stock Query*: Text any symbol\n"
        "   └ Examples: `BOSCH`, `RELIANCE`, `TCS`, `INFY`\n\n"
        "📈 *Technical Chart*: Text `CHART <SYMBOL>`\n"
        "   └ Examples: `CHART BOSCH`, `CHART TCS`\n\n"
        "🎯 *Breakout Radar*: Text `BREAKOUT` or `SCAN`\n"
        "   └ Top live VCP setups & pivot breakout targets\n\n"
        "💼 *Portfolio Health*: Text `PORTFOLIO` or `STATUS`\n"
        "   └ Live valuation, today's P&L, leaders & laggards\n\n"
        "📝 *Log Trade*: Text `BUY <SYMBOL> <QTY> <PRICE>`\n"
        "   └ Example: `BUY BOSCH 5 44000`\n\n"
        "🌐 *Market Pulse*: Text `NIFTY` or `MARKET`\n"
        "   └ Nifty 50, Sensex, India VIX levels\n\n"
        "🦈 *Super-Investors*: Text `SHARK`\n"
        "   └ Top multi-shark consensus stock picks\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "_Tip: All queries are executed in real-time by the workstation engine._"
    )


def process_incoming_message(body: str) -> str:
    """
    Main dispatch router for inbound WhatsApp messages.
    """
    cleaned = (body or "").strip()
    upper = cleaned.upper()

    if not cleaned:
        return handle_help_query()

    # Meta Quick-reply button click mapping
    if upper in ["BTN_PORTFOLIO", "PORTFOLIO", "STATUS", "PF", "MYSTOCKS"]:
        return handle_portfolio_query()
    elif upper in ["BTN_NIFTY", "NIFTY", "MARKET", "SENSEX", "INDICES"]:
        return handle_market_query()
    elif upper in ["BTN_SHARKS", "SHARK", "SHARKS", "SUPERSTAR", "WHALES"]:
        return handle_shark_query()
    elif upper in ["BTN_BREAKOUT", "BREAKOUT", "SCAN", "VCP"]:
        return handle_breakout_query()
    elif upper.startswith("CHART"):
        return handle_chart_query(cleaned)
    elif re.match(r"^(?:LOG\s+)?BUY\s+", upper):
        return handle_log_buy_query(cleaned)
    elif upper in ["HELP", "MENU", "START", "HI", "HELLO"]:
        return handle_help_query()
    else:
        # Treat as single stock symbol query
        return handle_stock_query(cleaned)

