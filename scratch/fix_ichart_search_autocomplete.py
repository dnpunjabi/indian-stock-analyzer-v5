import re

# 1. Update index.html input element
index_path = 'backend/static/index.html'
with open(index_path, 'r', encoding='utf-8') as f:
    html_code = f.read()

old_input_html = """<input type="text" id="ichart-standalone-search-input" 
                                   placeholder="Search any NSE/BSE Ticker (e.g. RELIANCE, TCS, TATAMOTORS, GRANULES)..." 
                                   style="width: 100%; box-sizing: border-box; padding: 9px 12px 9px 38px !important; font-size: 13px; font-weight: 600; background: rgba(0, 0, 0, 0.4); border: 1px solid var(--border-glass, rgba(255, 255, 255, 0.2)); border-radius: 8px; color: #ffffff !important; outline: none; transition: all 0.2s;"
                                   autocomplete="off" 
                                   onkeydown="if(event.key === 'Enter' && this.value.trim()){ window.openStandaloneInteractiveChart && window.openStandaloneInteractiveChart(this.value.trim(), [this.value.trim()], 'search', 'Search'); }" />"""

new_input_html = """<input type="text" id="ichart-standalone-search-input" 
                                   placeholder="Search any NSE/BSE Ticker (e.g. RELIANCE, TCS, TATAMOTORS, GRANULES)..." 
                                   style="width: 100%; box-sizing: border-box; padding: 9px 12px 9px 38px !important; font-size: 13px; font-weight: 600; border-radius: 8px; outline: none; transition: all 0.2s;"
                                   autocomplete="off" 
                                   oninput="window.handleIChartSearchInput && window.handleIChartSearchInput(this)"
                                   onkeydown="if(event.key === 'Enter' && this.value.trim()){ window.openStandaloneInteractiveChart && window.openStandaloneInteractiveChart(this.value.trim(), [this.value.trim()], 'search', 'Search'); }" />"""

if old_input_html in html_code:
    html_code = html_code.replace(old_input_html, new_input_html)
    print("Updated input element in index.html with oninput handler and removed hardcoded white color.")
else:
    print("WARNING: Could not find exact old_input_html string in index.html")

html_code = html_code.replace('app.js?v=5.1.5', 'app.js?v=5.1.6')
html_code = html_code.replace('styles.css?v=5.1.1', 'styles.css?v=5.1.6')

with open(index_path, 'w', encoding='utf-8') as f:
    f.write(html_code)

print("Updated index.html asset version to v=5.1.6.")


# 2. Append CSS rules to styles.css for Light/Dark mode styling
css_path = 'backend/static/styles.css'
with open(css_path, 'r', encoding='utf-8') as f:
    css_code = f.read()

search_css = """

/* Standalone i-Chart Search Bar & Autocomplete Light/Dark Mode Enhancements */
#ichart-standalone-search-input {
    background: rgba(15, 23, 42, 0.6) !important;
    border: 1px solid var(--border-glass, rgba(255, 255, 255, 0.2)) !important;
    color: #ffffff !important;
}

[data-mode="light"] #ichart-standalone-search-input,
[data-theme="light"] #ichart-standalone-search-input,
body.light-theme #ichart-standalone-search-input {
    background: #ffffff !important;
    border: 1px solid #cbd5e1 !important;
    color: #0f172a !important;
    font-weight: 700 !important;
}

[data-mode="light"] #ichart-standalone-search-input::placeholder,
[data-theme="light"] #ichart-standalone-search-input::placeholder,
body.light-theme #ichart-standalone-search-input::placeholder {
    color: #64748b !important;
}

#ichart-standalone-autocomplete {
    background: rgba(15, 23, 42, 0.95) !important;
    border: 1px solid #3b82f6 !important;
    color: #f8fafc !important;
}

[data-mode="light"] #ichart-standalone-autocomplete,
[data-theme="light"] #ichart-standalone-autocomplete,
body.light-theme #ichart-standalone-autocomplete {
    background: #ffffff !important;
    border: 1px solid #3b82f6 !important;
    color: #0f172a !important;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15) !important;
}
"""

if 'Standalone i-Chart Search Bar & Autocomplete Light/Dark Mode Enhancements' not in css_code:
    css_code += '\n' + search_css

with open(css_path, 'w', encoding='utf-8') as f:
    f.write(css_code)

print("Updated styles.css with search bar theme styles.")


# 3. Add handleIChartSearchInput to app.js
app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

handle_input_js = """
// Global Standalone i-Chart Autocomplete Search Handler
window.handleIChartSearchInput = function(inputEl) {
    if (!inputEl) return;
    const query = inputEl.value.trim().toLowerCase();
    const box = document.getElementById('ichart-standalone-autocomplete');
    if (!box) return;

    if (!query) {
        box.style.display = 'none';
        return;
    }

    const sourceArrays = [
        window.allVcpStocks, window.allWeinsteinStocks, window.allHtfStocks, window.all3wtStocks,
        window.allFlatBaseStocks, window.allEpisodicStocks, window.allPocketStocks, window.allOliverKellStocks,
        window.allCupHandleStocks, window.allRsnhStocks, window.allUndercutStocks, window.allConfluenceCandidates,
        window.activeWlQuantMatrixData, window.allUniverseStocks
    ];

    const matches = [];
    const seen = new Set();

    sourceArrays.forEach(arr => {
        if (Array.isArray(arr)) {
            arr.forEach(s => {
                const sym = typeof s === 'string' ? s : (s.symbol || s.ticker || s.stock || '');
                const name = typeof s === 'object' ? (s.company_name || s.name || s.company || '') : '';
                const clean = sym.replace('.NS','').replace('.BO','').trim().toUpperCase();
                if (clean && !seen.has(clean)) {
                    if (clean.toLowerCase().includes(query) || name.toLowerCase().includes(query)) {
                        seen.add(clean);
                        matches.push({ symbol: clean, name: name });
                    }
                }
            });
        }
    });

    const fallbackList = ['RELIANCE', 'TCS', 'HDFCBANK', 'TATAMOTORS', 'ICICIBANK', 'INFY', 'BHARTIARTL', 'SBIN', 'ITC', 'LTIM', 'BOSCHLTD', 'GRANULES', 'NETWEB', 'APLAPOLLO', 'SUZLON', 'TRENT', 'BSE'];
    fallbackList.forEach(clean => {
        if (!seen.has(clean) && clean.toLowerCase().includes(query)) {
            seen.add(clean);
            matches.push({ symbol: clean, name: 'NSE Stock' });
        }
    });

    if (matches.length === 0) {
        box.style.display = 'none';
        return;
    }

    const isLight = document.documentElement.getAttribute('data-mode') === 'light';
    box.innerHTML = matches.slice(0, 10).map(m => `
        <div class="autocomplete-item" 
             onclick="document.getElementById('ichart-standalone-search-input').value='${m.symbol}'; document.getElementById('ichart-standalone-autocomplete').style.display='none'; window.openStandaloneInteractiveChart && window.openStandaloneInteractiveChart('${m.symbol}', ['${m.symbol}'], 'search', 'Search');" 
             style="padding: 9px 14px; cursor: pointer; border-bottom: 1px solid ${isLight ? '#f1f5f9' : 'rgba(255,255,255,0.06)'}; display: flex; justify-content: space-between; align-items: center; font-size: 12.5px;">
            <strong style="color: ${isLight ? '#2563eb' : '#60a5fa'}; font-weight: 800;">${m.symbol}</strong>
            <span style="color: ${isLight ? '#64748b' : '#94a3b8'}; font-size: 11px;">${m.name || 'NSE Stock'}</span>
        </div>
    `).join('');
    box.style.display = 'block';
};
"""

if 'window.handleIChartSearchInput =' not in app_code:
    app_code += '\n' + handle_input_js
    print("Added handleIChartSearchInput to app.js.")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_code)

print("Updated app.js successfully.")
