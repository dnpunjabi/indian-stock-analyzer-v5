import re

# 1. Update backend/main.py get_indicator_synthesis
main_path = 'backend/main.py'
with open(main_path, 'r', encoding='utf-8') as f:
    main_code = f.read()

old_synth_start = """@app.get("/api/chart/indicator-synthesis")
async def get_indicator_synthesis(
    ticker: str,
    indicator: str = "lux-algo",
    period: str = "1y",
    interval: str = "1d",
    length: int = 14,
    mult: float = 1.0,
    int_sens: int = 3,
    ext_sens: int = 25,
    show_last: int = 10
):
    \"\"\"
    Synthesizes custom technical indicator calculations (LuxAlgo SMC, Trendlines with Breaks, or Mxwll)
    into a structured tactical summary using Groq LLM.
    \"\"\"
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker parameter is required.")"""

new_synth_start = """@app.get("/api/chart/indicator-synthesis")
async def get_indicator_synthesis(
    ticker: str,
    indicator: str = "lux-algo",
    period: str = "1y",
    interval: str = "1d",
    length: int = 14,
    mult: float = 1.0,
    int_sens: int = 3,
    ext_sens: int = 25,
    show_last: int = 10
):
    \"\"\"
    Synthesizes custom technical indicator calculations (LuxAlgo SMC, Trendlines with Breaks, or Mxwll)
    into a structured tactical summary using Groq LLM.
    \"\"\"
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker parameter is required.")
        
    ticker = ticker.strip().upper()
    if not ticker.endswith('.NS') and not ticker.endswith('.BO') and not ticker.startswith('^'):
        ticker = ticker + '.NS'"""

if old_synth_start in main_code:
    main_code = main_code.replace(old_synth_start, new_synth_start)
    print("Updated get_indicator_synthesis in backend/main.py to auto-append .NS")
else:
    print("WARNING: Could not find old_synth_start in backend/main.py")

with open(main_path, 'w', encoding='utf-8') as f:
    f.write(main_code)


# 2. Update backend/static/app.js triggerTVIndicatorSynthesis
app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

old_trigger_code = """    const ticker = window.getActiveChartSymbol();
    if (!ticker) {
        content.innerHTML = `<span style="color: var(--text-muted);">Please load or search a stock ticker first.</span>`;
        return;
    }
    const indicator = document.getElementById('tv-active-indicator')?.value || 'lux-algo';"""

new_trigger_code = """    const rawTicker = window.getActiveChartSymbol();
    if (!rawTicker) {
        content.innerHTML = `<span style="color: var(--text-muted);">Please load or search a stock ticker first.</span>`;
        return;
    }
    let ticker = rawTicker.trim().toUpperCase();
    if (!ticker.endsWith('.NS') && !ticker.endsWith('.BO') && !ticker.startsWith('^')) {
        ticker = ticker + '.NS';
    }
    const indicator = document.getElementById('tv-active-indicator')?.value || 'lux-algo';"""

if old_trigger_code in app_code:
    app_code = app_code.replace(old_trigger_code, new_trigger_code)
    print("Updated triggerTVIndicatorSynthesis in backend/static/app.js to format ticker with .NS")
else:
    print("WARNING: Could not find old_trigger_code in app.js")

# Improve error detail extraction in triggerTVIndicatorSynthesis
old_fetch_check = """        const res = await fetch(url);
        if (!res.ok) throw new Error("Server returned error status.");
        const data = await res.json();"""

new_fetch_check = """        const res = await fetch(url);
        if (!res.ok) {
            let errDetail = "Server returned error status.";
            try {
                const errJson = await res.json();
                if (errJson && errJson.detail) errDetail = errJson.detail;
            } catch(e) {}
            throw new Error(errDetail);
        }
        const data = await res.json();"""

if old_fetch_check in app_code:
    app_code = app_code.replace(old_fetch_check, new_fetch_check)
    print("Updated res.ok error handling in triggerTVIndicatorSynthesis.")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_code)

# 3. Bump index.html to app.js?v=5.2.1
index_path = 'backend/static/index.html'
with open(index_path, 'r', encoding='utf-8') as f:
    html_code = f.read()

html_code = html_code.replace('app.js?v=5.2.0', 'app.js?v=5.2.1')
with open(index_path, 'w', encoding='utf-8') as f:
    f.write(html_code)

print("Updated index.html asset version to app.js?v=5.2.1.")
