import re

app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

# Replace handleIChartSearchInput implementation with full Stage Masterclass autosearch logic
old_handle_fn_pattern = r"// Global Standalone i-Chart Autocomplete Search Handler[\s\S]*?};"

new_handle_fn = """// Global Standalone i-Chart Autocomplete Search Handler (Matching Stage Masterclass Engine)
window.handleIChartSearchInput = function(inputEl) {
    if (!inputEl) return;
    const query = inputEl.value.trim().toUpperCase();
    const box = document.getElementById('ichart-standalone-autocomplete');
    if (!box) return;

    clearTimeout(window._ichartSearchDebounce);

    if (!query || query.length < 1) {
        box.style.display = 'none';
        return;
    }

    window._ichartSearchDebounce = setTimeout(async () => {
        try {
            const res = await fetch(`/api/search/suggestions?q=${encodeURIComponent(query)}`);
            const suggestions = await res.json();

            if (!Array.isArray(suggestions) || suggestions.length === 0) {
                box.style.display = 'none';
                return;
            }

            box.innerHTML = suggestions.slice(0, 8).map(s => {
                const sym = typeof s === 'string' ? s : (s.symbol || s.ticker || '');
                const baseSym = typeof s === 'object' ? (s.base_symbol || sym) : sym;
                const cleanSym = baseSym.replace('.NS','').replace('.BO','').trim().toUpperCase();
                const name = typeof s === 'object' ? (s.name || s.company_name || '') : '';
                
                return `
                    <div class="watchlist-autocomplete-item" 
                         onclick="document.getElementById('ichart-standalone-search-input').value='${cleanSym}'; document.getElementById('ichart-standalone-autocomplete').style.display='none'; window.openStandaloneInteractiveChart && window.openStandaloneInteractiveChart('${cleanSym}', ['${cleanSym}'], 'search', 'Search');" 
                         style="padding: 10px 14px; cursor: pointer; border-bottom: 1px solid var(--border-glass, rgba(255,255,255,0.05)); display: flex; justify-content: space-between; align-items: center; transition: background 0.15s;">
                        <div>
                            <strong style="font-size: 13px; font-weight: 800;">${baseSym}</strong>
                            <span style="font-size: 11px; margin-left: 6px;" class="ticker-pill">${sym}</span>
                        </div>
                        <span style="font-size: 11.5px; font-weight: 600;" class="sector-pill">${name}</span>
                    </div>
                `;
            }).join('');
            box.style.display = 'block';
        } catch (err) {
            console.error("i-Chart search autocomplete error:", err);
        }
    }, 120);
};"""

app_code = re.sub(old_handle_fn_pattern, new_handle_fn, app_code)

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_code)

print("Updated app.js with Stage Masterclass API autosearch logic.")


# 2. Update index.html input listeners
index_path = 'backend/static/index.html'
with open(index_path, 'r', encoding='utf-8') as f:
    html_code = f.read()

html_code = html_code.replace('app.js?v=5.1.6', 'app.js?v=5.1.7')
html_code = html_code.replace('styles.css?v=5.1.6', 'styles.css?v=5.1.7')

with open(index_path, 'w', encoding='utf-8') as f:
    f.write(html_code)

print("Updated index.html asset version to v=5.1.7.")
