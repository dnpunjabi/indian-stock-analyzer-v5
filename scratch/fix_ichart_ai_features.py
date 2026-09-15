import re

app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

# 1. Update triggerTVIndicatorSynthesis
old_synthesis_start = """    if (!activeStockProfile || !activeStockProfile.ticker) {
        content.innerHTML = `<span style="color: var(--text-muted);">Please load a stock ticker profile first.</span>`;
        return;
    }

    const ticker = activeStockProfile.ticker;"""

new_synthesis_start = """    const ticker = window.getActiveChartSymbol();
    if (!ticker) {
        content.innerHTML = `<span style="color: var(--text-muted);">Please load or search a stock ticker first.</span>`;
        return;
    }"""

if old_synthesis_start in app_code:
    app_code = app_code.replace(old_synthesis_start, new_synthesis_start)
    print("Updated triggerTVIndicatorSynthesis in app.js.")
else:
    print("WARNING: Could not find old_synthesis_start in app.js")


# 2. Update sendTvChartMessage
old_chat_symbol = "symbol: activeStockProfile ? activeStockProfile.ticker : 'STOCK',"

new_chat_symbol = """symbol: (function(){
                const s = window.getActiveChartSymbol() || 'RELIANCE';
                return (s.endsWith('.NS') || s.endsWith('.BO') || s.startsWith('^')) ? s : s + '.NS';
            })(),"""

if old_chat_symbol in app_code:
    app_code = app_code.replace(old_chat_symbol, new_chat_symbol)
    print("Updated sendTvChartMessage symbol payload in app.js.")
else:
    print("WARNING: Could not find old_chat_symbol in app.js")


# Add ticker validation guard to sendTvChartMessage
old_send_fn_start = """async function sendTvChartMessage(customText = null) {
    const input = document.getElementById('tv-chat-input');
    const sendBtn = document.getElementById('tv-btn-chat-send');
    const spinner = document.getElementById('tv-chat-spinner');
    
    const promptText = customText || (input ? input.value.trim() : '');
    if (!promptText) return;"""

new_send_fn_start = """async function sendTvChartMessage(customText = null) {
    const input = document.getElementById('tv-chat-input');
    const sendBtn = document.getElementById('tv-btn-chat-send');
    const spinner = document.getElementById('tv-chat-spinner');
    
    const promptText = customText || (input ? input.value.trim() : '');
    if (!promptText) return;

    const activeSym = window.getActiveChartSymbol();
    if (!activeSym) {
        appendTvChatMessage('bot', "⚠️ Please load or search a stock ticker first before asking technical analysis questions.");
        return;
    }"""

if old_send_fn_start in app_code:
    app_code = app_code.replace(old_send_fn_start, new_send_fn_start)
    print("Added ticker guard to sendTvChartMessage in app.js.")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_code)

print("Updated app.js successfully.")


# 3. Bump index.html to app.js?v=5.2.0
index_path = 'backend/static/index.html'
with open(index_path, 'r', encoding='utf-8') as f:
    html_code = f.read()

html_code = html_code.replace('app.js?v=5.1.9', 'app.js?v=5.2.0')
with open(index_path, 'w', encoding='utf-8') as f:
    f.write(html_code)

print("Updated index.html asset version to app.js?v=5.2.0.")
