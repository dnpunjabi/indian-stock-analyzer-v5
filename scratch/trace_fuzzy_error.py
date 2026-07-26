import os
import sys
import traceback
import dotenv

dotenv.load_dotenv()
sys.path.insert(0, os.path.abspath('.'))

from backend.main import get_db, get_fuzzy_summary_for_symbol

with get_db() as conn:
    row = conn.execute("SELECT symbol FROM watchlist_items LIMIT 1").fetchone()
    sym = row["symbol"]
    print(f"Testing symbol: {sym}")
    try:
        row = conn.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ? OR symbol = ?", (sym, sym.split('.')[0])).fetchone()
        if row:
            print("Found cached profile!")
        else:
            print("No cached profile found!")
    except Exception as e:
        traceback.print_exc()

    # Now let's run get_fuzzy_summary_for_symbol with explicit exception catching:
    try:
        import json
        from backend.fuzzy_engine import evaluate_fuzzy_logic
        row = conn.execute("SELECT profile_json FROM cached_profiles WHERE symbol = ? OR symbol = ?", (sym, sym.split('.')[0])).fetchone()
        profile = json.loads(row["profile_json"])
        fundamentals = profile.get("fundamentals", {})
        technicals = profile.get("technicals", {})
        quality = profile.get("earnings_quality", {})
        sector = profile.get("sector", "Unknown")

        rsi = float(technicals.get("rsi", 50.0))
        current_price = float(technicals.get("current_price", 0.0))
        sma_200 = float(technicals.get("sma_200", 0.0))
        dma_prox = ((current_price - sma_200) / sma_200 * 100.0) if sma_200 > 0 else 0.0
        trend_str = technicals.get("trend_50_vs_200", "Neutral")
        adx = float(technicals.get("adx", 22.0))

        stage = 1
        if trend_str == "Bullish" and current_price >= sma_200:
            stage = 2
        elif trend_str == "Bearish" and current_price < sma_200:
            stage = 4
        elif rsi > 65 and trend_str != "Bullish":
            stage = 3

        altman_z = float(quality.get("altman_z_score", 3.0))
        piotroski = int(quality.get("piotroski_score", 6))
        promoter_holding = float(fundamentals.get("promoter_holding_pct", 50.0))
        promoter_pledge_delta = float(fundamentals.get("promoter_pledge_pct", 0.0))

        volume = float(fundamentals.get("volume", 1.0))
        average_volume = float(fundamentals.get("average_volume", 1.0))
        relative_volume = volume / average_volume if average_volume > 0 else 1.0

        sector_markdown = False
        sec_row = conn.execute("SELECT return_1m FROM sector_regime_stats WHERE sector = ?", (sector,)).fetchone()
        if sec_row and sec_row["return_1m"] is not None and float(sec_row["return_1m"]) < -5.0:
            sector_markdown = True

        sales_growth = float(fundamentals.get("sales_growth_3y_pct", 0.0))
        profit_growth = float(fundamentals.get("profit_growth_3y_pct", 0.0))
        roe_pct = float(fundamentals.get("roe_pct", 12.0))
        opm_delta = (profit_growth - sales_growth) / 10.0
        roe_delta = 1.0 if roe_pct > 15.0 else -1.0 if roe_pct < 8.0 else 0.0
        debt_delta = 0.0

        res = evaluate_fuzzy_logic(
            opm_delta=opm_delta, roe_delta=roe_delta, debt_delta=debt_delta,
            rsi=rsi, dma_prox=dma_prox, adx=adx, stage=stage,
            altman_z=altman_z, piotroski=piotroski,
            promoter_holding=promoter_holding, promoter_pledge_delta=promoter_pledge_delta,
            relative_volume=relative_volume, sector_markdown=sector_markdown
        )
        print("Success! Result:", res)
    except Exception as err:
        traceback.print_exc()
