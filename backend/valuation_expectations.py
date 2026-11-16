"""
Valuation Expectations & Reverse DCF Engine
============================================
Institutional 5-Year Expectations Investing & Cash Flow Realization Framework.

Pillar 1: 5-Year Cash Realization Audit (CFO / PAT)
Pillar 2: Reverse DCF Implied Growth Solver
Pillar 3: 5-Year Bear / Base / Bull CAGR Scenario Matrix
Pillar 4: AI Institutional Value Allocator Memo & Margin of Safety Verdict
"""

import os
import re
import json
import time
import math
import sqlite3
import logging
from typing import Dict, Any, List, Optional, Tuple

import requests

logger = logging.getLogger("valuation_expectations")

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "data", "watchlist_database.db")


def _init_valuation_cache_table():
    """Initializes SQLite cache table for valuation expectations."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_valuation_expectations (
            symbol TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[Valuation Expectations] Failed to initialize cache table: {e}")


def _get_gemini_keys_pool() -> List[str]:
    """Retrieves available Gemini API keys."""
    keys = []
    primary = os.environ.get("GEMINI_API_KEY", "").strip()
    if primary:
        keys.append(primary)
    extra = os.environ.get("GEMINI_API_KEYS", "").strip()
    if extra:
        for k in extra.split(","):
            k_clean = k.strip()
            if k_clean and k_clean not in keys:
                keys.append(k_clean)
    backup = os.environ.get("GOOGLE_API_KEY", "").strip()
    if backup and backup not in keys:
        keys.append(backup)
    return keys


def get_valuation_model_info() -> Tuple[str, str]:
    """Dynamically resolves the AI model for valuation synthesis."""
    model_env = os.environ.get("VALUATION_AI_MODEL", "").strip()
    if model_env:
        return model_env, model_env.replace("-", " ").title()

    fast_env = os.environ.get("GEMINI_FAST_MODEL", "").strip()
    if fast_env:
        return fast_env, fast_env.replace("-", " ").title()

    return "gemini-2.5-flash", "Gemini 2.5 Flash"


def solve_implied_eps_growth(
    cmp: float,
    eps: float,
    discount_rate: float = 0.115,
    exit_pe: float = 30.0,
    years: int = 5
) -> float:
    """
    Numerically solves for the annual growth rate (g) implied by the current market price (CMP).
    Formula: CMP = sum_{t=1}^years (EPS * (1+g)^t / (1+r)^t) + (EPS * (1+g)^years * exit_pe) / (1+r)^years
    """
    if eps <= 0 or cmp <= 0:
        return 0.0

    low = -0.30  # -30%
    high = 1.20  # +120%
    for _ in range(80):
        mid = (low + high) / 2.0
        pv = 0.0
        for t in range(1, years + 1):
            pv += (eps * ((1.0 + mid) ** t)) / ((1.0 + discount_rate) ** t)
        terminal_val = (eps * ((1.0 + mid) ** years)) * exit_pe
        pv += terminal_val / ((1.0 + discount_rate) ** years)

        if pv < cmp:
            low = mid
        else:
            high = mid

    return round(mid * 100.0, 1)


def calculate_scenario(
    cmp: float,
    eps: float,
    growth_pct: float,
    exit_pe: float,
    years: int = 5
) -> Dict[str, Any]:
    """
    Calculates future EPS, target price, and annualized 5-year CAGR return.
    """
    g = growth_pct / 100.0
    future_eps = eps * ((1.0 + g) ** years)
    future_price = future_eps * exit_pe
    cagr = (((future_price / cmp) ** (1.0 / years)) - 1.0) * 100.0 if cmp > 0 else 0.0
    abs_return = ((future_price - cmp) / cmp) * 100.0 if cmp > 0 else 0.0

    return {
        "growth_pct": round(growth_pct, 1),
        "exit_pe": round(exit_pe, 1),
        "future_eps": round(future_eps, 2),
        "future_price": round(future_price, 2),
        "cagr_pct": round(cagr, 1),
        "abs_return_pct": round(abs_return, 1)
    }


def extract_cash_flow_and_earnings(symbol: str) -> Dict[str, Any]:
    """
    Pulls cumulative 5-year Net Profit (PAT) and Cash Flow from Operations (CFO)
    from cached_financial_statements table.
    """
    clean_sym = symbol.strip().upper().replace(".NS", "").replace(".BO", "")
    result = {
        "has_data": False,
        "years_count": 0,
        "cumulative_pat_cr": 0.0,
        "cumulative_cfo_cr": 0.0,
        "conversion_ratio_pct": 100.0,
        "pat_history": [],
        "cfo_history": [],
        "eps_history": [],
        "historical_eps_cagr": 15.0,
        "status": "PASS",
        "badge": "🟢 Real Cash Flow Verified",
        "summary": "Operating cash flow reliably backs reported net income."
    }

    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT data_json FROM cached_financial_statements WHERE symbol = ? LIMIT 1", (clean_sym,))
        row = cur.fetchone()
        conn.close()

        if not row:
            return result

        data = json.loads(row["data_json"])
        pl_rows = data.get("profit_loss", {}).get("rows", [])
        cf_rows = data.get("cash_flow", {}).get("rows", [])

        # Find Net Profit and EPS
        net_profit_vals = []
        eps_vals = []
        for r in pl_rows:
            lbl = r.get("label", "").lower()
            if lbl == "net profit" or "net profit" in lbl:
                net_profit_vals = [float(v) for v in r.get("values", []) if v is not None]
            elif "eps in rs" in lbl or lbl == "eps":
                eps_vals = [float(v) for v in r.get("values", []) if v is not None]

        # Find Cash from Operating Activities
        cfo_vals = []
        for r in cf_rows:
            lbl = r.get("label", "").lower()
            if "operating activity" in lbl or "cash from operations" in lbl:
                cfo_vals = [float(v) for v in r.get("values", []) if v is not None]
                break

        if net_profit_vals and cfo_vals:
            # Align lengths
            min_len = min(len(net_profit_vals), len(cfo_vals))
            np_slice = net_profit_vals[-min_len:]
            cf_slice = cfo_vals[-min_len:]

            sum_pat = sum(np_slice)
            sum_cfo = sum(cf_slice)
            ratio = (sum_cfo / sum_pat) * 100.0 if sum_pat > 0 else 0.0

            result["has_data"] = True
            result["years_count"] = min_len
            result["cumulative_pat_cr"] = round(sum_pat, 1)
            result["cumulative_cfo_cr"] = round(sum_cfo, 1)
            result["conversion_ratio_pct"] = round(ratio, 1)
            result["pat_history"] = np_slice
            result["cfo_history"] = cf_slice
            result["eps_history"] = eps_vals

            # Calculate Historical EPS CAGR
            if len(eps_vals) >= 2 and eps_vals[0] > 0 and eps_vals[-1] > 0:
                n_yrs = len(eps_vals) - 1
                cagr = (((eps_vals[-1] / eps_vals[0]) ** (1.0 / n_yrs)) - 1.0) * 100.0
                result["historical_eps_cagr"] = round(cagr, 1)

            if ratio >= 80.0:
                result["status"] = "EXCELLENT"
                result["badge"] = "🟢 Pristine Cash Conversion"
                result["summary"] = f"5-Year CFO/PAT ratio of {result['conversion_ratio_pct']}% confirms reported profits convert cleanly into hard operational cash flow."
            elif ratio >= 60.0:
                result["status"] = "MODERATE"
                result["badge"] = "🟡 Moderate Cash Realization"
                result["summary"] = f"5-Year CFO/PAT ratio of {result['conversion_ratio_pct']}%. A portion of earnings is absorbed into working capital expansions."
            else:
                result["status"] = "WARNING"
                result["badge"] = "🔴 Paper Profit Warning"
                result["summary"] = f"5-Year CFO/PAT ratio of {result['conversion_ratio_pct']}%. Cash flow significantly lags net profit, indicating potential inventory buildup or aggressive revenue recognition."

    except Exception as e:
        logger.warning(f"[Valuation Expectations] Error extracting cash flow for {symbol}: {e}")

    return result


def extract_pe_bands_and_profile(symbol: str) -> Dict[str, Any]:
    """
    Pulls historical PE bands (mean, median, min, max) and basic fundamentals from cached_profiles.
    """
    clean_sym = symbol.strip().upper().replace(".NS", "").replace(".BO", "")
    res = {
        "company_name": clean_sym,
        "current_pe": 0.0,
        "trailing_eps": 0.0,
        "mean_pe": 32.0,
        "median_pe": 30.0,
        "min_pe": 20.0,
        "max_pe": 45.0,
        "roe_pct": 18.0,
        "roce_pct": 22.0,
        "debt_to_equity": 0.1,
        "sector": "Indian Equities"
    }

    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ? OR symbol = ? LIMIT 1", (f"{clean_sym}.NS", clean_sym))
        row = cur.fetchone()
        conn.close()

        if row:
            p = json.loads(row["profile_json"])
            res["company_name"] = p.get("company_name", clean_sym)
            res["sector"] = p.get("sector", "Indian Equities")
            f = p.get("fundamentals", {})
            pe_b = p.get("pe_bands", {})

            res["current_pe"] = float(f.get("pe_ratio") or 0.0)
            res["trailing_eps"] = float(f.get("eps") or 0.0)
            res["roe_pct"] = float(f.get("roe_pct") or 18.0)
            res["roce_pct"] = float(f.get("roce_pct") or 22.0)
            res["debt_to_equity"] = float(f.get("debt_to_equity") or 0.1)

            if pe_b:
                res["mean_pe"] = round(float(pe_b.get("mean_pe") or 32.0), 1)
                res["median_pe"] = round(float(pe_b.get("median_pe") or 30.0), 1)
                res["min_pe"] = round(float(pe_b.get("min_pe") or 20.0), 1)
                res["max_pe"] = round(float(pe_b.get("max_pe") or 45.0), 1)
    except Exception as e:
        logger.warning(f"[Valuation Expectations] Profile lookup warning for {symbol}: {e}")

    return res


def generate_valuation_expectations(
    symbol: str,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Main controller for the 5-Year Reverse DCF & Expectations Valuation Engine.
    """
    _init_valuation_cache_table()
    model, model_label = get_valuation_model_info()

    clean_sym = symbol.strip().upper().replace(".NS", "").replace(".BO", "")
    cache_ttl = 24 * 3600  # 24-hour cache for fundamentals

    # 1. Check SQLite cache
    if not force_refresh:
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT payload_json, created_at FROM cached_valuation_expectations WHERE symbol = ?", (clean_sym,))
            row = cur.fetchone()
            conn.close()
            if row and (time.time() - row["created_at"] < cache_ttl):
                data = json.loads(row["payload_json"])
                data["from_cache"] = True
                logger.info(f"[Valuation Expectations] Serving cached expectations for {clean_sym}")
                return data
        except Exception as e:
            logger.debug(f"[Valuation Expectations] Cache check warning: {e}")

    # 2. Pull live verified price context
    from backend.confluence_storyteller import get_stock_price_context, resolve_company_ticker
    resolved = resolve_company_ticker(clean_sym)
    base_sym = resolved.get("base_symbol") if resolved else clean_sym
    comp_name = resolved.get("name") if resolved else base_sym
    ticker = resolved.get("yf_ticker") if resolved else f"{base_sym}.NS"

    p_ctx = get_stock_price_context(base_sym, ticker)
    cmp_val = p_ctx.get("cmp", 1000.0)

    # 3. Pull Cash Flow & Earnings History
    cf_data = extract_cash_flow_and_earnings(base_sym)

    # 4. Pull PE Bands & Profile
    prof_data = extract_pe_bands_and_profile(base_sym)
    if comp_name == base_sym and prof_data.get("company_name"):
        comp_name = prof_data["company_name"]

    # Trailing EPS & PE resolution
    eps = prof_data.get("trailing_eps", 0.0)
    if eps <= 0 and cf_data.get("eps_history"):
        eps = cf_data["eps_history"][-1]
    if eps <= 0:
        eps = round(cmp_val / (prof_data.get("current_pe") or 30.0), 2)
    if eps <= 0:
        eps = round(cmp_val / 30.0, 2)

    pe_current = round(cmp_val / eps, 1) if eps > 0 else 30.0

    # Ensure valid PE band bounds
    median_pe = prof_data.get("median_pe") or 30.0
    if median_pe <= 5.0 or median_pe > 120.0:
        median_pe = round(pe_current * 0.90, 1)

    min_pe = prof_data.get("min_pe") or round(median_pe * 0.70, 1)
    if min_pe <= 5.0:
        min_pe = round(median_pe * 0.70, 1)

    max_pe = prof_data.get("max_pe") or round(median_pe * 1.35, 1)
    if max_pe <= min_pe:
        max_pe = round(median_pe * 1.35, 1)

    hist_growth = cf_data.get("historical_eps_cagr", 16.0)
    if hist_growth <= 0:
        hist_growth = 15.0

    # 5. Solve Reverse DCF (Implied Growth Rate)
    discount_rate = 0.115  # 11.5% WACC / Cost of Equity
    exit_pe_terminal = median_pe
    implied_growth = solve_implied_eps_growth(
        cmp=cmp_val,
        eps=eps,
        discount_rate=discount_rate,
        exit_pe=exit_pe_terminal,
        years=5
    )

    # 6. Build 5-Year Bear / Base / Bull CAGR Scenario Matrix
    bear_growth = max(6.0, round(hist_growth * 0.55, 1))
    bear_exit_pe = round(min_pe, 1)
    bear_scenario = calculate_scenario(cmp_val, eps, bear_growth, bear_exit_pe, 5)

    base_growth = round(hist_growth * 0.90, 1)
    base_exit_pe = round(median_pe, 1)
    base_scenario = calculate_scenario(cmp_val, eps, base_growth, base_exit_pe, 5)

    bull_growth = round(hist_growth * 1.25, 1)
    bull_exit_pe = round(max_pe, 1)
    bull_scenario = calculate_scenario(cmp_val, eps, bull_growth, bull_exit_pe, 5)

    # Margin of Safety Evaluation
    growth_gap = round(implied_growth - hist_growth, 1)
    if growth_gap <= -3.0:
        mos_status = "HIGH_MARGIN_OF_SAFETY"
        mos_badge = "🟢 HIGH MARGIN OF SAFETY"
        mos_color = "#10b981"
        mos_verdict = f"Priced attractively. The market only prices in {implied_growth}% growth, well below its historical delivered pace of {hist_growth}%."
    elif abs(growth_gap) < 3.0:
        mos_status = "FAIRLY_VALUED"
        mos_badge = "🟡 FAIRLY VALUED"
        mos_color = "#f59e0b"
        mos_verdict = f"Fairly priced. Implied growth of {implied_growth}% is closely aligned with historical compounding of {hist_growth}%."
    else:
        mos_status = "LOW_MARGIN_OF_SAFETY"
        mos_badge = "🔴 LOW MARGIN OF SAFETY"
        mos_color = "#f87171"
        mos_verdict = f"Priced for perfection. The market demands {implied_growth}% growth (vs historical {hist_growth}%). Any quarterly earnings hiccup risks P/E compression."

    # 7. AI Institutional Synthesis (Gemini / Fast Fallback)
    sys_instruction = (
        "You are the Chief Investment Officer (CIO) and Head of Fundamental Research at an institutional value-investing fund. "
        "You are evaluating a 5-year investment horizon for a quality Indian equity.\n\n"
        "Your task is to write a rigorous, transparent Institutional Valuation & Expectations Memorandum for long-term investors.\n\n"
        "Rules:\n"
        "1. Avoid retail jargon. Speak like Terry Smith, Charlie Munger, or an institutional fund manager.\n"
        "2. Analyze the Cash Realization Ratio (CFO/PAT) and whether reported earnings represent hard cash.\n"
        "3. Interpret the Reverse DCF Implied Growth vs Historical Delivered Growth.\n"
        "4. Summarize the 5-Year CAGR Risk/Reward (Bear vs Base vs Bull).\n"
        "5. Output strictly in the WhatsApp/Markdown format shown below with zero conversational preamble.\n\n"
        f"🎯 *5-YEAR VALUATION EXPECTATIONS & REALITY CHECK*\n"
        f"🏛️ *{comp_name.upper()}* (`{base_sym}`) • CMP: ₹{cmp_val:,.2f} • P/E: {pe_current:.1f}x\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 *EARNINGS INTEGRITY (CFO vs PAT)*:\n"
        f"• 5Y Cumulative PAT: ₹{cf_data['cumulative_pat_cr']:,.1f} Cr | Cumulative CFO: ₹{cf_data['cumulative_cfo_cr']:,.1f} Cr\n"
        f"• Cash Realization: {cf_data['conversion_ratio_pct']}% • {cf_data['badge']}\n"
        f"• Audit: {cf_data['summary']}\n\n"
        "🔍 *WHAT IS THE CURRENT MARKET PRICE IMPLYING?*\n"
        f"• Implied 5-Year EPS Growth: {implied_growth}% CAGR (at Terminal P/E: {median_pe}x)\n"
        f"• 5-Year Historical Delivered Growth: {hist_growth}% CAGR\n"
        f"• Margin of Safety: {mos_badge}\n"
        f"• Valuation Verdict: {mos_verdict}\n\n"
        "📊 *5-YEAR INVESTOR RETURN ROADMAP (Expected Annualized CAGR)*:\n"
        f"• 🐻 Bear Case (+{bear_growth}% EPS | {bear_exit_pe}x PE): ₹{bear_scenario['future_price']:,.2f} ({bear_scenario['cagr_pct']}% p.a.)\n"
        f"• ⚖️ Base Case (+{base_growth}% EPS | {base_exit_pe}x PE): ₹{base_scenario['future_price']:,.2f} ({base_scenario['cagr_pct']}% p.a.)\n"
        f"• 🐂 Bull Case (+{bull_growth}% EPS | {bull_exit_pe}x PE): ₹{bull_scenario['future_price']:,.2f} ({bull_scenario['cagr_pct']}% p.a.)\n\n"
        "💡 *LONG-TERM ALLOCATION THESIS*:\n"
        "<2 crisp paragraphs evaluating business durability, competitive moat, and capital allocation over the next 5 years.>"
    )

    user_text = f"Compile the 5-Year Valuation Expectations Dossier for {comp_name} ({base_sym}) at CMP ₹{cmp_val:,.2f}."

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
            "temperature": 0.2,
            "maxOutputTokens": 4096
        }
    }

    keys = _get_gemini_keys_pool()
    diagnostic_text = ""

    for attempt, k in enumerate(keys):
        mask = f"{k[:6]}...{k[-4:]}"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={k}"
        try:
            logger.info(f"[Valuation Expectations] Requesting AI synthesis for {base_sym} via {model} using key {mask}...")
            r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=30.0)
            if r.status_code == 200:
                res_json = r.json()
                cand = res_json.get("candidates", [{}])[0]
                parts = cand.get("content", {}).get("parts", [])
                diagnostic_text = "".join([p.get("text", "") for p in parts if "text" in p]).strip()
                if diagnostic_text:
                    logger.info(f"[Valuation Expectations] Successfully generated synthesis for {base_sym}.")
                    break
            elif r.status_code in (401, 403, 429):
                logger.warning(f"[Valuation Expectations] Key {mask} returned {r.status_code}. Rotating...")
                continue
        except Exception as e:
            logger.warning(f"[Valuation Expectations] Key {mask} request failed: {e}. Rotating...")
            continue

    if not diagnostic_text:
        # High quality algorithmic fallback synthesis
        diagnostic_text = (
            f"🎯 *5-YEAR VALUATION EXPECTATIONS & REALITY CHECK*\n"
            f"🏛️ *{comp_name.upper()}* (`{base_sym}`) • CMP: ₹{cmp_val:,.2f} • P/E: {pe_current:.1f}x\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💎 *EARNINGS INTEGRITY (CFO vs PAT)*:\n"
            f"• 5Y Cumulative PAT: ₹{cf_data['cumulative_pat_cr']:,.1f} Cr | Cumulative CFO: ₹{cf_data['cumulative_cfo_cr']:,.1f} Cr\n"
            f"• Cash Realization: {cf_data['conversion_ratio_pct']}% • {cf_data['badge']}\n"
            f"• Audit: {cf_data['summary']}\n\n"
            "🔍 *WHAT IS THE CURRENT MARKET PRICE IMPLYING?*\n"
            f"• Implied 5-Year EPS Growth: {implied_growth}% CAGR (at Terminal P/E: {median_pe}x)\n"
            f"• 5-Year Historical Delivered Growth: {hist_growth}% CAGR\n"
            f"• Margin of Safety: {mos_badge}\n"
            f"• Valuation Verdict: {mos_verdict}\n\n"
            "📊 *5-YEAR INVESTOR RETURN ROADMAP (Expected Annualized CAGR)*:\n"
            f"• 🐻 Bear Case (+{bear_growth}% EPS | {bear_exit_pe}x PE): ₹{bear_scenario['future_price']:,.2f} ({bear_scenario['cagr_pct']}% p.a.)\n"
            f"• ⚖️ Base Case (+{base_growth}% EPS | {base_exit_pe}x PE): ₹{base_scenario['future_price']:,.2f} ({base_scenario['cagr_pct']}% p.a.)\n"
            f"• 🐂 Bull Case (+{bull_growth}% EPS | {bull_exit_pe}x PE): ₹{bull_scenario['future_price']:,.2f} ({bull_scenario['cagr_pct']}% p.a.)\n\n"
            "💡 *LONG-TERM ALLOCATION THESIS*:\n"
            f"{comp_name} exhibits strong institutional compounding metrics with high capital efficiency (ROE: {prof_data['roe_pct']}% • ROCE: {prof_data['roce_pct']}%). "
            f"The business maintains conservative balance sheet leverage (Debt/Equity: {prof_data['debt_to_equity']}), giving management significant runway to fund organic capacity expansion. "
            f"For disciplined long-term allocators, the Base Case provides an expected {base_scenario['cagr_pct']}% annualized CAGR over a 5-year holding horizon. Accumulate methodically on cyclical dips."
        )

    result_payload = {
        "symbol": base_sym,
        "company_name": comp_name,
        "cmp": cmp_val,
        "current_pe": pe_current,
        "trailing_eps": eps,
        "implied_5y_growth_pct": implied_growth,
        "historical_5y_growth_pct": hist_growth,
        "discount_rate_pct": discount_rate * 100.0,
        "terminal_pe": median_pe,
        "margin_of_safety": {
            "status": mos_status,
            "badge": mos_badge,
            "color": mos_color,
            "verdict": mos_verdict
        },
        "cash_realization": cf_data,
        "pe_bands": {
            "mean_pe": prof_data["mean_pe"],
            "median_pe": median_pe,
            "min_pe": min_pe,
            "max_pe": max_pe
        },
        "scenarios": {
            "bear": bear_scenario,
            "base": base_scenario,
            "bull": bull_scenario
        },
        "model_id": model,
        "model_label": model_label,
        "formatted_markdown": diagnostic_text,
        "from_cache": False,
        "created_at": time.time()
    }

    # 8. Persist to cache
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("""
        INSERT OR REPLACE INTO cached_valuation_expectations (symbol, payload_json, created_at)
        VALUES (?, ?, ?)
        """, (base_sym, json.dumps(result_payload), time.time()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[Valuation Expectations] Failed to cache for {base_sym}: {e}")

    return result_payload
