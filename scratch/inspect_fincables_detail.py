import sys
import os
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

def inspect_fincables_details():
    ticker = "FINCABLES.NS"
    df = yf.download(ticker, period="1y", interval="1d", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    close = df['Close'].iloc[-1]
    high_52w = df['High'].max()
    sma50 = df['Close'].rolling(50).mean().iloc[-1]
    dist_50d_sma = ((close - sma50) / sma50) * 100
    dist_52w_high = ((close - high_52w) / high_52w) * 100

    print("=== FINOLEX CABLES (FINCABLES.NS) DETAILED PRICE METRICS ===")
    print(f"Current Close Price: ₹{close:.2f}")
    print(f"52-Week High: ₹{high_52w:.2f}")
    print(f"Distance to 52W High: {dist_52w_high:.2f}%")
    print(f"50-Day SMA: ₹{sma50:.2f}")
    print(f"Price Extension above 50D SMA: +{dist_50d_sma:.2f}%")
    
    print("\nRecent 5 Trading Days:")
    tail = df.tail(5)
    for idx, row in tail.iterrows():
        date_str = idx.strftime('%Y-%m-%d')
        prev_close = df['Close'].shift(1).loc[idx]
        gap_pct = ((row['Open'] - prev_close) / prev_close) * 100
        vol = row['Volume']
        print(f"Date: {date_str} | Open: ₹{row['Open']:.2f} | Close: ₹{row['Close']:.2f} | Gap: {gap_pct:+.2f}% | Vol: {vol:,.0f}")

if __name__ == "__main__":
    inspect_fincables_details()
