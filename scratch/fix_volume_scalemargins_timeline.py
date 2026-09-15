import re

# 1. Update app.js: Fix volumeSeries scaleMargins and rightPriceScale scaleMargins
app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    js = f.read()

# Fix rightPriceScale in createChart
old_price_scale = """            rightPriceScale: {
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
            },"""

new_price_scale = """            rightPriceScale: {
                borderColor: isDarkTheme ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)',
                visible: true,
                scaleMargins: {
                    top: 0.08,
                    bottom: 0.08,
                },
            },"""

if old_price_scale in js:
    js = js.replace(old_price_scale, new_price_scale)
    print("Updated rightPriceScale in app.js")

# Fix volumeSeries scaleMargins
old_vol_margins = """            volumeSeries.priceScale().applyOptions({
                scaleMargins: {
                    top: 0.8, // highest point of the series will be 80% from top (bottom 20% of chart)
                    bottom: 0,
                },
            });"""

new_vol_margins = """            volumeSeries.priceScale().applyOptions({
                scaleMargins: {
                    top: 0.8,
                    bottom: 0.05,
                },
            });"""

if old_vol_margins in js:
    js = js.replace(old_vol_margins, new_vol_margins)
    print("Updated volumeSeries scaleMargins in app.js")

# Fix createChart height to 480px
js = js.replace('height: 460,', 'height: 480,')
print("Updated createChart height to 480 in app.js")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(js)

# 2. Update styles.css: Update #tv-chart-container height to 480px
styles_path = 'backend/static/styles.css'
with open(styles_path, 'r', encoding='utf-8') as f:
    css = f.read()

css = css.replace('height: 460px;', 'height: 480px;')
css = css.replace('min-height: 460px;', 'min-height: 480px;')
with open(styles_path, 'w', encoding='utf-8') as f:
    f.write(css)
print("Updated styles.css height to 480px")

# 3. Update index.html: Update #tv-chart-container inline style height to 480px & bump version to 5.3.2
html_path = 'backend/static/index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

html = html.replace('height: 460px;', 'height: 480px;')
html = html.replace('app.js?v=5.3.1', 'app.js?v=5.3.2')
with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)
print("Updated index.html height to 480px and version to 5.3.2")

print("Finished applying fix_volume_scalemargins_timeline.py!")
