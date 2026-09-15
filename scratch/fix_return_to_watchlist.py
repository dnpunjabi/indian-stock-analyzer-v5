app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

old_return_fn = """window.returnToPreviousScreenerTab = function() {
    const state = window.activeIChartState;
    if (state.screenerTabKey) {
        if (typeof window.switchTab === 'function') {
            window.switchTab('vcp');
        }
        if (typeof window.switchQuantScannerSubtab === 'function') {
            window.switchQuantScannerSubtab(state.screenerTabKey);
        }
    }
};"""

new_return_fn = """window.returnToPreviousScreenerTab = function() {
    const state = window.activeIChartState;
    if (!state || !state.screenerTabKey) return;
    
    const key = state.screenerTabKey;
    if (key === 'watchlist') {
        if (typeof window.switchTab === 'function') {
            window.switchTab('watchlist');
        }
    } else {
        if (typeof window.switchTab === 'function') {
            window.switchTab('vcp');
        }
        if (typeof window.switchQuantScannerSubtab === 'function') {
            window.switchQuantScannerSubtab(key);
        }
    }
};"""

if old_return_fn in app_code:
    app_code = app_code.replace(old_return_fn, new_return_fn)
    print("Replaced returnToPreviousScreenerTab successfully.")
else:
    print("WARNING: Could not find exact old_return_fn string in app.js")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_code)

# Bump index.html to app.js?v=5.1.2
index_path = 'backend/static/index.html'
with open(index_path, 'r', encoding='utf-8') as f:
    html_code = f.read()

html_code = html_code.replace('app.js?v=5.1.1', 'app.js?v=5.1.2')
with open(index_path, 'w', encoding='utf-8') as f:
    f.write(html_code)

print("Updated index.html asset version to app.js?v=5.1.2.")
