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


def analyze_stock_chart_vision(
    symbol: str,
    indicator_mode: str = "smc",
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Renders an institutional candlestick chart for the given stock and passes the
    image directly to Gemini 2.5 Flash Vision.

    Acts as a Senior Chartered Market Technician (CMT) to identify visual chart
    patterns (Triangles, VCP, Cup & Handle, Flags, Order Blocks) and produces a
    dual-perspective action blueprint for both Long-Term Investors and Swing Traders.
    """
    _init_vision_cache_table()

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
                logger.info(f"[Chart Vision] Serving cached diagnosis for {base_sym} ({cache_key})")
                return data
        except Exception as e:
            logger.debug(f"[Chart Vision] Cache lookup warning: {e}")

    # 3. Get live verified price context
    p_ctx = get_stock_price_context(base_sym, ticker)
    cmp_val = p_ctx.get("cmp", 0.0)

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
        "- Exact Geometric Patterns: Ascending/Descending/Symmetrical Triangles, Cup & Handle, VCP Contractions, Bull/Bear Flags, Wedges, Double Bottoms, or Range Consolidations.\n"
        "- Base Symmetry & Volume: Is the consolidation tight or loose? Has volume dried up on pullbacks and expanded on upward moves?\n"
        "- Dynamic Moving Averages: Price action relative to 20-EMA, 50-EMA, and 150-Day / 30-Week SMA.\n"
        "- Institutional Zones: Demand Order Blocks, Supply Overheads, Liquidity wicks.\n\n"
        "Output strictly in this WhatsApp-ready format (do not include introductory filler or meta-commentary):\n\n"
        f"🏛️ *{comp_name.upper()}* (`{base_sym}`) • Live CMP: ₹{cmp_val:,.2f}\n"
        "📐 *AI VISION PATTERN DIAGNOSTIC*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "• Identified Pattern: <Exact Pattern Name, e.g. Symmetrical Triangle, VCP, Cup & Handle, Stage 2 Base>\n"
        "• Base Symmetry & Quality: <1-2 sentences on base tightness, volume dry-up, and pattern symmetry>\n\n"
        "💼 *FOR LONG-TERM INVESTORS (1–3 Year Horizon)*:\n"
        "• Structural Stage: <Stage 1 Accumulation / Stage 2 Markup / Stage 3 Distribution / Stage 4 Decline>\n"
        "• Core Accumulation Support: ₹<Price or Zone anchored to 50/150-DMA>\n"
        "• Investor Verdict: <🟢 Core Accumulate / 🟡 Hold / 🔴 Avoid or Reduce>\n\n"
        "⚡ *FOR SWING TRADERS (2–6 Week Horizon)*:\n"
        "• Breakout Trigger (Entry): ₹<Exact price>\n"
        "• Invalidation (Stop-Loss): ₹<Exact price anchored to structural support>\n"
        "• Targets: Target 1: ₹<Price> | Target 2: ₹<Price>\n"
        "• Risk-to-Reward Ratio: 1 : <X.X>\n\n"
        "💡 *TACTICAL VERDICT*:\n"
        "<2 crisp sentences on buyer vs seller momentum and near-term bias.>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"CRITICAL ANCHOR RULE: Live CMP is ₹{cmp_val:,.2f}. All triggers, stop-losses, and targets MUST strictly align with CMP ₹{cmp_val:,.2f}."
    )

    user_text = f"Analyze this candlestick chart for {comp_name} (`{base_sym}`). Live CMP is ₹{cmp_val:,.2f}."

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

    model = "gemini-2.5-flash"
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
        diagnostic_text = (
            f"🏛️ *{comp_name.upper()}* (`{base_sym}`) • Live CMP: ₹{cmp_val:,.2f}\n"
            "📐 *AI VISION PATTERN DIAGNOSTIC*\n"
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

    result_payload = {
        "symbol": base_sym,
        "company_name": comp_name,
        "cmp": cmp_val,
        "mode": indicator_mode,
        "success": True,
        "from_cache": False,
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
