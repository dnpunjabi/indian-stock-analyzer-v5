import re

# 1. Update index.html: Add inline onclick="applyIChartTimeframe('...')" to all timeline zoom buttons
html_path = 'backend/static/index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

old_tf_bar = """                                <!-- Timeline Quick Timeframe Selector Bar -->
                                <div id="tv-chart-timeframe-bar" style="display: flex; gap: 6px; align-items: center; justify-content: flex-start; padding: 6px 12px; background: var(--bg-card-sub); border-radius: 6px; border: 1px solid var(--border-glass); font-size: 12px; flex-wrap: wrap;">
                                    <span style="font-size: 11px; font-weight: 700; color: var(--text-muted); margin-right: 4px; text-transform: uppercase; letter-spacing: 0.05em; display: flex; align-items: center; gap: 4px;">
                                        📅 Timeline Zoom:
                                    </span>
                                    <button type="button" class="tv-tf-btn" data-range="1M" style="padding: 3px 10px; font-size: 11.5px; font-weight: 600; border-radius: 4px; border: 1px solid var(--border-glass); background: transparent; color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease;">1M</button>
                                    <button type="button" class="tv-tf-btn" data-range="3M" style="padding: 3px 10px; font-size: 11.5px; font-weight: 600; border-radius: 4px; border: 1px solid var(--border-glass); background: transparent; color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease;">3M</button>
                                    <button type="button" class="tv-tf-btn" data-range="6M" style="padding: 3px 10px; font-size: 11.5px; font-weight: 600; border-radius: 4px; border: 1px solid var(--border-glass); background: transparent; color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease;">6M</button>
                                    <button type="button" class="tv-tf-btn" data-range="1Y" style="padding: 3px 10px; font-size: 11.5px; font-weight: 600; border-radius: 4px; border: 1px solid var(--border-glass); background: transparent; color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease;">1Y</button>
                                    <button type="button" class="tv-tf-btn" data-range="YTD" style="padding: 3px 10px; font-size: 11.5px; font-weight: 600; border-radius: 4px; border: 1px solid var(--border-glass); background: transparent; color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease;">YTD</button>
                                    <button type="button" class="tv-tf-btn active" data-range="ALL" style="padding: 3px 10px; font-size: 11.5px; font-weight: 600; border-radius: 4px; border: 1px solid var(--border-glass); background: #3b82f6; color: #ffffff; cursor: pointer; transition: all 0.15s ease;">ALL</button>
                                </div>"""

new_tf_bar = """                                <!-- Timeline Quick Timeframe Selector Bar -->
                                <div id="tv-chart-timeframe-bar" style="display: flex; gap: 6px; align-items: center; justify-content: flex-start; padding: 6px 12px; background: var(--bg-card-sub); border-radius: 6px; border: 1px solid var(--border-glass); font-size: 12px; flex-wrap: wrap;">
                                    <span style="font-size: 11px; font-weight: 700; color: var(--text-muted); margin-right: 4px; text-transform: uppercase; letter-spacing: 0.05em; display: flex; align-items: center; gap: 4px;">
                                        📅 Timeline Zoom:
                                    </span>
                                    <button type="button" class="tv-tf-btn" data-range="1M" onclick="applyIChartTimeframe('1M')" style="padding: 3px 10px; font-size: 11.5px; font-weight: 600; border-radius: 4px; border: 1px solid var(--border-glass); background: transparent; color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease;">1M</button>
                                    <button type="button" class="tv-tf-btn" data-range="3M" onclick="applyIChartTimeframe('3M')" style="padding: 3px 10px; font-size: 11.5px; font-weight: 600; border-radius: 4px; border: 1px solid var(--border-glass); background: transparent; color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease;">3M</button>
                                    <button type="button" class="tv-tf-btn" data-range="6M" onclick="applyIChartTimeframe('6M')" style="padding: 3px 10px; font-size: 11.5px; font-weight: 600; border-radius: 4px; border: 1px solid var(--border-glass); background: transparent; color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease;">6M</button>
                                    <button type="button" class="tv-tf-btn" data-range="1Y" onclick="applyIChartTimeframe('1Y')" style="padding: 3px 10px; font-size: 11.5px; font-weight: 600; border-radius: 4px; border: 1px solid var(--border-glass); background: transparent; color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease;">1Y</button>
                                    <button type="button" class="tv-tf-btn" data-range="YTD" onclick="applyIChartTimeframe('YTD')" style="padding: 3px 10px; font-size: 11.5px; font-weight: 600; border-radius: 4px; border: 1px solid var(--border-glass); background: transparent; color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease;">YTD</button>
                                    <button type="button" class="tv-tf-btn active" data-range="ALL" onclick="applyIChartTimeframe('ALL')" style="padding: 3px 10px; font-size: 11.5px; font-weight: 600; border-radius: 4px; border: 1px solid var(--border-glass); background: #3b82f6; color: #ffffff; cursor: pointer; transition: all 0.15s ease;">ALL</button>
                                </div>"""

if old_tf_bar in html:
    html = html.replace(old_tf_bar, new_tf_bar)
    print("Updated index.html with direct inline onclick handlers")

html = html.replace('app.js?v=5.2.5', 'app.js?v=5.3.0')

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

# 2. Update app.js: Define global window.applyIChartTimeframe and sanitize/deduplicate candlestick data
app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    js = f.read()

# Add global applyIChartTimeframe function definition at the top of chart renderer section
global_tf_func = """// ==================== GLOBAL ICHART TIMEFRAME ZOOM HANDLER ====================
window.applyIChartTimeframe = function(range) {
    const chart = window.activeTVWorkstationChart;
    const dataArr = window.activeTVCandleData;
    const btns = document.querySelectorAll('.tv-tf-btn');

    btns.forEach(b => {
        const bRange = b.getAttribute('data-range');
        if (bRange === range) {
            b.classList.add('active');
            b.style.background = '#3b82f6';
            b.style.color = '#ffffff';
            b.style.borderColor = '#3b82f6';
        } else {
            b.classList.remove('active');
            b.style.background = 'transparent';
            b.style.color = 'var(--text-secondary)';
            b.style.borderColor = 'var(--border-glass)';
        }
    });

    if (!chart) return;

    if (range === 'ALL' || !dataArr || !dataArr.length) {
        chart.timeScale().fitContent();
        return;
    }

    const totalBars = dataArr.length;
    let numBars = totalBars;

    if (range === '1M') numBars = 22;
    else if (range === '3M') numBars = 66;
    else if (range === '6M') numBars = 126;
    else if (range === '1Y') numBars = 252;
    else if (range === 'YTD') {
        const currentYear = new Date().getFullYear();
        const firstYtdIdx = dataArr.findIndex(c => {
            if (!c || !c.time) return false;
            const yr = parseInt(String(c.time).split('-')[0], 10);
            return yr === currentYear;
        });
        if (firstYtdIdx !== -1 && firstYtdIdx < totalBars) {
            numBars = totalBars - firstYtdIdx;
        } else {
            numBars = Math.min(180, totalBars);
        }
    }

    const fromIdx = Math.max(0, totalBars - numBars);
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
    }
};
"""

if "window.applyIChartTimeframe = function" not in js:
    target_render_marker = "// ==================== INTERACTIVE WORKSTATION CHART CONTROLS & RENDERER ===================="
    js = js.replace(target_render_marker, global_tf_func + "\n" + target_render_marker)
    print("Added global applyIChartTimeframe function to app.js")

# Update candlestick data sanitization in app.js
old_candle_mapping = """        const candleData = data.candlesticks.map(c => ({
            time: c.time,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close
        }));
        candleSeries.setData(candleData);
        setupTfButtons(candleData);"""

new_candle_mapping = """        // Strictly sanitize, sort and deduplicate candlestick data for Lightweight Charts
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

if old_candle_mapping in js:
    js = js.replace(old_candle_mapping, new_candle_mapping)
    print("Updated candlestick data sanitization in app.js")

# Update timeScale config in createChart
old_timescale_config = """            timeScale: {
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)',
                visible: true,
                borderVisible: true,
            },"""

new_timescale_config = """            timeScale: {
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)',
                visible: true,
                borderVisible: true,
                rightOffset: 5,
                barSpacing: 6,
                minBarSpacing: 1,
            },"""

if old_timescale_config in js:
    js = js.replace(old_timescale_config, new_timescale_config)
    print("Updated timeScale config in createChart in app.js")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(js)

print("Done applying apply_quick_timeline_fix.py")
