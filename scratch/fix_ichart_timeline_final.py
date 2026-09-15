import re

# 1. Update backend/static/app.js
app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    js = f.read()

# Replace timeScale options in createChart with clean config (matching working volume chart)
old_timescale = """            timeScale: {
                visible: true,
                timeVisible: false,
                secondsVisible: false,
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)',
                borderVisible: true,
            },"""

new_timescale = """            timeScale: {
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)',
                visible: true,
                borderVisible: true,
            },"""

if old_timescale in js:
    js = js.replace(old_timescale, new_timescale)
    print("Cleaned up timeScale options in app.js")

# Update setupTfButtons to use addEventListener and exact candle date range setting
old_setup_tf = """        // Timeline timeframe quick range selection handler
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

new_setup_tf = """        // Timeline timeframe quick range selection handler
        const setupTfButtons = (candleDataArr) => {
            const containerEl = document.getElementById('tv-chart-timeframe-bar');
            if (!containerEl || !candleDataArr || !candleDataArr.length) return;
            const btns = containerEl.querySelectorAll('.tv-tf-btn');
            if (!btns.length) return;

            const totalBars = candleDataArr.length;
            const lastCandle = candleDataArr[totalBars - 1];

            btns.forEach(btn => {
                // Remove old listeners by replacing onclick / adding event listener
                btn.onclick = null;
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();

                    btns.forEach(b => {
                        b.classList.remove('active');
                        b.style.background = 'transparent';
                        b.style.color = 'var(--text-secondary)';
                        b.style.borderColor = 'var(--border-glass)';
                    });
                    btn.classList.add('active');
                    btn.style.background = '#3b82f6';
                    btn.style.color = '#ffffff';
                    btn.style.borderColor = '#3b82f6';

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
                            numBars = Math.min(180, totalBars);
                        }
                    }

                    const fromIdx = Math.max(0, totalBars - numBars);
                    const fromCandle = candleDataArr[fromIdx];

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
                });
            });
        };"""

if old_setup_tf in js:
    js = js.replace(old_setup_tf, new_setup_tf)
    print("Updated setupTfButtons in app.js with bulletproof click listeners and date string range zoom")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(js)

# Update index.html version to 5.2.5
html_path = 'backend/static/index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

html = html.replace('app.js?v=5.2.4', 'app.js?v=5.2.5')

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

print("Finished applying fix_ichart_timeline_final.py!")
