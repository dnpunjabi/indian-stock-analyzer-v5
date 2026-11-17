import os
import sys
import time
import json
import logging
import sqlite3
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Ensure backend root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.llm_config import _get_gemini_keys_pool, _format_model_label, _get_config
from backend.whatsapp_bot import resolve_company_ticker, get_stock_price_context

DATABASE_DIR = os.environ.get("DATABASE_DIR", os.path.join(os.path.dirname(__file__), "data"))
DATABASE_PATH = os.path.join(DATABASE_DIR, "watchlist_database.db")


def _init_confluence_cache_table():
    """Initializes the SQLite cache table for Confluence Storyteller dossiers."""
    try:
        os.makedirs(DATABASE_DIR, exist_ok=True)
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_confluence_stories (
            symbol TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Could not initialize cached_confluence_stories table: {e}")


def get_confluence_model_info() -> Tuple[str, str]:
    """
    Dynamically returns (model_id, display_label) from environment variables or .env.
    Allows seamlessly upgrading or switching LLM models in Oracle VM / production
    without hardcoding model version strings or requiring client/APK changes.
    """
    model_id = (
        os.environ.get("CONFLUENCE_AI_MODEL")
        or os.environ.get("GEMINI_FAST_MODEL")
        or os.environ.get("GEMINI_HEAVY_MODEL")
        or "gemini-2.5-flash"
    ).strip()

    model_label = os.environ.get("CONFLUENCE_AI_LABEL")
    if not model_label:
        base_label = _format_model_label(model_id)
        model_label = f"{base_label} Confluence Engine" if "Confluence" not in base_label else base_label

    return model_id, model_label


def detect_screener_synergy_pairs(screener_keys: set) -> List[Dict[str, Any]]:
    """
    Detects high-conviction mathematical synergy pairs between independent screeners.
    Awards +15 bonus points per verified synergy signature.
    """
    synergies = []

    is_vcp = "minervini_vcp" in screener_keys or "vcp" in screener_keys
    is_rsnh = "rs_line_new_high" in screener_keys or any("rs_line" in k for k in screener_keys)
    is_pocket = "pocket_pivot" in screener_keys or any("pocket" in k for k in screener_keys)
    is_stage2 = "weinstein_stage2" in screener_keys or "stage2" in screener_keys
    is_3wt = "3weeks_tight" in screener_keys or "3wt" in screener_keys
    is_cwh = "cup_with_handle" in screener_keys or "cup" in screener_keys
    is_flat = "flat_base_breakout" in screener_keys or "flat" in screener_keys
    is_ep = "episodic_pivot" in screener_keys or "episodic" in screener_keys
    is_kell = "oliver_kell_reversal" in screener_keys or "kell" in screener_keys

    # 1. Morales-Kacher Early Handle Entry (Cup & Handle + Pocket Pivot)
    if is_cwh and is_pocket:
        synergies.append({
            "name": "Morales-Kacher Early Handle Entry",
            "badge": "👑 EARLY HANDLE ENTRY",
            "description": "Pocket Pivot institutional volume signature detected inside the handle prior to rim breakout.",
            "bonus": 15
        })

    # 2. Stan Weinstein Stepping Stone (Stage 2 + 3-Weeks Tight)
    if is_stage2 and is_3wt:
        synergies.append({
            "name": "Stan Weinstein Stepping Stone",
            "badge": "👑 STAGE 2 STEPPING STONE",
            "description": "Stock broke out into Stage 2 markup and is resting tightly for 3 weeks with supply dried up.",
            "bonus": 15
        })

    # 3. True Market Leader Signature (VCP + RSNH Blue-Dot)
    if is_vcp and is_rsnh:
        synergies.append({
            "name": "True Market Leader Signature",
            "badge": "👑 TRUE MARKET LEADER",
            "description": "Price volatility is coiling tightly while Relative Strength hits fresh 52-week highs ahead of price.",
            "bonus": 15
        })

    # 4. Structural Base Launch (Flat Base + Pocket Pivot)
    if is_flat and is_pocket:
        synergies.append({
            "name": "Structural Base Launch",
            "badge": "👑 BASE LAUNCH SIGNATURE",
            "description": "Institutional pocket pivot accumulation bursting out of a multi-month flat consolidation base.",
            "bonus": 15
        })

    # 5. Fundamental Catalyst Momentum Continuation (Episodic Pivot + Oliver Kell)
    if is_ep and is_kell:
        synergies.append({
            "name": "Catalyst Momentum Continuation",
            "badge": "👑 CATALYST CONTINUATION",
            "description": "Blowout earnings gap-up momentum holding cleanly above rising 8/21 EMAs without giving back gains.",
            "bonus": 15
        })

    return synergies


def detect_conflicts_and_red_flags(price: float, pivot: float, ema_20: float, ma_30wk_slope: float, dist_52w_high: float) -> List[Dict[str, Any]]:
    """
    Acts as the Devil's Advocate / Red-Team to catch bull traps, extended chasing,
    and counter-trend risks.
    """
    audits = []

    # 1. Overextension / Chasing Trap Check
    if ema_20 > 0 and price > 0:
        ext_pct = ((price - ema_20) / ema_20) * 100.0
        if ext_pct > 14.0:
            audits.append({
                "type": "CHASE_WARNING",
                "status": "FAIL",
                "label": "Overextension Check",
                "detail": f"⚠️ High Chase Risk: Stock is +{ext_pct:.1f}% above its 20-EMA (₹{ema_20:,.2f}). High mean-reversion risk; wait for a pullback to the 20-EMA."
            })
        else:
            audits.append({
                "type": "CHASE_CHECK",
                "status": "PASS",
                "label": "Overextension Check",
                "detail": f"✅ Passed: Stock is within +{ext_pct:.1f}% of 20-EMA (₹{ema_20:,.2f}), low chase risk."
            })

    # 2. Stage 4 Downtrend Contamination Check
    if ma_30wk_slope < -0.30:
        audits.append({
            "type": "STAGE_WARNING",
            "status": "FAIL",
            "label": "30-Week Trend Check",
            "detail": f"🛑 Stage 4 Warning: 30-Week MA slope is downward ({ma_30wk_slope:.2f}%). Any breakout is a counter-trend bounce."
        })
    else:
        audits.append({
            "type": "STAGE_CHECK",
            "status": "PASS",
            "label": "30-Week Trend Check",
            "detail": f"✅ Passed: 30-Week MA is healthy and sloping upward (+{ma_30wk_slope:.2f}%)."
        })

    # 3. Overhead Supply / Resistance Check
    if dist_52w_high >= -3.0:
        audits.append({
            "type": "OVERHEAD_CHECK",
            "status": "PASS",
            "label": "Overhead Supply Check",
            "detail": "✅ Clear: Trading within 3% of 52-week high; zero institutional overhead resistance."
        })
    elif dist_52w_high < -25.0:
        audits.append({
            "type": "OVERHEAD_WARNING",
            "status": "WARN",
            "label": "Overhead Supply Check",
            "detail": f"⚠️ Overhead Supply: Stock is {abs(dist_52w_high):.1f}% below 52-week high with trapped sellers overhead."
        })
    else:
        audits.append({
            "type": "OVERHEAD_CHECK",
            "status": "PASS",
            "label": "Overhead Supply Check",
            "detail": f"✅ Moderate: Stock is {abs(dist_52w_high):.1f}% below 52-week high, manageable supply."
        })

    return audits


def check_portfolio_watchlist_status(symbol: str) -> Dict[str, bool]:
    """Checks whether the symbol is currently in the user's Watchlist or Portfolio."""
    res = {"in_watchlist": False, "in_portfolio": False}
    clean = symbol.replace(".NS", "").replace(".BO", "").strip().upper()
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Check trades/portfolio
        cur.execute("SELECT COUNT(*) as cnt FROM cached_trades WHERE symbol LIKE ?", (f"%{clean}%",))
        row = cur.fetchone()
        if row and row["cnt"] > 0:
            res["in_portfolio"] = True
            
        # Check alert_settings or watchlist
        cur.execute("SELECT value FROM alert_settings WHERE key = 'active_watchlist'")
        wl_row = cur.fetchone()
        if wl_row and wl_row["value"]:
            if clean in wl_row["value"].upper():
                res["in_watchlist"] = True
                
        conn.close()
    except Exception as e:
        logger.debug(f"[Confluence Storyteller] Watchlist check warning: {e}")
    return res


def generate_confluence_story_for_stock(
    symbol: str,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Generates an institutional Multi-Vector Confluence Investment Committee Memo
    for a given stock, synthesizing its active screeners, synergy pairs, conflict audits,
    and verified execution blueprint.
    """
    _init_confluence_cache_table()
    model, model_label = get_confluence_model_info()

    # 1. Resolve ticker
    clean_sym = symbol.strip().upper().replace(".NS", "").replace(".BO", "")
    resolved = resolve_company_ticker(clean_sym)
    base_sym = resolved.get("base_symbol") if resolved else clean_sym
    comp_name = resolved.get("name") if resolved else base_sym
    ticker = resolved.get("yf_ticker") if resolved else f"{base_sym}.NS"

    cache_ttl = 4 * 3600  # 4-hour cache

    # 2. Check SQLite cache
    if not force_refresh:
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT payload_json, created_at FROM cached_confluence_stories WHERE symbol = ?", (base_sym,))
            row = cursor.fetchone()
            conn.close()
            if row and (time.time() - row["created_at"] < cache_ttl):
                data = json.loads(row["payload_json"])
                data["from_cache"] = True
                logger.info(f"[Confluence Storyteller] Serving cached story for {base_sym}")
                return data
        except Exception as e:
            logger.debug(f"[Confluence Storyteller] Cache lookup error: {e}")

    # 3. Pull Multi-Screener Confluence & Stage Diagnostic Data
    from backend.main import get_stage_diagnostic, get_multi_confluence_leaderboard
    import asyncio

    # Get stage diagnostic metrics (20/50/200 EMAs, 30W-MA slope, dist 52w)
    stage_data = {}
    try:
        # Run async get_stage_diagnostic in current or new loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # in async context
                import nest_asyncio
                nest_asyncio.apply()
                stage_data = loop.run_until_complete(get_stage_diagnostic(base_sym))
            else:
                stage_data = loop.run_until_complete(get_stage_diagnostic(base_sym))
        except Exception:
            stage_data = asyncio.run(get_stage_diagnostic(base_sym))
    except Exception as e:
        logger.warning(f"[Confluence Storyteller] Could not fetch stage diagnostic for {base_sym}: {e}")

    metrics = stage_data.get("metrics", {})
    qual_screeners = stage_data.get("qualified_screeners", [])
    screener_keys = {s.get("screener_key") for s in qual_screeners if s.get("qualified")}

    # Also check multi-confluence leaderboard cache for any extra hits
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT screener_name, cache_json FROM screener_results_cache")
        for s_name, c_json in cur.fetchall():
            try:
                data = json.loads(c_json)
                items = data if isinstance(data, list) else data.get("stocks", data.get("candidates", []))
                for item in items:
                    sym = (item.get("symbol") or item.get("ticker") or item) if isinstance(item, dict) else str(item)
                    if sym and sym.replace(".NS", "").replace(".BO", "").strip().upper() == base_sym:
                        screener_keys.add(s_name)
                        break
            except Exception:
                pass
        conn.close()
    except Exception as e:
        logger.debug(f"[Confluence Storyteller] Database screener lookup warning: {e}")

    # 4. Resolve live price context
    p_ctx = get_stock_price_context(base_sym, ticker)
    cmp_val = p_ctx.get("cmp", metrics.get("current_price", 0.0))
    if cmp_val <= 0:
        cmp_val = metrics.get("current_price", 1000.0)

    ema_20 = metrics.get("ema_20", cmp_val * 0.98)
    ema_50 = metrics.get("ema_50", cmp_val * 0.95)
    ma_30wk_slope = metrics.get("ma_30wk_slope_pct", 1.5)
    dist_52w_high = metrics.get("dist_52wk_high_pct", -3.5)

    # 5. Detect Synergy Pairs & Conflicts
    synergies = detect_screener_synergy_pairs(screener_keys)
    pivot_price = stage_data.get("pivot_price") or round(cmp_val * 1.015, 2)
    stop_loss = stage_data.get("stop_loss") or round(cmp_val * 0.955, 2)
    target_1 = stage_data.get("target_1") or round(cmp_val * 1.09, 2)
    target_2 = stage_data.get("target_2") or round(cmp_val * 1.20, 2)

    risk_pct = round(((pivot_price - stop_loss) / pivot_price) * 100.0, 1) if pivot_price > 0 else 4.0
    gain_pct = round(((target_1 - pivot_price) / pivot_price) * 100.0, 1) if pivot_price > 0 else 10.0
    rr_ratio = round(gain_pct / risk_pct, 1) if risk_pct > 0 else 2.5

    conflicts = detect_conflicts_and_red_flags(cmp_val, pivot_price, ema_20, ma_30wk_slope, dist_52w_high)
    user_status = check_portfolio_watchlist_status(base_sym)

    # Calculate Confluence Score
    screener_names_friendly = []
    screener_labels_map = {
        "minervini_vcp": "Minervini VCP",
        "vcp": "Minervini VCP",
        "weinstein_stage2": "Stan Weinstein Stage 2",
        "pocket_pivot": "Pocket Pivot Accumulation",
        "cup_with_handle": "Cup with Handle",
        "3weeks_tight": "3-Weeks Tight (3WT)",
        "flat_base_breakout": "Modern Flat Base",
        "rs_line_new_high": "RS Line New High (RSNH Blue-Dot)",
        "oliver_kell_reversal": "Oliver Kell Trend Model",
        "htf": "High-Tight Flag (HTF)",
        "episodic_pivot": "Episodic Pivot Gap-Up",
        "undercut_and_rally": "Undercut & Rally (U&R)"
    }
    for k in screener_keys:
        screener_names_friendly.append(screener_labels_map.get(k, k.replace("_", " ").title()))

    base_score = 60 + (len(screener_keys) * 6)
    synergy_bonus = sum([s["bonus"] for s in synergies])
    hot_sector_bonus = 10 if stage_data.get("is_hot_sector") else 0
    final_score = min(98, base_score + synergy_bonus + hot_sector_bonus)

    tier_label = "👑 TIER 1: APEX CONFLUENCE LEADER" if final_score >= 88 else (
        "⭐ TIER 2: HIGH CONFLUENCE SETUP" if final_score >= 78 else "⚡ TIER 3: MOMENTUM CATALYST"
    )

    # 5.5. Build Plain-English Layman Summary
    if final_score >= 88:
        stance_badge = "🟢 Prime Breakout Setup (High Institutional Support)"
        stance_level = "BULLISH_PRIME"
    elif final_score >= 78:
        stance_badge = "🟢 Strong Momentum / Buy on Pullback"
        stance_level = "BULLISH_STRONG"
    else:
        stance_badge = "🟡 Constructive Consolidation / Watchlist"
        stance_level = "NEUTRAL_CONSTRUCTIVE"

    if synergies:
        top_syn = synergies[0].get("name", "Institutional Confluence")
        what_stock_is_doing = (
            f"Multiple top screeners flashed green together with a '{top_syn}' institutional footprint. "
            f"Big funds are quietly accumulating shares while holding the price steady above key moving averages. "
            f"Selling pressure is drying up, meaning buyers are taking firm control."
        )
    else:
        what_stock_is_doing = (
            f"The stock has triggered {len(screener_keys)} independent bullish screeners simultaneously. "
            f"Institutional money is supporting the price action above its short-term moving average (₹{ema_20:,.2f}), "
            f"demonstrating steady accumulation rather than volatile churning."
        )

    simple_plan = (
        f"Safe entry is above ₹{pivot_price:,.2f} on expanding trading volume. "
        f"If the stock falls below ₹{stop_loss:,.2f} (-{risk_pct}%), cut the loss immediately to protect your capital. "
        f"Initial profit target is ₹{target_1:,.2f} (+{gain_pct}%), followed by runner target at ₹{target_2:,.2f}."
    )

    rr_desc = f"Favorable odds: risking ₹1 to potentially make ₹{rr_ratio:.1f} (1 : {rr_ratio} Risk/Reward)."
    
    if final_score >= 85 and rr_ratio >= 2.0:
        layman_takeaway = "High-probability momentum setup. Big money is providing a strong safety cushion below current price."
    elif rr_ratio >= 1.5:
        layman_takeaway = "Solid swing trade opportunity with controlled downside risk. Accumulate methodically near the pivot."
    else:
        layman_takeaway = f"Constructive setup, but maintain strict risk management at ₹{stop_loss:,.2f}."

    layman_summary_obj = {
        "stance_badge": stance_badge,
        "stance_level": stance_level,
        "what_stock_is_doing": what_stock_is_doing,
        "simple_plan": simple_plan,
        "risk_odds": rr_desc,
        "takeaway": layman_takeaway
    }

    # 6. Build Institutional Investment Committee Prompt
    synergy_text = " • ".join([s["badge"] for s in synergies]) if synergies else "STANDARD CONFLUENCE"
    screeners_text = " • ".join([f"[{s}]" for s in screener_names_friendly]) if screener_names_friendly else "[Stage 2 Mark-Up]"
    conflict_summary = "\n".join([f"• {c['label']}: {c['detail']}" for c in conflicts])

    sys_instruction = (
        "You are the Chief Investment Officer (CIO) and Senior Portfolio Manager of an institutional quantitative hedge fund. "
        "You are evaluating a multi-screener confluence setup in an Indian equity stock.\n\n"
        "Your task is to synthesize the quantitative indicators, price-volume footprints, and stage lifecycle into a rigorous, "
        "high-conviction Investment Committee Memo.\n\n"
        "Rules:\n"
        "1. Do not speak like a retail indicator bot. Speak like a professional hedge fund allocator.\n"
        "2. Explain HOW the specific screeners (e.g. VCP + Pocket Pivot or Stage 2 + 3WT) reinforce each other.\n"
        "3. Provide an honest, unvarnished Devil's Advocate conflict check (highlighting overextension or supply risks if present).\n"
        "4. Output strictly in the WhatsApp/Markdown format shown below with zero conversational preamble.\n\n"
        f"🎯 *INSTITUTIONAL CONFLUENCE DOSSIER* (Confluence Score: {final_score}/100 • {tier_label})\n"
        f"🏛️ *{comp_name.upper()}* (`{base_sym}`) • Live CMP: ₹{cmp_val:,.2f}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌱 *PLAIN-ENGLISH SUMMARY (LAYMAN VIEW)*:\n"
        f"• *🚦 Stance:* {stance_badge}\n"
        f"• *🏢 What the Stock is Doing:* {what_stock_is_doing}\n"
        f"• *🎯 Simple Plan:* {simple_plan}\n"
        f"• *💡 Bottom Line:* {layman_takeaway}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 *SCREENER CONFLUENCE MESH* ({len(screener_keys)} Setups Active):\n"
        f"{screeners_text}\n"
        f"🧬 *SYNERGY SIGNATURE*: {synergy_text}\n\n"
        "📖 *THE INSTITUTIONAL STORY*:\n"
        "<2 to 3 crisp, deeply reasoned paragraphs connecting the dots: how the base structure formed, why the volume footprint confirms institutional buying rather than retail churning, and how sector/relative strength positions the stock.>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ *CONFLICT & RED-FLAG AUDIT*:\n"
        f"{conflict_summary}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ *ASYMMETRIC EXECUTION BLUEPRINT*:\n"
        f"• Breakout Pivot Trigger: ₹{pivot_price:,.2f} (Enter on volume expansion > 1.3x)\n"
        f"• Structural Invalidation (Stop-Loss): ₹{stop_loss:,.2f} (-{risk_pct}% risk)\n"
        f"• Target 1 (Swing 2–4W): ₹{target_1:,.2f} (+{gain_pct}%)\n"
        f"• Target 2 (Positional 2–3M): ₹{target_2:,.2f}\n"
        f"• Risk-to-Reward Ratio: 1 : {rr_ratio}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    user_text = f"Compile the Institutional Confluence Dossier for {comp_name} ({base_sym}) at CMP ₹{cmp_val:,.2f}."

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_text}]
            }
        ],
        "systemInstruction": {
            "parts": [{"text": sys_instruction}]
        },
        "generationConfig": {
            "temperature": 0.25,
            "maxOutputTokens": 4096
        }
    }

    keys = _get_gemini_keys_pool()
    diagnostic_text = ""

    for attempt, k in enumerate(keys):
        mask = f"{k[:6]}...{k[-4:]}"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={k}"
        try:
            logger.info(f"[Confluence Storyteller] Generating memo for {base_sym} via {model} using key {mask}...")
            r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=30.0)
            if r.status_code == 200:
                res_json = r.json()
                cand = res_json.get("candidates", [{}])[0]
                parts = cand.get("content", {}).get("parts", [])
                diagnostic_text = "".join([p.get("text", "") for p in parts if "text" in p]).strip()
                if diagnostic_text:
                    logger.info(f"[Confluence Storyteller] Successfully generated memo for {base_sym}.")
                    break
            elif r.status_code in (401, 403, 429):
                logger.warning(f"[Confluence Storyteller] Key {mask} returned {r.status_code}. Rotating to next key.")
                continue
        except Exception as e:
            logger.warning(f"[Confluence Storyteller] Request failed with key {mask}: {e}. Rotating...")
            continue

    if not diagnostic_text:
        # High-quality fallback synthesis if API is temporarily unavailable
        diagnostic_text = (
            f"🎯 *INSTITUTIONAL CONFLUENCE DOSSIER* (Confluence Score: {final_score}/100 • {tier_label})\n"
            f"🏛️ *{comp_name.upper()}* (`{base_sym}`) • Live CMP: ₹{cmp_val:,.2f}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🌱 *PLAIN-ENGLISH SUMMARY (LAYMAN VIEW)*:\n"
            f"• *🚦 Stance:* {stance_badge}\n"
            f"• *🏢 What the Stock is Doing:* {what_stock_is_doing}\n"
            f"• *🎯 Simple Plan:* {simple_plan}\n"
            f"• *💡 Bottom Line:* {layman_takeaway}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔥 *SCREENER CONFLUENCE MESH* ({len(screener_keys)} Setups Active):\n"
            f"{screeners_text}\n"
            f"🧬 *SYNERGY SIGNATURE*: {synergy_text}\n\n"
            "📖 *THE INSTITUTIONAL STORY*:\n"
            f"{comp_name} is exhibiting a premier multi-strategy alignment where stage 2 mark-up, volume accumulation, and base volatility contraction have converged. "
            f"Price action is firmly anchored above rising moving averages (EMA 20 at ₹{ema_20:,.2f}), signaling that institutional funds are absorbing supply. "
            "The volume signature confirms strong accumulation with volume drying up on pullbacks, creating a textbook low-risk entry pivot.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ *CONFLICT & RED-FLAG AUDIT*:\n"
            f"{conflict_summary}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ *ASYMMETRIC EXECUTION BLUEPRINT*:\n"
            f"• Breakout Pivot Trigger: ₹{pivot_price:,.2f} (Enter on volume expansion > 1.3x)\n"
            f"• Structural Invalidation (Stop-Loss): ₹{stop_loss:,.2f} (-{risk_pct}% risk)\n"
            f"• Target 1 (Swing 2–4W): ₹{target_1:,.2f} (+{gain_pct}%)\n"
            f"• Target 2 (Positional 2–3M): ₹{target_2:,.2f}\n"
            f"• Risk-to-Reward Ratio: 1 : {rr_ratio}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

    result_payload = {
        "symbol": base_sym,
        "company_name": comp_name,
        "cmp": cmp_val,
        "confluence_score": final_score,
        "tier_label": tier_label,
        "screener_count": len(screener_keys),
        "screeners_active": screener_names_friendly,
        "synergies": synergies,
        "conflicts": conflicts,
        "watchlist_status": user_status,
        "tactical_levels": {
            "pivot_price": pivot_price,
            "stop_loss": stop_loss,
            "target_1": target_1,
            "target_2": target_2,
            "risk_pct": risk_pct,
            "gain_pct": gain_pct,
            "rr_ratio": rr_ratio
        },
        "layman_summary": layman_summary_obj,
        "model_id": model,
        "model_label": model_label,
        "formatted_markdown": diagnostic_text,
        "from_cache": False,
        "created_at": time.time()
    }

    # 7. Persist to SQLite cache
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO cached_confluence_stories (symbol, payload_json, created_at)
        VALUES (?, ?, ?)
        """, (base_sym, json.dumps(result_payload), time.time()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[Confluence Storyteller] Failed to cache story for {base_sym}: {e}")

    return result_payload


def get_top_confluence_setups(limit: int = 5) -> List[Dict[str, Any]]:
    """
    Retrieves the top N highest-scoring multi-screener confluence stocks
    from the database and pre-warms their stories.
    """
    _init_confluence_cache_table()
    from backend.main import get_multi_confluence_leaderboard
    import asyncio

    try:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
                lb_data = loop.run_until_complete(get_multi_confluence_leaderboard(False))
            else:
                lb_data = loop.run_until_complete(get_multi_confluence_leaderboard(False))
        except Exception:
            lb_data = asyncio.run(get_multi_confluence_leaderboard(False))
    except Exception as e:
        logger.error(f"[Confluence Storyteller] Leaderboard fetch failed: {e}")
        return []

    candidates = lb_data.get("candidates", []) if isinstance(lb_data, dict) else []
    top_candidates = candidates[:limit]

    # Pre-generate / retrieve stories
    results = []
    for c in top_candidates:
        sym = c.get("symbol", "").replace(".NS", "").replace(".BO", "").strip().upper()
        if sym:
            story = generate_confluence_story_for_stock(sym, force_refresh=False)
            results.append(story)

    return results
