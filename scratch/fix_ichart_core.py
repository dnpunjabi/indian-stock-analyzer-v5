import re

# 1. Update app.js
app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add getActiveChartSymbol definition near activeIChartState initialization
helper_code = """
window.getActiveChartSymbol = function() {
    if (typeof activeStockProfile !== 'undefined' && activeStockProfile && activeStockProfile.ticker) {
        return activeStockProfile.ticker;
    }
    if (window.activeIChartState && window.activeIChartState.currentSymbol) {
        return window.activeIChartState.currentSymbol;
    }
    if (window.currentIChartSymbol) {
        return window.currentIChartSymbol;
    }
    return null;
};
"""

if 'window.getActiveChartSymbol =' not in content:
    content = helper_code + '\n' + content

# Make sure openStandaloneIChartTab sets window.currentIChartSymbol
content = content.replace(
    'window.activeIChartState.currentSymbol = cleanSym;',
    'window.currentIChartSymbol = cleanSym;\n    window.activeIChartState.currentSymbol = cleanSym;'
)

# Replace activeSym resolution logic in checkbox listeners with window.getActiveChartSymbol()
old_active_sym_pattern = r"const activeSym = \(typeof activeStockProfile !== 'undefined' && activeStockProfile && activeStockProfile\.ticker\) \? activeStockProfile\.ticker : window\.currentIChartSymbol;"
new_active_sym_code = "const activeSym = window.getActiveChartSymbol();"

content = re.sub(old_active_sym_pattern, new_active_sym_code, content)

# Replace activeTicker in toggleIChartTimeframe
old_active_ticker_pattern = r"const activeTicker = \(typeof activeStockProfile !== 'undefined' && activeStockProfile && activeStockProfile\.ticker\) \? activeStockProfile\.ticker : window\.currentIChartSymbol;"
new_active_ticker_code = "const activeTicker = window.getActiveChartSymbol();"

content = re.sub(old_active_ticker_pattern, new_active_ticker_code, content)

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated app.js successfully.")

# 2. Update index.html to bump version tag
index_path = 'backend/static/index.html'
with open(index_path, 'r', encoding='utf-8') as f:
    html_content = f.read()

html_content = html_content.replace('app.js?v=5.0.4', 'app.js?v=5.0.5')
html_content = html_content.replace('styles.css?v=5.0.3', 'styles.css?v=5.0.5')

with open(index_path, 'w', encoding='utf-8') as f:
    f.write(html_content)

print("Updated index.html asset version tags to v=5.0.5.")
