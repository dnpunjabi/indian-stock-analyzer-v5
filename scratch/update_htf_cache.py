import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath('.'))
from backend.main import get_db, fetch_history_df, _save_screener_db_cache
from backend.swing_utils import detect_high_tight_flag

async def update_htf():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, company_name, sector, cap_type FROM screener_universe WHERE symbol NOT LIKE '%DUMMY%'")
        stocks = [dict(r) for r in cursor.fetchall()]

    sem = asyncio.Semaphore(25)

    async def check(item):
        sym = item['symbol']
        try:
            df = await fetch_history_df(sym, period='6mo', interval='1d')
            if df is not None and not df.empty:
                h_res = detect_high_tight_flag(df)
                if h_res.get('is_htf') or h_res.get('htf_status') in ['HTF_BREAKOUT_READY', 'HTF_FLAG_FORMING']:
                    return {
                        'symbol': sym,
                        'base_symbol': sym.replace('.NS', '').replace('.BO', ''),
                        'company_name': item['company_name'],
                        'sector': item['sector'],
                        'cap_type': item['cap_type'],
                        'htf_status': h_res['htf_status'],
                        'pole_gain_pct': h_res['pole_gain_pct'],
                        'flag_depth_pct': h_res['flag_depth_pct'],
                        'flag_days': h_res['flag_days'],
                        'vdu_ratio': h_res['vdu_ratio'],
                        'pivot_price': h_res['pivot_price'],
                        'current_price': h_res['current_price'],
                        'day_change_pct': h_res.get('day_change_pct', 0.0)
                    }
        except Exception:
            pass
        return None

    results = [r for r in await asyncio.gather(*[check(item) for item in stocks]) if r is not None]
    results.sort(key=lambda x: (x["htf_status"] == "HTF_BREAKOUT_READY", x["pole_gain_pct"]), reverse=True)
    _save_screener_db_cache('htf', results)
    print(f'Saved {len(results)} HTF setup(s) to database cache: {[r["symbol"] for r in results]}')

if __name__ == "__main__":
    asyncio.run(update_htf())
