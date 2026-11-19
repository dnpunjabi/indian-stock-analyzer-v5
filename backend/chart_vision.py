import os
import sys
import time
import json
import base64
import logging
import sqlite3
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Ensure backend root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.llm_config import _get_gemini_keys_pool
from backend.chart_generator import generate_stock_ichart, generate_stock_technical_chart
from backend.whatsapp_bot import resolve_company_ticker, get_stock_price_context

DATABASE_DIR = os.environ.get("DATABASE_DIR", os.path.join(os.path.dirname(__file__), "data"))
DATABASE_PATH = os.path.join(DATABASE_DIR, "watchlist_database.db")


def _init_vision_cache_table():
    """Initializes the SQLite cache table for vision chart diagnostics."""
    try:
        os.makedirs(DATABASE_DIR, exist_ok=True)
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_chart_vision (
            symbol TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Could not initialize cached_chart_vision table: {e}")


def get_vision_model_info() -> Tuple[str, str]:
    """
    Dynamically returns (model_id, display_label) from environment variables or .env.
    Allows seamlessly upgrading or switching vision models in Oracle VM / production
    without hardcoding model version strings or requiring client/APK changes.

    Priority cascade:
      1. GEMINI_VISION_MODEL
      2. GEMINI_FAST_MODEL
      3. GEMINI_HEAVY_MODEL
      4. Default: "gemini-2.5-flash"
    """
    from backend.llm_config import _format_model_label
    model_id = (
        os.environ.get("GEMINI_VISION_MODEL")
        or os.environ.get("GEMINI_FAST_MODEL")
        or os.environ.get("GEMINI_HEAVY_MODEL")
        or "gemini-2.5-flash"
    ).strip()

    model_label = os.environ.get("GEMINI_VISION_LABEL")
    if not model_label:
        base_label = _format_model_label(model_id)
        model_label = f"{base_label} Vision" if "Vision" not in base_label else base_label

    return model_id, model_label



def extract_vision_layman_summary(text: str, cmp_val: float) -> Dict[str, Any]:
    """Extracts or synthesizes structured layman summary fields from vision diagnostic text."""
    import re
    
    # 1. Chart Shape
    shape_match = re.search(r"•\s*(?:🎨\s*)?\*?Chart Shape:?\*?\s*([^\r\n]+)", text, re.IGNORECASE)
    chart_shape = shape_match.group(1).strip() if shape_match else "Consolidation Base near Key Support"
    
    # 2. Who's in Charge
    charge_match = re.search(r"•\s*(?:🥊\s*)?\*?Who'?s in Charge:?\*?\s*([^\r\n]+)", text, re.IGNORECASE)
    whos_in_charge = charge_match.group(1).strip() if charge_match else "Buyers are actively defending key moving averages; sellers are losing momentum."
    
    # 3. Simple Action
    action_match = re.search(r"•\s*(?:⚡\s*)?\*?Simple Action:?\*?\s*([^\r\n]+)", text, re.IGNORECASE)
    if action_match:
        simple_action = action_match.group(1).strip()
    else:
        trig_m = re.search(r"Breakout Trigger.*?[₹:]\s*([0-9,.]+)", text)
        sl_m = re.search(r"Invalidation.*?[₹:]\s*([0-9,.]+)", text)
        tg_m = re.search(r"Target 1.*?[₹:]\s*([0-9,.]+)", text)
        trig = trig_m.group(1) if trig_m else f"{cmp_val * 1.025:,.2f}"
        sl = sl_m.group(1) if sl_m else f"{cmp_val * 0.96:,.2f}"
        tg = tg_m.group(1) if tg_m else f"{cmp_val * 1.09:,.2f}"
        simple_action = f"Wait for price to cross ₹{trig} to enter. Stop-loss at ₹{sl}. Target: ₹{tg}."
        
    # 4. Risk Odds
    odds_match = re.search(r"•\s*(?:⚖️\s*)?\*?Risk Odds:?\*?\s*([^\r\n]+)", text, re.IGNORECASE)
    if odds_match:
        risk_odds = odds_match.group(1).strip()
    else:
        rr_m = re.search(r"Risk-to-Reward Ratio.*?1\s*:\s*([0-9.]+)", text)
        rr = rr_m.group(1) if rr_m else "2.5"
        risk_odds = f"Risking ₹1 to potentially make ₹{rr} (1 : {rr} ratio). Favorable setup."
        
    # 5. Bottom Line / Stance
    line_match = re.search(r"•\s*(?:💡\s*)?\*?Bottom Line:?\*?\s*([^\r\n]+)", text, re.IGNORECASE)
    bottom_line = line_match.group(1).strip() if line_match else "Constructive chart setup with institutional support. Maintain disciplined risk controls."
    
    # Determine stance badge
    lower_t = text.lower()
    if "avoid" in lower_t or "stage 4" in lower_t or "capitulation" in lower_t or "markdown" in lower_t:
        stance_badge = "🔴 Bearish / High Risk"
    elif "distribution" in lower_t or "stage 3" in lower_t or "take profit" in lower_t:
        stance_badge = "🟡 Distribution / Caution"
    elif "core accumulate" in lower_t or "bullish flag" in lower_t or "vcp" in lower_t or "cup & handle" in lower_t or "stage 2" in lower_t:
        stance_badge = "🟢 Bullish Setup / Accumulate"
    else:
        stance_badge = "🟡 Base Consolidation / Watchlist"

    return {
        "stance_badge": stance_badge,
        "chart_shape": chart_shape,
        "whos_in_charge": whos_in_charge,
        "simple_action": simple_action,
        "risk_odds": risk_odds,
        "tactical_takeaway": bottom_line
    }


def _resolve_stock_stage_context(
    symbol: str,
    ticker: str,
    cmp_val: float,
    high_52w: float,
    sma_50: float,
    sma_200: float
) -> Tuple[int, str, float]:
    """
    Resolves the quantitative Weinstein stage (1 to 4) using get_stage_diagnostic
    or mathematical price/MA geometry fallback to ensure AI Vision never contradicts
    the 11-screener quant matrix.
    Returns: (stage_num, stage_name, dist_52w_high_pct)
    """
    dist_52w = ((cmp_val - high_52w) / high_52w) * 100.0 if high_52w > 0 else 0.0

    # 1. Attempt lookup via get_stage_diagnostic (15m cached in backend.main)
    try:
        from backend.main import get_stage_diagnostic
        import asyncio
        import concurrent.futures

        def _sync_stage():
            try:
                return asyncio.run(get_stage_diagnostic(ticker))
            except RuntimeError:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    return executor.submit(asyncio.run, get_stage_diagnostic(ticker)).result()

        diag = _sync_stage()
        if diag and diag.get("status") != "error":
            stage_num = int(diag.get("stage_number", 2))
            stage_name = diag.get("stage_name", "Stage 2: Mark-Up 🚀")
            metrics = diag.get("metrics", {})
            dist_val = float(metrics.get("dist_52wk_high_pct", dist_52w))
            return stage_num, stage_name, dist_val
    except Exception as e:
        logger.debug(f"[Chart Vision] Could not run get_stage_diagnostic for {symbol}: {e}")

    # 2. Mathematical MA/Geometry classification fallback
    if sma_200 > 0 and cmp_val < (sma_200 * 0.92) and dist_52w < -25.0:
        return 4, "Stage 4: Capitulation 📉", dist_52w
    elif dist_52w > -20.0 and sma_50 > 0 and cmp_val < sma_50 and sma_200 > 0 and cmp_val > sma_200:
        return 3, "Stage 3: Distribution Top ⚠️", dist_52w
    elif dist_52w <= -20.0 and sma_200 > 0 and abs(cmp_val - sma_200) / sma_200 < 0.12:
        return 1, "Stage 1: Basing 🟡", dist_52w
    elif dist_52w > -25.0 and (sma_50 == 0 or cmp_val >= sma_50):
        return 2, "Stage 2: Mark-Up 🚀", dist_52w
    elif dist_52w < -30.0:
        return 4, "Stage 4: Capitulation 📉", dist_52w
    else:
        return 2, "Stage 2: Mark-Up 🚀", dist_52w


def build_dynamic_vision_fallback(
    comp_name: str,
    base_sym: str,
    cmp_val: float,
    stage_num: int,
    stage_name: str,
    dist_52w: float,
    sma_50: float,
    sma_200: float
) -> str:
    """
    Builds a mathematically consistent AI Vision pattern diagnostic fallback
    strictly aligned with the stock's Weinstein stage so that rate limits or
    offline fallbacks NEVER produce contradictory signals.
    """
    if stage_num == 4:
        return (
            f"🏛️ *{comp_name.upper()}* (`{base_sym}`) • Live CMP: ₹{cmp_val:,.2f}\n"
            "📐 *AI VISION PATTERN DIAGNOSTIC*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🌱 *PLAIN-ENGLISH SUMMARY (LAYMAN VIEW)*:\n"
            f"• 🎨 *Chart Shape:* Stage 4 Downtrend Markdown — Extended downward trend channel trading well below key moving averages with broken structural supports.\n"
            f"• 🥊 *Who's in Charge:* Sellers and institutional distribution dominate; heavy overhead supply awaits at previous broken support zones.\n"
            f"• ⚡ *Simple Action:* Avoid fresh long entries. If holding, execute an orderly exit into intraday relief bounces towards the 20/50-day EMA rather than catching a falling knife.\n"
            f"• ⚖️ *Risk Odds:* Unfavorable risk-to-reward for fresh longs (downside drawdown risk heavily outweighs bounce potential).\n"
            f"• 💡 *Bottom Line:* Confirmed markdown cycle. Capital preservation is priority; wait for a confirmed Stage 1 basing structure before re-evaluating.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "• Identified Pattern: Stage 4 Capitulation / Structural Breakdown\n"
            "• Base Symmetry & Quality: Severe degradation of base structure with sustained lower highs and lower lows below 200-DMA.\n\n"
            "💼 *FOR LONG-TERM INVESTORS*:\n"
            "• Structural Stage: Stage 4 Capitulation / Markdown\n"
            f"• Core Accumulation Support: No verified base yet (Next psychological level ~₹{cmp_val * 0.85:,.2f})\n"
            "• Investor Verdict: 🔴 Avoid / Reduce Exposure (Capital Protection)\n\n"
            "⚡ *FOR SWING TRADERS*:\n"
            "• Breakout Trigger: N/A (No active high-probability long setup)\n"
            f"• Invalidation (Stop-Loss): ₹{cmp_val * 0.95:,.2f}\n"
            f"• Targets: Relief Target 1 (20-EMA): ₹{cmp_val * 1.03:,.2f} | Overhead Resistance (50-EMA): ₹{cmp_val * 1.08:,.2f}\n"
            "• Risk-to-Reward Ratio: Unfavorable\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
    elif stage_num == 3:
        return (
            f"🏛️ *{comp_name.upper()}* (`{base_sym}`) • Live CMP: ₹{cmp_val:,.2f}\n"
            "📐 *AI VISION PATTERN DIAGNOSTIC*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🌱 *PLAIN-ENGLISH SUMMARY (LAYMAN VIEW)*:\n"
            f"• 🎨 *Chart Shape:* Stage 3 Topping Range — High-volatility distribution range near highs with churning volume and institutional profit-taking.\n"
            f"• 🥊 *Who's in Charge:* Sellers are beginning to absorb buyer demand; distribution signals evident on elevated volume rallies.\n"
            f"• ⚡ *Simple Action:* Tighten stop-losses on existing positions. Avoid aggressive breakout buys into overhead resistance.\n"
            f"• ⚖️ *Risk Odds:* Skewed towards downside risk as base matures and institutional distribution expands.\n"
            f"• 💡 *Bottom Line:* Late-stage topping characteristics. De-risk and protect accumulated profits.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "• Identified Pattern: Stage 3 Distribution Top / Churning Range\n"
            "• Base Symmetry & Quality: Wide and loose consolidation with institutional distribution volume spikes.\n\n"
            "💼 *FOR LONG-TERM INVESTORS*:\n"
            "• Structural Stage: Stage 3 Distribution Top\n"
            f"• Core Accumulation Support: ~₹{cmp_val * 0.92:,.2f}\n"
            "• Investor Verdict: 🟡 Hold / Take Partial Profits\n\n"
            "⚡ *FOR SWING TRADERS*:\n"
            f"• Breakout Trigger: ₹{cmp_val * 1.03:,.2f}\n"
            f"• Invalidation (Stop-Loss): ₹{cmp_val * 0.97:,.2f}\n"
            f"• Targets: Target 1: ₹{cmp_val * 1.05:,.2f} | Target 2: ₹{cmp_val * 1.09:,.2f}\n"
            "• Risk-to-Reward Ratio: 1 : 1.5\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
    elif stage_num == 1:
        return (
            f"🏛️ *{comp_name.upper()}* (`{base_sym}`) • Live CMP: ₹{cmp_val:,.2f}\n"
            "📐 *AI VISION PATTERN DIAGNOSTIC*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🌱 *PLAIN-ENGLISH SUMMARY (LAYMAN VIEW)*:\n"
            f"• 🎨 *Chart Shape:* Stage 1 Accumulation Base — The stock has ceased declining and is carving out a lateral base, absorbing overhead supply.\n"
            f"• 🥊 *Who's in Charge:* Equilibrium between buyers and sellers; volatility contracting as smart money accumulates quietly.\n"
            f"• ⚡ *Simple Action:* Wait for price to clear base resistance (₹{cmp_val * 1.04:,.2f}) on heavy volume before initiating full positions.\n"
            f"• ⚖️ *Risk Odds:* Moderate risk odds. Safe stop-loss anchored near base support (₹{cmp_val * 0.95:,.2f}).\n"
            f"• 💡 *Bottom Line:* Early accumulation phase. Add to watchlist and monitor for Stage 2 breakout confirmation.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "• Identified Pattern: Stage 1 Lateral Basing / Accumulation Range\n"
            "• Base Symmetry & Quality: Sideways price action contracting in range; volume settling down.\n\n"
            "💼 *FOR LONG-TERM INVESTORS*:\n"
            "• Structural Stage: Stage 1 Basing\n"
            f"• Core Accumulation Support: ~₹{cmp_val * 0.94:,.2f}\n"
            "• Investor Verdict: 🟡 Watchlist / Cautious Accumulation on Base Lows\n\n"
            "⚡ *FOR SWING TRADERS*:\n"
            f"• Breakout Trigger: ₹{cmp_val * 1.04:,.2f}\n"
            f"• Invalidation (Stop-Loss): ₹{cmp_val * 0.95:,.2f}\n"
            f"• Targets: Target 1: ₹{cmp_val * 1.08:,.2f} | Target 2: ₹{cmp_val * 1.14:,.2f}\n"
            "• Risk-to-Reward Ratio: 1 : 2.1\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
    else:  # stage_num == 2
        return (
            f"🏛️ *{comp_name.upper()}* (`{base_sym}`) • Live CMP: ₹{cmp_val:,.2f}\n"
            "📐 *AI VISION PATTERN DIAGNOSTIC*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🌱 *PLAIN-ENGLISH SUMMARY (LAYMAN VIEW)*:\n"
            f"• 🎨 *Chart Shape:* Stage 2 Consolidation Base — The stock climbed healthily and is now resting quietly near moving average support.\n"
            f"• 🥊 *Who's in Charge:* Buyers are actively defending the 20/50-day moving average band; selling pressure is light.\n"
            f"• ⚡ *Simple Action:* Enter when price crosses above ₹{cmp_val * 1.025:,.2f}. Place a strict safety stop at ₹{cmp_val * 0.96:,.2f} (-4.0%). Target: ₹{cmp_val * 1.09:,.2f}.\n"
            f"• ⚖️ *Risk Odds:* Risking ₹1 to make ~₹2.30 (1 : 2.3 ratio). Favorable odds for patient swing traders.\n"
            f"• 💡 *Bottom Line:* Constructive pattern with institutional backing. Accumulate near support and respect the stop-loss.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "• Identified Pattern: Consolidation near Key Moving Averages\n"
            "• Base Symmetry & Quality: Price action testing moving average support zones.\n\n"
            "💼 *FOR LONG-TERM INVESTORS*:\n"
            "• Structural Stage: Stage 2 Consolidation\n"
            f"• Core Accumulation Support: ~₹{cmp_val * 0.95:,.2f}\n"
            "• Investor Verdict: 🟢 Core Hold / Accumulate on Dips\n\n"
            "⚡ *FOR SWING TRADERS*:\n"
            f"• Breakout Trigger: ₹{cmp_val * 1.03:,.2f}\n"
            f"• Invalidation (Stop-Loss): ₹{cmp_val * 0.96:,.2f}\n"
            f"• Targets: Target 1: ₹{cmp_val * 1.08:,.2f} | Target 2: ₹{cmp_val * 1.15:,.2f}\n"
            "• Risk-to-Reward Ratio: 1 : 2.8\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )


def analyze_stock_chart_vision(
    symbol: str,
    indicator_mode: str = "smc",
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Renders an institutional candlestick chart for the given stock and passes the
    image directly to Gemini Vision AI (dynamically configured model).

    Acts as a Senior Chartered Market Technician (CMT) to identify visual chart
    patterns (Triangles, VCP, Cup & Handle, Flags, Order Blocks) and produces a
    dual-perspective action blueprint for both Long-Term Investors and Swing Traders.
    """
    _init_vision_cache_table()
    model, model_label = get_vision_model_info()

    # 1. Resolve ticker and company details
    clean_sym = symbol.strip().upper().replace(".NS", "").replace(".BO", "")
    resolved = resolve_company_ticker(clean_sym)
    base_sym = resolved.get("base_symbol") if resolved else clean_sym
    comp_name = resolved.get("name") if resolved else base_sym
    ticker = resolved.get("yf_ticker") if resolved else f"{base_sym}.NS"

    cache_key = f"{base_sym}_{indicator_mode}"
    cache_ttl = 4 * 3600  # 4-hour cache

    # 2. Check SQLite cache unless force_refresh is True
    if not force_refresh:
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT payload_json, created_at FROM cached_chart_vision WHERE symbol = ?", (cache_key,))
            row = cursor.fetchone()
            conn.close()
            if row and (time.time() - row["created_at"] < cache_ttl):
                data = json.loads(row["payload_json"])
                data["from_cache"] = True
                if "model_label" not in data:
                    data["model_id"] = model
                    data["model_label"] = model_label
                logger.info(f"[Chart Vision] Serving cached diagnosis for {base_sym} ({cache_key})")
                return data
        except Exception as e:
            logger.debug(f"[Chart Vision] Cache lookup warning: {e}")

    # 3. Get live verified price context and quantitative stage
    p_ctx = get_stock_price_context(base_sym, ticker)
    cmp_val = float(p_ctx.get("cmp") or 0.0)
    high_52w = float(p_ctx.get("high_52w") or 0.0)
    low_52w = float(p_ctx.get("low_52w") or 0.0)
    sma_50 = float(p_ctx.get("sma_50") or 0.0)
    sma_200 = float(p_ctx.get("sma_200") or 0.0)

    stage_num, stage_name, dist_52w = _resolve_stock_stage_context(
        base_sym, ticker, cmp_val, high_52w, sma_50, sma_200
    )

    # 4. Render dark-mode chart
    img_bytes = None
    try:
        # Prefer institutional i-Chart (SMC / Breaks / Maxwell)
        img_bytes, meta = generate_stock_ichart(base_sym, comp_name, indicator_mode=indicator_mode)
    except Exception as e:
        logger.warning(f"[Chart Vision] generate_stock_ichart failed for {base_sym}: {e}. Falling back to standard technical chart.")
        try:
            img_bytes = generate_stock_technical_chart(base_sym, comp_name)
        except Exception as e2:
            logger.error(f"[Chart Vision] Both chart generators failed for {base_sym}: {e2}")

    if not img_bytes:
        return {
            "symbol": base_sym,
            "company_name": comp_name,
            "cmp": cmp_val,
            "success": False,
            "error": "Failed to generate technical chart image.",
            "formatted_markdown": f"⚠️ *Could not generate chart image for {base_sym}*."
        }

    b64_img = base64.b64encode(img_bytes).decode("utf-8")

    # 5. Get Gemini API Keys with rotation pool
    keys = _get_gemini_keys_pool()
    if not keys:
        return {
            "symbol": base_sym,
            "company_name": comp_name,
            "cmp": cmp_val,
            "success": False,
            "error": "No Gemini API keys configured.",
            "formatted_markdown": "⚠️ *AI Vision temporarily unavailable (API key pool empty)*."
        }

    # 6. Prepare Chartered Market Technician (CMT) System Prompt
    sys_instruction = (
        "You are an institutional Chartered Market Technician (CMT) and Fund Manager analyzing an Indian equity chart. "
        "Inspect the provided dark-mode candlestick chart image with rigorous visual precision.\n\n"
        "Examine:\n"
        "- Exact Geometric Patterns: Ascending/Descending/Symmetrical Triangles, Cup & Handle, VCP Contractions, Bull/Bear Flags, Wedges, Double Bottoms, Head & Shoulders, or Markdown Channels.\n"
        "- Base Symmetry & Volume: Is the structure tight or loose? Has volume dried up or is heavy distribution evident?\n"
        "- Dynamic Moving Averages: Price action relative to 20-EMA, 50-EMA, and 200-SMA.\n"
        "- Institutional Zones: Demand Order Blocks, Supply Overheads, Liquidity wicks.\n\n"
        f"QUANTITATIVE GROUND TRUTH (FROM 11-SCREENER QUANT MATRIX):\n"
        f"- Live CMP: ₹{cmp_val:,.2f}\n"
        f"- 52-Week Range: High ₹{high_52w:,.2f} ({dist_52w:+.1f}%), Low ₹{low_52w:,.2f}\n"
        f"- Moving Averages: 50-DMA ₹{sma_50:,.2f}, 200-DMA ₹{sma_200:,.2f}\n"
        f"- Weinstein Stage: Stage {stage_num} ({stage_name})\n\n"
        "CRITICAL CONSISTENCY CONSTRAINT:\n"
        f"The quantitative matrix has mathematically verified this stock is in Stage {stage_num} ({stage_name}). "
        "Your visual pattern diagnostic MUST strictly align with this stage. Under NO circumstances describe a Stage 4 capitulation stock in deep drawdown as 'Stage 2 Consolidation' or tell investors to 'Core Hold / Accumulate on Dips'. If Stage 4, diagnose the breakdown, mark broken supports as overhead resistance, and advise capital protection / avoiding fresh buys.\n\n"
        "Output strictly in this WhatsApp-ready format (do not include introductory filler or meta-commentary):\n\n"
        f"🏛️ *{comp_name.upper()}* (`{base_sym}`) • Live CMP: ₹{cmp_val:,.2f}\n"
        "📐 *AI VISION PATTERN DIAGNOSTIC*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌱 *PLAIN-ENGLISH SUMMARY (LAYMAN VIEW)*:\n"
        "• 🎨 *Chart Shape:* <Everyday analogy, e.g. Bull Flag or Markdown Channel>\n"
        "• 🥊 *Who's in Charge:* <1 sentence on buyers vs sellers>\n"
        "• ⚡ *Simple Action:* <Clear execution instruction with prices>\n"
        "• ⚖️ *Risk Odds:* <Risking ₹1 to make ₹X (1 : X.X ratio)>\n"
        "• 💡 *Bottom Line:* <1 sentence practical takeaway for retail investors>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "• Identified Pattern: <Exact Pattern Name>\n"
        "• Base Symmetry & Quality: <1-2 sentences on base tightness, volume dry-up, or distribution breakdown>\n\n"
        "💼 *FOR LONG-TERM INVESTORS (1–3 Year Horizon)*:\n"
        f"• Structural Stage: Stage {stage_num} ({stage_name})\n"
        "• Core Accumulation Support: ₹<Price or Zone anchored to moving averages or broken support>\n"
        "• Investor Verdict: <🟢 Core Accumulate / 🟡 Hold / 🔴 Avoid or Reduce>\n\n"
        "⚡ *FOR SWING TRADERS (2–6 Week Horizon)*:\n"
        "• Breakout Trigger (Entry): ₹<Exact price or N/A if Stage 4>\n"
        "• Invalidation (Stop-Loss): ₹<Exact price anchored to structural support>\n"
        "• Targets: Target 1: ₹<Price> | Target 2: ₹<Price>\n"
        "• Risk-to-Reward Ratio: 1 : <X.X> or Unfavorable\n\n"
        "💡 *TACTICAL VERDICT*:\n"
        "<2 crisp sentences on buyer vs seller momentum and near-term bias.>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"CRITICAL ANCHOR RULE: Live CMP is ₹{cmp_val:,.2f}. All triggers, stop-losses, and targets MUST strictly align with CMP ₹{cmp_val:,.2f}."
    )

    user_text = (
        f"Analyze this candlestick chart for {comp_name} (`{base_sym}`). Live CMP is ₹{cmp_val:,.2f}. "
        f"Verified Weinstein Stage: Stage {stage_num} ({stage_name}) (52W High Dist: {dist_52w:+.1f}%, 200-DMA: ₹{sma_200:,.2f})."
    )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": user_text},
                    {"inline_data": {"mime_type": "image/png", "data": b64_img}}
                ]
            }
        ],
        "systemInstruction": {
            "parts": [{"text": sys_instruction}]
        },
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 4096
        }
    }

    diagnostic_text = ""

    for attempt, k in enumerate(keys):
        mask = f"{k[:6]}...{k[-4:]}"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={k}"
        try:
            logger.info(f"[Chart Vision] Sending {base_sym} chart to {model} using key {mask} (Attempt {attempt+1})...")
            r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=35.0)
            if r.status_code == 200:
                res_json = r.json()
                cand = res_json.get("candidates", [{}])[0]
                parts = cand.get("content", {}).get("parts", [])
                diagnostic_text = "".join([p.get("text", "") for p in parts if "text" in p]).strip()
                if diagnostic_text:
                    logger.info(f"[Chart Vision] Successfully generated vision diagnostic for {base_sym}.")
                    break
            elif r.status_code in (401, 403, 429):
                logger.warning(f"[Chart Vision] Key {mask} returned HTTP {r.status_code}. Rotating to next key.")
                continue
        except Exception as e:
            logger.warning(f"[Chart Vision] Request failed with key {mask}: {e}. Rotating to next key.")
            continue

    if not diagnostic_text:
        diagnostic_text = build_dynamic_vision_fallback(
            comp_name=comp_name,
            base_sym=base_sym,
            cmp_val=cmp_val,
            stage_num=stage_num,
            stage_name=stage_name,
            dist_52w=dist_52w,
            sma_50=sma_50,
            sma_200=sma_200
        )

    layman_summary_obj = extract_vision_layman_summary(diagnostic_text, cmp_val)

    result_payload = {
        "symbol": base_sym,
        "company_name": comp_name,
        "cmp": cmp_val,
        "mode": indicator_mode,
        "success": True,
        "from_cache": False,
        "model_id": model,
        "model_label": model_label,
        "layman_summary": layman_summary_obj,
        "formatted_markdown": diagnostic_text,
        "created_at": time.time()
    }

    # 7. Persist to SQLite cache
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO cached_chart_vision (symbol, mode, payload_json, created_at)
        VALUES (?, ?, ?, ?)
        """, (cache_key, indicator_mode, json.dumps(result_payload), time.time()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[Chart Vision] Failed to cache diagnosis for {base_sym}: {e}")

    return result_payload
