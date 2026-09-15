app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

old_back_btn_logic = """    if (backBtn && backLabel) {
        if (window.activeIChartState.screenerLabel) {
            backLabel.innerText = `Back to ${window.activeIChartState.screenerLabel}`;
            backBtn.style.display = 'inline-flex';
        } else {
            backBtn.style.display = 'none';
        }
    }"""

new_back_btn_logic = """    if (backBtn && backLabel) {
        const isSearchMode = !window.activeIChartState.screenerTabKey || 
                             window.activeIChartState.screenerTabKey === 'search' || 
                             window.activeIChartState.screenerLabel === 'Search';
        if (!isSearchMode && window.activeIChartState.screenerLabel) {
            backLabel.innerText = `Back to ${window.activeIChartState.screenerLabel}`;
            backBtn.style.display = 'inline-flex';
        } else {
            backBtn.style.display = 'none';
        }
    }"""

if old_back_btn_logic in app_code:
    app_code = app_code.replace(old_back_btn_logic, new_back_btn_logic)
    print("Replaced back button logic to hide when screenerTabKey is 'search'.")
else:
    print("WARNING: Could not find old_back_btn_logic in app.js")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_code)

print("Updated app.js successfully.")

# Bump index.html to app.js?v=5.1.8
index_path = 'backend/static/index.html'
with open(index_path, 'r', encoding='utf-8') as f:
    html_code = f.read()

html_code = html_code.replace('app.js?v=5.1.7', 'app.js?v=5.1.8')
with open(index_path, 'w', encoding='utf-8') as f:
    f.write(html_code)

print("Updated index.html asset version to app.js?v=5.1.8.")
