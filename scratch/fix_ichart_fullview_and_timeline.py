import re

# 1. Update backend/static/styles.css
styles_path = 'backend/static/styles.css'
with open(styles_path, 'r', encoding='utf-8') as f:
    css = f.read()

# Fix height: 440px !important on #tv-chart-container so fullscreen rule can take precedence
old_css_block = """#tv-chart-container {
    width: 100% !important;
    min-width: 100% !important;
    max-width: 100% !important;
    height: 440px !important;
    min-height: 440px !important;
    margin: 6px 0 !important;
    border-left: none !important;
    border-right: none !important;
    border-radius: 0 !important;
    padding: 0 !important;
    box-sizing: border-box !important;
}"""

new_css_block = """#tv-chart-container {
    width: 100% !important;
    min-width: 100% !important;
    max-width: 100% !important;
    height: 460px;
    min-height: 460px;
    margin: 6px 0 !important;
    border-left: none !important;
    border-right: none !important;
    border-radius: 0 !important;
    padding: 0 !important;
    box-sizing: border-box !important;
}

#tv-chart-card.fullscreen-card-active #tv-chart-container {
    height: calc(100vh - 220px) !important;
    min-height: 500px !important;
}"""

if old_css_block in css:
    css = css.replace(old_css_block, new_css_block)
    print("Updated #tv-chart-container CSS height rules in styles.css")

# Also fix the initial #tv-chart-container height rule around line 29854
old_css_initial = """#tv-chart-container {
    height: 420px !important;
    min-height: 420px !important;
    display: block !important;
    position: relative !important;
    overflow: hidden !important;
}"""

new_css_initial = """#tv-chart-container {
    height: 460px;
    min-height: 460px;
    display: block !important;
    position: relative !important;
    overflow: visible;
}"""

if old_css_initial in css:
    css = css.replace(old_css_initial, new_css_initial)
    print("Updated initial #tv-chart-container CSS height rules in styles.css")

with open(styles_path, 'w', encoding='utf-8') as f:
    f.write(css)

# 2. Update backend/static/index.html to add Full View button and update container style
html_path = 'backend/static/index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

# Update header title to include Full View button
old_header_title = """                                <h3 style="margin: 0; display: flex; align-items: center; gap: 8px;">
                                    <span>📈</span> INTERACTIVE WORKSTATION CHART
                                </h3>"""

new_header_title = """                                <div style="display: flex; align-items: center; gap: 12px;">
                                    <h3 style="margin: 0; display: flex; align-items: center; gap: 8px;">
                                        <span>📈</span> INTERACTIVE WORKSTATION CHART
                                    </h3>
                                    <button type="button" id="tv-chart-fullscreen-btn" title="Toggle Fullscreen Expanded View (Press ESC to exit)" style="display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; background: var(--bg-card-sub); border: 1px solid var(--border-glass); color: var(--text-secondary); cursor: pointer; transition: all 0.2s ease;">
                                        <span>⛶</span> Full View
                                    </button>
                                </div>"""

if old_header_title in html:
    html = html.replace(old_header_title, new_header_title)
    print("Added Full View button to header in index.html")

# Update #tv-chart-container height in index.html
html = html.replace('height: 420px; border-radius: 6px; overflow: hidden;', 'height: 460px; border-radius: 6px; overflow: visible;')

# Update asset version to 5.2.3
html = html.replace('app.js?v=5.2.2', 'app.js?v=5.2.3')

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

# 3. Update backend/static/app.js: Update createChart height to 460 and handle Full View button & dblclick
app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    js = f.read()

# Replace height: 420 with height: 460 in LightweightCharts.createChart
js = js.replace('height: 420,', 'height: 460,')
print("Updated createChart height to 460 in app.js")

# Bind Full View button click in setupFullscreenToggle block
old_fullscreen_setup = """        // 1. TradingView Workstation Chart
        setupFullscreenToggle('tv-chart-card', '#tv-chart-container', 420, (width, height) => {
            try {
                if (activeTVWorkstationChart && width > 50 && height > 50) {
                    activeTVWorkstationChart.resize(width, height);
                }
            } catch (e) {}
        });"""

new_fullscreen_setup = """        // 1. TradingView Workstation Chart Full View Toggle Handler
        setupFullscreenToggle('tv-chart-card', '#tv-chart-container', 460, (width, height) => {
            try {
                if (activeTVWorkstationChart && width > 50 && height > 50) {
                    activeTVWorkstationChart.resize(width, height);
                }
            } catch (e) {}
        });

        const tvFsBtn = document.getElementById('tv-chart-fullscreen-btn');
        if (tvFsBtn) {
            tvFsBtn.onclick = (e) => {
                e.stopPropagation();
                const card = document.getElementById('tv-chart-card');
                const tvContainer = document.getElementById('tv-chart-container');
                if (!card || !tvContainer) return;
                const isFullscreen = card.classList.contains('fullscreen-card-active');
                if (isFullscreen) {
                    card.classList.remove('fullscreen-card-active');
                    tvFsBtn.innerHTML = '<span>⛶</span> Full View';
                    setTimeout(() => {
                        const targetWidth = tvContainer.clientWidth || 600;
                        if (activeTVWorkstationChart) activeTVWorkstationChart.resize(targetWidth, 460);
                    }, 60);
                } else {
                    card.classList.add('fullscreen-card-active');
                    tvFsBtn.innerHTML = '<span>✕</span> Exit Full View';
                    setTimeout(() => {
                        const targetHeight = Math.max(tvContainer.clientHeight || 500, window.innerHeight - 240);
                        const targetWidth = tvContainer.clientWidth || (window.innerWidth - 40);
                        if (activeTVWorkstationChart) activeTVWorkstationChart.resize(targetWidth, targetHeight);
                    }, 60);
                }
            };
        }"""

if old_fullscreen_setup in js:
    js = js.replace(old_fullscreen_setup, new_fullscreen_setup)
    print("Updated fullscreen setup and bound tv-chart-fullscreen-btn in app.js")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(js)

print("Finished applying fix_ichart_fullview_and_timeline.py!")
