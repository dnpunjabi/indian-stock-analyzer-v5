import re

styles_path = 'backend/static/styles.css'
with open(styles_path, 'r', encoding='utf-8') as f:
    css = f.read()

# 1. Clean up block 1 (lines 29661-29673)
old_block_1 = """/* Force Chart.js and TradingView Lightweight Chart canvas elements to stretch 100% */
#stock-chart,
#fibonacci-chart,
.price-chart-container canvas,
.fib-chart-container canvas,
.tv-lightweight-charts,
.tv-lightweight-charts canvas,
.tv-lightweight-charts table {
    width: 100% !important;
    max-width: 100% !important;
    display: block !important;
    box-sizing: border-box !important;
}"""

new_block_1 = """/* Force Chart.js and container elements to stretch 100% */
#stock-chart,
#fibonacci-chart,
.price-chart-container canvas,
.fib-chart-container canvas,
.tv-lightweight-charts {
    width: 100% !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
}"""

if old_block_1 in css:
    css = css.replace(old_block_1, new_block_1)
    print("Fixed CSS block 1 in styles.css")

# 2. Clean up block 2 (lines 29708-29721)
old_block_2 = """/* Force Chart.js and TradingView elements to stretch 100% */
#stock-chart,
#fibonacci-chart,
.price-chart-container canvas,
.fib-chart-container canvas,
.tv-lightweight-charts,
.tv-lightweight-charts canvas,
.tv-lightweight-charts table {
    width: 100% !important;
    min-width: 100% !important;
    max-width: 100% !important;
    display: block !important;
    box-sizing: border-box !important;
}"""

new_block_2 = """/* Force Chart.js and container elements to stretch 100% */
#stock-chart,
#fibonacci-chart,
.price-chart-container canvas,
.fib-chart-container canvas,
.tv-lightweight-charts {
    width: 100% !important;
    min-width: 100% !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
}"""

if old_block_2 in css:
    css = css.replace(old_block_2, new_block_2)
    print("Fixed CSS block 2 in styles.css")

with open(styles_path, 'w', encoding='utf-8') as f:
    f.write(css)

# Update index.html version to 5.3.3
html_path = 'backend/static/index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

html = html.replace('app.js?v=5.3.2', 'app.js?v=5.3.3')

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

print("Finished applying fix_styles_lightweight_charts.py!")
