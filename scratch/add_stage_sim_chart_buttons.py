import re

app_path = 'backend/static/app.js'
with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

# 1. Add window.openExternalTVChart helper if not present
helper_code = """
window.openExternalTVChart = function(symbol) {
    if (!symbol) return;
    const cleanSym = symbol.replace('.NS', '').replace('.BO', '').trim().toUpperCase();
    const tvUrl = `https://in.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(cleanSym)}`;
    window.open(tvUrl, '_blank');
};
"""

if 'window.openExternalTVChart =' not in app_code:
    app_code = helper_code + '\n' + app_code
    print("Added window.openExternalTVChart helper function.")


# 2. Update renderStageDiagnosticResults to include cleanSym variable and chart buttons
old_verdict_banner = """                <div class="stage-verdict-top">
                    <div class="stage-verdict-symbol-info">
                        <h4 class="stage-verdict-symbol">
                            <span>📊</span> ${data.symbol} (${data.base_symbol || data.symbol})
                            <span class="stage-verdict-price">₹${(m.current_price || 0).toFixed(2)}</span>
                            <span class="stage-verdict-change ${(m.day_change_pct || 0) >= 0 ? 'pos' : 'neg'}">
                                ${(m.day_change_pct || 0) >= 0 ? '+' : ''}${(m.day_change_pct || 0).toFixed(2)}%
                            </span>
                        </h4>
                    </div>
                    <div class="stage-verdict-badge">
                        <span>${verdictTitle}</span>
                        <span class="stage-verdict-conf">(${data.stage_confidence}% Confidence)</span>
                    </div>
                </div>"""

new_verdict_banner = """                <div class="stage-verdict-top">
                    <div class="stage-verdict-symbol-info">
                        <h4 class="stage-verdict-symbol">
                            <span>📊</span> ${data.symbol} (${data.base_symbol || data.symbol})
                            <span class="stage-verdict-price">₹${(m.current_price || 0).toFixed(2)}</span>
                            <span class="stage-verdict-change ${(m.day_change_pct || 0) >= 0 ? 'pos' : 'neg'}">
                                ${(m.day_change_pct || 0) >= 0 ? '+' : ''}${(m.day_change_pct || 0).toFixed(2)}%
                            </span>
                        </h4>
                    </div>
                    <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                        <div style="display: flex; align-items: center; gap: 6px;">
                            <button class="btn-primary quant-ichart-btn" 
                                    style="font-size: 12px; padding: 5px 12px; border-radius: 8px; font-weight: 800; cursor: pointer; background: linear-gradient(135deg, #10b981, #059669); border: none; color: #fff; display: inline-flex; align-items: center; gap: 6px; box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);"
                                    onclick="event.stopPropagation(); window.openStandaloneInteractiveChart && window.openStandaloneInteractiveChart('${(data.symbol||'').replace('.NS','').replace('.BO','')}', ['${(data.symbol||'').replace('.NS','').replace('.BO','')}'], 'vcp', 'Stage 1-4 Simulator');" 
                                    title="Open Standalone i-Chart Workstation">
                                <span>📈</span> i-Chart
                            </button>
                            <button class="btn-secondary quant-tv-btn" 
                                    style="font-size: 12px; padding: 5px 12px; border-radius: 8px; font-weight: 800; cursor: pointer; background: rgba(255,255,255,0.08); border: 1px solid var(--border-glass, rgba(255,255,255,0.2)); color: var(--text-primary); display: inline-flex; align-items: center; gap: 6px;"
                                    onclick="event.stopPropagation(); window.openExternalTVChart && window.openExternalTVChart('${(data.symbol||'').replace('.NS','').replace('.BO','')}');" 
                                    title="Open TradingView External Chart">
                                <span>Chart</span> ↗
                            </button>
                        </div>
                        <div class="stage-verdict-badge">
                            <span>${verdictTitle}</span>
                            <span class="stage-verdict-conf">(${data.stage_confidence}% Confidence)</span>
                        </div>
                    </div>
                </div>"""

if old_verdict_banner in app_code:
    app_code = app_code.replace(old_verdict_banner, new_verdict_banner)
    print("Added dual action buttons (i-Chart & Chart) to Stage Verdict Banner.")
else:
    print("WARNING: Could not find old_verdict_banner in app.js")


# 3. Add chart buttons to 11-screener qualification grid cards
old_grid_card = """                        <div class="diag-screener-card ${isQual ? 'qualified qualified-card' : 'rejected rejected-card'}" data-qualified="${isQual}">
                            <div class="diag-screener-card-header">
                                <strong class="diag-screener-name">${s.icon} ${s.name}</strong>
                                <span class="diag-screener-badge ${isQual ? 'qual' : 'rej'}">
                                    ${isQual ? '✓ QUALIFIED' : '✗ REJECTED'}
                                </span>
                            </div>
                            <p class="diag-screener-reason">${reasonText}</p>
                        </div>"""

new_grid_card = """                        <div class="diag-screener-card ${isQual ? 'qualified qualified-card' : 'rejected rejected-card'}" data-qualified="${isQual}">
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

if old_grid_card in app_code:
    app_code = app_code.replace(old_grid_card, new_grid_card)
    print("Added dual action buttons to 11-screener qualification grid cards.")
else:
    print("WARNING: Could not find old_grid_card in app.js")


# 4. Add chart buttons to audit breakdown cards
old_audit_card_header = """                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; gap: 8px; flex-wrap: wrap;">
                                    <strong style="font-size: 13px; color: var(--text-color, #f8fafc); font-weight: 800;">${displayName}</strong>
                                    ${statusBadge}
                                </div>"""

new_audit_card_header = """                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; gap: 8px; flex-wrap: wrap;">
                                    <strong style="font-size: 13px; color: var(--text-color, #f8fafc); font-weight: 800;">${displayName}</strong>
                                    <div style="display: flex; align-items: center; gap: 6px;">
                                        <button class="btn-primary quant-ichart-btn" 
                                                style="font-size: 10.5px; padding: 2px 7px; border-radius: 6px; font-weight: 800; cursor: pointer; background: linear-gradient(135deg, #10b981, #059669); border: none; color: #fff; display: inline-flex; align-items: center; gap: 4px;"
                                                onclick="event.stopPropagation(); window.openStandaloneInteractiveChart && window.openStandaloneInteractiveChart('${(data.symbol||'').replace('.NS','').replace('.BO','')}', ['${(data.symbol||'').replace('.NS','').replace('.BO','')}'], '${s.key}', '${displayName}');" 
                                                title="Open i-Chart Workstation">
                                            <span>📈</span> i-Chart
                                        </button>
                                        <button class="btn-secondary quant-tv-btn" 
                                                style="font-size: 10.5px; padding: 2px 7px; border-radius: 6px; font-weight: 800; cursor: pointer; background: rgba(255,255,255,0.08); border: 1px solid var(--border-glass, rgba(255,255,255,0.2)); color: var(--text-primary); display: inline-flex; align-items: center; gap: 4px;"
                                                onclick="event.stopPropagation(); window.openExternalTVChart && window.openExternalTVChart('${(data.symbol||'').replace('.NS','').replace('.BO','')}');" 
                                                title="Open TradingView Chart">
                                            Chart ↗
                                        </button>
                                        ${statusBadge}
                                    </div>
                                </div>"""

if old_audit_card_header in app_code:
    app_code = app_code.replace(old_audit_card_header, new_audit_card_header)
    print("Added dual action buttons to audit breakdown cards.")
else:
    print("WARNING: Could not find old_audit_card_header in app.js")


with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_code)

print("Successfully updated app.js with Stage Simulator chart buttons.")

# 5. Bump index.html to app.js?v=5.0.8
index_path = 'backend/static/index.html'
with open(index_path, 'r', encoding='utf-8') as f:
    html_code = f.read()

html_code = html_code.replace('app.js?v=5.0.7', 'app.js?v=5.0.8')
with open(index_path, 'w', encoding='utf-8') as f:
    f.write(html_code)

print("Updated index.html asset version to app.js?v=5.0.8.")
