import re

# 1. Update index.html
index_path = 'backend/static/index.html'
with open(index_path, 'r', encoding='utf-8') as f:
    html_code = f.read()

search_bar_html = """
                    <!-- Standalone Direct Ticker Search Bar & Quick Ticker Pills -->
                    <div id="ichart-search-bar-container" style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.08); width: 100%;">
                        <div style="position: relative; flex: 1; min-width: 260px;">
                            <span style="position: absolute; left: 12px; top: 50%; transform: translateY(-50%); font-size: 14px; color: #94a3b8; pointer-events: none;">🔍</span>
                            <input type="text" id="ichart-standalone-search-input" 
                                   placeholder="Search any NSE/BSE Ticker (e.g. RELIANCE, TCS, TATAMOTORS, GRANULES)..." 
                                   style="width: 100%; box-sizing: border-box; padding: 9px 12px 9px 38px !important; font-size: 13px; font-weight: 600; background: rgba(0, 0, 0, 0.4); border: 1px solid var(--border-glass, rgba(255, 255, 255, 0.2)); border-radius: 8px; color: #ffffff !important; outline: none; transition: all 0.2s;"
                                   autocomplete="off" 
                                   onkeydown="if(event.key === 'Enter' && this.value.trim()){ window.openStandaloneInteractiveChart && window.openStandaloneInteractiveChart(this.value.trim(), [this.value.trim()], 'search', 'Search'); }" />
                            <div id="ichart-standalone-autocomplete" class="watchlist-autocomplete-box" style="display:none; position:absolute; top:calc(100% + 6px); left:0; right:0; z-index:9999; max-height:260px; overflow-y:auto; background: rgba(15, 23, 42, 0.95); border: 1px solid #3b82f6; border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);"></div>
                        </div>
                        <button id="ichart-standalone-search-btn" 
                                onclick="const val = document.getElementById('ichart-standalone-search-input').value.trim(); if(val && window.openStandaloneInteractiveChart){ window.openStandaloneInteractiveChart(val, [val], 'search', 'Search'); }"
                                style="background: linear-gradient(135deg, #3b82f6, #2563eb); color: white; border: none; border-radius: 8px; padding: 9px 18px; font-size: 12.5px; font-weight: 800; cursor: pointer; display: flex; align-items: center; gap: 6px; box-shadow: 0 4px 14px rgba(37, 99, 235, 0.3); white-space: nowrap;">
                            ⚡ Load Chart
                        </button>
                        <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                            <span style="font-size: 11px; font-weight: 700; color: var(--text-muted, #94a3b8); text-transform: uppercase;">Quick Tickers:</span>
                            <button class="ichart-quick-pill" onclick="window.openStandaloneInteractiveChart && window.openStandaloneInteractiveChart('RELIANCE', ['RELIANCE'], 'search', 'Search')" style="padding: 4px 9px; font-size: 11.5px; font-weight: 700; border-radius: 6px; background: rgba(255,255,255,0.06); border: 1px solid var(--border-glass, rgba(255,255,255,0.15)); color: var(--text-primary); cursor: pointer;">RELIANCE</button>
                            <button class="ichart-quick-pill" onclick="window.openStandaloneInteractiveChart && window.openStandaloneInteractiveChart('TCS', ['TCS'], 'search', 'Search')" style="padding: 4px 9px; font-size: 11.5px; font-weight: 700; border-radius: 6px; background: rgba(255,255,255,0.06); border: 1px solid var(--border-glass, rgba(255,255,255,0.15)); color: var(--text-primary); cursor: pointer;">TCS</button>
                            <button class="ichart-quick-pill" onclick="window.openStandaloneInteractiveChart && window.openStandaloneInteractiveChart('TATAMOTORS', ['TATAMOTORS'], 'search', 'Search')" style="padding: 4px 9px; font-size: 11.5px; font-weight: 700; border-radius: 6px; background: rgba(255,255,255,0.06); border: 1px solid var(--border-glass, rgba(255,255,255,0.15)); color: var(--text-primary); cursor: pointer;">TATAMOTORS</button>
                            <button class="ichart-quick-pill" onclick="window.openStandaloneInteractiveChart && window.openStandaloneInteractiveChart('HDFCBANK', ['HDFCBANK'], 'search', 'Search')" style="padding: 4px 9px; font-size: 11.5px; font-weight: 700; border-radius: 6px; background: rgba(255,255,255,0.06); border: 1px solid var(--border-glass, rgba(255,255,255,0.15)); color: var(--text-primary); cursor: pointer;">HDFCBANK</button>
                            <button class="ichart-quick-pill" onclick="window.openStandaloneInteractiveChart && window.openStandaloneInteractiveChart('GRANULES', ['GRANULES'], 'search', 'Search')" style="padding: 4px 9px; font-size: 11.5px; font-weight: 700; border-radius: 6px; background: rgba(255,255,255,0.06); border: 1px solid var(--border-glass, rgba(255,255,255,0.15)); color: var(--text-primary); cursor: pointer;">GRANULES</button>
                            <button class="ichart-quick-pill" onclick="window.openStandaloneInteractiveChart && window.openStandaloneInteractiveChart('NETWEB', ['NETWEB'], 'search', 'Search')" style="padding: 4px 9px; font-size: 11.5px; font-weight: 700; border-radius: 6px; background: rgba(255,255,255,0.06); border: 1px solid var(--border-glass, rgba(255,255,255,0.15)); color: var(--text-primary); cursor: pointer;">NETWEB</button>
                        </div>
                    </div>"""

target_div = '<div class="ichart-header-toolbar no-print"'
if 'ichart-standalone-search-input' not in html_code:
    pos = html_code.find('</div>\n                </div>\n\n                <!-- 30-Week MA Slope HUD Readout Badge -->')
    if pos != -1:
        html_code = html_code[:pos] + search_bar_html + '\n' + html_code[pos:]
        print("Inserted Standalone Search Bar HTML into index.html.")

html_code = html_code.replace('app.js?v=5.1.3', 'app.js?v=5.1.5')
with open(index_path, 'w', encoding='utf-8') as f:
    f.write(html_code)

print("Updated index.html asset version to app.js?v=5.1.5.")


# 2. Add Autocomplete JS listener to app.js
app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

autocomplete_js = """
// Setup Standalone i-Chart Autocomplete Search
document.addEventListener('DOMContentLoaded', function() {
    const input = document.getElementById('ichart-standalone-search-input');
    const box = document.getElementById('ichart-standalone-autocomplete');
    if (!input || !box) return;

    input.addEventListener('input', function() {
        const query = input.value.trim().toLowerCase();
        if (!query) {
            box.style.display = 'none';
            return;
        }

        const candidates = (window.allUniverseStocks || []).concat(window.allVcpStocks || []).concat(window.allWeinsteinStocks || []);
        const matches = [];
        const seen = new Set();

        candidates.forEach(s => {
            const sym = typeof s === 'string' ? s : (s.symbol || s.ticker || '');
            const name = typeof s === 'object' ? (s.company_name || s.name || '') : '';
            const clean = sym.replace('.NS','').replace('.BO','').trim();
            if (clean && !seen.has(clean)) {
                if (clean.toLowerCase().includes(query) || name.toLowerCase().includes(query)) {
                    seen.add(clean);
                    matches.push({ symbol: clean, name: name });
                }
            }
        });

        if (matches.length === 0) {
            box.style.display = 'none';
            return;
        }

        box.innerHTML = matches.slice(0, 10).map(m => `
            <div class="autocomplete-item" onclick="document.getElementById('ichart-standalone-search-input').value='${m.symbol}'; document.getElementById('ichart-standalone-autocomplete').style.display='none'; window.openStandaloneInteractiveChart && window.openStandaloneInteractiveChart('${m.symbol}', ['${m.symbol}'], 'search', 'Search');" style="padding: 8px 12px; cursor: pointer; border-bottom: 1px solid rgba(255,255,255,0.05); display: flex; justify-content: space-between; font-size: 12.5px;">
                <strong style="color: #60a5fa;">${m.symbol}</strong>
                <span style="color: #94a3b8; font-size: 11px;">${m.name || 'NSE Stock'}</span>
            </div>
        `).join('');
        box.style.display = 'block';
    });

    document.addEventListener('click', function(e) {
        if (!input.contains(e.target) && !box.contains(e.target)) {
            box.style.display = 'none';
        }
    });
});
"""

if 'Setup Standalone i-Chart Autocomplete Search' not in app_code:
    app_code += '\n' + autocomplete_js
    print("Added Standalone i-Chart Autocomplete JS logic to app.js.")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_code)

print("Updated app.js successfully.")
