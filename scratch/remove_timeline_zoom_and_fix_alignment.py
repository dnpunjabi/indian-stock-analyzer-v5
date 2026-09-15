import re

# 1. Update index.html: Remove tv-chart-timeframe-bar and update container height to 460px
html_path = 'backend/static/index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

# Remove timeframe bar HTML block
tf_bar_pattern = r'<!-- Timeline Quick Timeframe Selector Bar -->\s*<div id="tv-chart-timeframe-bar".*?</div>\s*'
html = re.sub(tf_bar_pattern, '', html, flags=re.DOTALL)

# Reset container height to 460px with overflow hidden for crisp alignment
html = html.replace('height: 480px;', 'height: 460px;')
html = html.replace('overflow: visible;', 'overflow: hidden;')

# Update asset version to 5.4.0
html = html.replace('app.js?v=5.3.3', 'app.js?v=5.4.0')
html = html.replace('app.js?v=5.3.2', 'app.js?v=5.4.0')

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)
print("Updated index.html: removed timeframe zoom bar, set container height to 460px")

# 2. Update styles.css: Reset container height to 460px
styles_path = 'backend/static/styles.css'
with open(styles_path, 'r', encoding='utf-8') as f:
    css = f.read()

css = css.replace('height: 480px;', 'height: 460px;')
css = css.replace('min-height: 480px;', 'min-height: 460px;')

with open(styles_path, 'w', encoding='utf-8') as f:
    f.write(css)
print("Updated styles.css: height set to 460px")

# 3. Update app.js: Clean up timeScale options, remove setupTfButtons, ensure fitContent() is called
app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    js = f.read()

# Remove window.applyIChartTimeframe helper if present
if "window.applyIChartTimeframe = function" in js:
    js = re.sub(r'// ==================== GLOBAL ICHART TIMEFRAME ZOOM HANDLER ====================.*?window\.applyIChartTimeframe = function.*?};\n', '', js, flags=re.DOTALL)

# Set clean timeScale options in createChart
old_create_chart = """        const chart = LightweightCharts.createChart(container, {
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
                scaleMargins: {
                    top: 0.08,
                    bottom: 0.08,
                },
            },
            timeScale: {
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)',
                visible: true,
                borderVisible: true,
                timeVisible: false,
                secondsVisible: false,
            },
        });"""

new_create_chart = """        const chart = LightweightCharts.createChart(container, {
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
                visible: true,
                borderVisible: true,
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)',
            },
        });"""

if old_create_chart in js:
    js = js.replace(old_create_chart, new_create_chart)
    print("Updated createChart block in app.js")

# Clean up candleData mapping and ensure chart.timeScale().fitContent() is called
old_data_setting = """        const candleData = data.candlesticks.map(c => ({
            time: c.time,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close
        }));
        candleSeries.setData(candleData);"""

new_data_setting = """        const rawCandles = (data.candlesticks || [])
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

if old_data_setting in js:
    js = js.replace(old_data_setting, new_data_setting)
    print("Updated candleData setting & fitContent in app.js")

# Remove volume scaleMargins override if present
js = js.replace("""            volumeSeries.priceScale().applyOptions({
                scaleMargins: {
                    top: 0.8,
                    bottom: 0.05,
                },
            });""", """            volumeSeries.priceScale().applyOptions({
                scaleMargins: {
                    top: 0.8,
                    bottom: 0.02,
                },
            });""")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(js)

print("Finished applying remove_timeline_zoom_and_fix_alignment.py!")
