app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

# 1. Update openStandaloneInteractiveChart fallback mapping for '3wt'
app_code = app_code.replace(
    "else if (screenerTabKey === '3wt') contextList = window.allThreeWtStocks;",
    "else if (screenerTabKey === '3wt') contextList = window.all3wtStocks || window.allThreeWtStocks;"
)

# 2. Update 3WT table row button to pass window.all3wtStocks
old_3wt_button = "window.openStandaloneInteractiveChart('${s.symbol}', null, '3wt', '3-Weeks Tight')"
new_3wt_button = "window.openStandaloneInteractiveChart('${s.symbol}', window.all3wtStocks, '3wt', '3-Weeks Tight')"

if old_3wt_button in app_code:
    app_code = app_code.replace(old_3wt_button, new_3wt_button)
    print("Replaced 3WT table row button contextList argument successfully.")
else:
    print("WARNING: Could not find exact old_3wt_button string in app.js")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_code)

print("Updated app.js successfully with 3WT stepper fix.")

# 3. Bump index.html to app.js?v=5.1.4
index_path = 'backend/static/index.html'
with open(index_path, 'r', encoding='utf-8') as f:
    html_code = f.read()

html_code = html_code.replace('app.js?v=5.1.3', 'app.js?v=5.1.4')
with open(index_path, 'w', encoding='utf-8') as f:
    f.write(html_code)

print("Updated index.html asset version to app.js?v=5.1.4.")
