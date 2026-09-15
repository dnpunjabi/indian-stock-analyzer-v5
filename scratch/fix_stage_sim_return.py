app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

# Replace 'vcp' with 'guide' in the Stage 1-4 Simulator verdict banner button
old_button_call = "', ['${(data.symbol||'').replace('.NS','').replace('.BO','')}'], 'vcp', 'Stage 1-4 Simulator');"
new_button_call = "', ['${(data.symbol||'').replace('.NS','').replace('.BO','')}'], 'guide', 'Stage 1-4 Simulator');"

if old_button_call in app_code:
    app_code = app_code.replace(old_button_call, new_button_call)
    print("Replaced screenerTabKey 'vcp' with 'guide' for Stage 1-4 Simulator.")
else:
    print("WARNING: Could not find exact old_button_call string in app.js")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_code)

# Bump index.html to app.js?v=5.1.3
index_path = 'backend/static/index.html'
with open(index_path, 'r', encoding='utf-8') as f:
    html_code = f.read()

html_code = html_code.replace('app.js?v=5.1.2', 'app.js?v=5.1.3')
with open(index_path, 'w', encoding='utf-8') as f:
    f.write(html_code)

print("Updated index.html asset version to app.js?v=5.1.3.")
