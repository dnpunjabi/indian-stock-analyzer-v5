with open('backend/static/app.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 1. Clean grid card header (lines 58686 to 58706)
grid_start = -1
for idx, line in enumerate(lines):
    if 'class="diag-screener-card' in line and '${isQual' in line:
        grid_start = idx
        break

if grid_start != -1:
    clean_grid_block = [
        '                        <div class="diag-screener-card ${isQual ? \'qualified qualified-card\' : \'rejected rejected-card\'}" data-qualified="${isQual}">\n',
        '                            <div class="diag-screener-card-header">\n',
        '                                <strong class="diag-screener-name">${s.icon} ${s.name}</strong>\n',
        '                                <span class="diag-screener-badge ${isQual ? \'qual\' : \'rej\'}">\n',
        '                                    ${isQual ? \'✅ QUALIFIED\' : \'❌ REJECTED\'}\n',
        '                                </span>\n',
        '                            </div>\n',
        '                            <p class="diag-screener-reason">${reasonText}</p>\n',
        '                        </div>\n'
    ]
    # Find closing div of diag-screener-card
    grid_end = grid_start
    while grid_end < len(lines) and '</div>' not in lines[grid_end]:
        grid_end += 1
    grid_end += 1 # Include </div>
    lines[grid_start:grid_end] = clean_grid_block
    print(f"Cleaned 11-Screener grid cards from line {grid_start+1} to {grid_end}.")


# 2. Clean audit breakdown card header
audit_start = -1
for idx, line in enumerate(lines):
    if 'class="audit-mobile-card"' in line:
        audit_start = idx
        break

if audit_start != -1:
    clean_audit_header = [
        '                            <div class="audit-mobile-card" style="background: var(--bg-glass-input, rgba(30, 41, 59, 0.5)); border: 1px solid ${isQual ? \'rgba(52, 211, 153, 0.3)\' : \'rgba(248, 113, 113, 0.25)\'}; border-radius: 10px; padding: 14px 16px;">\n',
        '                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; gap: 8px; flex-wrap: wrap;">\n',
        '                                    <strong style="font-size: 13px; color: var(--text-color, #f8fafc); font-weight: 800;">${displayName}</strong>\n',
        '                                    ${statusBadge}\n',
        '                                </div>\n'
    ]
    audit_header_end = audit_start
    while audit_header_end < len(lines) and '</div>' not in lines[audit_header_end]:
        audit_header_end += 1
    audit_header_end += 1
    lines[audit_start:audit_header_end] = clean_audit_header
    print(f"Cleaned audit breakdown cards from line {audit_start+1} to {audit_header_end}.")


with open('backend/static/app.js', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Updated app.js successfully.")

# Bump index.html to app.js?v=5.1.0
index_path = 'backend/static/index.html'
with open(index_path, 'r', encoding='utf-8') as f:
    html_code = f.read()

html_code = html_code.replace('app.js?v=5.0.9', 'app.js?v=5.1.0')
with open(index_path, 'w', encoding='utf-8') as f:
    f.write(html_code)

print("Updated index.html asset version to app.js?v=5.1.0.")
