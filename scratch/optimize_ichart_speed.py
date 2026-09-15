import re
import os

# 1. Update backend/main.py with TV_CHART_CACHE
main_path = 'backend/main.py'
with open(main_path, 'r', encoding='utf-8') as f:
    main_code = f.read()

if 'TV_CHART_CACHE = {}' not in main_code:
    main_code = "TV_CHART_CACHE = {}\n" + main_code

# Locate get_tv_chart_data implementation
old_endpoint_header = """@app.get("/api/chart/tv-chart-data")
async def get_tv_chart_data(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
    length: int = 14,
    mult: float = 1.0,
    int_sens: int = 3,
    ext_sens: int = 25,
    show_last: int = 10,
    pitchfork_type: str = "Original",
    pitchfork_dev: float = 5.0,
    pitchfork_depth: int = 34
):"""

new_endpoint_header = """@app.get("/api/chart/tv-chart-data")
async def get_tv_chart_data(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
    length: int = 14,
    mult: float = 1.0,
    int_sens: int = 3,
    ext_sens: int = 25,
    show_last: int = 10,
    pitchfork_type: str = "Original",
    pitchfork_dev: float = 5.0,
    pitchfork_depth: int = 34
):
    cache_key = (ticker.upper(), period, interval, length, mult, pitchfork_type, pitchfork_dev, pitchfork_depth)
    now_ts = time.time()
    if cache_key in TV_CHART_CACHE:
        cached_time, cached_data = TV_CHART_CACHE[cache_key]
        if now_ts - cached_time < 600:
            return cached_data"""

if 'cache_key = (ticker.upper(), period, interval' not in main_code:
    main_code = main_code.replace(old_endpoint_header, new_endpoint_header)

# Cache result before returning in get_tv_chart_data
old_return_statement = "return res_payload"
if old_return_statement in main_code and 'TV_CHART_CACHE[cache_key] =' not in main_code:
    main_code = main_code.replace(
        "return res_payload",
        "TV_CHART_CACHE[cache_key] = (now_ts, res_payload)\n        return res_payload"
    )

with open(main_path, 'w', encoding='utf-8') as f:
    f.write(main_code)

print("Updated backend/main.py with TV_CHART_CACHE (600s TTL).")


# 2. Update backend/static/app.js with client-side memory caching & parameter signature
app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

# Replace async function renderTVWorkstationChart(symbol) signature to accept forceRefresh
app_code = app_code.replace(
    "async function renderTVWorkstationChart(symbol) {",
    "async function renderTVWorkstationChart(symbol, forceRefresh = false) {"
)

# Update fetch block to use window.tvChartMemoryCache
old_fetch_block = """        // Fetch data (ext_sens corresponds to the Length parameter selected)
        const res = await fetch(`/api/chart/tv-chart-data?ticker=${encodeURIComponent(formattedTicker)}&length=${length}&mult=${mult}&ext_sens=${length}&int_sens=5&pitchfork_type=${encodeURIComponent(pitchforkType)}&pitchfork_dev=5.0&pitchfork_depth=34`);
        if (!res.ok) throw new Error("Failed to fetch interactive chart indicators.");
        const data = await res.json();
        window.latestTvChartData = data;"""

new_fetch_block = """        // Fast Client-Side Memory Caching
        window.tvChartMemoryCache = window.tvChartMemoryCache || {};
        const cacheKey = `${formattedTicker}_${length}_${mult}_${pitchforkType}`;
        let data = null;

        if (!forceRefresh && window.tvChartMemoryCache[cacheKey]) {
            data = window.tvChartMemoryCache[cacheKey];
        } else {
            const res = await fetch(`/api/chart/tv-chart-data?ticker=${encodeURIComponent(formattedTicker)}&length=${length}&mult=${mult}&ext_sens=${length}&int_sens=5&pitchfork_type=${encodeURIComponent(pitchforkType)}&pitchfork_dev=5.0&pitchfork_depth=34`);
            if (!res.ok) throw new Error("Failed to fetch interactive chart indicators.");
            data = await res.json();
            window.tvChartMemoryCache[cacheKey] = data;
        }
        window.latestTvChartData = data;"""

if 'window.tvChartMemoryCache =' not in app_code:
    app_code = app_code.replace(old_fetch_block, new_fetch_block)

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_code)

print("Updated backend/static/app.js with client-side memory caching for instant re-rendering.")
