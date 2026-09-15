import sys
import os
import pandas as pd
import numpy as np
import asyncio

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.main import fetch_history_df

async def validate_stocks_30wk_slope(symbols):
    print("==========================================================================================")
    print("               30-WEEK MOVING AVERAGE SLOPE VALIDATION REPORT                             ")
    print("==========================================================================================")
    print(f"{'Symbol':<15} | {'Price':<10} | {'30W MA (Today)':<15} | {'30W MA (20d Ago)':<15} | {'Slope % (20d)':<12} | {'Stage / Status'}")
    print("-" * 96)
    
    for sym in symbols:
        sym_yf = f"{sym}.NS" if not sym.endswith(".NS") else sym
        try:
            df = await fetch_history_df(sym_yf, period="1y", interval="1d")
            if df is None or df.empty or len(df) < 60:
                print(f"{sym:<15} | Insufficient daily price history (<60 bars)")
                continue
            
            close = df['Close']
            curr_price = float(close.iloc[-1])
            
            # 150-day Simple Moving Average (30-Week MA)
            sma_150 = close.rolling(150, min_periods=30).mean()
            curr_30w = float(sma_150.iloc[-1])
            past_20d_30w = float(sma_150.iloc[-20]) if len(sma_150) >= 20 else curr_30w
            
            slope_pct = ((curr_30w - past_20d_30w) / past_20d_30w) * 100.0 if past_20d_30w > 0 else 0.0
            
            # 200-day Simple Moving Average (40-Week MA) for secondary verification
            sma_200 = close.rolling(200, min_periods=50).mean()
            curr_200 = float(sma_200.iloc[-1])
            past_20d_200 = float(sma_200.iloc[-20]) if len(sma_200) >= 20 else curr_200
            slope_200_pct = ((curr_200 - past_20d_200) / past_20d_200) * 100.0 if past_20d_200 > 0 else 0.0
            
            if slope_pct > 0.3:
                status = "Stage 2 Mark-Up [Strong Upward Slope]"
            elif slope_pct >= -0.2:
                status = "Stage 1/3 Base/Top [Flat/Turning]"
            else:
                status = "Stage 4 Downtrend [Declining Slope]"
                
            print(f"{sym:<15} | Rs.{curr_price:<8.2f} | Rs.{curr_30w:<13.2f} | Rs.{past_20d_30w:<13.2f} | {slope_pct:+6.2f}%      | {status}")
        except Exception as e:
            print(f"{sym:<15} | Error: {e}")

if __name__ == "__main__":
    test_symbols = [
        "HAL", "BEL", "ADANIPORTS", "CHOLAFIN", "RELIANCE", 
        "TATASTEEL", "BANDHANBNK", "ADANIENT", "YESBANK"
    ]
    asyncio.run(validate_stocks_30wk_slope(test_symbols))
