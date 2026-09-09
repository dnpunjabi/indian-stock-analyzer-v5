import yfinance as yf

df = yf.Ticker('GVT&D.NS').history(period='1y')
highs = df['High'].values
lows = df['Low'].values
closes = df['Close'].values
dates = df.index.strftime('%Y-%m-%d').values
n = len(df)

print("=== GVT&D.NS RECENT OHLC DATES ===")
for i in range(n-25, n):
    print(f"Bar {i:3d} | {dates[i]} | High: Rs.{highs[i]:7.2f} | Low: Rs.{lows[i]:7.2f} | Close: Rs.{closes[i]:7.2f}")
