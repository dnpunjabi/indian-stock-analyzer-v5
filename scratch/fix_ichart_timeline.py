import re

# 1. Update styles.css: Remove destructive canvas and table overrides on .tv-lightweight-charts
styles_path = 'backend/static/styles.css'
with open(styles_path, 'r', encoding='utf-8') as f:
    css_content = f.read()

# Replace lines that force width 100% on canvas and table inside tv-lightweight-charts
target_css_1 = """#tv-chart-card,
#tv-chart-card .card-header,
#tv-chart-container,
#tv-chart-container .tv-lightweight-charts,
#tv-chart-container .tv-lightweight-charts canvas,
#tv-chart-container .tv-lightweight-charts table,
#tv-chart-legend-panel,
#tv-chart-smc-hud-panel {"""

replacement_css_1 = """#tv-chart-card,
#tv-chart-card .card-header,
#tv-chart-container,
#tv-chart-container .tv-lightweight-charts,
#tv-chart-legend-panel,
#tv-chart-smc-hud-panel {"""

if target_css_1 in css_content:
    css_content = css_content.replace(target_css_1, replacement_css_1)
    print("Updated CSS group 1 in styles.css")

target_css_2 = """#tv-chart-container .tv-lightweight-charts,
#tv-chart-container .tv-lightweight-charts canvas,
#tv-chart-container .tv-lightweight-charts table {
    width: 100% !important;
    min-width: 100% !important;
    max-width: 100% !important;
    left: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    box-sizing: border-box !important;
}"""

replacement_css_2 = """#tv-chart-container .tv-lightweight-charts {
    width: 100% !important;
    height: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    box-sizing: border-box !important;
}"""

if target_css_2 in css_content:
    css_content = css_content.replace(target_css_2, replacement_css_2)
    print("Updated CSS group 2 in styles.css")

with open(styles_path, 'w', encoding='utf-8') as f:
    f.write(css_content)

# 2. Update app.js: Update createChart timeScale options & handle timeframe buttons
app_js_path = 'backend/static/app.js'
with open(app_js_path, 'r', encoding='utf-8') as f:
    js_content = f.read()

target_timescale = """            timeScale: {
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
            },"""

replacement_timescale = """            timeScale: {
                visible: true,
                timeVisible: false,
                secondsVisible: false,
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.12)',
                borderVisible: true,
                fitContent: true,
            },"""

if target_timescale in js_content:
    js_content = js_content.replace(target_timescale, replacement_timescale)
    print("Updated timeScale options in app.js")

# Add timeframe button binding helper inside renderTVWorkstationChart
target_fit_content = "activeTVWorkstationChart = chart;"
replacement_fit_content = """activeTVWorkstationChart = chart;

        // Timeline timeframe quick range selection handler
        const setupTfButtons = (candleDataArr) => {
            const btns = document.querySelectorAll('.tv-tf-btn');
            if (!btns.length || !candleDataArr.length) return;
            btns.forEach(btn => {
                btn.onclick = () => {
                    btns.forEach(b => {
                        b.classList.remove('active');
                        b.style.background = 'transparent';
                        b.style.color = 'var(--text-secondary)';
                    });
                    btn.classList.add('active');
                    btn.style.background = '#3b82f6';
                    btn.style.color = '#ffffff';

                    const range = btn.getAttribute('data-range');
                    if (range === 'ALL') {
                        chart.timeScale().fitContent();
                        return;
                    }

                    const lastCandle = candleDataArr[candleDataArr.length - 1];
                    const lastDate = new Date(lastCandle.time);
                    let fromDate = new Date(lastDate);

                    if (range === '1M') fromDate.setMonth(fromDate.getMonth() - 1);
                    else if (range === '3M') fromDate.setMonth(fromDate.getMonth() - 3);
                    else if (range === '6M') fromDate.setMonth(fromDate.getMonth() - 6);
                    else if (range === '1Y') fromDate.setFullYear(fromDate.getFullYear() - 1);
                    else if (range === 'YTD') fromDate = new Date(lastDate.getFullYear(), 0, 1);

                    const fromStr = fromDate.toISOString().split('T')[0];
                    chart.timeScale().setVisibleRange({
                        from: fromStr,
                        to: lastCandle.time
                    });
                };
            });
        };"""

if target_fit_content in js_content and "setupTfButtons" not in js_content:
    js_content = js_content.replace(target_fit_content, replacement_fit_content, 1)
    print("Added setupTfButtons to app.js")

# Call setupTfButtons after candleSeries.setData(candleData)
target_set_data = "candleSeries.setData(candleData);"
replacement_set_data = """candleSeries.setData(candleData);
        setupTfButtons(candleData);"""

if target_set_data in js_content and "setupTfButtons(candleData);" not in js_content:
    js_content = js_content.replace(target_set_data, replacement_set_data, 1)
    print("Called setupTfButtons in app.js")

with open(app_js_path, 'w', encoding='utf-8') as f:
    f.write(js_content)

# 3. Update index.html: Add timeline timeframe quick selector bar & update version
html_path = 'backend/static/index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    html_content = f.read()

target_html_container = """                                <!-- Chart Canvas Container -->
                                <div id="tv-chart-container" style="width: 100%; height: 420px; border-radius: 6px; overflow: hidden; border: 1px solid var(--border-glass); background: transparent; position: relative;">
                                    <!-- Loaded dynamically via Lightweight Charts -->
                                </div>"""

replacement_html_container = """                                <!-- Chart Canvas Container -->
                                <div id="tv-chart-container" style="width: 100%; height: 420px; border-radius: 6px; overflow: hidden; border: 1px solid var(--border-glass); background: transparent; position: relative;">
                                    <!-- Loaded dynamically via Lightweight Charts -->
                                </div>
                                <!-- Timeline Quick Timeframe Selector Bar -->
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

if target_html_container in html_content:
    html_content = html_content.replace(target_html_container, replacement_html_container)
    print("Added timeline selector bar to index.html")

# Update asset version in index.html to 5.2.2
html_content = html_content.replace('app.js?v=5.2.1', 'app.js?v=5.2.2')

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html_content)

print("Done updating timeline fix across styles.css, app.js, and index.html")
