app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

target_str = """                        <div class="diag-screener-card ${isQual ? 'qualified qualified-card' : 'rejected rejected-card'}" data-qualified="${isQual}">
                            <div class="diag-screener-card-header">
                                <strong class="diag-screener-name">${s.icon} ${s.name}</strong>
                                <span class="diag-screener-badge ${isQual ? 'qual' : 'rej'}">
                                    ${isQual ? '✓ QUALIFIED' : '✗ REJECTED'}
                                </span>
                            </div>
                            <p class="diag-screener-reason">${reasonText}</p>
                        </div>"""

replacement_str = """                        <div class="diag-screener-card ${isQual ? 'qualified qualified-card' : 'rejected rejected-card'}" data-qualified="${isQual}">
                            <div class="diag-screener-card-header" style="flex-wrap: wrap; gap: 6px;">
                                <strong class="diag-screener-name">${s.icon} ${s.name}</strong>
                                <div style="display: flex; align-items: center; gap: 6px;">
                                    <button class="btn-primary quant-ichart-btn" 
                                            style="font-size: 10.5px; padding: 2px 7px; border-radius: 6px; font-weight: 800; cursor: pointer; background: linear-gradient(135deg, #10b981, #059669); border: none; color: #fff; display: inline-flex; align-items: center; gap: 4px;"
                                            onclick="event.stopPropagation(); window.openStandaloneInteractiveChart && window.openStandaloneInteractiveChart('${(data.symbol||'').replace('.NS','').replace('.BO','')}', ['${(data.symbol||'').replace('.NS','').replace('.BO','')}'], '${s.key}', '${s.name}');" 
                                            title="Open i-Chart Workstation">
                                        <span>📈</span> i-Chart
                                    </button>
                                    <button class="btn-secondary quant-tv-btn" 
                                            style="font-size: 10.5px; padding: 2px 7px; border-radius: 6px; font-weight: 800; cursor: pointer; background: rgba(255,255,255,0.08); border: 1px solid var(--border-glass, rgba(255,255,255,0.2)); color: var(--text-primary); display: inline-flex; align-items: center; gap: 4px;"
                                            onclick="event.stopPropagation(); window.openExternalTVChart && window.openExternalTVChart('${(data.symbol||'').replace('.NS','').replace('.BO','')}');" 
                                            title="Open TradingView Chart">
                                        Chart ↗
                                    </button>
                                    <span class="diag-screener-badge ${isQual ? 'qual' : 'rej'}">
                                        ${isQual ? '✓ QUALIFIED' : '✗ REJECTED'}
                                    </span>
                                </div>
                            </div>
                            <p class="diag-screener-reason">${reasonText}</p>
                        </div>"""

if target_str in app_code:
    app_code = app_code.replace(target_str, replacement_str)
    print("Replaced grid card buttons successfully.")
else:
    # Try regex match
    print("Trying fallback regex replacement...")
    lines = app_code.split('\n')
    for idx, line in enumerate(lines):
        if 'class="diag-screener-card' in line and '${isQual' in line:
            print(f"Found line at {idx+1}")
    
with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_code)
