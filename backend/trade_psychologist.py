"""
Trade Psychologist & Behavioral Mirror Engine
=============================================
Pre-trade behavioral sanity check & devil's advocate audit for Swing Traders & Long-Term Investors.
Zero trade logging, zero portfolio tracking, 100% focused on objective behavioral risk checks.
"""

import os
import sys
import re
import json
import time
import math
import sqlite3
import logging
from typing import Dict, Any, List, Optional, Tuple

import requests

logger = logging.getLogger("trade_psychologist")

# Ensure backend root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.llm_config import _get_gemini_keys_pool, _format_model_label
from backend.whatsapp_bot import resolve_company_ticker, get_stock_price_context
from backend.valuation_expectations import extract_pe_bands_and_profile, extract_cash_flow_and_earnings

DATABASE_DIR = os.environ.get("DATABASE_DIR", os.path.join(os.path.dirname(__file__), "data"))
DATABASE_PATH = os.path.join(DATABASE_DIR, "watchlist_database.db")


def _init_psychology_cache_table():
    """Initializes SQLite cache table for psychology intent evaluations."""
    try:
        os.makedirs(DATABASE_DIR, exist_ok=True)
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_psychology_audits (
            cache_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Could not initialize cached_psychology_audits table: {e}")


def get_psychology_model_info() -> Tuple[str, str]:
    """
    Returns engine id and label.
    100% deterministic quantitative rules engine (zero LLM / external AI API).
    """
    model_id = os.environ.get("PSYCHOLOGY_AI_MODEL", "apex-quant-engine").strip()
    model_label = os.environ.get(
        "PSYCHOLOGY_AI_LABEL",
        "🛡️ Apex Deterministic Quant Engine"
    ).strip()
    return model_id, model_label


def generate_devils_advocate_thesis(
    action: str,
    horizon: str,
    comp_name: str,
    base_sym: str,
    eval_price: float,
    pivot_price: float,
    pivot_extension_pct: float,
    ema_20: float,
    ema20_dist_pct: float,
    ema_50: float,
    ema50_dist_pct: float,
    sma_200: float,
    dist_52w_high: float,
    volume_ratio: float,
    stop_loss: float,
    target_1: float,
    current_pe: float,
    median_pe: float,
    cfo_ratio: float,
    debt_to_equity: float,
    roe_pct: float,
    implied_5y_growth: float,
    hist_5y_growth: float,
    fii_curr: float,
    fii_prev: float,
    prom_pledge: float
) -> Dict[str, Any]:
    """
    Constructs an institutional Devil's Advocate Counter-Thesis tailored to the investment horizon:
    - For BUY: The Top 3 Bear Arguments + Invalidation Trigger.
    - For SELL: The Top 3 Bull Arguments + Invalidation Trigger.
    """
    da_points = []
    is_swing = (horizon or "swing").lower() == "swing"

    if action == "BUY":
        stance = "BEAR"
        stance_color = "#ef4444"

        if is_swing:
            da_title = "😈 DEVIL'S ADVOCATE: SWING TRADER'S BEAR CASE (2–8 WEEKS)"

            # Point 1: Mean Reversion Pullback Risk
            if ema20_dist_pct > 3.0 or pivot_extension_pct > 2.5:
                da_points.append({
                    "title": "Short-Term Mean-Reversion Pullback",
                    "detail": f"Price is stretched +{ema20_dist_pct}% above its 20-day EMA (₹{ema_20:,.2f}) and +{pivot_extension_pct}% from base pivot. In Indian swing trading, moves extended >3% frequently experience a sharp 3–6% shakeout back to dynamic support before continuation."
                })
            else:
                da_points.append({
                    "title": "Low-Volume Breakout Churn",
                    "detail": f"Volume is running at {volume_ratio:.2f}x average. Entering without decisive institutional volume (> 1.3x) exposes swing capital to sideways range-bound chop and time-decay risk."
                })

            # Point 2: Overhead Supply & Resistance
            if dist_52w_high < -6.0:
                da_points.append({
                    "title": "Overhead Trapped Supply & Resistance",
                    "detail": f"The stock is {abs(dist_52w_high):.1f}% below its 52-week high. Prior swing buyers trapped at higher prices create a dense supply ceiling, making immediate clean breakouts difficult."
                })
            else:
                da_points.append({
                    "title": "All-Time High Exhaustion",
                    "detail": f"Trading within {abs(dist_52w_high):.1f}% of highs without building a multi-week tight base increases the probability of false breakout 'bull traps' engineered to absorb retail liquidity."
                })

            # Point 3: Risk-to-Reward Geometry
            downside_risk = abs((eval_price - stop_loss) / eval_price) * 100.0 if eval_price > 0 else 5.0
            rr_val = round(((target_1 - eval_price) / eval_price) / (downside_risk / 100.0), 1) if downside_risk > 0 else 1.5
            da_points.append({
                "title": "Stop-Loss Risk / Reward Asymmetry",
                "detail": f"Current swing geometry offers a 1 : {rr_val} risk-to-reward ratio with downside risk of -{downside_risk:.1f}% to stop ₹{stop_loss:,.2f}. If broader market indices (Nifty/Sensex) wobble, your stop will likely get triggered before reaching Target 1 (₹{target_1:,.2f})."
            })

            invalidation = f"{comp_name} decisively clears and sustains above ₹{pivot_price:,.2f} on volume > 1.3x 20-day average, or executes a clean low-volume retest of 20-day EMA (₹{ema_20:,.2f}) printing an immediate bullish reversal candle."

        else:
            da_title = "😈 DEVIL'S ADVOCATE: LONG-TERM INVESTOR'S BEAR CASE (1–3 YEARS)"

            # Point 1: Valuation Multiple Compression
            if current_pe > (median_pe * 1.15) and current_pe > 30.0:
                premium_pct = round(((current_pe - median_pe) / median_pe) * 100.0, 1) if median_pe > 0 else 20.0
                da_points.append({
                    "title": "Valuation Multiple De-Rating Risk",
                    "detail": f"Current P/E of {current_pe:.1f}x trades at a +{premium_pct}% premium to its 5-year median ({median_pe:.1f}x). Over a 3-year holding period, multiple contraction back to median levels will aggressively erode compounding returns even if earnings grow."
                })
            else:
                da_points.append({
                    "title": "Terminal Multiple Ceiling",
                    "detail": f"At {current_pe:.1f}x P/E, valuation already prices in steady execution. Unless revenue growth accelerates significantly beyond its historical {hist_5y_growth:.1f}% CAGR pace, upside from multiple expansion is minimal."
                })

            # Point 2: Cash Realization & Working Capital Leakage
            if cfo_ratio < 80.0:
                leak_pct = round(100.0 - cfo_ratio, 1)
                da_points.append({
                    "title": "Accrual Accounting & Free Cash Flow Drag",
                    "detail": f"5-Year Cash Realization (CFO/PAT) is {cfo_ratio:.1f}%. Roughly {leak_pct}% of reported profits are trapped in working capital and receivables rather than converting into hard distributable free cash flow."
                })
            else:
                da_points.append({
                    "title": "Capex Reinvestment & Free Cash Flow Hurdle",
                    "detail": f"While historical cash conversion is sound ({cfo_ratio:.1f}%), sustaining a {roe_pct:.1f}% ROE in an evolving competitive sector demands high continuous capex, which could constrain dividend growth."
                })

            # Point 3: Moat Durability & Compounding Deceleration
            if debt_to_equity > 0.6:
                da_points.append({
                    "title": "Balance Sheet Leverage Vulnerability",
                    "detail": f"Debt-to-Equity is {debt_to_equity:.2f}. Over a 3-year horizon, higher debt service obligations reduce resilience during economic downturns."
                })
            else:
                da_points.append({
                    "title": "Scale Deceleration & Competitive Drag",
                    "detail": f"As {comp_name}'s revenue base expands, maintaining high double-digit compounding becomes mathematically harder. Larger market-cap leaders naturally experience growth moderation."
                })

            invalidation = f"Two consecutive quarters of revenue growth decelerating below 8% YoY, or 5-year CFO/PAT cash realization deteriorating below 70%, confirming structural moat erosion."

    else:
        stance = "BULL"
        stance_color = "#10b981"

        if is_swing:
            da_title = "😇 DEVIL'S ADVOCATE: SWING TRADER'S BULL CASE (2–8 WEEKS)"

            # Point 1: Support Capitulation
            if abs(ema50_dist_pct) < 3.5 or abs(ema20_dist_pct) < 2.0:
                da_points.append({
                    "title": "Capitulating Directly into Support",
                    "detail": f"Price is resting directly on dynamic moving average support (₹{ema_50:,.2f}) on below-average volume ({volume_ratio:.2f}x). Selling here capitulates into support right where institutional swing buyers accumulate."
                })
            else:
                da_points.append({
                    "title": "Oversold Mean-Reversion Bounce",
                    "detail": f"The stock has absorbed recent selling. Cashing out into a red streak risks selling at the cyclical low right before an algorithmic relief rally."
                })

            # Point 2: Cutting Runners Too Early
            da_points.append({
                "title": "Cutting Stage 2 Momentum Leaders Prematurely",
                "detail": f"If {comp_name} is in a confirmed Stage 2 markup, taking full profits on routine pullbacks forfeits subsequent 15–25% runner legs. Trailing a stop below the 20-EMA captures more alpha."
            })

            # Point 3: Volume Confirmation Missing
            da_points.append({
                "title": "No Heavy Institutional Distribution",
                "detail": f"Selling volume is muted ({volume_ratio:.2f}x 20D average). True institutional exit is marked by massive volume spikes. Selling on quiet volume is often an emotional retail exit."
            })

            invalidation = f"{comp_name} breaks and closes decisively below structural support at ₹{stop_loss:,.2f} on expanding delivery volume (> 1.4x 20-day average), confirming institutional distribution."

        else:
            da_title = "😇 DEVIL'S ADVOCATE: LONG-TERM INVESTOR'S BULL CASE (1–3 YEARS)"

            # Point 1: Compounding Friction
            da_points.append({
                "title": "The Compounding Tax & Reinvestment Friction",
                "detail": f"Selling a business with {roe_pct:.1f}% ROE and {cfo_ratio:.1f}% cash conversion triggers capital gains tax and creates cash-drag friction. Finding an equal or better multi-year replacement is statistically difficult."
            })

            # Point 2: Cash Realization Engine Intact
            da_points.append({
                "title": "Cash Conversion Engine Remains Resilient",
                "detail": f"5-Year CFO/PAT of {cfo_ratio:.1f}% proves earnings are genuine cash. Elite cash-generating companies consistently compound through business cycles."
            })

            # Point 3: Multi-Year Economic Runway
            da_points.append({
                "title": "Long Industry Compounding Runway",
                "detail": f"With conservative leverage ({debt_to_equity:.2f} D/E), management has the balance sheet capacity to fund organic expansion and capture market share over a 3-year cycle."
            })

            invalidation = f"Structural impairment in company economics: ROCE dropping permanently below 12% or debt-to-equity surging above 1.0 without corresponding asset expansion."

    return {
        "title": da_title,
        "stance": stance,
        "stance_color": stance_color,
        "points": da_points,
        "invalidation_trigger": invalidation
    }


def evaluate_trade_intent(
    symbol: str,
    action: str = "BUY",
    horizon: str = "swing",
    intended_price: Optional[float] = None,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Evaluates a user's trade intent against technical pivots, moving averages,
    risk-to-reward ratios, and balance sheet quality.
    
    Zero trade logging: solely acts as an objective behavioral mirror.
    """
    _init_psychology_cache_table()
    model, model_label = get_psychology_model_info()

    # 1. Normalize Inputs
    clean_sym = symbol.strip().upper().replace(".NS", "").replace(".BO", "")
    norm_action = "SELL" if "SELL" in action.upper() else "BUY"
    norm_horizon = "invest" if "invest" in horizon.lower() or "long" in horizon.lower() else "swing"

    resolved = resolve_company_ticker(clean_sym)
    base_sym = resolved.get("base_symbol") if resolved else clean_sym
    comp_name = resolved.get("name") if resolved else base_sym
    ticker = resolved.get("yf_ticker") if resolved else f"{base_sym}.NS"

    cache_key = f"{base_sym}_{norm_action}_{norm_horizon}_{int(intended_price or 0)}"
    cache_ttl = 3600  # 1 hour cache

    # 2. Check Cache
    if not force_refresh:
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT payload_json, created_at FROM cached_psychology_audits WHERE cache_key = ?", (cache_key,))
            row = cursor.fetchone()
            conn.close()
            if row and (time.time() - row["created_at"] < cache_ttl):
                data = json.loads(row["payload_json"])
                data["from_cache"] = True
                return data
        except Exception as e:
            logger.debug(f"[Trade Psychologist] Cache lookup warning: {e}")

    # 3. Resolve Live Market Data
    p_ctx = get_stock_price_context(base_sym, ticker)
    cmp_val = float(p_ctx.get("cmp", 0.0))
    if cmp_val <= 0:
        cmp_val = 1000.0

    eval_price = float(intended_price) if intended_price and intended_price > 0 else cmp_val

    # 4. Resolve Technical Indicators & Base Pivots
    ema_20 = cmp_val * 0.97
    ema_50 = cmp_val * 0.94
    sma_200 = cmp_val * 0.88
    dist_52w_high = -4.0
    volume_ratio = 1.0
    pivot_price = round(cmp_val * 0.98, 2)
    stop_loss = round(cmp_val * 0.945, 2)
    target_1 = round(cmp_val * 1.09, 2)
    target_2 = round(cmp_val * 1.18, 2)
    fii_curr = 0.0
    fii_prev = 0.0
    prom_pledge = 0.0

    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ? OR symbol LIKE ?", (base_sym, f"%{base_sym}%"))
        row = cur.fetchone()
        if row:
            p_obj = json.loads(row["profile_json"])
            tech = p_obj.get("technicals", {})
            stage = p_obj.get("stage_analysis", {})
            fund = p_obj.get("fundamentals", {})
            shp = p_obj.get("shareholding", {})
            
            if tech.get("ema_20"): ema_20 = float(tech["ema_20"])
            if tech.get("ema_50"): ema_50 = float(tech["ema_50"])
            if tech.get("sma_200"): sma_200 = float(tech["sma_200"])
            if tech.get("dist_52wk_high_pct"): dist_52w_high = float(tech["dist_52wk_high_pct"])
            if tech.get("volume_ratio"): volume_ratio = float(tech["volume_ratio"])
            
            if stage.get("pivot_price"): pivot_price = float(stage["pivot_price"])
            if stage.get("stop_loss"): stop_loss = float(stage["stop_loss"])
            if stage.get("target_1"): target_1 = float(stage["target_1"])
            if stage.get("target_2"): target_2 = float(stage["target_2"])

            if shp:
                if shp.get("FIIs"): fii_curr = float(shp["FIIs"])
                if shp.get("FIIs_prev"): fii_prev = float(shp["FIIs_prev"])
                if shp.get("Promoter Pledging %"): prom_pledge = float(shp["Promoter Pledging %"])
        conn.close()
    except Exception as e:
        logger.debug(f"[Trade Psychologist] DB profile lookup warning: {e}")

    # Fallback sanity for pivot & stops if missing
    if pivot_price <= 0: pivot_price = round(cmp_val * 0.98, 2)
    if stop_loss <= 0: stop_loss = round(eval_price * 0.95, 2)
    if target_1 <= 0: target_1 = round(eval_price * 1.09, 2)

    # If user provided a specific intended price, scale stop & target proportionally
    if intended_price and intended_price > 0 and cmp_val > 0 and abs(intended_price - cmp_val) > 0.01:
        scale_ratio = eval_price / cmp_val
        stop_loss = round(stop_loss * scale_ratio, 2)
        target_1 = round(target_1 * scale_ratio, 2)

    # 5. Resolve Fundamentals & Valuation
    cf_data = extract_cash_flow_and_earnings(base_sym)
    prof_data = extract_pe_bands_and_profile(base_sym)
    
    current_pe = prof_data.get("current_pe", 0.0)
    median_pe = prof_data.get("median_pe", 32.0)
    cfo_ratio = cf_data.get("conversion_ratio_pct", 100.0)
    debt_to_equity = prof_data.get("debt_to_equity", 0.2)
    roe_pct = prof_data.get("roe_pct", 16.0)
    implied_5y_growth = float(prof_data.get("implied_5y_growth_pct", 0.0) or 0.0)
    hist_5y_growth = float(prof_data.get("historical_5y_growth_pct", 15.0) or 15.0)

    # 6. Quantitative Psychology Calculations
    pivot_extension_pct = round(((eval_price - pivot_price) / pivot_price) * 100.0, 1) if pivot_price > 0 else 0.0
    ema20_dist_pct = round(((eval_price - ema_20) / ema_20) * 100.0, 1) if ema_20 > 0 else 0.0
    ema50_dist_pct = round(((eval_price - ema_50) / ema_50) * 100.0, 1) if ema_50 > 0 else 0.0
    
    downside_risk_pct = round(abs((eval_price - stop_loss) / eval_price) * 100.0, 1) if eval_price > 0 else 5.0
    upside_target_pct = round(((target_1 - eval_price) / eval_price) * 100.0, 1) if eval_price > 0 else 10.0
    rr_ratio = round(upside_target_pct / downside_risk_pct, 1) if downside_risk_pct > 0 else 2.0

    # 7. Behavioral Decision Engine (Devil's Advocate Rules)
    status = "NEUTRAL"
    badge = "🟡 CONSTRUCTIVE EVALUATION"
    badge_color = "#f59e0b"
    cro_verdict = ""
    recommendation = ""

    if norm_action == "BUY":
        if norm_horizon == "swing":
            # Swing Trading Bias Detection
            if pivot_extension_pct >= 6.5 or ema20_dist_pct >= 8.5 or rr_ratio < 1.3:
                status = "FOMO_CHASING"
                badge = "⚠️ HIGH FOMO RISK (CHASING EXTENSION)"
                badge_color = "#f87171"
                cro_verdict = (
                    f"You are eyeing {comp_name} after a large upward move. The price is already +{pivot_extension_pct}% "
                    f"extended above its base breakout pivot (₹{pivot_price:,.2f}) and +{ema20_dist_pct}% above its 20-day EMA. "
                    f"Entering here forces you to risk ₹1 to potentially gain only ₹{rr_ratio:.1f}. A routine mean-reversion pullback "
                    f"to the 20-EMA will likely hit your stop-loss before any upside targets."
                )
                recommendation = (
                    f"Do NOT chase this move. Step back and avoid retail FOMO. Place an alert near ₹{ema_20:,.2f} (20-EMA support) "
                    f"and wait for a low-volume contraction before committing swing capital."
                )
            elif rr_ratio >= 2.0 and pivot_extension_pct <= 4.0:
                status = "RATIONAL_ENTRY"
                badge = "🟢 HIGH-PROBABILITY RATIONAL ENTRY"
                badge_color = "#10b981"
                cro_verdict = (
                    f"Excellent technical discipline. {comp_name} is within +{pivot_extension_pct}% of its ₹{pivot_price:,.2f} pivot, "
                    f"meaning risk is anchored closely to structural support. Downside risk is -{downside_risk_pct}%, while swing target "
                    f"yields +{upside_target_pct}% (Risk-to-Reward: 1 : {rr_ratio})."
                )
                recommendation = (
                    f"Favorable odds. Execute with planned discipline: enter near ₹{eval_price:,.2f}, set a strict stop-loss at "
                    f"₹{stop_loss:,.2f} (-{downside_risk_pct}%), and take initial profits at ₹{target_1:,.2f}."
                )
            else:
                status = "MODERATE_ENTRY"
                badge = "🟡 MODERATE ENTRY (CONTROLLED SIZING)"
                badge_color = "#f59e0b"
                if pivot_extension_pct < 0:
                    cro_verdict = (
                        f"{comp_name} is currently consolidating {abs(pivot_extension_pct):.1f}% below its breakout pivot (₹{pivot_price:,.2f}). "
                        f"Entering before the breakout is an early anticipation trade. Risk-to-reward is 1 : {rr_ratio}."
                    )
                    recommendation = (
                        f"You may enter a starter position, but keep your stop-loss tight at ₹{stop_loss:,.2f} (-{downside_risk_pct}%) "
                        f"and add only after volume expands on a breakout above ₹{pivot_price:,.2f}."
                    )
                else:
                    cro_verdict = (
                        f"The setup is constructive but slightly stretched (+{pivot_extension_pct}% from pivot). "
                        f"The risk-reward ratio is acceptable (1 : {rr_ratio}), but entry timing is not optimal."
                    )
                    recommendation = (
                        f"If you choose to enter, use a half-size allocation (50% position) to mitigate pullback risk, and keep a "
                        f"hard stop-loss at ₹{stop_loss:,.2f}."
                    )
        else:
            # Long-Term Investment Bias Detection
            if dist_52w_high < -25.0 and (cfo_ratio < 55.0 or debt_to_equity > 1.2):
                status = "FALLING_KNIFE"
                badge = "⚠️ VALUE TRAP / FALLING KNIFE WARNING"
                badge_color = "#f87171"
                cro_verdict = (
                    f"{comp_name} is down {abs(dist_52w_high):.1f}% from its 52-week peak, which makes it appear psychologically 'cheap'. "
                    f"However, 5-year Cash Realization (CFO/PAT) is low at {cfo_ratio:.1f}% and debt is elevated ({debt_to_equity:.2f} D/E). "
                    f"You may be anchoring to past prices rather than evaluating current corporate cash generation."
                )
                recommendation = (
                    "Do NOT average down on hope. A stock down 30% can easily drop another 30% if earnings decay. "
                    "Wait for at least 2 consecutive quarters of operational cash recovery before allocating long-term capital."
                )
            elif current_pe > (median_pe * 1.35) and current_pe > 42.0:
                status = "VALUATION_EXTREME"
                badge = "🟡 PRICED FOR PERFECTION (LOW SAFETY MARGIN)"
                badge_color = "#f59e0b"
                cro_verdict = (
                    f"{comp_name} is a proven compounder, but current valuation ({current_pe:.1f}x P/E) trades at a hefty premium "
                    f"to its 5-year median ({median_pe:.1f}x). The market is pricing in aggressive growth with little room for operational hiccups."
                )
                recommendation = (
                    f"Avoid lump-sum capital deployment at peak multiples. If accumulating, use a disciplined SIP approach or "
                    f"accumulate on cyclical market corrections when multiples derate closer to {median_pe:.1f}x."
                )
            else:
                status = "RATIONAL_INVESTMENT"
                badge = "🟢 HIGH-CONVICTION COMPOUNDER ACCUMULATION"
                badge_color = "#10b981"
                cro_verdict = (
                    f"High-quality corporate profile. {comp_name} generates real operational cash flow (CFO/PAT: {cfo_ratio:.1f}%), "
                    f"maintains conservative balance sheet leverage ({debt_to_equity:.2f} D/E), and compounds capital efficiently (ROE: {roe_pct:.1f}%)."
                )
                recommendation = (
                    f"Sound long-term decision. Accumulate methodically around CMP ₹{cmp_val:,.2f}. Hold for a 2–3 year investment horizon."
                )
    else:
        # SELL Intent Diagnostics
        if (abs(ema50_dist_pct) < 2.5 or abs(ema20_dist_pct) < 1.5) and volume_ratio < 0.85:
            status = "PANIC_SELL"
            badge = "🛡️ PANIC SELL WARNING (SELLING AT SUPPORT)"
            badge_color = "#f87171"
            cro_verdict = (
                f"{comp_name} has experienced a pullback, but it is currently resting directly on dynamic moving average support "
                f"(₹{ema_50:,.2f}) with volume drying up ({volume_ratio:.2f}x average volume). Selling here is capitulating into support "
                f"out of short-term emotional fatigue."
            )
            recommendation = (
                f"Hold your fire. Professional traders do not sell at support on light volume. Wait for a reaction bounce. "
                f"Only trigger your exit if the price decisively closes below ₹{stop_loss:,.2f}."
            )
        elif pivot_extension_pct > 20.0 or ema20_dist_pct > 14.0:
            status = "PRUDENT_PROFIT_TAKING"
            badge = "🟢 DISCIPLINED PROFIT-TAKING (CLIMACTIC RUN)"
            badge_color = "#10b981"
            cro_verdict = (
                f"{comp_name} is +{pivot_extension_pct}% extended above its base and +{ema20_dist_pct}% above the 20-EMA. "
                f"Booking profits into climactic strength is the hallmark of professional risk management."
            )
            recommendation = (
                f"Excellent decision. Lock in profits on 50% of your position now, and trail the remainder with a protective stop at the 20-EMA."
            )
        else:
            status = "RATIONAL_EXIT"
            badge = "🟡 RATIONAL EXIT EVALUATION"
            badge_color = "#f59e0b"
            cro_verdict = (
                f"Exiting {comp_name} at ₹{eval_price:,.2f} is consistent with disciplined capital protection or portfolio rebalancing."
            )
            recommendation = (
                f"Execute the exit smoothly and keep the liberated cash ready for high-confluence setups with 1 : 2.5+ risk-reward ratios."
            )

    # 7b. Generate Devil's Advocate Counter-Thesis
    devils_advocate = generate_devils_advocate_thesis(
        action=norm_action,
        horizon=norm_horizon,
        comp_name=comp_name,
        base_sym=base_sym,
        eval_price=eval_price,
        pivot_price=pivot_price,
        pivot_extension_pct=pivot_extension_pct,
        ema_20=ema_20,
        ema20_dist_pct=ema20_dist_pct,
        ema_50=ema_50,
        ema50_dist_pct=ema50_dist_pct,
        sma_200=sma_200,
        dist_52w_high=dist_52w_high,
        volume_ratio=volume_ratio,
        stop_loss=stop_loss,
        target_1=target_1,
        current_pe=current_pe,
        median_pe=median_pe,
        cfo_ratio=cfo_ratio,
        debt_to_equity=debt_to_equity,
        roe_pct=roe_pct,
        implied_5y_growth=implied_5y_growth,
        hist_5y_growth=hist_5y_growth,
        fii_curr=fii_curr,
        fii_prev=fii_prev,
        prom_pledge=prom_pledge
    )

    # 8. Build Plain-English WhatsApp & Markdown Output
    action_label = "BUY / ACCUMULATE" if norm_action == "BUY" else "SELL / EXIT"
    horizon_label = "⚡ Swing Trade (2–8 Weeks)" if norm_horizon == "swing" else "🏛️ Long-Term (1–3 Years)"

    da_title = devils_advocate["title"]
    da_points_md = "\n".join([f"{i+1}. *{p['title']}*: {p['detail']}" for i, p in enumerate(devils_advocate["points"])])
    da_inval = devils_advocate["invalidation_trigger"]

    if norm_horizon == "swing":
        cards = [
            {
                "title": "🎯 Base Breakout Pivot",
                "value": f"₹{pivot_price:,.2f}",
                "sub": f"Extension: {'+' if pivot_extension_pct >= 0 else ''}{pivot_extension_pct}%",
                "color": "#38bdf8"
            },
            {
                "title": "⚡ 20-Day EMA Proximity",
                "value": f"₹{ema_20:,.2f}",
                "sub": f"Distance: {'+' if ema20_dist_pct >= 0 else ''}{ema20_dist_pct}%",
                "color": "#a78bfa"
            },
            {
                "title": "⚖️ Risk / Reward Ratio",
                "value": f"1 : {rr_ratio}",
                "sub": f"SL: ₹{stop_loss:,.2f} | T1: ₹{target_1:,.2f}",
                "color": "#34d399" if rr_ratio >= 2.0 else ("#f59e0b" if rr_ratio >= 1.3 else "#ef4444")
            },
            {
                "title": "📊 Volume & Dynamic Support",
                "value": f"{volume_ratio:.2f}x Vol",
                "sub": f"50-EMA: ₹{ema_50:,.2f}",
                "color": "#34d399" if volume_ratio >= 1.0 else "#94a3b8"
            }
        ]
        facts_md = (
            "📊 *THE COLD HARD FACTS (SWING GEOMETRY)*:\n"
            f"• Base Breakout Pivot: ₹{pivot_price:,.2f} (Extension: {'+' if pivot_extension_pct >= 0 else ''}{pivot_extension_pct}%)\n"
            f"• Distance from 20-Day EMA: {'+' if ema20_dist_pct >= 0 else ''}{ema20_dist_pct}%\n"
            f"• Potential Downside Risk: -{downside_risk_pct}% (Stop-Loss: ₹{stop_loss:,.2f})\n"
            f"• Realistic Upside Target: +{upside_target_pct}% (Target 1: ₹{target_1:,.2f})\n"
            f"• Risk-to-Reward Ratio: 1 : {rr_ratio} ({'Favorable' if rr_ratio >= 2.0 else 'Unfavorable'})\n"
            f"• Volume Activity: {volume_ratio:.2f}x • 50-EMA Support: ₹{ema_50:,.2f}"
        )
    else:
        pe_diff = round(((current_pe - median_pe) / median_pe) * 100.0, 1) if median_pe > 0 else 0.0
        cards = [
            {
                "title": "💎 5Y Cash Realization",
                "value": f"{cfo_ratio:.1f}%",
                "sub": "Pristine Real Cash" if cfo_ratio >= 80 else ("Moderate Cash Flow" if cfo_ratio >= 60 else "Accrual Leakage"),
                "color": "#34d399" if cfo_ratio >= 80 else ("#f59e0b" if cfo_ratio >= 60 else "#ef4444")
            },
            {
                "title": "⚖️ Valuation Multiple",
                "value": f"{current_pe:.1f}x P/E",
                "sub": f"5Y Median: {median_pe:.1f}x ({'+' if pe_diff >= 0 else ''}{pe_diff}%)",
                "color": "#34d399" if pe_diff <= 0 else ("#f59e0b" if pe_diff <= 25 else "#ef4444")
            },
            {
                "title": "🚀 Capital Compounding",
                "value": f"{roe_pct:.1f}% ROE",
                "sub": f"ROCE: {prof_data.get('roce_pct', 0.0):.1f}% capital return",
                "color": "#38bdf8"
            },
            {
                "title": "🛡️ Balance Sheet Leverage",
                "value": f"{debt_to_equity:.2f} D/E",
                "sub": "Virtually Debt-Free" if debt_to_equity < 0.2 else ("Conservative Solvency" if debt_to_equity <= 0.8 else "Elevated Debt Load"),
                "color": "#34d399" if debt_to_equity < 0.4 else ("#f59e0b" if debt_to_equity <= 0.8 else "#ef4444")
            }
        ]
        facts_md = (
            "📊 *THE COLD HARD FACTS (COMPOUNDING & VALUATION)*:\n"
            f"• 5Y Cash Realization (CFO/PAT): {cfo_ratio:.1f}% ({'Pristine Real Cash' if cfo_ratio >= 80 else 'Accrual Drag'})\n"
            f"• Valuation Multiple: {current_pe:.1f}x P/E (5Y Median: {median_pe:.1f}x | {'+' if pe_diff >= 0 else ''}{pe_diff}%)\n"
            f"• Capital Efficiency: ROE {roe_pct:.1f}% • ROCE {prof_data.get('roce_pct', 0.0):.1f}%\n"
            f"• Balance Sheet Leverage: {debt_to_equity:.2f} Debt-to-Equity\n"
            f"• 5-Year Historical Growth: {hist_5y_growth:.1f}% CAGR vs Market Implied: {implied_5y_growth:.1f}%"
        )

    diagnostic_text = (
        f"🧠 *PRE-TRADE BEHAVIORAL MIRROR & RISK AUDIT*\n"
        f"🏛️ *{comp_name.upper()}* (`{base_sym}`) • Live CMP: ₹{cmp_val:,.2f}\n"
        f"🎯 *Intent:* {action_label} • *Horizon:* {horizon_label}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🚦 *PSYCHOLOGY STANCE*: {badge}\n\n"
        f"{facts_md}\n\n"
        "🧠 *CHIEF RISK OFFICER BEHAVIORAL DIAGNOSTIC*:\n"
        f"{cro_verdict}\n\n"
        f"{da_title}:\n"
        f"{da_points_md}\n\n"
        f"🛑 *Invalidation Trigger*: {da_inval}\n\n"
        "💡 *ACTIONABLE RECOMMENDATION*:\n"
        f"{recommendation}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    result_payload = {
        "symbol": base_sym,
        "company_name": comp_name,
        "cmp": cmp_val,
        "eval_price": eval_price,
        "action": norm_action,
        "horizon": norm_horizon,
        "status": status,
        "badge": badge,
        "badge_color": badge_color,
        "cards": cards,
        "hard_facts": {
            "pivot_price": pivot_price,
            "pivot_extension_pct": pivot_extension_pct,
            "ema_20": ema_20,
            "ema20_dist_pct": ema20_dist_pct,
            "ema_50": ema_50,
            "stop_loss": stop_loss,
            "downside_risk_pct": downside_risk_pct,
            "target_1": target_1,
            "upside_target_pct": upside_target_pct,
            "rr_ratio": rr_ratio,
            "cfo_ratio_pct": cfo_ratio,
            "current_pe": current_pe,
            "median_pe": median_pe,
            "roe_pct": roe_pct,
            "roce_pct": prof_data.get("roce_pct", 0.0),
            "debt_to_equity": debt_to_equity,
            "volume_ratio": volume_ratio
        },
        "cro_verdict": cro_verdict,
        "devils_advocate": devils_advocate,
        "recommendation": recommendation,
        "formatted_markdown": diagnostic_text,
        "model_id": model,
        "model_label": model_label,
        "from_cache": False,
        "created_at": time.time()
    }

    # 9. Persist to cache
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("""
        INSERT OR REPLACE INTO cached_psychology_audits (cache_key, payload_json, created_at)
        VALUES (?, ?, ?)
        """, (cache_key, json.dumps(result_payload), time.time()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"[Trade Psychologist] Cache save warning: {e}")

    return result_payload
