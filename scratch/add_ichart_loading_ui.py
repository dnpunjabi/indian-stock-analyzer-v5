import re

# 1. Add CSS spinner keyframes to styles.css
css_path = 'backend/static/styles.css'
with open(css_path, 'r', encoding='utf-8') as f:
    css_code = f.read()

spinner_css = """

/* i-Chart Workstation Cyber Spinner & Loading Overlay */
@keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}

.ichart-spinner {
    width: 44px;
    height: 44px;
    border: 3.5px solid rgba(59, 130, 246, 0.2);
    border-top: 3.5px solid #3b82f6;
    border-right: 3.5px solid #10b981;
    border-radius: 50%;
    animation: spin 0.75s linear infinite;
    box-shadow: 0 0 16px rgba(59, 130, 246, 0.3);
}

[data-mode="light"] .ichart-loading-overlay,
[data-theme="light"] .ichart-loading-overlay,
body.light-theme .ichart-loading-overlay {
    background: #ffffff !important;
    border: 1px solid #cbd5e1 !important;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05) !important;
}
"""

if 'ichart-spinner' not in css_code:
    css_code += '\n' + spinner_css

with open(css_path, 'w', encoding='utf-8') as f:
    f.write(css_code)

print("Updated styles.css with ichart spinner styles.")


# 2. Add loading overlay & pending HUD to app.js
app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

# Add loading overlay at beginning of renderTVWorkstationChart
old_render_start = "const container = document.getElementById('tv-chart-container');\n    if (!container) return;"

new_render_start = """const container = document.getElementById('tv-chart-container');
    if (!container) return;

    // Show Loading Overlay
    const cleanDisplayTicker = formattedTicker.replace('.NS', '').replace('.BO', '');
    const isLightMode = document.documentElement.getAttribute('data-mode') === 'light';
    container.innerHTML = `
        <div class="ichart-loading-overlay" style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 420px; width: 100%; background: ${isLightMode ? '#ffffff' : 'rgba(15, 23, 42, 0.75)'}; border-radius: 12px; border: 1px solid ${isLightMode ? '#cbd5e1' : 'rgba(255,255,255,0.08)'}; gap: 14px; backdrop-filter: blur(8px);">
            <div class="ichart-spinner"></div>
            <div style="text-align: center;">
                <div style="font-size: 14px; font-weight: 800; color: ${isLightMode ? '#0f172a' : '#f8fafc'}; letter-spacing: 0.02em;">⚡ Loading i-Chart Workstation for <span style="color: #3b82f6;">${cleanDisplayTicker}</span>...</div>
                <div style="font-size: 11.5px; color: ${isLightMode ? '#64748b' : '#94a3b8'}; margin-top: 4px;">Computing 30W MA Slope, EMAs & Technical Indicators</div>
            </div>
        </div>
    `;"""

if 'const cleanDisplayTicker = formattedTicker' not in app_code:
    app_code = app_code.replace(old_render_start, new_render_start, 1)

# Add pending HUD updates inside openStandaloneInteractiveChart
old_hud_pending = "// Fetch and update HUD readout badge metrics"
new_hud_pending = """// Set Pending Loading HUD metrics
    const symEl = document.getElementById('ichart-hud-symbol');
    const priceEl = document.getElementById('ichart-hud-price-badge');
    const maValEl = document.getElementById('ichart-hud-ma-val');
    const slopeValEl = document.getElementById('ichart-hud-slope-val');

    if (symEl) symEl.innerText = cleanSym;
    if (priceEl) priceEl.innerText = 'Price: Loading...';
    if (maValEl) maValEl.innerText = '30W MA (150 SMA): Computing...';
    if (slopeValEl) {
        slopeValEl.innerText = 'Slope: Calculating...';
        slopeValEl.style.color = '#94a3b8';
    }

    // Fetch and update HUD readout badge metrics"""

if '// Set Pending Loading HUD metrics' not in app_code:
    app_code = app_code.replace(old_hud_pending, new_hud_pending, 1)

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_code)

print("Updated app.js with chart loading overlay and pending HUD states.")


# 3. Bump index.html version tag to v=5.1.9
index_path = 'backend/static/index.html'
with open(index_path, 'r', encoding='utf-8') as f:
    html_code = f.read()

html_code = html_code.replace('app.js?v=5.1.8', 'app.js?v=5.1.9')
html_code = html_code.replace('styles.css?v=5.1.7', 'styles.css?v=5.1.9')

with open(index_path, 'w', encoding='utf-8') as f:
    f.write(html_code)

print("Updated index.html asset version to v=5.1.9.")
