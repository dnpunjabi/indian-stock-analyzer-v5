import re

app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

# Replace list extraction logic inside openStandaloneInteractiveChart
old_list_extraction = """    let list = [];
    if (Array.isArray(contextList) && contextList.length > 0) {
        list = contextList.map(item => (typeof item === 'string' ? item : (item.symbol || item.ticker))).filter(Boolean);
    }
    if (list.length === 0) list = [cleanSym];
    
    let cIdx = list.indexOf(cleanSym);
    if (cIdx < 0) cIdx = 0;"""

new_list_extraction = """    let list = [];
    if (Array.isArray(contextList) && contextList.length > 0) {
        list = contextList.map(item => {
            const raw = (typeof item === 'string' ? item : (item.symbol || item.ticker || item.stock || item.name));
            return raw ? raw.replace('.NS', '').replace('.BO', '').trim().toUpperCase() : null;
        }).filter(Boolean);
    }
    if (list.length === 0) list = [cleanSym];

    let cIdx = list.indexOf(cleanSym);
    if (cIdx < 0) {
        // Fallback partial matching if exact string index was not found
        cIdx = list.findIndex(sym => sym === cleanSym || cleanSym.includes(sym) || sym.includes(cleanSym));
        if (cIdx < 0) cIdx = 0;
    }"""

if old_list_extraction in app_code:
    app_code = app_code.replace(old_list_extraction, new_list_extraction)
    print("Replaced list extraction in openStandaloneInteractiveChart successfully.")
else:
    print("WARNING: Could not find exact old_list_extraction string in app.js")

# Add global keyboard arrow listener for i-Chart stock stepping
keyboard_listener = """
// Global Keyboard Shortcut for i-Chart Stock Stepper (ArrowLeft / ArrowRight)
document.addEventListener('keydown', function(e) {
    const ichartTab = document.getElementById('tab-interactive-chart');
    if (!ichartTab || ichartTab.style.display === 'none') return;
    
    // Ignore when typing inside input fields, textareas, or select dropdowns
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
    
    if (e.key === 'ArrowLeft') {
        e.preventDefault();
        if (typeof window.navigateIChartStock === 'function') window.navigateIChartStock(-1);
    } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        if (typeof window.navigateIChartStock === 'function') window.navigateIChartStock(1);
    }
});
"""

if 'Global Keyboard Shortcut for i-Chart Stock Stepper' not in app_code:
    app_code += '\n' + keyboard_listener
    print("Added global keyboard ArrowLeft/ArrowRight listener for i-Chart stepper.")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_code)

print("Updated app.js with fixed stepper indexing.")

# Bump index.html version tag to v=5.0.7
index_path = 'backend/static/index.html'
with open(index_path, 'r', encoding='utf-8') as f:
    html_code = f.read()

html_code = html_code.replace('app.js?v=5.0.6', 'app.js?v=5.0.7')
with open(index_path, 'w', encoding='utf-8') as f:
    f.write(html_code)

print("Updated index.html asset version to app.js?v=5.0.7.")
