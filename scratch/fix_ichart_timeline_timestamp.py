import re

# Update app.js to use Unix timestamp integers for Lightweight Charts timeline date labels
app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    js = f.read()

# Replace candlestick data mapping to use integer Unix timestamps for time
old_mapping = """        const rawCandles = (data.candlesticks || [])
            .filter(c => c && c.time && typeof c.time === 'string')
            .map(c => ({
                time: c.time.trim(),
                open: Number(c.open),
                high: Number(c.high),
                low: Number(c.low),
                close: Number(c.close)
            }))
            .sort((a, b) => a.time.localeCompare(b.time));

        const candleData = [];
        const seenTimes = new Set();
        for (const item of rawCandles) {
            if (!seenTimes.has(item.time)) {
                seenTimes.add(item.time);
                candleData.push(item);
            }
        }

        candleSeries.setData(candleData);
        chart.timeScale().fitContent();"""

new_mapping = """        // Convert string YYYY-MM-DD to integer Unix timestamp (in seconds) for 100% reliable timeline dates
        const parseUnixSeconds = (timeStr) => {
            if (!timeStr) return 0;
            const cleanStr = String(timeStr).trim();
            const dateObj = new Date(cleanStr.includes('T') ? cleanStr : cleanStr + 'T00:00:00Z');
            return Math.floor(dateObj.getTime() / 1000);
        };

        const rawCandles = (data.candlesticks || [])
            .filter(c => c && c.time && typeof c.time === 'string')
            .map(c => {
                const tStr = c.time.trim();
                const ts = parseUnixSeconds(tStr);
                return {
                    time: ts > 0 ? ts : tStr,
                    rawTimeStr: tStr,
                    open: Number(c.open),
                    high: Number(c.high),
                    low: Number(c.low),
                    close: Number(c.close),
                    volume: Number(c.volume || 0)
                };
            })
            .filter(c => c.time > 0)
            .sort((a, b) => a.time - b.time);

        const candleData = [];
        const seenTimes = new Set();
        for (const item of rawCandles) {
            if (!seenTimes.has(item.time)) {
                seenTimes.add(item.time);
                candleData.push({
                    time: item.time,
                    open: item.open,
                    high: item.high,
                    low: item.low,
                    close: item.close
                });
            }
        }

        candleSeries.setData(candleData);
        chart.timeScale().fitContent();"""

if old_mapping in js:
    js = js.replace(old_mapping, new_mapping)
    print("Updated candleData mapping to use Unix timestamps in app.js")

# Update volumeSeries time mapping to use Unix timestamps
old_vol = """            const volumeData = candleData.map(c => {
                const isUp = c.close >= c.open;
                return {
                    time: c.time,
                    value: c.volume || 0,
                    color: isUp ? 'rgba(16, 185, 129, 0.35)' : 'rgba(239, 68, 68, 0.35)',
                };
            });"""

new_vol = """            const volumeData = rawCandles.map(c => {
                const isUp = c.close >= c.open;
                return {
                    time: c.time,
                    value: c.volume || 0,
                    color: isUp ? 'rgba(16, 185, 129, 0.35)' : 'rgba(239, 68, 68, 0.35)',
                };
            });"""

if old_vol in js:
    js = js.replace(old_vol, new_vol)
    print("Updated volumeData mapping to use Unix timestamps in app.js")

# Update createChart height to 480px and clean timeScale config
old_create_chart = """        const chart = LightweightCharts.createChart(container, {
            width: container.clientWidth || 600,
            height: 460,
            layout: {
                background: { type: 'solid', color: 'transparent' },
                textColor: isDarkTheme ? '#94a3b8' : '#334155',
                fontFamily: 'Inter, sans-serif',
            },
            grid: {
                vertLines: { color: isDarkTheme ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.03)' },
                horzLines: { color: isDarkTheme ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.03)' },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
            },
            rightPriceScale: {
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)',
                visible: true,
            },
            timeScale: {
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)',
                visible: true,
                borderVisible: true,
                timeVisible: false,
                secondsVisible: false,
                rightOffset: 5,
            },
        });"""

new_create_chart = """        const chart = LightweightCharts.createChart(container, {
            width: container.clientWidth || 600,
            height: 480,
            layout: {
                background: { type: 'solid', color: 'transparent' },
                textColor: isDarkTheme ? '#94a3b8' : '#334155',
                fontFamily: 'Inter, sans-serif',
            },
            grid: {
                vertLines: { color: isDarkTheme ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.03)' },
                horzLines: { color: isDarkTheme ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.03)' },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
            },
            rightPriceScale: {
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)',
                visible: true,
            },
            timeScale: {
                visible: true,
                borderVisible: true,
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)',
                timeVisible: false,
                secondsVisible: false,
            },
        });"""

if old_create_chart in js:
    js = js.replace(old_create_chart, new_create_chart)
    print("Updated createChart block in app.js")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(js)

# Update index.html and styles.css height to 480px
html_path = 'backend/static/index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

html = html.replace('height: 460px;', 'height: 480px;')
html = html.replace('app.js?v=5.4.1', 'app.js?v=5.4.2')
html = html.replace('app.js?v=5.4.0', 'app.js?v=5.4.2')
with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

styles_path = 'backend/static/styles.css'
with open(styles_path, 'r', encoding='utf-8') as f:
    css = f.read()

css = css.replace('height: 460px;', 'height: 480px;')
css = css.replace('min-height: 460px;', 'min-height: 480px;')
with open(styles_path, 'w', encoding='utf-8') as f:
    f.write(css)

print("Finished applying fix_ichart_timeline_timestamp.py!")
