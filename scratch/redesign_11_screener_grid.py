import re

# 1. Fix app.js HTML template for 11-screener grid
app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    app_lines = f.readlines()

new_grid_template = [
    '                        <div class="diag-screener-card ${isQual ? \'qualified qualified-card\' : \'rejected rejected-card\'}" data-qualified="${isQual}">\n',
    '                            <div class="diag-screener-card-header">\n',
    '                                <strong class="diag-screener-name">${s.icon} ${s.name}</strong>\n',
    '                                <span class="diag-screener-badge ${isQual ? \'qual\' : \'rej\'}">\n',
    '                                    ${isQual ? \'✓ QUALIFIED\' : \'✗ REJECTED\'}\n',
    '                                </span>\n',
    '                            </div>\n',
    '                            <div class="diag-screener-reason-body">\n',
    '                                <p class="diag-screener-reason">${reasonText}</p>\n',
    '                            </div>\n',
    '                        </div>\n'
]

grid_start = -1
for idx, line in enumerate(app_lines):
    if 'class="diag-screener-card' in line and '${isQual' in line:
        grid_start = idx
        break

if grid_start != -1:
    grid_end = grid_start
    while grid_end < len(app_lines) and '`;' not in app_lines[grid_end]:
        grid_end += 1
    app_lines[grid_start:grid_end] = new_grid_template
    with open(app_path, 'w', encoding='utf-8') as f:
        f.writelines(app_lines)
    print(f"Updated app.js lines {grid_start+1} to {grid_end}.")
else:
    print("WARNING: Could not find grid_start in app.js")


# 2. Append enhanced responsive CSS to styles.css
css_path = 'backend/static/styles.css'
with open(css_path, 'r', encoding='utf-8') as f:
    css_content = f.read()

enhanced_css = """

/* ==========================================================================
   ULTRA-PREMIUM RESPONSIVE 11-SCREENER QUALIFICATION CARDS GRID SYSTEM
   ========================================================================== */
.diag-screener-grid {
    display: grid !important;
    grid-template-columns: repeat(3, 1fr) !important;
    gap: 14px !important;
    margin-bottom: 24px !important;
    width: 100% !important;
    box-sizing: border-box !important;
}

@media (max-width: 1100px) {
    .diag-screener-grid {
        grid-template-columns: repeat(2, 1fr) !important;
        gap: 12px !important;
    }
}

@media (max-width: 680px) {
    .diag-screener-grid {
        grid-template-columns: 1fr !important;
        gap: 10px !important;
    }
}

.diag-screener-card {
    border-radius: 12px !important;
    padding: 14px 16px !important;
    box-sizing: border-box !important;
    display: flex !important;
    flex-direction: column !important;
    justify-content: space-between !important;
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.12) !important;
    position: relative !important;
    overflow: hidden !important;
}

.diag-screener-card:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2) !important;
}

/* Dark Mode Grid Cards */
.diag-screener-card.qualified-card,
.diag-screener-card.qualified {
    background: linear-gradient(180deg, rgba(16, 185, 129, 0.08) 0%, rgba(15, 23, 42, 0.85) 100%) !important;
    border: 1px solid rgba(16, 185, 129, 0.35) !important;
    border-top: 3px solid #10b981 !important;
}

.diag-screener-card.rejected-card,
.diag-screener-card.rejected {
    background: linear-gradient(180deg, rgba(239, 68, 68, 0.04) 0%, rgba(15, 23, 42, 0.65) 100%) !important;
    border: 1px solid rgba(239, 68, 68, 0.2) !important;
    border-top: 3px solid #ef4444 !important;
}

.diag-screener-card-header {
    display: flex !important;
    justify-content: space-between !important;
    align-items: center !important;
    margin-bottom: 10px !important;
    gap: 8px !important;
    flex-wrap: nowrap !important;
}

.diag-screener-name {
    font-size: 13px !important;
    font-weight: 800 !important;
    letter-spacing: -0.01em !important;
    color: #f8fafc !important;
    line-height: 1.35 !important;
    display: flex !important;
    align-items: center !important;
    gap: 6px !important;
}

.diag-screener-badge {
    font-size: 11px !important;
    font-weight: 800 !important;
    padding: 3px 9px !important;
    border-radius: 6px !important;
    letter-spacing: 0.03em !important;
    white-space: nowrap !important;
    display: inline-flex !important;
    align-items: center !important;
}

.diag-screener-badge.qual {
    background: rgba(16, 185, 129, 0.2) !important;
    color: #34d399 !important;
    border: 1px solid rgba(16, 185, 129, 0.4) !important;
}

.diag-screener-badge.rej {
    background: rgba(239, 68, 68, 0.15) !important;
    color: #f87171 !important;
    border: 1px solid rgba(239, 68, 68, 0.3) !important;
}

.diag-screener-reason-body {
    margin-top: 4px !important;
    flex: 1 !important;
}

.diag-screener-reason {
    font-size: 12px !important;
    line-height: 1.55 !important;
    color: #cbd5e1 !important;
    margin: 0 !important;
    font-weight: 500 !important;
}

/* Light Mode Overrides for 11-Screener Qualification Cards Grid */
[data-mode="light"] .diag-screener-card,
[data-theme="light"] .diag-screener-card,
body.light-theme .diag-screener-card {
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.05) !important;
}

[data-mode="light"] .diag-screener-name,
[data-theme="light"] .diag-screener-name,
body.light-theme .diag-screener-name {
    color: #0f172a !important;
}

[data-mode="light"] .diag-screener-reason,
[data-theme="light"] .diag-screener-reason,
body.light-theme .diag-screener-reason {
    color: #334155 !important;
}

[data-mode="light"] .diag-screener-card.qualified-card,
[data-theme="light"] .diag-screener-card.qualified-card,
body.light-theme .diag-screener-card.qualified-card,
[data-mode="light"] .diag-screener-card.qualified,
[data-theme="light"] .diag-screener-card.qualified,
body.light-theme .diag-screener-card.qualified {
    background: linear-gradient(180deg, #f0fdf4 0%, #ffffff 100%) !important;
    border: 1px solid #6ee7b7 !important;
    border-top: 3px solid #10b981 !important;
}

[data-mode="light"] .diag-screener-card.rejected-card,
[data-theme="light"] .diag-screener-card.rejected-card,
body.light-theme .diag-screener-card.rejected-card,
[data-mode="light"] .diag-screener-card.rejected,
[data-theme="light"] .diag-screener-card.rejected,
body.light-theme .diag-screener-card.rejected {
    background: linear-gradient(180deg, #fef2f2 0%, #ffffff 100%) !important;
    border: 1px solid #fca5a5 !important;
    border-top: 3px solid #ef4444 !important;
}

[data-mode="light"] .diag-screener-badge.qual,
[data-theme="light"] .diag-screener-badge.qual,
body.light-theme .diag-screener-badge.qual {
    background: #dcfce7 !important;
    color: #15803d !important;
    border: 1px solid #86efac !important;
}

[data-mode="light"] .diag-screener-badge.rej,
[data-theme="light"] .diag-screener-badge.rej,
body.light-theme .diag-screener-badge.rej {
    background: #fee2e2 !important;
    color: #b91c1c !important;
    border: 1px solid #fca5a5 !important;
}
"""

if 'ULTRA-PREMIUM RESPONSIVE 11-SCREENER QUALIFICATION CARDS GRID SYSTEM' not in css_content:
    css_content += '\n' + enhanced_css

with open(css_path, 'w', encoding='utf-8') as f:
    f.write(css_content)

print("Updated styles.css with responsive 3-column grid design.")

# 3. Bump index.html version tag to v=5.1.1
index_path = 'backend/static/index.html'
with open(index_path, 'r', encoding='utf-8') as f:
    html_code = f.read()

html_code = html_code.replace('app.js?v=5.1.0', 'app.js?v=5.1.1')
html_code = html_code.replace('styles.css?v=5.0.5', 'styles.css?v=5.1.1')
with open(index_path, 'w', encoding='utf-8') as f:
    f.write(html_code)

print("Updated index.html asset version to v=5.1.1.")
