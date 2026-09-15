import re

# Update app.js: Fix timeScale options and setupTfButtons
app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    js = f.read()

# 1. Clean up timeScale options in createChart
old_timescale = """            timeScale: {
                visible: true,
                timeVisible: false,
                secondsVisible: false,
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.12)',
                borderVisible: true,
                fitContent: true,
            },"""

new_timescale = """            timeScale: {
                visible: true,
                timeVisible: false,
                secondsVisible: false,
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)',
                borderVisible: true,
            },"""

if old_timescale in js:
    js = js.replace(old_timescale, new_timescale)
    print("Fixed timeScale options in app.js")

# 2. Update setupTfButtons implementation to use setVisibleLogicalRange
old_setup_tf = """        // Timeline timeframe quick range selection handler
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

new_setup_tf = """        // Timeline timeframe quick range selection handler
        const setupTfButtons = (candleDataArr) => {
            const btns = document.querySelectorAll('.tv-tf-btn');
            if (!btns.length || !candleDataArr || !candleDataArr.length) return;
            const totalBars = candleDataArr.length;
            btns.forEach(btn => {
                btn.onclick = (e) => {
                    if (e) e.stopPropagation();
                    btns.forEach(b => {
                        b.classList.remove('active');
                        b.style.background = 'transparent';
                        b.style.color = 'var(--text-secondary)';
                    });
                    btn.classList.add('active');
                    btn.style.background = '#3b82f6';
                    btn.style.color = '#ffffff';

                    const range = btn.getAttribute('data-range');
                    if (range === 'ALL' || !totalBars) {
                        chart.timeScale().fitContent();
                        return;
                    }

                    let numBars = totalBars;
                    if (range === '1M') numBars = 22;
                    else if (range === '3M') numBars = 66;
                    else if (range === '6M') numBars = 126;
                    else if (range === '1Y') numBars = 252;
                    else if (range === 'YTD') {
                        const currentYear = new Date().getFullYear();
                        const firstYtdIdx = candleDataArr.findIndex(c => {
                            if (!c || !c.time) return false;
                            const yr = parseInt(c.time.split('-')[0], 10);
                            return yr === currentYear;
                        });
                        if (firstYtdIdx !== -1 && firstYtdIdx < totalBars) {
                            numBars = totalBars - firstYtdIdx;
                        } else {
                            numBars = 180;
                        }
                    }

                    const fromIndex = Math.max(0, totalBars - numBars);
                    try {
                        chart.timeScale().setVisibleLogicalRange({
                            from: fromIndex,
                            to: totalBars - 1
                        });
                    } catch (err) {
                        console.warn('setVisibleLogicalRange error:', err);
                        chart.timeScale().fitContent();
                    }
                };
            });
        };"""

if old_setup_tf in js:
    js = js.replace(old_setup_tf, new_setup_tf)
    print("Updated setupTfButtons in app.js to use setVisibleLogicalRange")

# Ensure chart.timeScale().fitContent() is called right after setting candlestick data
if "chart.timeScale().fitContent();" not in js:
    js = js.replace("setupTfButtons(candleData);", "setupTfButtons(candleData);\n        chart.timeScale().fitContent();")
    print("Added chart.timeScale().fitContent() call in app.js")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(js)

# Update index.html asset version to 5.2.4
html_path = 'backend/static/index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

html = html.replace('app.js?v=5.2.3', 'app.js?v=5.2.4')

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

print("Finished applying fix_ichart_timeline_zoom.py!")
