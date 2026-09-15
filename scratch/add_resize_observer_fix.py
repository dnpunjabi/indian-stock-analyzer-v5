import re

# Update app.js: Add ResizeObserver and clean timeScale config for TV Workstation Chart
app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    js = f.read()

# Add ResizeObserver right after activeTVWorkstationChart = chart;
old_chart_assign = """        activeTVWorkstationChart = chart;"""

new_chart_assign = """        activeTVWorkstationChart = chart;

        // Auto-ResizeObserver for container layout changes
        if (window.tvChartResizeObserver) {
            try { window.tvChartResizeObserver.disconnect(); } catch (e) {}
        }
        window.tvChartResizeObserver = new ResizeObserver(entries => {
            for (let entry of entries) {
                const w = entry.contentRect.width;
                const h = entry.contentRect.height;
                if (activeTVWorkstationChart && w > 50 && h > 50) {
                    activeTVWorkstationChart.resize(w, h);
                    try { activeTVWorkstationChart.timeScale().fitContent(); } catch (err) {}
                }
            }
        });
        window.tvChartResizeObserver.observe(container);"""

if old_chart_assign in js and "window.tvChartResizeObserver =" not in js:
    js = js.replace(old_chart_assign, new_chart_assign, 1)
    print("Added ResizeObserver on #tv-chart-container in app.js")

# Update timeScale options in createChart
old_timescale = """            timeScale: {
                visible: true,
                borderVisible: true,
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)',
            },"""

new_timescale = """            timeScale: {
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)',
                visible: true,
                borderVisible: true,
                timeVisible: false,
                secondsVisible: false,
                rightOffset: 5,
            },"""

if old_timescale in js:
    js = js.replace(old_timescale, new_timescale)
    print("Updated timeScale options in createChart in app.js")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(js)

# Update index.html version to 5.4.1
html_path = 'backend/static/index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

html = html.replace('app.js?v=5.4.0', 'app.js?v=5.4.1')

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

print("Finished applying add_resize_observer_fix.py!")
