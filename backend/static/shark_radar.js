/**
 * shark_radar.js — Client-Side Logic for Shark Radar Module (Indian Stock Analyzer 5.0)
 * 
 * Features:
 * - Directory Leaderboard with live search and sorting.
 * - Multi-Shark Consensus Screener (Multi-Shark Overlaps).
 * - Real-Time Smart Money Alerts Log with rich financial cards and direct stock research link.
 * - 1-Click Clone to Workspace Watchlist.
 * - Stock Research Terminal Integration ("Smart Money Presence Badge").
 * - Full Dark & Light Mode Theme Support + Mobile App Layout.
 */

(function () {
    let allSharkInvestors = [];
    let currentSharkConsensus = [];
    let currentSharkAlerts = [];
    let activeSubTab = 'superstars'; // 'superstars' | 'consensus' | 'alerts'

    // ─── LOAD SHARK RADAR DATA ─────────────────────────────────────────────
    window.loadSharkRadarData = async function (force = false) {
        const loadingIndicator = document.getElementById('shark-loading-indicator');
        if (loadingIndicator) loadingIndicator.style.display = 'flex';

        try {
            // 1. Fetch Superstar Directory
            const resDir = await fetch(`/api/sharks?force=${force}`);
            const dataDir = await resDir.json();
            if (dataDir.status === 'success' && dataDir.investors) {
                allSharkInvestors = dataDir.investors;
                renderSharkInvestors(allSharkInvestors);
                updateSharkHeroMetrics(allSharkInvestors);
            }

            // 2. Fetch Shark Consensus
            const resConsensus = await fetch('/api/sharks/consensus?min_sharks=2');
            const dataConsensus = await resConsensus.json();
            if (dataConsensus.status === 'success' && dataConsensus.consensus) {
                currentSharkConsensus = dataConsensus.consensus;
                renderSharkConsensus(currentSharkConsensus);
                const consensusBadge = document.getElementById('shark-metric-consensus');
                if (consensusBadge) consensusBadge.textContent = `${currentSharkConsensus.length} Overlapping Stocks`;
            }

            // 3. Fetch Alert History
            const resAlerts = await fetch('/api/sharks/alerts/history?limit=40');
            const dataAlerts = await resAlerts.json();
            if (dataAlerts.status === 'success' && dataAlerts.alerts) {
                currentSharkAlerts = dataAlerts.alerts;
                renderSharkAlerts(currentSharkAlerts);
            }
        } catch (err) {
            console.error('[SharkRadar] Error loading data:', err);
            if (window.showToast) window.showToast('Failed to load Shark Radar data.', 'error');
        } finally {
            if (loadingIndicator) loadingIndicator.style.display = 'none';
        }
    };

    // ─── HERO METRICS ──────────────────────────────────────────────────────
    function updateSharkHeroMetrics(investors) {
        const countEl = document.getElementById('shark-metric-count');
        const aumEl = document.getElementById('shark-metric-aum');
        if (countEl) countEl.textContent = `${investors.length} Superstars`;

        if (aumEl) {
            const totalCr = investors.reduce((acc, inv) => acc + (inv.net_worth_cr || 0), 0);
            aumEl.textContent = totalCr >= 100000 
                ? `₹${(totalCr / 100000).toFixed(2)} Lakh Cr` 
                : `₹${totalCr.toLocaleString('en-IN', { maximumFractionDigits: 1 })} Cr`;
        }
    }

    // ─── SUB-TAB SWITCHING ─────────────────────────────────────────────────
    window.switchSharkSubTab = function (tabKey) {
        activeSubTab = tabKey;
        const tabs = ['superstars', 'consensus', 'alerts'];
        tabs.forEach(t => {
            const btn = document.getElementById(`shark-subtab-btn-${t}`);
            const sidebarBtn = document.getElementById(`tab-shark-sub-${t}-btn`);
            const view = document.getElementById(`shark-subview-${t}`);
            if (btn) {
                if (t === tabKey) btn.classList.add('active');
                else btn.classList.remove('active');
            }
            if (sidebarBtn) {
                if (t === tabKey) sidebarBtn.classList.add('active');
                else sidebarBtn.classList.remove('active');
            }
            if (view) {
                view.style.display = (t === tabKey) ? 'block' : 'none';
            }
        });

        // Automatically dismiss mobile sidebar drawer upon selecting a sub-view
        if (typeof window.closeMobileSidebar === 'function') {
            window.closeMobileSidebar();
        } else {
            const sb = document.getElementById('sidebar');
            if (sb && sb.classList.contains('open')) sb.classList.remove('open');
        }
    };

    // ─── SEARCH & FILTER DIRECTORY ─────────────────────────────────────────
    window.filterSharkInvestors = function () {
        const query = (document.getElementById('shark-search-input')?.value || '').toLowerCase().trim();
        const sortBy = document.getElementById('shark-sort-select')?.value || 'net_worth';

        let filtered = allSharkInvestors.filter(inv => {
            if (!query) return true;
            return (
                (inv.name || '').toLowerCase().includes(query) ||
                (inv.sector_preference || '').toLowerCase().includes(query) ||
                (inv.top_holdings || '').toLowerCase().includes(query)
            );
        });

        if (sortBy === 'stocks_count') {
            filtered.sort((a, b) => (b.stocks_count || 0) - (a.stocks_count || 0));
        } else {
            filtered.sort((a, b) => (b.net_worth_cr || 0) - (a.net_worth_cr || 0));
        }

        renderSharkInvestors(filtered);
    };

    // ─── RENDER DIRECTORY CARDS ────────────────────────────────────────────
    function renderSharkInvestors(investors) {
        const grid = document.getElementById('shark-investors-grid');
        if (!grid) return;

        if (!investors || investors.length === 0) {
            grid.innerHTML = `
                <div style="grid-column: 1 / -1; padding: 40px; text-align: center; color: var(--text-secondary, #64748b); font-size: 14px;">
                    No superstar investors found matching your search.
                </div>
            `;
            return;
        }

        grid.innerHTML = investors.map(inv => {
            // Get Initials for avatar
            const initials = inv.name.split(' ').map(w => w[0]).filter(Boolean).slice(0, 2).join('').toUpperCase();
            
            // Format Top Holdings chips:
            // Filter out junk, standalone currency artifacts like "(304,259.33 Cr )", or stray dashes
            const topHoldings = (inv.top_holdings || '')
                .split('|')
                .map(s => s.trim().replace(/\s+/g, ' '))
                .filter(s => {
                    if (!s || s === '-' || s === '--') return false;
                    if (s.startsWith('(') && (s.includes('Cr') || s.includes('Lakh'))) return false;
                    if (/^\(?\d+[,\d.]*\s*(Cr|Lakh)?\)?$/i.test(s)) return false;
                    return true;
                })
                .slice(0, 3);

            const holdingsHtml = topHoldings.length > 0 
                ? topHoldings.map(h => `<span class="shark-pill-holding">${escapeHtml(h)}</span>`).join('')
                : '<span style="font-size: 11px; color: var(--text-muted, #94a3b8);">Holdings updating...</span>';

            // Recent Buy or Sell:
            // Only render badge if there is a real, non-dash stock name!
            let recentHtml = '';
            const rb = (inv.recently_bought || '').trim();
            const rs = (inv.recently_sold || '').trim();
            if (rb && rb !== '-' && rb !== '--' && rb !== 'N/A' && rb !== 'None') {
                const stockName = rb.split('|')[0].trim();
                if (stockName && stockName !== '-') {
                    recentHtml = `<span class="shark-pill-buy" title="Recent Disclosed Accumulation">🟢 Bought: ${escapeHtml(stockName)}</span>`;
                }
            } else if (rs && rs !== '-' && rs !== '--' && rs !== 'N/A' && rs !== 'None') {
                const stockName = rs.split('|')[0].trim();
                if (stockName && stockName !== '-') {
                    recentHtml = `<span class="shark-pill-sell" title="Recent Disclosed Trimming">🔴 Trimmed: ${escapeHtml(stockName)}</span>`;
                }
            }

            return `
                <div class="shark-card">
                    <div>
                        <div class="shark-card-header">
                            <div class="shark-avatar">${initials}</div>
                            <div style="overflow: hidden;">
                                <h3 class="shark-name" title="${escapeHtml(inv.name)}">${escapeHtml(inv.name)}</h3>
                                <div class="shark-sector">
                                    ${escapeHtml(inv.sector_preference || 'Equities Portfolio')}
                                </div>
                            </div>
                        </div>

                        <div class="shark-stats-row">
                            <div class="shark-stat-item">
                                <span class="shark-stat-label">Portfolio Value</span>
                                <span class="shark-stat-val">${escapeHtml(inv.net_worth_str || '₹--')}</span>
                            </div>
                            <div class="shark-stat-item" style="text-align: right;">
                                <span class="shark-stat-label">Public Stocks</span>
                                <span class="shark-stat-val" style="color: #f59e0b;">${inv.stocks_count || 0}</span>
                            </div>
                        </div>

                        <div style="margin-bottom: 8px;">
                            <span class="shark-stat-label" style="display: block; margin-bottom: 4px;">Top Holdings:</span>
                            <div class="shark-chips-wrap">
                                ${holdingsHtml}
                            </div>
                        </div>

                        ${recentHtml ? `<div style="margin-bottom: 14px;">${recentHtml}</div>` : ''}
                    </div>

                    <div class="shark-card-actions">
                        <button class="shark-btn-inspect" onclick="window.openSharkPortfolioModal('${inv.id}')">
                            🔍 Inspect Portfolio
                        </button>
                        <button class="shark-btn-clone" onclick="window.cloneSharkWatchlist('${inv.id}', '${escapeHtml(inv.name)}', this)" title="1-Click Clone to Watchlist">
                            📋 Clone
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    }

    // ─── RENDER CONSENSUS VIEW ─────────────────────────────────────────────
    function renderSharkConsensus(consensus) {
        const container = document.getElementById('shark-consensus-container');
        if (!container) return;

        if (!consensus || consensus.length === 0) {
            container.innerHTML = `
                <div style="padding: 40px; text-align: center; color: var(--text-secondary, #64748b); font-size: 14px;">
                    Syncing superstar portfolios... Consensus overlaps will appear here once 2 or more sharks hold the same stock.
                </div>
            `;
            return;
        }

        let rowsHtml = consensus.map(c => {
            const investorsChips = c.investors.map(inv => `
                <span class="shark-pill-holding" style="margin-right: 4px; margin-bottom: 4px; display: inline-block;">
                    <strong>${escapeHtml(inv.investor_name)}</strong>: ${inv.holding_percent}% 
                    ${inv.holding_value_cr > 0 ? `(₹${inv.holding_value_cr} Cr)` : ''}
                </span>
            `).join('');

            return `
                <tr>
                    <td>
                        <strong class="shark-stock-name">${escapeHtml(c.company_name || c.symbol)}</strong>
                        <div class="shark-ticker-sym">${escapeHtml(c.symbol)}</div>
                    </td>
                    <td>
                        <span class="shark-count-badge">🦈 ${c.shark_count} Sharks</span>
                    </td>
                    <td>
                        <strong style="color: #10b981; font-size: 14px;">${c.total_shark_stake_pct}%</strong>
                    </td>
                    <td>
                        <strong class="shark-stock-name" style="font-family: monospace;">₹${c.total_shark_value_cr.toLocaleString('en-IN')} Cr</strong>
                    </td>
                    <td style="max-width: 380px;">
                        ${investorsChips}
                    </td>
                    <td>
                        <button class="shark-btn-inspect" style="padding: 5px 12px; font-size: 11.5px;" onclick="window.researchSharkStock('${c.symbol}')">
                            ⚡ Research
                        </button>
                    </td>
                </tr>
            `;
        }).join('');

        container.innerHTML = `
            <table class="shark-table">
                <thead>
                    <tr>
                        <th>Company / Symbol</th>
                        <th>Shark Count</th>
                        <th>Combined Stake</th>
                        <th>Combined Value</th>
                        <th>Co-Invested Sharks</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    ${rowsHtml}
                </tbody>
            </table>
        `;
    }

    // ─── RENDER ALERTS LOG ─────────────────────────────────────────────────
    function renderSharkAlerts(alerts) {
        const container = document.getElementById('shark-alerts-container');
        if (!container) return;

        if (!alerts || alerts.length === 0) {
            container.innerHTML = `
                <div style="padding: 40px; text-align: center; color: var(--text-secondary, #64748b); font-size: 14px;">
                    No recent shark alert events recorded. Alerts trigger automatically upon new entries or >= +0.5% stake hikes as quarterly filings publish.
                </div>
            `;
            return;
        }

        function formatRelTime(dateStr) {
            if (!dateStr) return { rel: 'Recently', exact: '' };
            try {
                const d = new Date(dateStr.replace(' ', 'T'));
                if (isNaN(d.getTime())) return { rel: dateStr, exact: dateStr };
                const diffMs = new Date() - d;
                const diffSecs = Math.floor(diffMs / 1000);
                const diffMins = Math.floor(diffSecs / 60);
                const diffHours = Math.floor(diffMins / 60);
                const diffDays = Math.floor(diffHours / 24);

                let rel = '';
                if (diffSecs < 60) rel = 'Just now';
                else if (diffMins < 60) rel = `${diffMins}m ago`;
                else if (diffHours < 24) rel = `${diffHours}h ago`;
                else if (diffDays === 1) rel = 'Yesterday';
                else if (diffDays < 7) rel = `${diffDays}d ago`;
                else rel = d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });

                return { rel, exact: dateStr };
            } catch (e) {
                return { rel: dateStr, exact: dateStr };
            }
        }

        container.innerHTML = alerts.map(a => {
            const isNew = a.change_type === 'NEW_ENTRY';
            const badge = isNew 
                ? '<span class="shark-badge-new">🟢 NEW STAKE ENTRY</span>'
                : '<span class="shark-badge-hike">📈 AGGRESSIVE STAKE HIKE</span>';

            // Clean formatted human text
            let actionText = '';
            if (isNew) {
                actionText = `entered a brand new disclosed stake of <strong style="color: #f59e0b;">${a.stake_percent}%</strong> in <strong class="shark-stock-name" style="color: #38bdf8;">${escapeHtml(a.symbol)}</strong>`;
            } else {
                actionText = `aggressively increased stake by <strong style="color: #10b981;">+${a.change_percent}%</strong> to <strong style="color: #f59e0b;">${a.stake_percent}%</strong> in <strong class="shark-stock-name" style="color: #38bdf8;">${escapeHtml(a.symbol)}</strong>`;
            }

            // Extract approx value if present in message_text (supports Lakhs and Crores, ignores 0.0)
            let valStr = '';
            const valMatch = (a.message_text || '').match(/approx\s*(₹[0-9,.]+\s*(?:Cr|L))/i);
            if (valMatch && !valMatch[1].includes('₹0.0')) {
                valStr = valMatch[1];
            }

            const initials = (a.investor_name || '').split(' ').map(w => w[0]).filter(Boolean).slice(0, 2).join('').toUpperCase();
            const timeInfo = formatRelTime(a.sent_at);

            return `
                <div class="shark-alert-card">
                    <div class="shark-alert-main">
                        <div class="shark-alert-avatar">${initials}</div>
                        <div class="shark-alert-body">
                            <div class="shark-alert-header">
                                ${badge}
                                <strong class="shark-alert-investor">${escapeHtml(a.investor_name)}</strong>
                                <span class="shark-alert-stock-chip" onclick="window.researchSharkStock('${a.symbol}')" title="Click to analyze ${escapeHtml(a.symbol)}">
                                    ${escapeHtml(a.symbol)} ↗
                                </span>
                                ${valStr ? `<span class="shark-alert-val-pill">${valStr}</span>` : ''}
                            </div>
                            <div class="shark-alert-desc">
                                Superstar investor <strong>${escapeHtml(a.investor_name)}</strong> ${actionText}.
                            </div>
                        </div>
                    </div>
                    <div class="shark-alert-meta">
                        <div class="shark-alert-time-box">
                            <span class="shark-alert-time-label">⏱️ ALERT DISPATCHED</span>
                            <span class="shark-alert-time-rel" title="Server scan & alert trigger: ${escapeHtml(a.sent_at || '')}">
                                ${timeInfo.rel}
                            </span>
                            <span class="shark-alert-time-exact">${escapeHtml(timeInfo.exact)}</span>
                        </div>
                        <button class="shark-btn-research" onclick="window.researchSharkStock('${a.symbol}')">
                            ⚡ Research
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    }

    // ─── DEEP DIVE MODAL ───────────────────────────────────────────────────
    let currentModalInvestorId = null;

    function notifyShark(message, type = 'success') {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
            return;
        }
        if (typeof showToast === 'function') {
            showToast(message, type);
            return;
        }
        let container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            container.className = 'toast-container';
            container.style.cssText = 'position:fixed; top:20px; right:20px; z-index:9999999; display:flex; flex-direction:column; gap:8px;';
            document.body.appendChild(container);
        }
        const toast = document.createElement('div');
        toast.style.cssText = 'background: #0f172a; border: 1px solid #10b981; color: #f8fafc; padding: 12px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; box-shadow: 0 10px 25px rgba(0,0,0,0.5); font-family: Inter, sans-serif;';
        if (type === 'error') toast.style.borderColor = '#ef4444';
        if (type === 'info') toast.style.borderColor = '#38bdf8';
        toast.textContent = message;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    }

    window.openSharkPortfolioModal = async function (investorId) {
        currentModalInvestorId = investorId;
        let modal = document.getElementById('shark-portfolio-modal');
        if (!modal) {
            console.error('[SharkRadar] Modal container not found in DOM.');
            return;
        }

        // Guarantee modal is a direct child of document.body so no parent can clip or hide it
        if (modal.parentElement !== document.body) {
            document.body.appendChild(modal);
        }

        modal.style.display = 'flex';
        modal.style.zIndex = '1000000';
        const bodyEl = document.getElementById('shark-modal-body');
        if (bodyEl) {
            bodyEl.innerHTML = `
                <div style="padding: 60px; text-align: center; color: #f59e0b; font-size: 15px; font-weight: 700;">
                    Loading detailed portfolio filings...
                </div>
            `;
        }

        try {
            const res = await fetch(`/api/sharks/${investorId}`);
            const data = await res.json();
            if (data.status === 'success' && data.portfolio) {
                renderSharkModalContent(data.portfolio);
            } else {
                if (bodyEl) bodyEl.innerHTML = `<div style="padding: 40px; color: #ef4444;">Failed to load portfolio details: ${escapeHtml(data.detail || 'Unknown error')}</div>`;
            }
        } catch (err) {
            console.error('[SharkRadar] Error loading portfolio modal:', err);
            if (bodyEl) bodyEl.innerHTML = `<div style="padding: 40px; color: #ef4444;">Failed to load portfolio details.</div>`;
        }
    };

    function renderSharkModalContent(p) {
        const titleEl = document.getElementById('shark-modal-title');
        const bodyEl = document.getElementById('shark-modal-body');
        if (titleEl) titleEl.textContent = `${p.investor_name || 'Superstar'} Portfolio`;

        if (!bodyEl) return;

        const holdings = p.holdings || [];
        const rowsHtml = holdings.map(h => {
            let changeChip = '<span class="shark-sector">Unchanged</span>';
            if (h.change_type === 'NEW') {
                changeChip = '<span class="shark-pill-buy" style="font-weight: 800;">★ NEW ENTRY</span>';
            } else if (h.change_pct > 0) {
                changeChip = `<span class="shark-pill-buy">+${h.change_pct}%</span>`;
            } else if (h.change_pct < 0) {
                changeChip = `<span class="shark-pill-sell">${h.change_pct}%</span>`;
            }

            return `
                <tr>
                    <td>
                        <strong class="shark-stock-name" style="cursor: pointer;" onclick="window.researchSharkStock('${h.symbol}')" title="Click to analyze stock">
                            ${escapeHtml(h.stock_name)}
                        </strong>
                        <div class="shark-ticker-sym">${escapeHtml(h.symbol)}</div>
                    </td>
                    <td><strong class="shark-stock-name" style="font-family: monospace;">${h.holding_value_str}</strong></td>
                    <td class="shark-sector" style="font-family: monospace;">${(h.shares_count || 0).toLocaleString('en-IN')}</td>
                    <td><strong style="color: #f59e0b;">${h.latest_stake_pct}%</strong></td>
                    <td>${changeChip}</td>
                    <td class="shark-sector" style="font-size: 11px; max-width: 180px;">${escapeHtml(h.holder_name || '-')}</td>
                </tr>
            `;
        }).join('');

        bodyEl.innerHTML = `
            ${p.bio ? `
                <div class="shark-bio-box" style="padding: 12px 16px; border-radius: 6px; margin-bottom: 20px; font-size: 12.5px; line-height: 1.5;">
                    ${escapeHtml(p.bio)}
                </div>
            ` : ''}

            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; flex-wrap: wrap; gap: 10px;">
                <div class="shark-sector">
                    Total Disclosed Holdings: <strong class="shark-stock-name">${holdings.length} stocks</strong>
                </div>
                <div style="display: flex; gap: 10px;">
                    <button class="shark-btn-clone" style="padding: 6px 14px;" onclick="window.cloneSharkWatchlist('${p.investor_id}', '${escapeHtml(p.investor_name)}', this)">
                        📋 Clone as Watchlist
                    </button>
                    <button class="shark-btn-inspect" style="padding: 6px 14px;" onclick="window.refreshSharkPortfolio('${p.investor_id}')">
                        ↻ Refresh Filings
                    </button>
                </div>
            </div>

            <div class="shark-table-container" style="max-height: 480px; overflow-y: auto;">
                <table class="shark-table">
                    <thead>
                        <tr>
                            <th>Stock</th>
                            <th>Value</th>
                            <th>Quantity</th>
                            <th>Latest Stake</th>
                            <th>QoQ Change</th>
                            <th>Holding Entity / Alias</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rowsHtml || '<tr><td colspan="6" style="text-align: center; padding: 20px;">No public holdings listed.</td></tr>'}
                    </tbody>
                </table>
            </div>
        `;
    }

    window.closeSharkPortfolioModal = function () {
        const modal = document.getElementById('shark-portfolio-modal');
        if (modal) modal.style.display = 'none';
        currentModalInvestorId = null;
    };

    // ─── 1-CLICK CLONE TO WATCHLIST ────────────────────────────────────────
    window.cloneSharkWatchlist = async function (investorId, investorName, btnElement = null) {
        let origHtml = '';
        if (btnElement) {
            origHtml = btnElement.innerHTML;
            btnElement.innerHTML = '⏳ Cloning...';
            btnElement.disabled = true;
        }
        try {
            const res = await fetch(`/api/sharks/${investorId}/clone-watchlist`, { method: 'POST' });
            const data = await res.json();
            if (data.status === 'success') {
                const msg = `✓ Successfully cloned ${data.total_stocks} stocks into Watchlist: "${data.watchlist_name}"!`;
                notifyShark(msg, 'success');
                if (btnElement) {
                    btnElement.innerHTML = '✓ Cloned!';
                    btnElement.style.background = '#10b981';
                    btnElement.style.color = '#000';
                    btnElement.style.borderColor = '#10b981';
                    setTimeout(() => {
                        btnElement.innerHTML = origHtml;
                        btnElement.disabled = false;
                        btnElement.style.background = '';
                        btnElement.style.color = '';
                        btnElement.style.borderColor = '';
                    }, 3500);
                }

                // If user is on watchlist tab or watchlist functions exist, refresh them
                if (window.loadWatchlistRegistry) window.loadWatchlistRegistry();
                if (window.renderWatchlistItems) window.renderWatchlistItems();
            } else {
                const errMsg = data.detail || data.message || 'Failed to clone watchlist.';
                notifyShark(errMsg, 'error');
                if (btnElement) {
                    btnElement.innerHTML = origHtml;
                    btnElement.disabled = false;
                }
            }
        } catch (err) {
            console.error('[SharkRadar] Error cloning watchlist:', err);
            notifyShark('Error cloning watchlist: ' + (err.message || err), 'error');
            if (btnElement) {
                btnElement.innerHTML = origHtml;
                btnElement.disabled = false;
            }
        }
    };

    // ─── REFRESH SINGLE INVESTOR ───────────────────────────────────────────
    window.refreshSharkPortfolio = async function (investorId) {
        if (!investorId) investorId = currentModalInvestorId;
        if (!investorId) return;

        notifyShark('Refreshing latest filings...', 'info');
        try {
            const res = await fetch(`/api/sharks/${investorId}/refresh`, { method: 'POST' });
            const data = await res.json();
            if (data.status === 'success' && data.portfolio) {
                renderSharkModalContent(data.portfolio);
                notifyShark('✓ Latest filings refreshed successfully!', 'success');
            } else {
                notifyShark(data.detail || 'Failed to refresh filings.', 'error');
            }
        } catch (err) {
            console.error('[SharkRadar] Error refreshing portfolio:', err);
            notifyShark('Failed to refresh filings.', 'error');
        }
    };

    // ─── ACTION: JUMP TO STOCK RESEARCH TERMINAL ───────────────────────────
    window.researchSharkStock = function (symbol) {
        window.closeSharkPortfolioModal();
        if (window.switchTab) {
            window.switchTab('analyzer');
        }
        const searchInput = document.getElementById('desktop-global-search') || document.getElementById('ticker-input');
        if (searchInput) {
            searchInput.value = symbol;
            if (window.analyzeStock) {
                window.analyzeStock(symbol);
            } else {
                const form = searchInput.closest('form');
                if (form) form.dispatchEvent(new Event('submit'));
            }
        }
    };

    // ─── STOCK RESEARCH TAB INTEGRATION ("SMART MONEY BADGE") ──────────────
    window.fetchSharkStockPresence = async function (symbol) {
        if (!symbol) return;
        const cleanSym = symbol.replace('.NS', '').replace('.BO', '').trim().toUpperCase();
        const card = document.getElementById('shark-presence-card');
        const listEl = document.getElementById('shark-presence-list');
        const badgeEl = document.getElementById('shark-presence-count-badge');

        if (!card || !listEl) return;

        try {
            const res = await fetch(`/api/stocks/${cleanSym}/sharks`);
            const data = await res.json();

            if (data.status === 'success' && data.sharks && data.sharks.length > 0) {
                card.style.display = 'block';
                if (badgeEl) badgeEl.textContent = `${data.sharks.length} SHARK${data.sharks.length > 1 ? 'S' : ''}`;

                listEl.innerHTML = data.sharks.map(s => {
                    let chgText = '';
                    if (s.change_type === 'NEW') chgText = ' • <span style="color:#10b981; font-weight:700;">★ New Entry</span>';
                    else if (s.change_percent > 0) chgText = ` • <span style="color:#10b981; font-weight:700;">+${s.change_percent}%</span>`;
                    else if (s.change_percent < 0) chgText = ` • <span style="color:#ef4444; font-weight:700;">${s.change_percent}%</span>`;

                    return `
                        <div class="shark-presence-item" style="display: flex; justify-content: space-between; align-items: center; padding: 6px 10px; border-radius: 6px; margin-bottom: 4px;">
                            <div>
                                <strong class="shark-stock-name">${escapeHtml(s.investor_name)}</strong>
                                ${s.holding_entity && s.holding_entity !== s.investor_name ? `<span class="shark-sector" style="font-size: 11px;"> via ${escapeHtml(s.holding_entity)}</span>` : ''}
                            </div>
                            <div>
                                <span style="font-weight: 800; color: #f59e0b;">${s.holding_percent}%</span>
                                ${s.holding_value_cr > 0 ? `<span class="shark-ticker-sym" style="font-weight: 700;"> (₹${s.holding_value_cr} Cr)</span>` : ''}
                                ${chgText}
                            </div>
                        </div>
                    `;
                }).join('');
            } else {
                card.style.display = 'none';
            }
        } catch (err) {
            console.warn('[SharkRadar] Error checking shark presence for stock:', err);
            card.style.display = 'none';
        }
    };

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }
})();
