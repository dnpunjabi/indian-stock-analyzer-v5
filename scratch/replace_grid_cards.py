with open('backend/static/app.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_block = [
    '                        <div class="diag-screener-card ${isQual ? \'qualified qualified-card\' : \'rejected rejected-card\'}" data-qualified="${isQual}">\n',
    '                            <div class="diag-screener-card-header" style="flex-wrap: wrap; gap: 6px;">\n',
    '                                <strong class="diag-screener-name">${s.icon} ${s.name}</strong>\n',
    '                                <div style="display: flex; align-items: center; gap: 6px;">\n',
    '                                    <button class="btn-primary quant-ichart-btn" \n',
    '                                            style="font-size: 10.5px; padding: 2px 7px; border-radius: 6px; font-weight: 800; cursor: pointer; background: linear-gradient(135deg, #10b981, #059669); border: none; color: #fff; display: inline-flex; align-items: center; gap: 4px;"\n',
    '                                            onclick="event.stopPropagation(); window.openStandaloneInteractiveChart && window.openStandaloneInteractiveChart(\'${(data.symbol||\'\').replace(\'.NS\',\'\').replace(\'.BO\',\'\')}\', [\'${(data.symbol||\'\').replace(\'.NS\',\'\').replace(\'.BO\',\'\')}\'], \'${s.key}\', \'${s.name}\');" \n',
    '                                            title="Open i-Chart Workstation">\n',
    '                                        <span>📈</span> i-Chart\n',
    '                                    </button>\n',
    '                                    <button class="btn-secondary quant-tv-btn" \n',
    '                                            style="font-size: 10.5px; padding: 2px 7px; border-radius: 6px; font-weight: 800; cursor: pointer; background: rgba(255,255,255,0.08); border: 1px solid var(--border-glass, rgba(255,255,255,0.2)); color: var(--text-primary); display: inline-flex; align-items: center; gap: 4px;"\n',
    '                                            onclick="event.stopPropagation(); window.openExternalTVChart && window.openExternalTVChart(\'${(data.symbol||\'\').replace(\'.NS\',\'\').replace(\'.BO\',\'\')}\');" \n',
    '                                            title="Open TradingView Chart">\n',
    '                                        Chart ↗\n',
    '                                    </button>\n',
    '                                    <span class="diag-screener-badge ${isQual ? \'qual\' : \'rej\'}">\n',
    '                                        ${isQual ? \'✅ QUALIFIED\' : \'❌ REJECTED\'}\n',
    '                                    </span>\n',
    '                                </div>\n',
    '                            </div>\n',
    '                            <p class="diag-screener-reason">${reasonText}</p>\n',
    '                        </div>\n'
]

start_idx = -1
for idx, line in enumerate(lines):
    if 'class="diag-screener-card' in line and '${isQual' in line:
        start_idx = idx
        break

if start_idx != -1:
    end_idx = start_idx + 9 # 9 lines to replace
    lines[start_idx:end_idx] = new_block
    with open('backend/static/app.js', 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f"Replaced lines {start_idx+1} to {end_idx} in app.js successfully.")
else:
    print("Could not find start_idx.")
