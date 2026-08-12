import os
import json
import sqlite3
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
import yfinance as yf
import pandas as pd
import requests

from backend.main import get_db, compute_active_holdings, fetch_enriched_sector_regime, _MARKET_MOVERS_CACHE, get_market_news
from backend.financial_utils import get_complete_financial_profile
from backend.llm_config import call_llm, TASK_FAST

def fetch_weekly_portfolio_summary() -> dict:
    """
    Computes active portfolio holdings and calculates 5-day / weekly performance totals,
    including weekly P&L (₹), weekly return %, top 2 weekly gainers, and top 2 drag stocks.
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, symbol, name, sector, quantity, purchase_price, purchase_date, transaction_type FROM portfolio_items")
            all_txs = [dict(row) for row in cursor.fetchall()]
        
        active_holdings = compute_active_holdings(all_txs)
        if not active_holdings:
            return {"active": False}

        symbols = list(set(h["symbol"] for h in active_holdings))
        quotes = {}

        try:
            # Download 7-day daily data to cover 5 trading days
            df = yf.download(symbols, period="7d", interval="1d", progress=False)
            if not df.empty:
                is_multi = isinstance(df.columns, pd.MultiIndex)
                for sym in symbols:
                    try:
                        if is_multi:
                            close_series = df['Close'][sym].dropna()
                        else:
                            close_series = df['Close'].dropna()
                        
                        if len(close_series) >= 2:
                            curr_price = float(close_series.iloc[-1])
                            week_start_price = float(close_series.iloc[0])
                            weekly_chg_pct = ((curr_price - week_start_price) / week_start_price * 100.0) if week_start_price > 0 else 0.0
                            weekly_chg_val = curr_price - week_start_price
                            quotes[sym] = {
                                "current_price": curr_price,
                                "weekly_chg_pct": weekly_chg_pct,
                                "weekly_chg_val": weekly_chg_val
                            }
                    except Exception:
                        pass
        except Exception as batch_err:
            print(f"Weekly Wrap-up: Portfolio batch download error: {batch_err}")

        # Fallback for missing symbols
        with get_db() as conn:
            cursor = conn.cursor()
            for h in active_holdings:
                sym = h["symbol"]
                if sym not in quotes:
                    cursor.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ?", (sym,))
                    cache_row = cursor.fetchone()
                    if cache_row:
                        try:
                            profile = json.loads(cache_row["profile_json"])
                            curr = profile.get("fundamentals", {}).get("current_price")
                            chg = profile.get("technicals", {}).get("price_change_pct") or 0.0
                            if curr:
                                prev = curr / (1 + (chg / 100.0))
                                quotes[sym] = {
                                    "current_price": curr,
                                    "weekly_chg_pct": chg,
                                    "weekly_chg_val": curr - prev
                                }
                        except Exception:
                            pass

        total_cost = 0.0
        total_value = 0.0
        total_weekly_change_val = 0.0
        
        enriched_holdings = []
        for h in active_holdings:
            sym = h["symbol"]
            qty = h["quantity"]
            purchase_price = h["purchase_price"]
            
            quote = quotes.get(sym, {"current_price": purchase_price, "weekly_chg_pct": 0.0, "weekly_chg_val": 0.0})
            curr_p = quote["current_price"]
            wk_chg_pct = quote["weekly_chg_pct"]
            wk_chg_val = quote["weekly_chg_val"]
            
            total_cost += qty * purchase_price
            total_value += qty * curr_p
            total_weekly_change_val += qty * wk_chg_val
            
            enriched_holdings.append({
                "symbol": sym,
                "name": h.get("name") or sym,
                "qty": qty,
                "cost": qty * purchase_price,
                "value": qty * curr_p,
                "weekly_change_pct": wk_chg_pct,
                "weekly_change_val": qty * wk_chg_val
            })

        total_weekly_change_pct = (total_weekly_change_val / (total_value - total_weekly_change_val) * 100.0) if (total_value - total_weekly_change_val) > 0 else 0.0
        total_return_val = total_value - total_cost
        total_return_pct = (total_return_val / total_cost * 100.0) if total_cost > 0 else 0.0

        enriched_holdings.sort(key=lambda x: x["weekly_change_pct"], reverse=True)
        top_gainers = enriched_holdings[:2]
        top_drag = sorted(enriched_holdings, key=lambda x: x["weekly_change_pct"])[:2]

        top_leader_symbols = [g["symbol"] for g in top_gainers]
        top_drag_symbols = [d["symbol"] for d in top_drag]
        all_tech_symbols = list(set(top_leader_symbols + top_drag_symbols))

        leader_technicals = {}
        drag_technicals = {}

        if all_tech_symbols:
            yf_tech = [s if s.endswith('.NS') or s.startswith('^') else f"{s}.NS" for s in all_tech_symbols]
            try:
                df_tech = yf.download(yf_tech, period="3mo", progress=False)
                if not df_tech.empty:
                    is_multi = isinstance(df_tech.columns, pd.MultiIndex)
                    for sym in all_tech_symbols:
                        try:
                            yf_key = sym if (sym.endswith('.NS') or sym.startswith('^')) else f"{sym}.NS"
                            if is_multi:
                                close_s = df_tech['Close'][yf_key].dropna()
                                low_s = df_tech['Low'][yf_key].dropna()
                                high_s = df_tech['High'][yf_key].dropna()
                            else:
                                close_s = df_tech['Close'].dropna()
                                low_s = df_tech['Low'].dropna()
                                high_s = df_tech['High'].dropna()

                            curr_p = float(close_s.iloc[-1]) if len(close_s) > 0 else 0.0
                            sma_20 = float(close_s.iloc[-20:].mean()) if len(close_s) >= 20 else curr_p
                            sma_50 = float(close_s.iloc[-50:].mean()) if len(close_s) >= 50 else sma_20
                            support_20d = float(low_s.iloc[-20:].min()) if len(low_s) >= 20 else curr_p * 0.95
                            resistance_20d = float(high_s.iloc[-20:].max()) if len(high_s) >= 20 else curr_p * 1.05

                            t_info = {
                                "current_price": curr_p,
                                "sma_20": sma_20,
                                "sma_50": sma_50,
                                "support": min(support_20d, sma_20),
                                "resistance": max(resistance_20d, sma_50)
                            }
                            clean_sym = sym.replace('.NS', '')
                            if sym in top_leader_symbols:
                                leader_technicals[clean_sym] = t_info
                            if sym in top_drag_symbols:
                                drag_technicals[clean_sym] = t_info
                        except Exception:
                            pass
            except Exception as d_err:
                print(f"Weekly Wrap-up: Technicals fetch error: {d_err}")

        return {
            "active": True,
            "total_cost": total_cost,
            "total_value": total_value,
            "total_weekly_change_val": total_weekly_change_val,
            "total_weekly_change_pct": total_weekly_change_pct,
            "total_return_val": total_return_val,
            "total_return_pct": total_return_pct,
            "top_gainers": top_gainers,
            "top_drag": top_drag,
            "leader_technicals": leader_technicals,
            "drag_technicals": drag_technicals
        }
    except Exception as e:
        print(f"Weekly Wrap-up: Portfolio aggregation error: {e}")
        return {"active": False}

def fetch_weekly_market_benchmarks() -> dict:
    """
    Fetches 5-day performance for Nifty 50 (^NSEI) and BSE Sensex (^BSESN).
    Also checks benchmark return % for portfolio alpha calculation.
    """
    try:
        benchmarks = {"^NSEI": "Nifty 50", "^BSESN": "BSE Sensex"}
        df = yf.download(list(benchmarks.keys()), period="7d", interval="1d", progress=False)
        result = {}
        if not df.empty:
            is_multi = isinstance(df.columns, pd.MultiIndex)
            for sym, name in benchmarks.items():
                try:
                    if is_multi:
                        series = df['Close'][sym].dropna()
                    else:
                        series = df['Close'].dropna()
                    if len(series) >= 2:
                        curr = float(series.iloc[-1])
                        start = float(series.iloc[0])
                        chg_val = curr - start
                        chg_pct = ((curr - start) / start * 100.0) if start > 0 else 0.0
                        result[name] = {
                            "current": curr,
                            "weekly_chg_val": chg_val,
                            "weekly_chg_pct": chg_pct
                        }
                except Exception:
                    pass
        return result
    except Exception as e:
        print(f"Weekly Wrap-up: Market benchmarks fetch error: {e}")
        return {}

def fetch_weekly_sector_rotation() -> dict:
    """
    Fetches sector regime stats to aggregate weekly sector leaders and laggards.
    """
    try:
        with get_db() as conn:
            sectors = fetch_enriched_sector_regime(conn)
        if not sectors:
            return {"active": False}
        
        sectors_sorted = [s for s in sectors if s.get("return_1d") is not None]
        sectors_sorted.sort(key=lambda x: x.get("return_1d", 0), reverse=True)
        
        top_sectors = sectors_sorted[:2]
        bottom_sectors = sectors_sorted[-2:] if len(sectors_sorted) >= 4 else sectors_sorted[2:]
        bottom_sectors.reverse()

        return {
            "active": True,
            "top_sectors": top_sectors,
            "bottom_sectors": bottom_sectors
        }
    except Exception as e:
        print(f"Weekly Wrap-up: Sector rotation fetch error: {e}")
        return {"active": False}

def fetch_weekly_catalysts_and_breakouts() -> dict:
    """
    Collects weekly breakouts and upcoming corporate events specifically scoped
    to user's Portfolio Holdings + Watchlist stocks.
    """
    try:
        events = []
        watchlist_breakouts = []
        target_syms = []
        with get_db() as conn:
            cursor = conn.cursor()
            # Combine Portfolio and Watchlist unique symbols
            cursor.execute("""
                SELECT symbol FROM portfolio_items
                UNION
                SELECT symbol FROM watchlist_items
            """)
            target_syms = [row["symbol"] for row in cursor.fetchall() if row["symbol"]]

            if target_syms:
                raw_syms = [s.replace(".NS", "") for s in target_syms]
                all_possible = list(set(target_syms + raw_syms))
                placeholders = ",".join(["?"] * len(all_possible))
                
                query = f"""
                    SELECT symbol, description AS event_title, event_date, event_type
                    FROM stock_events
                    WHERE (symbol IN ({placeholders}) OR REPLACE(symbol, '.NS', '') IN ({placeholders}))
                      AND date(event_date) >= date('now', '-1 day')
                    ORDER BY event_date ASC
                    LIMIT 6
                """
                cursor.execute(query, all_possible + all_possible)
                events = [dict(row) for row in cursor.fetchall()]

        if target_syms:
            yf_syms = [s if s.endswith('.NS') or s.startswith('^') else f"{s}.NS" for s in target_syms[:15]]
            try:
                df = yf.download(yf_syms, period="1mo", progress=False)
                if not df.empty and isinstance(df.columns, pd.MultiIndex):
                    for sym in yf_syms:
                        try:
                            c = df['Close'][sym].dropna()
                            h = df['High'][sym].dropna()
                            if len(c) >= 5 and len(h) >= 20:
                                curr = float(c.iloc[-1])
                                max_h = float(h.max())
                                if curr >= max_h * 0.98:
                                    clean_name = sym.replace('.NS', '')
                                    watchlist_breakouts.append({"symbol": clean_name, "price": curr, "high": max_h})
                        except Exception:
                            pass
            except Exception as batch_err:
                print(f"Weekly Wrap-up: Breakout batch download error: {batch_err}")

        return {
            "events": events,
            "breakouts": watchlist_breakouts
        }
    except Exception as e:
        print(f"Weekly Wrap-up: Catalysts fetch error: {e}")
        return {"events": [], "breakouts": []}

def get_weekly_wrapup_settings() -> dict:
    """
    Retrieves Weekly Wrap-up settings from key-value alert_settings DB table.
    """
    defaults = {
        "enabled": False,
        "day": "Saturday",
        "time": "10:00",
        "persona": "Institutional Analyst",
        "last_sent": "Never",
        "include_portfolio": True,
        "include_sectors": True,
        "include_events": True,
        "include_breakouts": True,
        "include_fiidii": True
    }
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM alert_settings WHERE key LIKE 'weekly_wrapup_%'")
            rows = cursor.fetchall()
            for row in rows:
                k = row["key"].replace("weekly_wrapup_", "")
                v = row["value"]
                if k in ["enabled", "include_portfolio", "include_sectors", "include_events", "include_breakouts", "include_fiidii"]:
                    defaults[k] = (v.lower() == "true")
                else:
                    defaults[k] = v
    except Exception as e:
        print(f"Weekly Wrap-up: Error loading settings: {e}")
    return defaults

def save_weekly_wrapup_settings(settings: dict) -> bool:
    """
    Saves Weekly Wrap-up settings to key-value alert_settings DB table.
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            for k, v in settings.items():
                db_key = f"weekly_wrapup_{k}"
                db_val = str(v)
                cursor.execute("""
                    INSERT INTO alert_settings (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """, (db_key, db_val))
            conn.commit()
        return True
    except Exception as e:
        print(f"Weekly Wrap-up: Error saving settings: {e}")
        return False

def generate_weekly_wrapup_content(settings: dict, mode: str = "preview") -> str:
    """
    Gathers weekly data and invokes LLM (or fallback template) to synthesize the Weekly Wrap-Up report.
    """
    portfolio_data = fetch_weekly_portfolio_summary()
    market_data = fetch_weekly_market_benchmarks()
    sector_data = fetch_weekly_sector_rotation()
    catalysts_data = fetch_weekly_catalysts_and_breakouts()

    persona = settings.get("persona", "Institutional Analyst")
    
    nifty = market_data.get("Nifty 50", {})
    sensex = market_data.get("BSE Sensex", {})
    nifty_chg_p = nifty.get("weekly_chg_pct", 0.0) if nifty else 0.0
    nifty_chg_v = nifty.get("weekly_chg_val", 0.0) if nifty else 0.0
    sensex_chg_p = sensex.get("weekly_chg_pct", 0.0) if sensex else 0.0
    sensex_chg_v = sensex.get("weekly_chg_val", 0.0) if sensex else 0.0
    
    nifty_str = f"Nifty 50: {nifty.get('current', 'N/A'):,.2f} ({nifty_chg_v:+.2f} pts, {nifty_chg_p:+.2f}%)" if nifty else "Nifty 50: N/A"
    sensex_str = f"BSE Sensex: {sensex.get('current', 'N/A'):,.2f} ({sensex_chg_v:+.2f} pts, {sensex_chg_p:+.2f}%)" if sensex else "BSE Sensex: N/A"

    port_str = "N/A"
    if portfolio_data.get("active"):
        p_val = portfolio_data.get("total_value", 0)
        p_chg_v = portfolio_data.get("total_weekly_change_val", 0)
        p_chg_p = portfolio_data.get("total_weekly_change_pct", 0)
        top_g = portfolio_data.get("top_gainers", [])
        top_d = portfolio_data.get("top_drag", [])
        
        # Calculate 5-day Portfolio Alpha vs Nifty 50
        alpha_val = p_chg_p - nifty_chg_p
        alpha_str = f"Alpha: {alpha_val:+.2f}% vs Nifty 50 ({nifty_chg_p:+.2f}%)"
        
        g_text = ", ".join([f"{x.get('symbol', '').replace('.NS','')} ({x.get('weekly_change_pct', x.get('chg_pct', 0)):+.1f}%)" for x in top_g]) if top_g else "None"
        d_text = ", ".join([f"{x.get('symbol', '').replace('.NS','')} ({x.get('weekly_change_pct', x.get('chg_pct', 0)):+.1f}%)" for x in top_d]) if top_d else "None"
        
        port_str = f"Valuation: ₹{p_val:,.2f} | 5-Day Net P&L: ₹{p_chg_v:,.2f} ({p_chg_p:+.2f}%) | {alpha_str}\nTop Weekly Outperformers: {g_text}\nWeekly Drag Holdings: {d_text}"

    sectors_str = "N/A"
    if sector_data.get("active"):
        t_sec = ", ".join([s.get("sector_name", s.get("sector", s.get("name", "Sector"))) for s in sector_data.get("top_sectors", [])])
        b_sec = ", ".join([s.get("sector_name", s.get("sector", s.get("name", "Sector"))) for s in sector_data.get("bottom_sectors", [])])
        sectors_str = f"Leading Sectors: {t_sec} | Lagging Sectors: {b_sec}"

    inc_portfolio = settings.get("include_portfolio", True)
    inc_sectors = settings.get("include_sectors", True)
    inc_events = settings.get("include_events", True)
    inc_breakouts = settings.get("include_breakouts", True)

    breakout_list = catalysts_data.get('breakouts', [])
    events_list = catalysts_data.get('events', [])

    if breakout_list:
        breakouts_formatted = ", ".join([f"{b['symbol']} (₹{b['price']:,.2f})" for b in breakout_list])
    else:
        breakouts_formatted = "None detected this week for tracked holdings"

    if events_list:
        events_formatted = "\n".join([
            f"• {e.get('symbol','').replace('.NS','')}: {e.get('event_title', e.get('event_type','Corporate Action'))} ({e.get('event_date','TBD')})"
            for e in events_list
        ])
    else:
        events_formatted = "• No upcoming corporate events scheduled for tracked holdings/watchlist."

    leader_tech_map = portfolio_data.get("leader_technicals", {})
    drag_tech_map = portfolio_data.get("drag_technicals", {})

    all_tech_lines = []
    if leader_tech_map:
        all_tech_lines.append("• Leader Outperformers:")
        for sym, t in leader_tech_map.items():
            all_tech_lines.append(f"  • {sym} (₹{t['current_price']:,.2f}): Support ₹{t['support']:,.2f} (20-DMA/Low) | Resistance ₹{t['resistance']:,.2f}")
    
    if drag_tech_map:
        all_tech_lines.append("• Drag Holdings:")
        for sym, t in drag_tech_map.items():
            all_tech_lines.append(f"  • {sym} (₹{t['current_price']:,.2f}): Support ₹{t['support']:,.2f} (20-DMA/Low) | Resistance ₹{t['resistance']:,.2f}")

    tech_levels_str = "\n".join(all_tech_lines) if all_tech_lines else "• No technical levels calculated."

    prompt = f"""
You are an expert Indian Stock Market {persona}. Construct a concise, publication-grade WEEKLY MARKET & PORTFOLIO RETROSPECTIVE report formatted for WhatsApp messages.

MANDATORY SECTIONS TO INCLUDE IN YOUR OUTPUT:

1. *📊 BENCHMARK SNAPSHOT (5-DAY)*
- {nifty_str}
- {sensex_str}

{"2. *📈 PORTFOLIO PERFORMANCE*" if inc_portfolio else ""}
{port_str if inc_portfolio else ""}

{"3. *⚡ SECTOR ROTATION HEATMAP*" if inc_sectors else ""}
{sectors_str if inc_sectors else ""}

{"4. *📅 CATALYSTS & RADAR (TRACKED HOLDINGS & WATCHLIST)*" if (inc_events or inc_breakouts) else ""}
{"- Portfolio/Watchlist 52W Breakouts: " + breakouts_formatted if inc_breakouts else ""}
{"- Upcoming Corporate Events & Earnings:\n" + events_formatted if inc_events else ""}

{"5. *🛡️ KEY TECHNICAL LEVELS (LEADER & DRAG HOLDINGS)*\n" + tech_levels_str if (inc_portfolio and (leader_tech_map or drag_tech_map)) else ""}

6. *🎯 Tactical Playbook for Next Week*
- Provide 2-3 sentences of actionable guidance (e.g. stop-loss discipline, sector rebalancing, risk management).

FORMAT INSTRUCTIONS:
- Use exact bold headers with emojis as shown above (*📊 BENCHMARK SNAPSHOT (5-DAY)*, etc.).
- Do not omit the *⚡ SECTOR ROTATION HEATMAP* section.
- Keep output under 350 words. Do not use Markdown header hashes (# or ##). Use bullet points (•) for lists.
"""
    try:
        response = call_llm(TASK_FAST, f"You are an expert Indian Stock Market {persona}.", prompt)
        if response and len(response.strip()) > 50:
            return response.strip()
    except Exception as llm_err:
        print(f"Weekly Wrap-up LLM generation error: {llm_err}")

    date_str = datetime.now().strftime("%Y-%m-%d")
    fallback_parts = [
        f"*📅 WEEKLY MARKET & PORTFOLIO RETROSPECTIVE* ({date_str})",
        f"Persona: _{persona}_\n",
        "*📊 MARKET BENCHMARKS*",
        f"• {nifty_str}",
        f"• {sensex_str}\n"
    ]
    if inc_portfolio:
        fallback_parts.extend(["*📈 PORTFOLIO 5-DAY PERFORMANCE*", f"• {port_str}\n"])
    if inc_sectors:
        fallback_parts.extend(["*⚡ SECTOR ROTATION HEATMAP*", f"• {sectors_str}\n"])
    if inc_events or inc_breakouts:
        cat_lines = ["*📅 CATALYSTS & RADAR*"]
        if inc_breakouts:
            cat_lines.append(f"• Breakouts: {breakouts_formatted}")
        if inc_events:
            cat_lines.append(f"• Corporate Events:\n{events_formatted}")
        fallback_parts.extend(cat_lines)
        fallback_parts.append("")
    if inc_portfolio and (leader_tech_map or drag_tech_map):
        fallback_parts.extend(["*🛡️ KEY TECHNICAL LEVELS (LEADER & DRAG HOLDINGS)*", tech_levels_str, ""])
    fallback_parts.extend([
        "*🎯 TACTICAL PLAYBOOK*",
        "Review portfolio holdings against 20-day moving averages and maintain disciplined stop-loss levels ahead of next week's market open."
    ])
    return "\n".join(fallback_parts)

async def trigger_weekly_wrapup(on_demand: bool = True, persona: Optional[str] = None) -> dict:
    """
    Triggers Weekly Wrap-Up generation, dispatches via Meta WhatsApp Cloud API or UltraMsg webhook, and updates DB timestamp.
    """
    settings = get_weekly_wrapup_settings()
    if persona:
        settings["persona"] = persona
    content = generate_weekly_wrapup_content(settings, mode="dispatch" if not on_demand else "preview")
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_weekly_wrapup_settings({"last_sent": now_str})

    whatsapp_sent = False
    whatsapp_error = None

    # 1. Primary Dispatch: Meta WhatsApp Cloud API
    try:
        from backend.daily_wrapup import send_whatsapp_wrapup
        wa_res = await send_whatsapp_wrapup(content)
        if wa_res.get("status") == "success":
            whatsapp_sent = True
        else:
            whatsapp_error = wa_res.get("message", "WhatsApp Cloud API send failed")
    except Exception as w_err:
        whatsapp_error = str(w_err)

    # 2. Secondary Fallback Dispatch: UltraMsg API from DB
    if not whatsapp_sent:
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT key, value FROM alert_settings WHERE key IN ('ultramsg_instance', 'ultramsg_token', 'ultramsg_phone')")
                creds = {row["key"]: row["value"] for row in cursor.fetchall()}
                
            instance = creds.get("ultramsg_instance")
            token = creds.get("ultramsg_token")
            phone = creds.get("ultramsg_phone")
            
            if instance and token and phone:
                url = f"https://api.ultramsg.com/{instance}/messages/chat"
                payload = {
                    "token": token,
                    "to": phone,
                    "body": content
                }
                res = requests.post(url, data=payload, timeout=10)
                if res.status_code == 200:
                    whatsapp_sent = True
                    whatsapp_error = None
                else:
                    whatsapp_error = f"UltraMsg HTTP {res.status_code}: {res.text}"
        except Exception as um_err:
            if not whatsapp_error:
                whatsapp_error = str(um_err)

    return {
        "status": "success",
        "last_sent": now_str,
        "content": content,
        "whatsapp_sent": whatsapp_sent,
        "whatsapp_error": whatsapp_error
    }
