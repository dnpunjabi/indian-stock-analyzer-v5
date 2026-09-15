import re

# Update backend/static/app.js with Business Day time object conversion for Lightweight Charts
app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    js = f.read()

# 1. Update timeScale config in createChart to clean standard options
old_timescale = """            timeScale: {
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)',
                visible: true,
                borderVisible: true,
                rightOffset: 5,
                barSpacing: 6,
                minBarSpacing: 1,
            },"""

new_timescale = """            timeScale: {
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)',
                visible: true,
                borderVisible: true,
                timeVisible: false,
                secondsVisible: false,
            },"""

if old_timescale in js:
    js = js.replace(old_timescale, new_timescale)
    print("Updated timeScale config in createChart in app.js")

# 2. Update candleData mapping to use clean business day time format
old_mapping = """        // Strictly sanitize, sort and deduplicate candlestick data for Lightweight Charts
        const rawCandles = (data.candlesticks || [])
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

        window.activeTVCandleData = candleData;
        candleSeries.setData(candleData);
        chart.timeScale().fitContent();"""

new_mapping = """        // Helper to format string date YYYY-MM-DD into Business Day object { year, month, day }
        const parseBusinessDay = (timeStr) => {
            if (!timeStr) return null;
            const parts = String(timeStr).trim().split('-');
            if (parts.length === 3) {
                const y = parseInt(parts[0], 10);
                const m = parseInt(parts[1], 10);
                const d = parseInt(parts[2], 10);
                if (!isNaN(y) && !isNaN(m) && !isNaN(d)) {
                    return { year: y, month: m, day: d };
                }
            }
            return timeStr;
        };

        // Strictly sanitize, sort and deduplicate candlestick data for Lightweight Charts
        const rawCandles = (data.candlesticks || [])
            .filter(c => c && c.time && typeof c.time === 'string')
            .map(c => {
                const tStr = c.time.trim();
                return {
                    time: tStr,
                    timeObj: parseBusinessDay(tStr),
                    open: Number(c.open),
                    high: Number(c.high),
                    low: Number(c.low),
                    close: Number(c.close),
                    volume: Number(c.volume || 0)
                };
            })
            .sort((a, b) => a.time.localeCompare(b.time));

        const candleData = [];
        const seenTimes = new Set();
        for (const item of rawCandles) {
            if (!seenTimes.has(item.time)) {
                seenTimes.add(item.time);
                candleData.push({
                    time: item.timeObj,
                    rawTimeStr: item.time,
                    open: item.open,
                    high: item.high,
                    low: item.low,
                    close: item.close
                });
            }
        }

        window.activeTVCandleData = candleData;
        candleSeries.setData(candleData);
        chart.timeScale().fitContent();"""

if old_mapping in js:
    js = js.replace(old_mapping, new_mapping)
    print("Updated candleData mapping to use Business Day objects in app.js")

# 3. Update volume series time mapping to use Business Day objects
old_vol_mapping = """            const volumeData = data.candlesticks.map(c => {
                const isUp = c.close >= c.open;
                return {
                    time: c.time,
                    value: c.volume,
                    color: isUp ? 'rgba(16, 185, 129, 0.35)' : 'rgba(239, 68, 68, 0.35)',
                };
            }).filter(d => d.value !== undefined && d.value !== null);"""

new_vol_mapping = """            const volumeData = candleData.map(c => {
                const isUp = c.close >= c.open;
                return {
                    time: c.time,
                    value: c.volume || 0,
                    color: isUp ? 'rgba(16, 185, 129, 0.35)' : 'rgba(239, 68, 68, 0.35)',
                };
            });"""

if old_vol_mapping in js:
    js = js.replace(old_vol_mapping, new_vol_mapping)
    print("Updated volumeData time mapping in app.js")

# 4. Update window.applyIChartTimeframe to work with candleData objects
old_apply_tf = """    const fromIdx = Math.max(0, totalBars - numBars);
    const fromCandle = dataArr[fromIdx];
    const lastCandle = dataArr[totalBars - 1];

    try {
        if (fromCandle && fromCandle.time && lastCandle && lastCandle.time) {
            chart.timeScale().setVisibleRange({
                from: fromCandle.time,
                to: lastCandle.time
            });
        } else {
            chart.timeScale().setVisibleLogicalRange({
                from: fromIdx,
                to: totalBars - 1
            });
        }
    } catch (err) {
        try {
            chart.timeScale().setVisibleLogicalRange({
                from: fromIdx,
                to: totalBars - 1
            });
        } catch (e2) {
            chart.timeScale().fitContent();
        }
    }"""

new_apply_tf = """    const fromIdx = Math.max(0, totalBars - numBars);
    const fromCandle = dataArr[fromIdx];
    const lastCandle = dataArr[totalBars - 1];

    try {
        if (fromCandle && fromCandle.time && lastCandle && lastCandle.time) {
            chart.timeScale().setVisibleRange({
                from: fromCandle.time,
                to: lastCandle.time
            });
        } else {
            chart.timeScale().setVisibleLogicalRange({
                from: fromIdx,
                to: totalBars - 1
            });
        }
    } catch (err) {
        chart.timeScale().fitContent();
    }"""

if old_apply_tf in js:
    js = js.replace(old_apply_tf, new_apply_tf)
    print("Updated applyIChartTimeframe in app.js")

# Update asset version in index.html to 5.3.1
html_path = 'backend/static/index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

html = html.replace('app.js?v=5.3.0', 'app.js?v=5.3.1')

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(js)

print("Done applying fix_ichart_timeline_business_day.py!")
