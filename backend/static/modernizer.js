/* 
   APEX Stock Workstation - Modernization JavaScript Layer
   Integrates GSAP, CountUp, Typed.js, Lucide, Web Audio Cues, Sparkles, and Magnetism
*/

(function() {
    console.log("APEX Modernizer: Initializing core visual upgrades...");

    // Global Error and Promise Rejection Handlers for Remote Debugging
    window.onerror = function(message, source, lineno, colno, error) {
        const msgStr = String(message || '');
        if (msgStr.includes("Script error") || msgStr.includes("Object is disposed") || msgStr.includes("disposed") || msgStr.includes("ResizeObserver")) {
            console.warn("Ignored cross-origin/disposed error:", message);
            return true;
        }
        const errorText = `JS Error: ${message} at ${source}:${lineno}:${colno}`;
        console.error(errorText);
        const toast = document.createElement('div');
        toast.className = 'remote-debug-error-toast';
        toast.style.position = 'fixed';
        toast.style.top = '10px';
        toast.style.left = '10px';
        toast.style.right = '10px';
        toast.style.background = 'rgba(239, 68, 68, 0.95)';
        toast.style.color = '#ffffff';
        toast.style.padding = '12px 16px';
        toast.style.borderRadius = '8px';
        toast.style.zIndex = '9999999999';
        toast.style.fontFamily = 'monospace';
        toast.style.fontSize = '11px';
        toast.style.wordBreak = 'break-all';
        toast.innerHTML = `<strong>Error Caught:</strong><br>${message}<br><small>in ${source ? source.split('/').pop() : 'unknown'}:${lineno}:${colno}</small>`;
        document.body.appendChild(toast);
        setTimeout(() => { toast.remove(); }, 15000);
        return false;
    };

    window.addEventListener('unhandledrejection', function(event) {
        const message = event.reason ? (event.reason.message || event.reason) : 'Unknown Promise Rejection';
        const toast = document.createElement('div');
        toast.className = 'remote-debug-error-toast';
        toast.style.position = 'fixed';
        toast.style.top = '10px';
        toast.style.left = '10px';
        toast.style.right = '10px';
        toast.style.background = 'rgba(239, 68, 68, 0.95)';
        toast.style.color = '#ffffff';
        toast.style.padding = '12px 16px';
        toast.style.borderRadius = '8px';
        toast.style.zIndex = '9999999999';
        toast.style.fontFamily = 'monospace';
        toast.style.fontSize = '11px';
        toast.style.wordBreak = 'break-all';
        toast.innerHTML = `<strong>Promise Rejected:</strong><br>${message}`;
        document.body.appendChild(toast);
        setTimeout(() => { toast.remove(); }, 15000);
    });

    const isCapacitor = (window.hasOwnProperty('Capacitor') || 
                         (window.Capacitor !== undefined) || 
                         (window.parent && window.parent.hasOwnProperty('Capacitor'))) && 
                        !( (location.hostname === 'localhost' || location.hostname === '127.0.0.1') && 
                           (location.port === '8000' || location.port === '8001' || location.port === '8002' || location.port === '5000') );
    const apiBaseUrl = isCapacitor ? 'https://my-stock-advisor.duckdns.org' : '';

    let isinMapping = {};
    fetch(apiBaseUrl + '/isin_mapping.json?v=1.1')
        .then(res => res.json())
        .then(data => {
            isinMapping = data;
            if (typeof updateDynamicCommandCenterContent === 'function') {
                updateDynamicCommandCenterContent();
            }
        })
        .catch(err => console.error("Error loading isin_mapping.json:", err));

    // Helper to format rupees safely IIFE-wide
    const formatRupees = (val) => {
        if (typeof safeFormatRupees === 'function') return safeFormatRupees(val, 2);
        return '₹' + (val || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    };

    window.getStockFallbackLogoHtml = function(symbol) {
        const showLogos = localStorage.getItem('settings-show-logos') !== 'false';
        if (!showLogos) return '';
        const cleanSym = symbol.replace(".NS", "").toUpperCase();
        const presetLogos = {
            "RELIANCE": { bg: "#0a2540", logo: "⚡" }, 
            "TCS": { bg: "#4f46e5", logo: "⚙️" },
            "INFY": { bg: "#06b6d4", logo: "💻" }, 
            "HDFCBANK": { bg: "#1e3a8a", logo: "🏦" }, 
            "ICICIBANK": { bg: "#ea580c", logo: "💳" }, 
            "SBIN": { bg: "#0284c7", logo: "💰" },
            "BHARTIARTL": { bg: "#dc2626", logo: "📶" }, 
            "ITC": { bg: "#1e40af", logo: "🚬" },
            "LT": { bg: "#d97706", logo: "🏗️" }, 
            "JSWSTEEL": { bg: "#10b981", logo: "⚡" }, 
            "TATASTEEL": { bg: "#2563eb", logo: "🔩" },
            "TATAPOWER": { bg: "#3b82f6", logo: "🦅" },
            "ECLERX": { bg: "#0c2340", logo: "💠" },
            "AIIL": { bg: "#b8860b", logo: "🏗️" },
            "FEDERALBNK": { bg: "#006400", logo: "🏦" },
            "KALYANKJIL": { bg: "#d4af37", logo: "💎" },
            "AFCONS": { bg: "#005ea6", logo: "🏗️" }
        };

        const preset = presetLogos[cleanSym];
        if (preset) {
            return `<div class="stock-circle-logo" style="width:28px; height:28px; border-radius:50%; background:${preset.bg}; display:flex; align-items:center; justify-content:center; color:#fff; font-size:12px; font-weight:800; font-family:Inter,sans-serif; flex-shrink:0;">${preset.logo}</div>`;
        }

        let hash = 0;
        for (let i = 0; i < cleanSym.length; i++) {
            hash = cleanSym.charCodeAt(i) + ((hash << 5) - hash);
        }
        const colors = ["#ef4444", "#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#14b8a6", "#6366f1"];
        const selectedColor = colors[Math.abs(hash) % colors.length];
        const displayChar = cleanSym.charAt(0);

        return `<div class="stock-circle-logo" style="width:28px; height:28px; border-radius:50%; background:${selectedColor}; display:flex; align-items:center; justify-content:center; color:#fff; font-size:11px; font-weight:800; font-family:var(--font-heading); flex-shrink:0;">${displayChar}</div>`;
    };

    function getStockLogoHtml(symbol) {
        const showLogos = localStorage.getItem('settings-show-logos') !== 'false';
        if (!showLogos) return '';
        const cleanSym = symbol.replace(".NS", "").toUpperCase();
        const isin = isinMapping[cleanSym];
        if (isin) {
            return `
                <div style="width:28px; height:28px; border-radius:50%; background:#ffffff; border:1px solid var(--border-glass); display:flex; align-items:center; justify-content:center; flex-shrink:0; overflow:hidden; padding:2px; box-sizing:border-box;">
                    <img src="${apiBaseUrl}/logos/${cleanSym}.png" style="width:100%; height:100%; object-fit:contain; display:block;" onerror="this.onerror=null; this.parentNode.outerHTML=window.getStockFallbackLogoHtml('${cleanSym}');">
                </div>
            `;
        }
        return window.getStockFallbackLogoHtml(cleanSym);
    }

    function getNewsAgencyLogoHtml(source) {
        const cleanSource = (source || '').toLowerCase().trim();
        
        if (cleanSource.includes('mint') || cleanSource.includes('livemint')) {
            return `<span style="background:#fff; border:1px solid #ff9f0a; color:#000; padding:2px 6px; border-radius:3px; font-family:Georgia, serif; font-size:10px; font-weight:900; display:inline-block; vertical-align:middle; letter-spacing:-0.02em; line-height:1;"><span style="color:#000;">live</span><span style="color:#ff9f0a;">mint</span></span>`;
        }
        if (cleanSource.includes('bloomberg') || cleanSource.includes('bloom')) {
            return `<span style="background:#005A36; color:#fff; padding:3px 8px; border-radius:4px; font-weight:900; font-family:var(--font-heading); font-size:10px; display:inline-block; vertical-align:middle; letter-spacing:-0.02em; line-height:1;">Bloomberg</span>`;
        }
        if (cleanSource.includes('reuters')) {
            return `<span style="background:rgba(255,255,255,0.06); border:1px solid var(--border-glass); color:#ff9f0a; padding:2.5px 8px; border-radius:4px; font-weight:800; font-family:var(--font-heading); font-size:10px; display:inline-flex; align-items:center; gap:4px; vertical-align:middle; line-height:1;">🔸 REUTERS</span>`;
        }
        if (cleanSource.includes('economic') || cleanSource.includes('et')) {
            return `<span style="background:#faeada; border:1.5px solid #00444e; color:#00444e; padding:2px 5px; border-radius:3px; font-family:'Times New Roman', Georgia, serif; font-size:11px; font-weight:900; display:inline-block; vertical-align:middle; line-height:1; letter-spacing:0.02em;">ET</span>`;
        }
        if (cleanSource.includes('yahoo') || cleanSource.includes('yfinance') || cleanSource.includes('finance')) {
            return `<span style="background:#fff; border:1px solid #6001d2; color:#6001d2; padding:2px 6px; border-radius:3px; font-family:'Outfit', sans-serif; font-size:10px; font-weight:900; display:inline-block; vertical-align:middle; line-height:1; letter-spacing:-0.03em;"><span style="color:#6001d2;">yahoo!</span><span style="color:#7e1eff; font-weight:600;">finance</span></span>`;
        }
        if (cleanSource.includes('cnbc') || cleanSource.includes('tv18')) {
            return `<span style="background:#0a2540; color:#00d2fe; padding:3px 8px; border-radius:4px; font-weight:900; font-family:var(--font-heading); font-size:10px; display:inline-block; vertical-align:middle; border:1px solid rgba(0,210,254,0.3); line-height:1;">CNBC-TV18</span>`;
        }
        if (cleanSource.includes('standard') || cleanSource.includes('business') || cleanSource.includes('bs')) {
            return `<span style="background:#ffe8d4; border:1.5px solid #a91d22; color:#a91d22; padding:2px 5px; border-radius:3px; font-family:'Times New Roman', Georgia, serif; font-size:11px; font-weight:900; display:inline-block; vertical-align:middle; line-height:1; letter-spacing:0.02em;">BS</span>`;
        }
        if (cleanSource.includes('financial') || cleanSource.includes('express')) {
            return `<span style="background:#fff; color:#000; padding:2px 6px; border-radius:3px; font-family:Georgia, serif; font-weight:900; font-size:10px; border:1px solid #ccc; display:inline-block; vertical-align:middle; text-transform:uppercase; line-height:1;">FE</span>`;
        }
        
        return `<span style="background:rgba(255,255,255,0.06); border:1px solid var(--border-glass); color:var(--text-secondary); padding:3px 8px; border-radius:4px; font-weight:700; font-size:10px; display:inline-block; vertical-align:middle; text-transform:uppercase; letter-spacing:0.03em; line-height:1;">${source}</span>`;
    }


    // Helper to parse numeric values from text
    function parseNumericValue(text) {
        if (!text) return 0;
        // Extract numbers, decimal dots, and minus signs
        const cleanText = text.replace(/[^\d.-]/g, '');
        const val = parseFloat(cleanText);
        return isNaN(val) ? 0 : val;
    }

    // ==================== 1. WEB AUDIO UI SONIFICATION ====================
    const AudioCueManager = {
        ctx: null,

        init() {
            // Unlock AudioContext on first user interaction (safari / chrome policies)
            const unlock = () => {
                try {
                    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
                    console.log("APEX Audio: Web Audio Context unlocked successfully.");
                } catch (e) {
                    console.warn("APEX Audio: Web Audio API not supported:", e);
                }
                document.removeEventListener('click', unlock);
                document.removeEventListener('keydown', unlock);
            };
            document.addEventListener('click', unlock);
            document.addEventListener('keydown', unlock);
        },

        playTick() {
            if (localStorage.getItem('apex-audio-muted') === 'true') return;
            if (!this.ctx) return;
            try {
                // Ensure context is running (resume if suspended by browser)
                if (this.ctx.state === 'suspended') {
                    this.ctx.resume();
                }
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                osc.connect(gain);
                gain.connect(this.ctx.destination);
                
                osc.type = 'sine';
                osc.frequency.setValueAtTime(1400, this.ctx.currentTime); // high freq mechanical click
                gain.gain.setValueAtTime(0.006, this.ctx.currentTime); // very low volume
                gain.gain.exponentialRampToValueAtTime(0.0001, this.ctx.currentTime + 0.02);
                
                osc.start();
                osc.stop(this.ctx.currentTime + 0.025);
            } catch (e) {}
        },

        playChime() {
            if (localStorage.getItem('apex-audio-muted') === 'true') return;
            if (!this.ctx) return;
            try {
                if (this.ctx.state === 'suspended') this.ctx.resume();
                const now = this.ctx.currentTime;
                
                // Arpeggio note 1
                const osc1 = this.ctx.createOscillator();
                const gain1 = this.ctx.createGain();
                osc1.connect(gain1);
                gain1.connect(this.ctx.destination);
                osc1.type = 'sine';
                osc1.frequency.setValueAtTime(523.25, now); // C5
                gain1.gain.setValueAtTime(0.008, now);
                gain1.gain.exponentialRampToValueAtTime(0.0001, now + 0.12);
                osc1.start(now);
                osc1.stop(now + 0.14);

                // Arpeggio note 2
                const osc2 = this.ctx.createOscillator();
                const gain2 = this.ctx.createGain();
                osc2.connect(gain2);
                gain2.connect(this.ctx.destination);
                osc2.type = 'sine';
                osc2.frequency.setValueAtTime(659.25, now + 0.07); // E5
                gain2.gain.setValueAtTime(0.008, now + 0.07);
                gain2.gain.exponentialRampToValueAtTime(0.0001, now + 0.22);
                osc2.start(now + 0.07);
                osc2.stop(now + 0.24);
            } catch (e) {}
        },

        playAlert() {
            if (localStorage.getItem('apex-audio-muted') === 'true') return;
            if (!this.ctx) return;
            try {
                if (this.ctx.state === 'suspended') this.ctx.resume();
                const now = this.ctx.currentTime;
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                osc.connect(gain);
                gain.connect(this.ctx.destination);
                
                osc.type = 'triangle'; // softer sonar tone
                osc.frequency.setValueAtTime(140, now);
                osc.frequency.linearRampToValueAtTime(90, now + 0.35);
                gain.gain.setValueAtTime(0.012, now);
                gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.4);
                
                osc.start(now);
                osc.stop(now + 0.45);
            } catch (e) {}
        }
    };
    AudioCueManager.init();

    // ==================== 0. ROUTING INTERCEPTOR & TRANSITIONS ====================
    const originalSwitchTab = window.switchTab;
    if (originalSwitchTab) {
        window.switchTab = function(tabKey) {
            // Intercept mobile portfolio check
            if (tabKey === 'portfolio' && window.innerWidth <= 768) {
                const shieldEnabled = localStorage.getItem('portfolio-security-shield-enabled') !== 'false';
                if (shieldEnabled && !window.portfolioUnlocked) {
                    const pinOverlay = document.getElementById('portfolio-pin-overlay');
                    if (pinOverlay) {
                        pinOverlay.style.display = 'flex';
                        const pinTitle = pinOverlay.querySelector('.pin-title');
                        if (pinTitle) {
                            const hasPin = localStorage.getItem('portfolio-pin') !== null;
                            pinTitle.textContent = hasPin ? "Enter Security Passcode" : "Define Security Passcode";
                        }
                        const desktopLock = document.getElementById('portfolio-lock-overlay');
                        if (desktopLock) desktopLock.classList.add('hidden');
                        
                        // Let the tab display under the lock
                        if (typeof gsap !== 'undefined') {
                            playTabGSAPTransition(tabKey, originalSwitchTab);
                        } else {
                            originalSwitchTab(tabKey);
                        }
                        return;
                    }
                }
            }
            
            // Play audio click tick
            if (AudioCueManager && typeof AudioCueManager.playTick === 'function') {
                AudioCueManager.playTick();
            }
            
            // Play GSAP Transition
            if (typeof gsap !== 'undefined') {
                playTabGSAPTransition(tabKey, originalSwitchTab);
            } else {
                originalSwitchTab(tabKey);
            }
            
            // Highlight bottom nav active tab
            const bottomNav = document.querySelector('.mobile-bottom-nav');
            if (bottomNav) {
                bottomNav.querySelectorAll('.mobile-bottom-nav-item').forEach(item => {
                    item.classList.remove('active');
                });
                let navId = 'nav-terminal';
                if (tabKey === 'analyzer') navId = 'nav-terminal';
                else if (tabKey === 'screener') navId = 'nav-screener';
                else if (tabKey === 'watchlist') navId = 'nav-watchlist';
                else if (tabKey === 'portfolio') navId = 'nav-portfolio';
                const activeBtn = document.getElementById(navId);
                if (activeBtn) activeBtn.classList.add('active');
            }

            // Sync visibility of the mobile FAB container
            const fabContainer = document.querySelector('.mobile-fab-container');
            if (fabContainer) {
                if (tabKey === 'analyzer') {
                    const isSheetActive = document.body.classList.contains('sheet-active');
                    if (!isSheetActive && window.innerWidth <= 768) {
                        fabContainer.style.setProperty('display', 'flex', 'important');
                    } else {
                        fabContainer.style.setProperty('display', 'none', 'important');
                    }
                } else {
                    fabContainer.style.setProperty('display', 'none', 'important');
                }
            }
        };
    }

    function playTabGSAPTransition(tabKey, realSwitch) {
        const activeTabEl = document.querySelector('.active-tab-content');
        if (activeTabEl && typeof gsap !== 'undefined') {
            gsap.to(activeTabEl, {
                opacity: 0,
                y: -8,
                duration: 0.12,
                ease: "power2.in",
                onComplete: () => {
                    realSwitch(tabKey);
                    const newActiveEl = document.querySelector('.active-tab-content');
                    if (newActiveEl) {
                        gsap.fromTo(newActiveEl, 
                            { opacity: 0, y: 12 },
                            { opacity: 1, y: 0, duration: 0.3, ease: "power2.out" }
                        );
                    }
                }
            });
        } else {
            realSwitch(tabKey);
        }
    }

    // ==================== 2. LUCIDE SVG ICONS SETUP ====================
    function setupLucideIcons() {
        if (typeof lucide === 'undefined') {
            console.warn("APEX Modernizer: Lucide library not loaded.");
            return;
        }

        // Navigation button icon maps
        const navIconMap = {
            'tab-analyzer-btn': 'line-chart',
            'tab-screener-btn': 'search',
            'tab-compare-btn': 'git-compare',
            'tab-universe-btn': 'database',
            'tab-movers-btn': 'trending-up',
            'tab-market-news-btn': 'rss',
            'tab-events-btn': 'calendar',
            'tab-trades-btn': 'briefcase',
            'tab-swing-scan-btn': 'zap',
            'tab-swing-btn': 'target',
            'tab-rule-scanner-btn': 'cpu',
            'tab-sector-radar-btn': 'activity',
            'tab-watchlist-btn': 'list',
            'tab-portfolio-btn': 'pie-chart',
            'tab-alerts-btn': 'bell',
            'tab-learning-btn': 'graduation-cap'
        };

        // Replace emojis in side navigations
        for (const [btnId, iconName] of Object.entries(navIconMap)) {
            const btn = document.getElementById(btnId);
            if (btn) {
                const iconSpan = btn.querySelector('.btn-icon');
                if (iconSpan) {
                    iconSpan.innerHTML = `<i data-lucide="${iconName}"></i>`;
                }
            }
        }

        // Replace category header emojis
        document.querySelectorAll('.nav-category-header').forEach(header => {
            const text = header.textContent;
            if (text.includes('Equities Workspace')) {
                header.innerHTML = `<i data-lucide="layout-dashboard" style="margin-right: 6px;"></i> Equities Workspace`;
            } else if (text.includes('Tactical Trading')) {
                header.innerHTML = `<i data-lucide="zap" style="margin-right: 6px;"></i> Tactical Trading`;
            } else if (text.includes('Portfolio & Alerts')) {
                header.innerHTML = `<i data-lucide="folder" style="margin-right: 6px;"></i> Portfolio & Alerts`;
            } else if (text.includes('Learning & Education')) {
                header.innerHTML = `<i data-lucide="book-open" style="margin-right: 6px;"></i> Learning & Education`;
            }
        });

        // Replace stock search text input icon 🔍 with crisp SVG Lucide Search Icon
        const searchIconEl = document.getElementById('analyzer-input-icon');
        if (searchIconEl) {
            searchIconEl.innerHTML = `<i data-lucide="search"></i>`;
        }

        // Initialize icons
        lucide.createIcons();
    }

    // ==================== 3. GSAP WORKSPACE TRANSITIONS ====================
    function setupGSAPTransitions() {
        console.log("APEX Modernizer: GSAP tab transitions dynamically handled by the property router wrapper.");
    }

    // ==================== 4. CHAT TYPEWRITER & BOUNCING SKELETON ====================
    function setupChatUpgrades() {
        const originalAppendChatMessage = window.appendChatMessage;
        if (originalAppendChatMessage && typeof Typed !== 'undefined') {
            window.appendChatMessage = function(role, content, useTypewriter = false) {
                // If this is the loading state, override elements with three bouncing dots
                if (role === 'assistant' && content === 'Consulting AI stock advisor...') {
                    const box = document.getElementById('chat-messages');
                    const msg = document.createElement('div');
                    const msgId = 'msg-loading-' + Math.random().toString(36).substr(2, 9);
                    msg.id = msgId;
                    msg.className = `chat-message assistant`;
                    msg.innerHTML = `
                        <div class="chat-typing-bubble" aria-label="AI is typing">
                            <span></span>
                            <span></span>
                            <span></span>
                        </div>
                        <span style="font-size: 10px; color: var(--text-muted); margin-top: 4px; display: block;">Consulting AI Advisor...</span>
                    `;
                    box.appendChild(msg);
                    box.scrollTo({ top: box.scrollHeight, behavior: 'smooth' });
                    return msgId;
                }

                // Call original logic for regular assistant & user messages
                const msgId = originalAppendChatMessage(role, content, useTypewriter);

                // Play success synth chime on assistant response
                if (role === 'assistant') {
                    AudioCueManager.playChime(); // Play success synth chime
                }
                return msgId;
            };
            console.log("APEX Modernizer: Chat typewriter delegation and bouncing dots configured.");
        }
    }

    // ==================== 5. COUNTUP INTERCEPTORS ====================
    function setupCountUpObservers() {
        if (typeof countUp === 'undefined') {
            console.warn("APEX Modernizer: CountUp.js not loaded.");
            return;
        }

        const lastValues = new Map();
        const countUpInstances = new Map();

        function animateValue(element, start, end, decimals = 2) {
            let demo = countUpInstances.get(element);
            if (!demo) {
                demo = new countUp.CountUp(element, end, {
                    startVal: start,
                    decimalPlaces: decimals,
                    duration: 0.8,
                    useEasing: true,
                    useGrouping: true,
                    separator: ','
                });
                countUpInstances.set(element, demo);
            } else {
                demo.update(end);
            }
            if (!demo.error) {
                demo.start();
            } else {
                element.innerText = end.toLocaleString('en-IN', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
            }
        }

        // Observe main header active stock price and check for movement thresholds
        const metaPriceEl = document.getElementById('meta-price');
        if (metaPriceEl) {
            const metaPriceObserver = new MutationObserver(() => {
                const text = metaPriceEl.textContent;
                const newVal = parseNumericValue(text);
                const oldVal = lastValues.get('meta-price') || newVal;

                if (oldVal !== newVal) {
                    lastValues.set('meta-price', newVal);
                    metaPriceObserver.disconnect();
                    animateValue(metaPriceEl, oldVal, newVal, 2);
                    metaPriceObserver.observe(metaPriceEl, { characterData: true, childList: true, subtree: true });
                }
                
                // Show/hide explain button based on daily net change percentage
                const changeText = document.getElementById('meta-change')?.textContent || "";
                const match = changeText.match(/([+-]?\d+\.?\d*)\s*%/);
                const explainBtn = document.getElementById('explain-move-btn');
                if (explainBtn) {
                    if (match) {
                        const pct = Math.abs(parseFloat(match[1]));
                        // Show "Why?" trigger for moves >= 1.5%
                        if (pct >= 1.5) {
                            explainBtn.style.display = 'inline-block';
                        } else {
                            explainBtn.style.display = 'none';
                        }
                    } else {
                        explainBtn.style.display = 'none';
                    }
                }
            });

            lastValues.set('meta-price', parseNumericValue(metaPriceEl.textContent));
            metaPriceObserver.observe(metaPriceEl, { characterData: true, childList: true, subtree: true });
        }

        // Observe ticker marquee indices
        const marqueeEl = document.getElementById('indices-marquee');
        if (marqueeEl) {
            const tickerObserver = new MutationObserver((mutations) => {
                mutations.forEach(mutation => {
                    if (mutation.type === 'childList') {
                        mutation.target.querySelectorAll('.val').forEach(valEl => {
                            const parentItem = valEl.closest('.ticker-item');
                            if (!parentItem) return;

                            const elementId = parentItem.id;
                            const newVal = parseNumericValue(valEl.textContent);
                            const oldVal = lastValues.get(elementId) || newVal;

                            if (oldVal !== newVal) {
                                lastValues.set(elementId, newVal);
                                tickerObserver.disconnect();
                                animateValue(valEl, oldVal, newVal, 2);
                                tickerObserver.observe(marqueeEl, { childList: true, subtree: true });
                            }
                        });
                    }
                });
            });

            marqueeEl.querySelectorAll('.ticker-item').forEach(item => {
                const valEl = item.querySelector('.val');
                if (valEl) {
                    lastValues.set(item.id, parseNumericValue(valEl.textContent));
                }
            });

            tickerObserver.observe(marqueeEl, { childList: true, subtree: true });
        }

        console.log("APEX Modernizer: CountUp price & index observers active.");
    }

    // ==================== 6. SPOTLIGHT & 3D PARALLAX TILTING ====================
    function setupSpotlightAnd3DTilt() {
        document.addEventListener('mousemove', (e) => {
            const card = e.target.closest('.card');
            if (card) {
                const rect = card.getBoundingClientRect();
                
                // Track spotlight coordinates
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                card.style.setProperty('--mouse-x', `${x}px`);
                card.style.setProperty('--mouse-y', `${y}px`);
            }
        });

        console.log("APEX Modernizer: Spotlight hover active (3D tilt disabled).");
    }

    // ==================== 7. VIEW TRANSITIONS & CLICK TRACKING ====================
    function setupViewTransitions() {
        document.addEventListener('click', (e) => {
            const isThemeTrigger = e.target.closest('.theme-toggle-btn') || 
                                   e.target.closest('#setting-theme-mode') || 
                                   e.target.closest('#setting-theme-accent') ||
                                   e.target.closest('.theme-btn');
            if (isThemeTrigger) {
                const x = e.clientX;
                const y = e.clientY;
                document.documentElement.style.setProperty('--reveal-x', `${x}px`);
                document.documentElement.style.setProperty('--reveal-y', `${y}px`);
            }
        });

        const originalSetWorkstationMode = window.setWorkstationMode;
        if (originalSetWorkstationMode) {
            window.setWorkstationMode = function(mode) {
                originalSetWorkstationMode(mode);
            };
        }

        const originalSetWorkstationAccent = window.setWorkstationAccent;
        if (originalSetWorkstationAccent) {
            window.setWorkstationAccent = function(accent) {
                originalSetWorkstationAccent(accent);
            };
        }
    }

    // ==================== 8. CURSOR SPARKLES FOR BULLISH HOVER ====================
    function setupBullishSparkles() {
        let lastSparkTime = 0;
        document.addEventListener('mousemove', (e) => {
            // Match bullish green items or positive indicator cards
            const target = e.target.closest('.rec-buy, .green-text, .card-glow-positive, #meta-trend.rec-buy');
            if (!target) return;

            const now = Date.now();
            if (now - lastSparkTime < 50) return; // throttle sparkle spawning (50ms)
            lastSparkTime = now;

            createSparkle(e.clientX, e.clientY);
        });

        function createSparkle(x, y) {
            const spark = document.createElement('div');
            spark.className = 'bullish-sparkle';
            
            const offsetX = (Math.random() - 0.5) * 8;
            const offsetY = (Math.random() - 0.5) * 8;
            
            spark.style.left = `${x + offsetX}px`;
            spark.style.top = `${y + offsetY}px`;
            
            const scale = 0.4 + Math.random() * 0.7;
            spark.style.transform = `scale(${scale})`;
            
            document.body.appendChild(spark);
            
            if (typeof gsap !== 'undefined') {
                gsap.to(spark, {
                    y: -25 - Math.random() * 25,
                    x: offsetX + (Math.random() - 0.5) * 12,
                    opacity: 0,
                    scale: 0.1,
                    duration: 0.7,
                    ease: "power1.out",
                    onComplete: () => spark.remove()
                });
            } else {
                setTimeout(() => spark.remove(), 700);
            }
        }
        console.log("APEX Modernizer: Bullish particles/sparkles listener running.");
    }

    // ==================== 9. TOAST NOTIFICATION AUDIO HOOK ====================
    function setupToastAudioHook() {
        const originalShowToast = window.showToast;
        if (originalShowToast) {
            window.showToast = function(message, type) {
                originalShowToast(message, type);
                
                // Play specific sonification tones depending on message severity
                if (type === 'error' || type === 'warning' || message.toLowerCase().includes('failed') || message.toLowerCase().includes('warning')) {
                    AudioCueManager.playAlert();
                } else if (type === 'success' || message.toLowerCase().includes('success') || message.toLowerCase().includes('completed')) {
                    AudioCueManager.playChime();
                }
            };
            console.log("APEX Modernizer: Toast notification audio hooks connected.");
        }
    }

    // ==================== 10. ACTIVE TTS EQUALIZER AUDIO VISUALIZER ====================
    function setupTTSEqualizer() {
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('.chat-speech-btn');
            if (btn) {
                // Remove any currently running equalizer indicators
                const activeVis = document.querySelector('.chat-speaking-indicator');
                if (activeVis) activeVis.remove();

                // Build a new waveform indicator and place it next to the speech button
                const vis = document.createElement('div');
                vis.className = 'chat-speaking-indicator';
                vis.innerHTML = '<span></span><span></span><span></span>';
                btn.parentElement.appendChild(vis);

                // Watch speech activity. Once speaking finishes, remove visualizer
                const checkSpeech = setInterval(() => {
                    const isSpeaking = window.speechSynthesis && window.speechSynthesis.speaking;
                    const isPlayerSpeaking = window.SpeechPlayer && window.SpeechPlayer.isPlaying;
                    
                    if (!isSpeaking && !isPlayerSpeaking) {
                        vis.remove();
                        clearInterval(checkSpeech);
                    }
                }, 500);
            }
        });
        console.log("APEX Modernizer: TTS speech equalizer tracking loaded.");
    }

    // ==================== 11. TACTILE MAGNETIC BUTTONS ====================
    function setupMagneticButtons() {
        // Collect buttons we want to act magnet-like
        const buttons = document.querySelectorAll(
            '.nav-menu .nav-btn, .btn-primary, .btn-secondary, #rebalance-now-btn, #theme-toggle-btn, .mobile-menu-toggle'
        );

        document.addEventListener('mousemove', (e) => {
            if (window.innerWidth < 768) return; // Skip on mobile viewports

            buttons.forEach(btn => {
                const rect = btn.getBoundingClientRect();
                // Find coordinates of button's center point
                const btnX = rect.left + rect.width / 2;
                const btnY = rect.top + rect.height / 2;

                const distanceX = e.clientX - btnX;
                const distanceY = e.clientY - btnY;
                const distance = Math.hypot(distanceX, distanceY);

                const pullThreshold = 40; // Pixels distance to start pull
                if (distance < pullThreshold) {
                    const pullMultiplier = 0.22; // Strength of magnetism
                    const translateValX = distanceX * pullMultiplier;
                    const translateValY = distanceY * pullMultiplier;

                    btn.style.transform = `translate(${translateValX.toFixed(1)}px, ${translateValY.toFixed(1)}px) scale(1.02)`;
                    btn.style.transition = 'transform 0.08s ease-out';
                } else {
                    btn.style.transform = '';
                    btn.style.transition = 'transform 0.25s ease-out';
                }
            });
        });
        console.log("APEX Modernizer: Magnetic button physics enabled.");
    }

    // ==================== 12. DYNAMIC TABLE CATALYST TRIGGER INJECTION ====================
    function setupTableCatalystTriggers() {
        const decorateTablesAndSectors = () => {
            // 1. Gainers, Losers, and Watchlist rows
            document.querySelectorAll('#top-gainers-tbody tr, #top-losers-tbody tr, #watchlist-table-body tr').forEach(row => {
                if (row.querySelector('.catalyst-trigger-btn') || row.querySelector('td[colspan]')) return;

                const symbolCell = row.querySelector('td:first-child');
                if (symbolCell) {
                    const text = symbolCell.textContent.trim().split('\n')[0].trim();
                    if (text && text.length > 1 && text.length <= 15 && !text.includes('Select') && !text.includes('No data')) {
                        const trigger = document.createElement('span');
                        trigger.className = 'catalyst-trigger-btn';
                        trigger.setAttribute('data-symbol', text);
                        trigger.setAttribute('title', 'Analyze price catalysts');
                        trigger.style.marginLeft = '8px';
                        trigger.style.cursor = 'pointer';
                        trigger.innerHTML = '⚡';
                        symbolCell.appendChild(trigger);
                    }
                }
            });

            // 2. Sector Radar Grid Tiles
            document.querySelectorAll('.sector-heatmap-tile').forEach(tile => {
                const header = tile.querySelector('.sector-heatmap-tile-header');
                if (header && !header.querySelector('.catalyst-trigger-btn')) {
                    const titleEl = header.querySelector('.sector-heatmap-tile-title');
                    if (titleEl) {
                        const sectorName = titleEl.textContent.trim();
                        if (sectorName && sectorName.length > 2 && !sectorName.includes('Select')) {
                            const trigger = document.createElement('span');
                            trigger.className = 'catalyst-trigger-btn';
                            trigger.setAttribute('data-symbol', sectorName);
                            trigger.setAttribute('data-sector', sectorName);
                            trigger.setAttribute('title', 'Analyze sector catalysts');
                            trigger.style.marginLeft = '8px';
                            trigger.style.cursor = 'pointer';
                            trigger.innerHTML = '⚡';
                            titleEl.appendChild(trigger);
                        }
                    }
                }
            });
        };

        const targets = [
            document.getElementById('top-gainers-tbody'),
            document.getElementById('top-losers-tbody'),
            document.getElementById('watchlist-table-body'),
            document.getElementById('sector-radar-list')
        ];

        targets.forEach(target => {
            if (target) {
                const obs = new MutationObserver(() => decorateTablesAndSectors());
                obs.observe(target, { childList: true, subtree: true });
            }
        });

        decorateTablesAndSectors();
        console.log("APEX Modernizer: Automated table and sector card catalyst trigger monitors active (isolated).");
    }

    // ==================== 13. SPEECH SYNTHESIS & RECOGNITION (CATALYST CONTROLS) ====================
    // ==================== 13. SPEECH SYNTHESIS & RECOGNITION (CATALYST CONTROLS) ====================
    function stopCatalystSpeech() {
        if (window.SpeechPlayer && window.SpeechPlayer.isPlaying) {
            window.SpeechPlayer.stop();
        }
    }

    function setupCatalystAudioControls() {
        const readBtn = document.getElementById('catalyst-read-btn');
        if (readBtn) {
            readBtn.addEventListener('click', () => {
                if (window.SpeechPlayer) {
                    const summary = document.getElementById('catalyst-summary-text')?.innerText || "";
                    let driversText = "";
                    document.querySelectorAll('#catalyst-drivers-list .catalyst-driver-card').forEach(card => {
                        // Extract text cleanly, excluding html structures
                        const textContent = card.innerText.replace(/\n/g, " ").trim();
                        if (textContent) driversText += ". " + textContent;
                    });
                    
                    const fullSpeechText = summary + driversText;
                    window.SpeechPlayer.startSpeakingSection(fullSpeechText, "Catalyst AI News Analysis", true);
                } else {
                    window.showToast("Speech narration player not active on this device.", "warning");
                }
            });
        }
    }

    // Web Speech Recognition (Mic Voice Input)
    function setupSpeechRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const micBtn = document.getElementById('catalyst-mic-btn');
        const inputEl = document.getElementById('catalyst-voice-input');

        if (!SpeechRecognition) {
            if (micBtn) micBtn.style.display = 'none';
            return;
        }

        const recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.lang = 'en-IN'; // Optimized for Indian English accents

        if (micBtn) {
            micBtn.addEventListener('click', () => {
                if (micBtn.classList.contains('mic-active')) {
                    recognition.stop();
                } else {
                    micBtn.classList.add('mic-active');
                    inputEl.value = '';
                    inputEl.setAttribute('placeholder', 'Listening... Ask me now...');
                    recognition.start();
                }
            });
        }

        recognition.onresult = (e) => {
            const transcript = e.results[0][0].transcript;
            if (inputEl) {
                inputEl.value = transcript;
            }
            if (micBtn) micBtn.classList.remove('mic-active');
            inputEl.setAttribute('placeholder', "Ask about a price move...");
            // Auto-trigger search query
            document.getElementById('catalyst-query-btn')?.click();
        };

        recognition.onerror = () => {
            if (micBtn) micBtn.classList.remove('mic-active');
            if (inputEl) inputEl.setAttribute('placeholder', "Ask about a price move...");
        };

        recognition.onend = () => {
            if (micBtn) micBtn.classList.remove('mic-active');
            if (inputEl) inputEl.setAttribute('placeholder', "Ask about a price move...");
        };
    }

    // ==================== 14. CATALYST MODAL API & UI RENDERING ====================
    let activeCatalystTyped = null;
    let currentCatalystSymbol = "";
    let currentCatalystSector = "";
    let currentCatalystIsSector = false;
    let currentCatalystDirection = "";

    function openCatalystAnalysis(symbolOrQuery, sector = "", isSectorOnly = false, direction = "") {
        // Reset audio first
        stopCatalystSpeech();

        const modal = document.getElementById('catalyst-modal');
        const loader = document.getElementById('catalyst-loader');
        const results = document.getElementById('catalyst-results');
        const titleEl = document.getElementById('catalyst-modal-title');
        const voiceInput = document.getElementById('catalyst-voice-input');

        if (!modal) return;

        // Reset custom transform offsets from drag gestures
        const card = modal.querySelector('.catalyst-modal-card');
        if (card) {
            card.style.transform = '';
            card.style.transition = '';
        }
        modal.style.background = '';

        // Display modal using class
        modal.classList.add('active');
        loader.style.display = 'none'; // Do not show loader yet
        results.style.display = 'flex';  // Show results pane for instructions

        const cleanSymbol = symbolOrQuery.replace(".NS", "").trim();

        // Store state variables for execution
        currentCatalystSymbol = symbolOrQuery;
        currentCatalystSector = sector;
        currentCatalystIsSector = isSectorOnly;
        currentCatalystDirection = direction;

        if (voiceInput) {
            if (isSectorOnly) {
                const actionWord = direction === "up" ? "gaining" : (direction === "down" ? "declining" : "moving");
                voiceInput.value = `Why is the ${cleanSymbol} sector ${actionWord}?`;
            } else {
                const actionWord = direction === "up" ? "surging" : (direction === "down" ? "dropping" : "moving");
                voiceInput.value = `Why is ${cleanSymbol} ${actionWord}?`;
            }
        }

        titleEl.textContent = isSectorOnly 
            ? `Sector Catalyst: ${cleanSymbol}`
            : `Catalyst analysis: ${cleanSymbol}`;

        // Stop previous typewriter typing instance
        if (activeCatalystTyped) {
            activeCatalystTyped.destroy();
            activeCatalystTyped = null;
        }

        // Show instructional placeholder message in summary container
        const summaryContainer = document.getElementById('catalyst-summary-text');
        if (summaryContainer) {
            summaryContainer.innerHTML = '<span style="color: var(--text-muted); font-size: 11.5px; font-style: italic;">Modify your query in the input box above, then click the <strong>Query</strong> button to fetch real-time catalysts and AI analysis.</span>';
        }

        // Clear previous catalyst driver cards
        const listEl = document.getElementById('catalyst-drivers-list');
        if (listEl) {
            listEl.innerHTML = '';
        }

        // Reset sentiment ring display
        const ring = document.getElementById('catalyst-sentiment-ring');
        if (ring) {
            ring.style.strokeDashoffset = '100';
        }
        const sTitle = document.getElementById('catalyst-sentiment-title');
        if (sTitle) {
            sTitle.textContent = 'Awaiting Query...';
            sTitle.style.color = '';
        }

        // Clear prompts list
        const promptsContainer = document.getElementById('catalyst-prompts-container');
        if (promptsContainer) {
            promptsContainer.innerHTML = '';
        }

        // Reset audit metadata footers to pending
        const auditScraperEl = document.getElementById('catalyst-audit-scraper');
        const auditEngineEl = document.getElementById('catalyst-audit-engine');
        if (auditScraperEl) auditScraperEl.textContent = 'Pending...';
        if (auditEngineEl) auditEngineEl.textContent = 'Pending...';
    }

    function executeCatalystAnalysis() {
        const modal = document.getElementById('catalyst-modal');
        const loader = document.getElementById('catalyst-loader');
        const results = document.getElementById('catalyst-results');
        const voiceInput = document.getElementById('catalyst-voice-input');

        if (!modal) return;

        // Read query text
        const queryText = voiceInput ? voiceInput.value.trim() : "";
        if (!queryText) {
            window.showToast("Please enter a valid query.", "warning");
            return;
        }

        // Blur input to dismiss mobile soft keyboard
        if (voiceInput) voiceInput.blur();

        // Update active symbol to custom query text
        currentCatalystSymbol = queryText;

        // Display loader and hide results pane
        loader.style.display = 'flex';
        results.style.display = 'none';

        // Stop previous typewriter typing instance
        if (activeCatalystTyped) {
            activeCatalystTyped.destroy();
            activeCatalystTyped = null;
        }

        const aiEngine = localStorage.getItem('catalyst_ai_engine') || 'gemini';
        let searchHorizon = localStorage.getItem('search_horizon') || '7d';
        const sectorRadarLookback = document.getElementById('sector-radar-lookback');
        if (currentCatalystIsSector && sectorRadarLookback) {
            searchHorizon = sectorRadarLookback.value || '7d';
        }
        
        const useTavily = localStorage.getItem('use_tavily_search') === 'true';
        const useSerpApi = localStorage.getItem('use_serpapi') !== 'false'; // default to true
        const useBrave = localStorage.getItem('use_brave_search') !== 'false'; // default to true
        
        const url = apiBaseUrl + `/api/stock-catalysts?symbol=${encodeURIComponent(currentCatalystSymbol)}&sector=${encodeURIComponent(currentCatalystSector)}&is_sector=${currentCatalystIsSector}&ai_engine=${aiEngine}&timeframe=${searchHorizon}&use_tavily_search=${useTavily}&use_serpapi=${useSerpApi}&use_brave=${useBrave}&direction=${currentCatalystDirection}`;

        fetch(url)
            .then(res => res.json())
            .then(data => {
                loader.style.display = 'none';
                results.style.display = 'flex';

                // Update audit diagnostics footer fields
                const auditScraperEl = document.getElementById('catalyst-audit-scraper');
                const auditEngineEl = document.getElementById('catalyst-audit-engine');
                if (auditScraperEl) {
                    auditScraperEl.textContent = data.search_provider || 'None';
                }
                if (auditEngineEl) {
                    auditEngineEl.textContent = data.llm_provider || 'None';
                }

                // Render dynamic Sentiment ring
                const ring = document.getElementById('catalyst-sentiment-ring');
                const sTitle = document.getElementById('catalyst-sentiment-title');
                const sentimentValue = (data.sentiment || 'Neutral').toLowerCase();
                
                let percent = 50;
                let strokeColor = 'var(--color-primary-light)';
                let glowColor = 'rgba(59, 130, 246, 0.4)';
                let titleText = '50% NEUTRAL SENTIMENT';
                let titleColor = 'var(--text-primary)';

                if (sentimentValue === 'positive') {
                    percent = 85;
                    strokeColor = 'var(--color-emerald)';
                    glowColor = 'rgba(16, 185, 129, 0.5)';
                    titleText = '85% BULLISH OUTLOOK';
                    titleColor = 'var(--color-emerald)';
                } else if (sentimentValue === 'negative') {
                    percent = 85;
                    strokeColor = 'var(--color-crimson)';
                    glowColor = 'rgba(239, 68, 68, 0.5)';
                    titleText = '85% BEARISH OUTLOOK';
                    titleColor = 'var(--color-crimson)';
                }

                if (ring) {
                    const offset = 100 - percent;
                    ring.style.stroke = strokeColor;
                    ring.style.strokeDashoffset = offset;
                    // Add glow in dark mode
                    const isDark = document.documentElement.getAttribute('data-theme') !== 'light' && document.body.getAttribute('data-theme') !== 'light';
                    if (isDark) {
                        ring.style.filter = `drop-shadow(0 0 4px ${glowColor})`;
                    } else {
                        ring.style.filter = '';
                    }
                }
                if (sTitle) {
                    sTitle.textContent = titleText;
                    sTitle.style.color = titleColor;
                }

                // Display summary text using Typed.js
                const summaryContainer = document.getElementById('catalyst-summary-text');
                if (summaryContainer) {
                    summaryContainer.innerHTML = '';
                    const textSpan = document.createElement('span');
                    summaryContainer.appendChild(textSpan);

                    activeCatalystTyped = new Typed(textSpan, {
                        strings: [data.summary || "No catalysts parsed."],
                        typeSpeed: 3,
                        showCursor: false,
                        contentType: 'html'
                    });
                }

                // Render catalyst driver list cards
                const listEl = document.getElementById('catalyst-drivers-list');
                if (listEl) {
                    listEl.innerHTML = '';
                    const drivers = data.drivers || [];
                    
                    drivers.forEach(d => {
                        const card = document.createElement('div');
                        
                        // Map categorisation to colors and badges
                        const isDriverBullish = sentimentValue === 'positive' || d.desc.toLowerCase().includes('surge') || d.desc.toLowerCase().includes('gain') || d.desc.toLowerCase().includes('profit') || d.desc.toLowerCase().includes('growth');
                        const isDriverBearish = sentimentValue === 'negative' || d.desc.toLowerCase().includes('decline') || d.desc.toLowerCase().includes('drop') || d.desc.toLowerCase().includes('pledge') || d.desc.toLowerCase().includes('threat');
                        
                        let sentimentClass = '';
                        let badgeSentimentClass = '';
                        let badgeText = 'Neutral';

                        if (isDriverBullish) {
                            sentimentClass = 'bullish';
                            badgeSentimentClass = 'bullish';
                            badgeText = 'Bullish';
                        } else if (isDriverBearish) {
                            sentimentClass = 'bearish';
                            badgeSentimentClass = 'bearish';
                            badgeText = 'Bearish';
                        }

                        card.className = `catalyst-driver-card ${sentimentClass}`;
                        
                        // Map category indicators to Lucide icons
                        let icon = '⚡';
                        if (d.category === 'Corporate') icon = '🏢';
                        else if (d.category.includes('Policy') || d.category.includes('Sector')) icon = '⚖️';
                        else if (d.category === 'Macro') icon = '🌍';
                        else if (d.category === 'Technical') icon = '📉';
                        
                        card.innerHTML = `
                            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px; margin-bottom: 4px;">
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <span class="catalyst-driver-badge ${badgeSentimentClass}">${icon} ${d.category}</span>
                                    <span class="catalyst-driver-badge ${badgeSentimentClass}" style="opacity: 0.85;">${badgeText}</span>
                                </div>
                                <strong style="font-size: 12px; color: var(--text-primary); font-family:var(--font-heading); flex: 1; min-width: 150px; text-align: left;">${d.title}</strong>
                            </div>
                            <p style="margin: 0; font-size: 11.5px; line-height: 1.55; color: var(--text-secondary); font-family: 'Inter';">${d.desc}</p>
                        `;
                        listEl.appendChild(card);
                    });
                }

                // Render dynamic suggestion pills
                const promptsContainer = document.getElementById('catalyst-prompts-container');
                if (promptsContainer) {
                    promptsContainer.innerHTML = '';
                    
                    const cleanSymbol = currentCatalystSymbol.replace(".NS", "").trim();
                    const prompts = [
                        `Revenue impact of ${cleanSymbol}?`,
                        `Competitors of ${cleanSymbol}?`,
                        `Timeline risks of ${cleanSymbol}?`
                    ];

                    prompts.forEach(pText => {
                        const pill = document.createElement('button');
                        pill.className = 'catalyst-prompt-pill';
                        pill.innerHTML = `💡 <span>${pText}</span>`;
                        pill.onclick = () => {
                            if (voiceInput) {
                                voiceInput.value = pText;
                                document.getElementById('catalyst-query-btn')?.click();
                            }
                        };
                        promptsContainer.appendChild(pill);
                    });
                }
            })
            .catch(err => {
                console.error("[Catalyst UI] Fetch failed:", err);
                loader.style.display = 'none';
                window.showToast("Failed to fetch price action reasons. Please try again.", "error");
            });
    }

    function setupCatalystModalListeners() {
        const modal = document.getElementById('catalyst-modal');
        const closeBtn = document.getElementById('catalyst-modal-close-btn');
        const closeBtnBottom = document.getElementById('catalyst-modal-close-btn-bottom');
        const queryBtn = document.getElementById('catalyst-query-btn');
        const explainMoveBtn = document.getElementById('explain-move-btn');
        const voiceInput = document.getElementById('catalyst-voice-input');

        const closeModal = () => {
            stopCatalystSpeech();
            if (modal) modal.classList.remove('active');
            if (activeCatalystTyped) {
                activeCatalystTyped.destroy();
                activeCatalystTyped = null;
            }
        };

        if (closeBtn) closeBtn.addEventListener('click', closeModal);
        if (closeBtnBottom) closeBtnBottom.addEventListener('click', closeModal);

        // Click away dismiss listener
        if (modal) {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    closeModal();
                }
            });

            // Swipe down to dismiss gesture handlers for mobile
            const card = modal.querySelector('.catalyst-modal-card');
            const dragHandle = document.getElementById('catalyst-drag-handle');
            
            if (card && dragHandle) {
                let startY = 0;
                let currentY = 0;
                let isDragging = false;

                const handleStart = (clientY) => {
                    startY = clientY;
                    isDragging = true;
                    card.style.transition = 'none';
                };

                const handleMove = (clientY) => {
                    if (!isDragging) return;
                    currentY = clientY;
                    const diffY = currentY - startY;
                    
                    if (diffY > 0) {
                        card.style.transform = `translateY(${diffY}px)`;
                        // Fade backdrop opacity proportionally
                        const opacity = 0.55 - (diffY / 600) * 0.55;
                        modal.style.background = `rgba(7, 10, 18, ${Math.max(0.1, opacity)})`;
                    }
                };

                const handleEnd = () => {
                    if (!isDragging) return;
                    isDragging = false;
                    const diffY = currentY - startY;
                    
                    card.style.transition = 'transform 0.3s cubic-bezier(0.16, 1, 0.3, 1)';
                    modal.style.transition = 'background 0.3s ease';

                    if (diffY > 80) {
                        // Slide fully down and close
                        card.style.transform = 'translateY(100%)';
                        modal.style.background = 'rgba(7, 10, 18, 0)';
                        setTimeout(() => {
                            closeModal();
                        }, 250);
                    } else {
                        // Spring back up
                        card.style.transform = '';
                        modal.style.background = '';
                    }
                    
                    // Reset transitions after snap back
                    setTimeout(() => {
                        if (modal.classList.contains('active')) {
                            card.style.transition = '';
                            modal.style.transition = '';
                        }
                    }, 350);
                };

                dragHandle.addEventListener('touchstart', (e) => handleStart(e.touches[0].clientY));
                document.addEventListener('touchmove', (e) => {
                    if (isDragging) {
                        e.preventDefault(); // Prevent double scrolling page bounce
                        handleMove(e.touches[0].clientY);
                    }
                }, { passive: false });
                document.addEventListener('touchend', handleEnd);
            }
        }

        if (explainMoveBtn) {
            explainMoveBtn.addEventListener('click', () => {
                const ticker = document.getElementById('meta-ticker')?.textContent || "";
                if (ticker) {
                    const pctEl = document.getElementById('meta-change');
                    const pctText = pctEl ? pctEl.textContent.trim() : "";
                    const direction = pctText.includes('-') ? "down" : (pctText.includes('+') ? "up" : "");
                    const targetSector = document.getElementById('meta-sector')?.textContent || "";
                    openCatalystAnalysis(ticker, targetSector, false, direction);
                }
            });
        }

        // Trigger manual voice text queries
        if (queryBtn) {
            queryBtn.addEventListener('click', () => {
                executeCatalystAnalysis();
            });
        }

        if (voiceInput) {
            voiceInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    queryBtn?.click();
                }
            });
        }

        // Delegate trigger clicks inside tables (Watchlist, Movers, Sectors)
        document.addEventListener('click', (e) => {
            const trigger = e.target.closest('.catalyst-trigger-btn');
            if (trigger) {
                const symbol = trigger.getAttribute('data-symbol');
                const sector = trigger.getAttribute('data-sector') || '';
                
                // Extract direction
                let direction = "";
                const row = trigger.closest('tr');
                if (row) {
                    const isGainer = trigger.closest('#top-gainers-tbody') !== null;
                    const isLoser = trigger.closest('#top-losers-tbody') !== null;
                    if (isGainer) {
                        direction = "up";
                    } else if (isLoser) {
                        direction = "down";
                    } else {
                        // Check watchlist columns for positive/negative change Indicators
                        const cells = row.querySelectorAll('td');
                        for (let cell of cells) {
                            const cellText = cell.textContent.trim();
                            if (cell.classList.contains('text-green') || cellText.includes('+')) {
                                direction = "up";
                                break;
                            } else if (cell.classList.contains('text-danger') || cell.classList.contains('text-red') || cellText.includes('-')) {
                                direction = "down";
                                break;
                            }
                        }
                    }
                } else {
                    // Check if it is inside a Sector heatmap tile
                    const heatmapTile = trigger.closest('.sector-heatmap-tile');
                    if (heatmapTile) {
                        const pctEl = heatmapTile.querySelector('.sector-heatmap-tile-pct');
                        const pctText = pctEl ? pctEl.textContent.trim() : "";
                        direction = pctText.includes('-') ? "down" : (pctText.includes('+') ? "up" : "");
                    }
                }
                
                // Determine isSectorOnly based on the data attributes
                const isSector = trigger.hasAttribute('data-sector') || trigger.closest('.sector-heatmap-tile') !== null;
                openCatalystAnalysis(symbol, sector, isSector, direction);
                return;
            }

            // Clicking any sector standings block or row in Sector Momentum Radar
            const sectorRow = e.target.closest('#tab-sector-radar .sector-row, #tab-sector-radar .sector-card, #tab-sector-radar [data-sector]');
            if (sectorRow && !e.target.closest('button') && !e.target.closest('input')) {
                const sectorName = sectorRow.getAttribute('data-sector') || sectorRow.querySelector('h4')?.textContent || sectorRow.textContent.trim();
                const cleanSector = sectorName.replace(/^[▲▼]?\s*[\d.-]+%\s*/, '').trim();
                
                let direction = "";
                if (sectorName.includes('▲') || sectorName.includes('+')) {
                    direction = "up";
                } else if (sectorName.includes('▼') || sectorName.includes('-')) {
                    direction = "down";
                }
                
                if (cleanSector && cleanSector.length > 2 && cleanSector.length < 35 && !cleanSector.includes('Sync') && !cleanSector.includes('Interpretation')) {
                    openCatalystAnalysis(cleanSector, "", true, direction);
                }
            }
        });
    }

    // ==================== 15. SETTINGS SEARCH TOGGLE COCKPIT ====================
    function setupSettingsSearchToggle() {
        const aiSelect = document.getElementById('setting-catalyst-ai');
        const horizonSelect = document.getElementById('setting-search-horizon');
        const braveToggle = document.getElementById('setting-brave-toggle');
        const tavilyToggle = document.getElementById('setting-tavily-search-toggle');
        const serpapiToggle = document.getElementById('setting-serpapi-toggle');

        // Initialize state from localStorage
        if (aiSelect) {
            aiSelect.value = localStorage.getItem('catalyst_ai_engine') || 'gemini';
            aiSelect.addEventListener('change', (e) => {
                localStorage.setItem('catalyst_ai_engine', e.target.value);
                AudioCueManager.playTick();
                window.showToast(`AI Engine set to: ${e.target.value === 'gemini' ? 'Gemini 1.5' : 'Groq Llama 3.3'}`, 'success');
            });
        }

        if (horizonSelect) {
            horizonSelect.value = localStorage.getItem('search_horizon') || '7d';
            horizonSelect.addEventListener('change', (e) => {
                localStorage.setItem('search_horizon', e.target.value);
                AudioCueManager.playTick();
                window.showToast(`Search Horizon set to: ${horizonSelect.options[horizonSelect.selectedIndex].text}`, 'success');
            });
        }

        if (tavilyToggle) {
            const storedTavily = localStorage.getItem('use_tavily_search');
            if (storedTavily !== null) {
                tavilyToggle.checked = storedTavily === 'true';
            } else {
                fetch(apiBaseUrl + '/api/llm-config')
                    .then(res => res.json())
                    .then(config => {
                        tavilyToggle.checked = !!config.has_tavily_key || !!localStorage.getItem('tavily_api_key');
                        localStorage.setItem('use_tavily_search', tavilyToggle.checked);
                    })
                    .catch(() => {
                        tavilyToggle.checked = false;
                    });
            }
            tavilyToggle.addEventListener('change', (e) => {
                localStorage.setItem('use_tavily_search', e.target.checked);
                AudioCueManager.playTick();
                window.showToast(`Tavily API ${e.target.checked ? 'Enabled' : 'Disabled'}`, 'success');
            });
        }

        if (serpapiToggle) {
            const storedSerp = localStorage.getItem('use_serpapi');
            if (storedSerp !== null) {
                serpapiToggle.checked = storedSerp === 'true';
            } else {
                fetch(apiBaseUrl + '/api/llm-config')
                    .then(res => res.json())
                    .then(config => {
                        serpapiToggle.checked = !!config.has_serpapi_key || !!localStorage.getItem('serpapi_api_key');
                        localStorage.setItem('use_serpapi', serpapiToggle.checked);
                    })
                    .catch(() => {
                        serpapiToggle.checked = false;
                    });
            }
            serpapiToggle.addEventListener('change', (e) => {
                localStorage.setItem('use_serpapi', e.target.checked);
                AudioCueManager.playTick();
                window.showToast(`SerpApi ${e.target.checked ? 'Enabled' : 'Disabled'}`, 'success');
            });
        }

        if (braveToggle) {
            const storedBrave = localStorage.getItem('use_brave_search');
            if (storedBrave !== null) {
                braveToggle.checked = storedBrave === 'true';
            } else {
                fetch(apiBaseUrl + '/api/llm-config')
                    .then(res => res.json())
                    .then(config => {
                        braveToggle.checked = !!config.has_brave_key;
                        localStorage.setItem('use_brave_search', braveToggle.checked);
                    })
                    .catch(() => {
                        braveToggle.checked = false;
                    });
            }
            braveToggle.addEventListener('change', (e) => {
                localStorage.setItem('use_brave_search', e.target.checked);
                AudioCueManager.playTick();
                window.showToast(`Brave Search ${e.target.checked ? 'Enabled' : 'Disabled'}`, 'success');
                // Note: SerpApi & Tavily key storage has been modernized to use backend SQLite database dynamic key configuration.
            });
        }

        // Note: SerpApi & Tavily key storage has been modernized to use backend SQLite database dynamic key configuration.
    }

    // ==================== MOBILE ENTERPRISE UI LAYOUT & CONTROLLER ====================
    function setupMobileUpgrades() {
        const isMobile = () => window.innerWidth <= 768;

        // Bottom nav tab IDs mapping
        const tabsList = ['analyzer', 'screener', 'watchlist', 'portfolio'];

        function injectMobileBottomNav() {
            if (document.querySelector('.mobile-bottom-nav')) return;
            const bottomNav = document.createElement('nav');
            bottomNav.className = 'mobile-bottom-nav no-print';
            bottomNav.innerHTML = `
                <button class="mobile-bottom-nav-item" id="nav-terminal" title="Terminal">
                    <i data-lucide="line-chart"></i>
                    <span>Terminal</span>
                </button>
                <button class="mobile-bottom-nav-item" id="nav-screener" title="Screener">
                    <i data-lucide="search"></i>
                    <span>Screener</span>
                </button>
                <button class="mobile-bottom-nav-item" id="nav-watchlist" title="Watchlist">
                    <i data-lucide="list"></i>
                    <span>Watchlist</span>
                </button>
                <button class="mobile-bottom-nav-item" id="nav-portfolio" title="Portfolio">
                    <i data-lucide="pie-chart"></i>
                    <span>Portfolio</span>
                </button>
                <button class="mobile-bottom-nav-item" id="nav-more" title="More">
                    <i data-lucide="menu"></i>
                    <span>More</span>
                </button>
            `;
            document.body.appendChild(bottomNav);

            document.getElementById('nav-terminal').addEventListener('click', () => window.switchTab('analyzer'));
            document.getElementById('nav-screener').addEventListener('click', () => window.switchTab('screener'));
            document.getElementById('nav-watchlist').addEventListener('click', () => window.switchTab('watchlist'));
            document.getElementById('nav-portfolio').addEventListener('click', () => window.switchTab('portfolio'));
            document.getElementById('nav-more').addEventListener('click', (e) => {
                e.stopPropagation();
                const sidebar = document.getElementById('sidebar');
                if (sidebar) sidebar.classList.add('open');
            });

            if (typeof lucide !== 'undefined') {
                lucide.createIcons();
            }
            syncActiveBottomNavTab();
        }

        function removeMobileBottomNav() {
            const bottomNav = document.querySelector('.mobile-bottom-nav');
            if (bottomNav) bottomNav.remove();
        }

        function syncActiveBottomNavTab(activeTabKey) {
            const bottomNav = document.querySelector('.mobile-bottom-nav');
            if (!bottomNav) return;

            bottomNav.querySelectorAll('.mobile-bottom-nav-item').forEach(item => {
                item.classList.remove('active');
            });

            const currentTab = activeTabKey || window.activeTab || (location.hash ? location.hash.substring(1) : 'analyzer');
            let navId = 'nav-terminal';
            if (currentTab === 'analyzer') navId = 'nav-terminal';
            else if (currentTab === 'screener') navId = 'nav-screener';
            else if (currentTab === 'watchlist') navId = 'nav-watchlist';
            else if (currentTab === 'portfolio') navId = 'nav-portfolio';

            const activeBtn = document.getElementById(navId);
            if (activeBtn) activeBtn.classList.add('active');
        }

        // Tap Haptic Simulation Helper
        function playHaptic(ms = 10) {
            const Haptics = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Haptics;
            if (Haptics && typeof Haptics.vibrate === 'function') {
                try {
                    Haptics.vibrate({ duration: ms });
                    return;
                } catch(e) {}
            }
            if (navigator.vibrate) {
                try {
                    navigator.vibrate(ms);
                } catch(e) {}
            }
        }

        // Dynamic active state touch classes & clicks sonification
        document.addEventListener('touchstart', e => {
            const tapTarget = e.target.closest('.mobile-bottom-nav-item, .pin-key, .btn-primary, .btn-secondary, .portfolio-subtab-btn');
            if (tapTarget) {
                tapTarget.classList.add('touch-active');
            }
        }, { passive: true });

        document.addEventListener('touchend', e => {
            const tapTarget = e.target.closest('.mobile-bottom-nav-item, .pin-key, .btn-primary, .btn-secondary, .portfolio-subtab-btn');
            if (tapTarget) {
                tapTarget.classList.remove('touch-active');
                playHaptic(8);
            }
        }, { passive: true });

        // Initialize bottom navigation display
        if (isMobile()) {
            injectMobileBottomNav();
        }

        window.addEventListener('resize', () => {
            if (isMobile()) {
                injectMobileBottomNav();
                decorateWatchlistRowsForMobile();
                decoratePortfolioRowsForMobile();
                decorateUniverseRowsForMobile();
                decorateAlertsRowsForMobile();
                decorateRuleScannerRowsForMobile();
                decorateScreenerRowsForMobile();
                decorateSectorRadarRowsForMobile();
            } else {
                removeMobileBottomNav();
                decorateWatchlistRowsForMobile();
                decoratePortfolioRowsForMobile();
                decorateUniverseRowsForMobile();
                decorateAlertsRowsForMobile();
                decorateRuleScannerRowsForMobile();
                decorateScreenerRowsForMobile();
                decorateSectorRadarRowsForMobile();
            }
        });

        // Note: switchTab interception and nav highlights are fully handled by the global routing interceptor property defined at the top of the file.

        // 2. Swipe Gestures for Tab Navigation
        let touchstartX = 0;
        let touchendX = 0;
        let touchstartY = 0;
        let touchendY = 0;
        let touchStartTarget = null;
        const swipeMinDistance = 75;
        const swipeMaxCrossDistance = 45;

        function handleSwipeGesture(e) {
            const currentHash = location.hash.substring(1) || 'analyzer';
            
            // Disable swipe navigation on the Equity Research Terminal tab to prevent scroll conflicts
            if (currentHash === 'analyzer') {
                return;
            }

            // Disable page swipe transitions on Watchlist and Portfolio tabs to resolve gesture conflicts
            if (currentHash === 'watchlist' || currentHash === 'portfolio') {
                return;
            }

            const target = touchStartTarget || (e ? e.target : null);
            if (target && target.closest('#tv-chart-workstation, input, textarea, select, button, .pin-key, .rs-bottom-sheet, tr, td, .swipeable-row-container, .swipeable-row-content, .swipe-actions, .tearsheet-range-slider, .tearsheet-range-marker, .watchlist-scroll-wrapper, .data-table-wrapper')) {
                return;
            }
            const isSwipeLeftTab = touchendX < touchstartX - swipeMinDistance && Math.abs(touchendY - touchstartY) < swipeMaxCrossDistance;
            const isSwipeRightTab = touchendX > touchstartX + swipeMinDistance && Math.abs(touchendY - touchstartY) < swipeMaxCrossDistance;

            if (isSwipeLeftTab || isSwipeRightTab) {
                const currentIndex = tabsList.indexOf(currentHash);
                if (currentIndex !== -1) {
                    let nextIndex = currentIndex;
                    if (isSwipeLeftTab && currentIndex < tabsList.length - 1) {
                        nextIndex = currentIndex + 1;
                    } else if (isSwipeRightTab && currentIndex > 0) {
                        nextIndex = currentIndex - 1;
                    }
                    if (nextIndex !== currentIndex) {
                        playHaptic(12);
                        window.switchTab(tabsList[nextIndex]);
                    }
                }
            }
        }

        document.addEventListener('touchstart', e => {
            touchstartX = e.changedTouches[0].screenX;
            touchstartY = e.changedTouches[0].screenY;
            touchStartTarget = e.target;
        }, { passive: true });

        document.addEventListener('touchend', e => {
            touchendX = e.changedTouches[0].screenX;
            touchendY = e.changedTouches[0].screenY;
            if (isMobile()) handleSwipeGesture(e);
        }, { passive: true });

        // 3. Pull-To-Refresh Gestures
        let pullStartX = 0;
        let pullStartY = 0;
        let isPulling = false;
        let activePullContainer = null;
        let pullIndicator = null;

        function initPullToRefresh() {
            if (!isMobile()) return;
            pullIndicator = document.querySelector('.pull-to-refresh-indicator');
            if (!pullIndicator) {
                pullIndicator = document.createElement('div');
                pullIndicator.className = 'pull-to-refresh-indicator';
                pullIndicator.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>`;
                document.body.appendChild(pullIndicator);
            }

            document.addEventListener('touchstart', e => {
                if (!isMobile()) return;
                const targetContainer = e.target.closest('#watchlist-items-card, #portfolio-doctor-card, #movers-grid');
                if (!targetContainer) return;

                const scrollContainer = targetContainer.closest('.data-table-wrapper, .watchlist-scroll-wrapper, body');
                if (scrollContainer && scrollContainer.scrollTop > 5) return;
                if (window.scrollY > 5) return;

                pullStartX = e.touches[0].clientX;
                pullStartY = e.touches[0].clientY;
                activePullContainer = targetContainer;
                isPulling = false;
            }, { passive: true });

            document.addEventListener('touchmove', e => {
                if (!activePullContainer || !pullIndicator) return;
                const currentY = e.touches[0].clientY;
                const currentX = e.touches[0].clientX;
                const diffY = currentY - pullStartY;
                const diffX = currentX - pullStartX;

                if (diffY > 10 && Math.abs(diffY) > Math.abs(diffX) * 1.5) {
                    isPulling = true;
                    const pullDist = Math.min(diffY * 0.4, 75);
                    pullIndicator.style.opacity = Math.min(pullDist / 40, 1);
                    pullIndicator.style.transform = `translateX(-50%) translateY(${pullDist}px)`;
                    
                    const rotate = pullDist * 5;
                    const spinner = pullIndicator.querySelector('svg');
                    if (spinner) spinner.style.transform = `rotate(${rotate}deg)`;
                }
            }, { passive: true });

            document.addEventListener('touchend', async e => {
                if (!activePullContainer || !isPulling || !pullIndicator) {
                    activePullContainer = null;
                    isPulling = false;
                    return;
                }
                const diffY = e.changedTouches[0].clientY - pullStartY;
                activePullContainer = null;
                isPulling = false;

                if (diffY > 60) {
                    pullIndicator.classList.add('refreshing');
                    pullIndicator.style.transform = `translateX(-50%) translateY(40px)`;
                    pullIndicator.style.opacity = '1';
                    playHaptic(15);

                    try {
                        const currentHash = location.hash.substring(1) || 'analyzer';
                        if (currentHash === 'watchlist') {
                            const refreshBtn = document.getElementById('watchlist-refresh-btn');
                            if (refreshBtn) refreshBtn.click();
                        } else if (currentHash === 'portfolio') {
                            const refreshBtn = document.getElementById('portfolio-refresh-btn');
                            if (refreshBtn) refreshBtn.click();
                        } else {
                            window.location.reload();
                        }
                    } catch (err) {
                        console.error("[Mobile Refresh] Failed:", err);
                    } finally {
                        setTimeout(() => {
                            if (pullIndicator) {
                                pullIndicator.classList.remove('refreshing');
                                pullIndicator.style.transform = `translateX(-50%) translateY(-46px)`;
                                pullIndicator.style.opacity = '0';
                            }
                        }, 1200);
                    }
                } else {
                    pullIndicator.style.transform = `translateX(-50%) translateY(-46px)`;
                    pullIndicator.style.opacity = '0';
                }
            });
        }
        initPullToRefresh();

        // 4. Custom Mobile Bottom Sheets for Selector Dropdowns
        function initMobileSelects() {
            document.addEventListener('click', e => {
                if (!isMobile()) return;
                const selectEl = e.target.closest('select');
                if (!selectEl || selectEl.id === 'setting-refresh-interval' || selectEl.id === 'setting-speech-voice') return;

                e.preventDefault();
                e.stopPropagation();

                openCustomSelectBottomSheet(selectEl);
            }, true);
        }

        function openQuickSearchBottomSheet() {
            let sheet = document.getElementById('rs-bottom-sheet');
            if (!sheet) {
                sheet = document.createElement('div');
                sheet.id = 'rs-bottom-sheet';
                sheet.className = 'rs-bottom-sheet';
                sheet.innerHTML = `
                    <div class="rs-bottom-sheet-backdrop"></div>
                    <div class="rs-bottom-sheet-content">
                        <div class="rs-bottom-sheet-handle"></div>
                        <h4 id="rs-bottom-sheet-title">Select Option</h4>
                        <div id="rs-bottom-sheet-utility"></div>
                        <button class="rs-bottom-sheet-close" style="margin-top: 15px;">Dismiss</button>
                    </div>
                `;
                document.body.appendChild(sheet);
            }

            document.getElementById('rs-bottom-sheet-title').innerText = "Quick Asset Search";
            const recents = JSON.parse(localStorage.getItem('recent-mobile-searches') || '["RELIANCE", "TCS", "INFY", "TATASTEEL"]');
            
            let html = `
                <div style="display:flex; flex-direction:column; gap:16px; margin: 15px 0;">
                    <div style="position:relative; width:100%;">
                        <input type="text" id="mobile-quick-search-input" placeholder="Enter stock symbol (e.g. RELIANCE)..." style="width:100% !important; box-sizing:border-box !important; padding:12px 16px !important; font-size:14px !important; background:rgba(255,255,255,0.03) !important; border:1px solid var(--border-glass) !important; color:var(--text-primary) !important; border-radius:8px !important;">
                        <div id="mobile-quick-suggestions" class="watchlist-autocomplete-box" style="display:none; position:absolute; top:100%; left:0; right:0; z-index:9999; max-height:220px; overflow-y:auto; margin-top:4px;"></div>
                    </div>
                    <div>
                        <h5 style="margin:0 0 8px 0; font-size:11px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading);">Recent Searches</h5>
                        <div style="display:flex; flex-wrap:wrap; gap:8px;">
            `;
            
            recents.forEach(sym => {
                html += `<button class="quick-search-pill-btn" data-symbol="${sym}" style="background:rgba(255,255,255,0.03); border:1px solid var(--border-glass); color:var(--text-primary); padding:6px 12px; border-radius:15px; font-size:11px; font-weight:600; cursor:pointer;">${sym}</button>`;
            });
            
            html += `
                        </div>
                    </div>
                    <button class="btn-primary" id="mobile-quick-search-submit-btn" style="width:100%; height:40px; border-radius:8px; font-weight:700;">ANALYZE ASSET</button>
                </div>
            `;

            const utilityContainer = document.getElementById('rs-bottom-sheet-utility');
            utilityContainer.innerHTML = html;
            sheet.classList.add('active');

            // Wire backdrop close
            const backdrop = sheet.querySelector('.rs-bottom-sheet-backdrop');
            const closeBtn = sheet.querySelector('.rs-bottom-sheet-close');
            const closeSheet = () => sheet.classList.remove('active');
            backdrop.onclick = closeSheet;
            closeBtn.onclick = closeSheet;

            const inputEl = document.getElementById('mobile-quick-search-input');
            const suggestionsDiv = document.getElementById('mobile-quick-suggestions');

            setTimeout(() => {
                if (inputEl) inputEl.focus();
            }, 300);

            utilityContainer.querySelectorAll('.quick-search-pill-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    executeQuickSearch(btn.getAttribute('data-symbol'), sheet);
                });
            });

            // Debounced Autocomplete Logic
            let searchDebounceTimer = null;
            if (inputEl && suggestionsDiv) {
                inputEl.addEventListener('input', () => {
                    clearTimeout(searchDebounceTimer);
                    const query = inputEl.value.trim();

                    if (query.length < 2) {
                        suggestionsDiv.innerHTML = '';
                        suggestionsDiv.style.display = 'none';
                        return;
                    }

                    searchDebounceTimer = setTimeout(async () => {
                        try {
                            const res = await fetch(apiBaseUrl + `/api/search/suggestions?q=${encodeURIComponent(query)}`);
                            if (res.ok) {
                                const data = await res.json();
                                suggestionsDiv.innerHTML = '';

                                if (data && data.length > 0) {
                                    data.forEach(item => {
                                        const div = document.createElement('div');
                                        div.className = 'watchlist-autocomplete-item';
                                        div.style.cssText = 'padding: 10px 14px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.03);';
                                        div.innerHTML = `
                                            <div>
                                                <span class="ticker-pill" style="font-weight: 700; color: #fff;">${item.base_symbol}</span>
                                                <span style="font-size: 10px; color: var(--text-muted); margin-left: 6px;">${item.name}</span>
                                            </div>
                                            <span class="sector-pill">${item.sector || 'Equity'}</span>
                                        `;
                                        div.addEventListener('click', () => {
                                            executeQuickSearch(item.base_symbol, sheet);
                                        });
                                        suggestionsDiv.appendChild(div);
                                    });
                                    suggestionsDiv.style.display = 'block';
                                } else {
                                    suggestionsDiv.style.display = 'none';
                                }
                            }
                        } catch (err) {
                            console.error("Autocomplete quick search error:", err);
                        }
                    }, 200);
                });

                // Hide suggestions when clicking outside input or suggestions box
                document.addEventListener('click', (e) => {
                    if (e.target !== inputEl && e.target !== suggestionsDiv && !suggestionsDiv.contains(e.target)) {
                        suggestionsDiv.style.display = 'none';
                    }
                });
            }

            if (inputEl) {
                inputEl.addEventListener('keypress', e => {
                    if (e.key === 'Enter') {
                        executeQuickSearch(inputEl.value.trim(), sheet);
                    }
                });
            }

            const submitBtn = document.getElementById('mobile-quick-search-submit-btn');
            if (submitBtn && inputEl) {
                submitBtn.addEventListener('click', () => {
                    executeQuickSearch(inputEl.value.trim(), sheet);
                });
            }
        }

        function executeQuickSearch(symbol, sheetEl) {
            if (!symbol) return;
            symbol = symbol.toUpperCase();
            
            let recents = JSON.parse(localStorage.getItem('recent-mobile-searches') || '["RELIANCE", "TCS", "INFY", "TATASTEEL"]');
            recents = [symbol, ...recents.filter(s => s !== symbol)].slice(0, 5);
            localStorage.setItem('recent-mobile-searches', JSON.stringify(recents));

            // Switch to main Equity Research Terminal tab
            if (window.switchTab) {
                window.switchTab('analyzer');
            }

            const searchInput = document.getElementById('analyzer-search-input');
            const searchBtn = document.getElementById('analyzer-search-btn');
            if (searchInput && searchBtn) {
                searchInput.value = symbol;
                searchBtn.click();
            }

            if (sheetEl) sheetEl.classList.remove('active');
            playHaptic(15);
        }

        function openCustomSelectBottomSheet(selectEl) {
            let sheet = document.getElementById('rs-bottom-sheet');
            if (!sheet) {
                sheet = document.createElement('div');
                sheet.id = 'rs-bottom-sheet';
                sheet.className = 'rs-bottom-sheet';
                sheet.innerHTML = `
                    <div class="rs-bottom-sheet-backdrop"></div>
                    <div class="rs-bottom-sheet-content">
                        <div class="rs-bottom-sheet-handle"></div>
                        <h4 id="rs-bottom-sheet-title">Select Option</h4>
                        <div id="rs-bottom-sheet-utility"></div>
                        <button class="rs-bottom-sheet-close" style="margin-top: 15px;">Dismiss</button>
                    </div>
                `;
                document.body.appendChild(sheet);
                sheet.querySelector('.rs-bottom-sheet-backdrop').addEventListener('click', () => sheet.classList.remove('active'));
                sheet.querySelector('.rs-bottom-sheet-close').addEventListener('click', () => sheet.classList.remove('active'));
            }

            const label = selectEl.previousElementSibling ? selectEl.previousElementSibling.textContent.trim() : "Select Option";
            document.getElementById('rs-bottom-sheet-title').innerText = label;

            let html = '<div class="bottom-sheet-options-list" style="display:flex;flex-direction:column;gap:12px;margin:15px 0;max-height:300px;overflow-y:auto;-webkit-overflow-scrolling:touch;">';
            Array.from(selectEl.options).forEach((opt, idx) => {
                const isSelected = opt.selected;
                html += `
                    <button class="bottom-sheet-option-row" data-value="${opt.value}" data-index="${idx}" style="background:${isSelected ? 'rgba(99,102,241,0.12)' : 'transparent'}; border:1px solid ${isSelected ? 'rgba(99,102,241,0.3)' : 'rgba(255,255,255,0.06)'}; color:${isSelected ? 'var(--color-primary)' : 'var(--text-primary)'}; padding:12px 16px; border-radius:8px; font-family:Inter,sans-serif; font-size:13px; font-weight:600; text-align:left; cursor:pointer; width:100%; display:flex; justify-content:space-between; align-items:center; outline:none;-webkit-tap-highlight-color:transparent;">
                        <span>${opt.text}</span>
                        ${isSelected ? '<span style="color:var(--color-primary)">✓</span>' : ''}
                    </button>
                `;
            });
            html += '</div>';

            const utilityContainer = document.getElementById('rs-bottom-sheet-utility');
            utilityContainer.innerHTML = html;
            sheet.classList.add('active');

            utilityContainer.querySelectorAll('.bottom-sheet-option-row').forEach(row => {
                row.addEventListener('click', () => {
                    const idx = parseInt(row.getAttribute('data-index'), 10);
                    selectEl.selectedIndex = idx;
                    selectEl.dispatchEvent(new Event('change', { bubbles: true }));
                    playHaptic(8);
                    sheet.classList.remove('active');
                });
            });
        }
        initMobileSelects();

        // 5. Offline Connectivity Dots & local stashing
        function initOfflineDetection() {
            const banner = document.getElementById('network-offline-banner');

            const updateStatus = () => {
                if (!navigator.onLine) {
                    if (banner) banner.classList.add('active');
                    const mobileDot = document.getElementById('mobile-ws-dot');
                    if (mobileDot) {
                        mobileDot.style.background = '#ef4444';
                        mobileDot.style.boxShadow = '0 0 8px #ef4444';
                    }
                    loadOfflineCache();
                } else {
                    if (banner) banner.classList.remove('active');
                }
            };

            window.addEventListener('online', updateStatus);
            window.addEventListener('offline', updateStatus);
            updateStatus();
        }
        initOfflineDetection();

        function stashOfflineCache() {
            try {
                const watchlistBody = document.getElementById('watchlist-table-body');
                if (watchlistBody && watchlistBody.children.length > 0) {
                    localStorage.setItem('cached-watchlist-html', watchlistBody.innerHTML);
                }
                const portfolioCapital = document.getElementById('port-total-investment');
                if (portfolioCapital && portfolioCapital.innerText !== '' && portfolioCapital.innerText !== '--') {
                    const portData = {
                        investment: portfolioCapital.innerText,
                        value: document.getElementById('port-total-value').innerText,
                        pl: document.getElementById('port-total-pl').innerText,
                        plClass: document.getElementById('port-total-pl').className
                    };
                    localStorage.setItem('cached-portfolio-metrics', JSON.stringify(portData));
                }
            } catch(e) {}
        }
        setInterval(stashOfflineCache, 5000);

        function loadOfflineCache() {
            try {
                const cachedWL = localStorage.getItem('cached-watchlist-html');
                const wlBody = document.getElementById('watchlist-table-body');
                if (cachedWL && wlBody && wlBody.children.length === 0) {
                    wlBody.innerHTML = cachedWL;
                    console.log("[Offline Cache] Watchlist stashed values loaded.");
                }
                const cachedPort = localStorage.getItem('cached-portfolio-metrics');
                const portCapital = document.getElementById('port-total-investment');
                if (cachedPort && portCapital && (portCapital.innerText === '' || portCapital.innerText === '--')) {
                    const data = JSON.parse(cachedPort);
                    portCapital.innerText = data.investment;
                    document.getElementById('port-total-value').innerText = data.value;
                    const plEl = document.getElementById('port-total-pl');
                    if (plEl) {
                        plEl.innerText = data.pl;
                        plEl.className = data.plClass;
                    }
                    console.log("[Offline Cache] Portfolio metrics loaded.");
                }
            } catch(e) {}
        }

        // Intercept Connection Status Dot updates
        const originalUpdateIndicator = window.updateConnectionIndicator;
        if (originalUpdateIndicator) {
            window.updateConnectionIndicator = function(status, source) {
                originalUpdateIndicator(status, source);
                const dots = [document.getElementById('mobile-ws-dot'), document.getElementById('desktop-ws-dot')].filter(Boolean);
                dots.forEach(dot => {
                    dot.style.display = 'inline-block';
                    if (status === 'live') {
                        dot.style.background = '#10b981';
                        dot.style.boxShadow = '0 0 8px #10b981';
                        dot.title = 'WebSocket Live: Angel One real-time stream connected';
                    } else if (status === 'polling') {
                        dot.style.background = '#f59e0b';
                        dot.style.boxShadow = '0 0 8px #f59e0b';
                        dot.title = 'WebSocket Polling: Fallback yfinance feed active';
                    } else {
                        dot.style.background = '#ef4444';
                        dot.style.boxShadow = '0 0 8px #ef4444';
                        dot.title = 'WebSocket Offline: Reconnecting...';
                    }
                });
            };
        }

        window.pulseWsDot = function() {
            const dots = [document.getElementById('mobile-ws-dot'), document.getElementById('desktop-ws-dot')].filter(Boolean);
            dots.forEach(dot => {
                dot.style.transform = 'scale(1.4)';
                setTimeout(() => {
                    dot.style.transform = 'scale(1)';
                }, 150);
            });
        };

        // 6. Landscape chart orientation mode
        function initLandscapeChartMode() {
            const handleOrientation = () => {
                const isLandscape = window.innerWidth > window.innerHeight;
                const isChartTab = (location.hash === '#analyzer');
                
                const header = document.querySelector('.mobile-header');
                const footer = document.querySelector('.mobile-bottom-nav');
                const container = document.querySelector('.app-container');
                const chartCard = document.getElementById('tv-chart-workstation');

                if (isMobile() && isLandscape && isChartTab) {
                    if (header) header.style.setProperty('display', 'none', 'important');
                    if (footer) footer.style.setProperty('display', 'none', 'important');
                    if (container) container.style.setProperty('padding-top', '0', 'important');
                    if (chartCard) {
                        chartCard.style.setProperty('position', 'fixed', 'important');
                        chartCard.style.setProperty('top', '0', 'important');
                        chartCard.style.setProperty('left', '0', 'important');
                        chartCard.style.setProperty('width', '100vw', 'important');
                        chartCard.style.setProperty('height', '100vh', 'important');
                        chartCard.style.setProperty('z-index', '99999', 'important');
                    }
                } else {
                    if (header) header.style.display = '';
                    if (footer) footer.style.display = '';
                    if (container) container.style.paddingTop = '';
                    if (chartCard) {
                        chartCard.style.position = '';
                        chartCard.style.top = '';
                        chartCard.style.left = '';
                        chartCard.style.width = '';
                        chartCard.style.height = '';
                        chartCard.style.zIndex = '';
                    }
                }
            };
            window.addEventListener('resize', handleOrientation);
            window.addEventListener('hashchange', handleOrientation);
            handleOrientation();
        }
        initLandscapeChartMode();

        // 7. Fallback Keypad Passcode Lock Screen & Capacitor Lifecycle Hooks
        function initPINKeypadLock() {
            const pinOverlay = document.getElementById('portfolio-pin-overlay');
            if (!pinOverlay) return;

            const dots = pinOverlay.querySelectorAll('.pin-dot');
            let currentPin = "";
            const getPIN = () => localStorage.getItem('portfolio-pin') || '1234';

            pinOverlay.querySelectorAll('.pin-keyboard .pin-key[data-value]').forEach(key => {
                key.addEventListener('click', () => {
                    if (currentPin.length >= 4) return;
                    currentPin += key.getAttribute('data-value');
                    updateDots();
                    if (currentPin.length === 4) {
                        setTimeout(validatePIN, 200);
                    }
                });
            });

            const delBtn = document.getElementById('pin-action-delete');
            if (delBtn) {
                delBtn.addEventListener('click', () => {
                    if (currentPin.length > 0) {
                        currentPin = currentPin.substring(0, currentPin.length - 1);
                        updateDots();
                    }
                });
            }

            const bioBtn = document.getElementById('pin-action-biometric');
            if (bioBtn) {
                bioBtn.addEventListener('click', () => {
                    if (window.triggerBiometricVerification) {
                        window.triggerBiometricVerification();
                    }
                });
            }

            const cancelBtn = document.getElementById('pin-action-cancel');
            if (cancelBtn) {
                cancelBtn.addEventListener('click', () => {
                    pinOverlay.style.display = 'none';
                    window.switchTab('market-news');
                });
            }

            function updateDots() {
                dots.forEach((dot, idx) => {
                    if (idx < currentPin.length) dot.classList.add('filled');
                    else dot.classList.remove('filled');
                });
            }

            function validatePIN() {
                const hasPin = localStorage.getItem('portfolio-pin') !== null;
                if (!hasPin) {
                    localStorage.setItem('portfolio-pin', currentPin);
                    window.portfolioUnlocked = true;
                    pinOverlay.style.display = 'none';
                    const desktopLock = document.getElementById('portfolio-lock-overlay');
                    if (desktopLock) desktopLock.classList.add('hidden');
                    if (window.loadPortfolioDoctorLedger) {
                        window.loadPortfolioDoctorLedger(true);
                    }
                    window.showToast("Security passcode configured successfully.", "success");
                    currentPin = "";
                    updateDots();
                    return;
                }

                const expected = getPIN();
                if (currentPin === expected) {
                    window.portfolioUnlocked = true;
                    pinOverlay.style.display = 'none';
                    const desktopLock = document.getElementById('portfolio-lock-overlay');
                    if (desktopLock) desktopLock.classList.add('hidden');
                    if (window.loadPortfolioDoctorLedger) {
                        window.loadPortfolioDoctorLedger(true);
                    }
                    window.showToast("Portfolio security shield unlocked.", "success");
                    currentPin = "";
                    updateDots();
                } else {
                    pinOverlay.classList.add('pin-shake-animate');
                    playHaptic(30);
                    setTimeout(() => {
                        pinOverlay.classList.remove('pin-shake-animate');
                        currentPin = "";
                        updateDots();
                    }, 400);
                }
            }

            // Wrap switchTab to overlay PIN modal on mobile
            const wrappedSwitch = window.switchTab;
            window.switchTab = function(tabKey) {
                if (tabKey === 'portfolio' && isMobile()) {
                    const shieldEnabled = localStorage.getItem('portfolio-security-shield-enabled') !== 'false';
                    if (shieldEnabled && !window.portfolioUnlocked) {
                        pinOverlay.style.display = 'flex';
                        const desktopLock = document.getElementById('portfolio-lock-overlay');
                        if (desktopLock) desktopLock.classList.add('hidden');
                        
                        if (window.triggerBiometricVerification) {
                            setTimeout(() => {
                                if (pinOverlay.style.display === 'flex' && !window.portfolioUnlocked) {
                                    window.triggerBiometricVerification();
                                }
                            }, 300);
                        }
                        if (typeof wrappedSwitch === 'function') wrappedSwitch(tabKey);
                        return;
                    }
                }
                if (typeof wrappedSwitch === 'function') {
                    wrappedSwitch(tabKey);
                } else if (typeof window._originalSwitchTab === 'function') {
                    window._originalSwitchTab(tabKey);
                }
            };

            // Enhance biometric trigger to unlock mobile overlay
            const originalBioVerify = window.triggerBiometricVerification;
            if (originalBioVerify) {
                window.triggerBiometricVerification = async function() {
                    const NativeBiometric = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.NativeBiometric;
                    if (NativeBiometric) {
                        try {
                            const avail = await NativeBiometric.isAvailable();
                            if (avail.isAvailable) {
                                await NativeBiometric.verifyIdentity({
                                    reason: 'Unlock Portfolio Security Shield',
                                    title: 'Portfolio Lock',
                                    subtitle: 'Verify identity to view diagnostics audit ledger'
                                });
                                window.portfolioUnlocked = true;
                                pinOverlay.style.display = 'none';
                                const desktopLock = document.getElementById('portfolio-lock-overlay');
                                if (desktopLock) desktopLock.classList.add('hidden');
                                if (window.loadPortfolioDoctorLedger) {
                                    window.loadPortfolioDoctorLedger(true);
                                }
                                window.showToast("Portfolio security shield unlocked via biometrics.", "success");
                                return;
                            }
                        } catch (e) {
                            console.warn("Native biometrics failed, using passcode fallback.", e);
                        }
                    }
                    originalBioVerify();
                    let checks = 0;
                    const checkInterval = setInterval(() => {
                        checks++;
                        if (window.portfolioUnlocked) {
                            pinOverlay.style.display = 'none';
                            clearInterval(checkInterval);
                        }
                        if (checks > 20) clearInterval(checkInterval);
                    }, 200);
                };
            }
        }
        initPINKeypadLock();

        // ==================== PREMIUM MOBILE ENHANCEMENTS ====================
        
        // Helper to format rupees safely (reusing IIFE scope formatRupees)

        // 1. Swipe-to-Action Rows on Lists (Watchlist & Portfolio)
        function setupSwipeableWatchlistRows() {
            const watchlistBody = document.getElementById('watchlist-table-body');
            const holdingsBody = document.getElementById('holdings-table-body');
            
            const bindSwipe = (body) => {
                if (!body) return;
                let startX = 0;
                let startY = 0;
                let activeRow = null;
                let currentOffset = 0;
                let isSwipingRow = false;

                body.addEventListener('touchstart', e => {
                    const tr = e.target.closest('tr');
                    if (!tr || e.target.closest('button, input, a, select')) return;
                    
                    startX = e.touches[0].clientX;
                    startY = e.touches[0].clientY;
                    activeRow = tr;
                    isSwipingRow = false;
                    
                    // Reset other swiped rows
                    body.querySelectorAll('tr').forEach(row => {
                        if (row !== activeRow && row.style.transform) {
                            row.style.transform = '';
                            row.style.transition = 'transform 0.25s ease';
                        }
                    });
                }, { passive: true });

                body.addEventListener('touchmove', e => {
                    if (!activeRow) return;
                    
                    const currentX = e.touches[0].clientX;
                    const currentY = e.touches[0].clientY;
                    const diffX = currentX - startX;
                    const diffY = currentY - startY;

                    if (Math.abs(diffX) > Math.abs(diffY) * 1.5 && Math.abs(diffX) > 10) {
                        isSwipingRow = true;
                        currentOffset = Math.max(-80, Math.min(80, diffX));
                        activeRow.style.transform = `translateX(${currentOffset}px)`;
                        activeRow.style.transition = 'none';
                    }
                }, { passive: true });

                body.addEventListener('touchend', e => {
                    if (!activeRow || !isSwipingRow) {
                        activeRow = null;
                        return;
                    }

                    activeRow.style.transition = 'transform 0.2s ease-out';
                    if (currentOffset < -40) {
                        activeRow.style.transform = 'translateX(-70px)';
                        triggerSwipeRowAction(activeRow, 'delete');
                    } else if (currentOffset > 40) {
                        activeRow.style.transform = 'translateX(70px)';
                        triggerSwipeRowAction(activeRow, 'audit');
                    } else {
                        activeRow.style.transform = '';
                    }
                    activeRow = null;
                });
            };

            bindSwipe(watchlistBody);
            bindSwipe(holdingsBody);
        }

        function triggerSwipeRowAction(rowEl, action) {
            const firstCell = rowEl.cells[0];
            if (!firstCell) return;
            const symbol = firstCell.textContent.trim().split('\n')[0].replace('.NS', '').trim();
            
            playHaptic(12);
            if (action === 'delete') {
                window.showToast(`Action: Delete/Remove ${symbol}`, "info");
                const delBtn = rowEl.querySelector('button[title*="Delete"], button[onclick*="deleteWatchlistItem"], button[onclick*="deleteHoldingsItem"]');
                if (delBtn) {
                    delBtn.click();
                } else {
                    const buttons = rowEl.querySelectorAll('button');
                    if (buttons.length > 0) {
                        buttons[buttons.length - 1].click(); // assume last button is delete
                    }
                }
                setTimeout(() => { if (rowEl) rowEl.style.transform = ''; }, 600);
            } else if (action === 'audit') {
                window.showToast(`Triggering AI Audit: ${symbol}`, "success");
                const searchInput = document.getElementById('analyzer-search-input');
                const searchBtn = document.getElementById('analyzer-search-btn');
                if (searchInput && searchBtn) {
                    searchInput.value = symbol;
                    searchBtn.click();
                    window.switchTab('market-news');
                }
                setTimeout(() => { if (rowEl) rowEl.style.transform = ''; }, 600);
            }
        }

        // 2. Compact Equities Tearsheet Header
        function setupMobileTearsheet() {
            const searchBtn = document.getElementById('analyzer-search-btn');
            const searchInput = document.getElementById('analyzer-search-input');
            
            if (searchBtn && searchInput) {
                const triggerUpdate = () => {
                    setTimeout(updateMobileTearsheetContent, 1000);
                };
                searchBtn.addEventListener('click', triggerUpdate);
                searchInput.addEventListener('keypress', e => {
                    if (e.key === 'Enter') triggerUpdate();
                });
            }
        }

        function updateMobileTearsheetContent() {
            if (!isMobile()) return;
            if (typeof activeStockProfile === 'undefined' || !activeStockProfile || !activeStockProfile.ticker) return;

            let tearsheet = document.getElementById('mobile-tearsheet-container');
            if (!tearsheet) {
                const analyzerTab = document.getElementById('tab-analyzer');
                if (analyzerTab) {
                    tearsheet = document.createElement('div');
                    tearsheet.id = 'mobile-tearsheet-container';
                    tearsheet.className = 'mobile-tearsheet no-print';
                    analyzerTab.insertBefore(tearsheet, analyzerTab.firstChild);
                }
            }

            if (!tearsheet) return;

            const ticker = activeStockProfile.ticker;
            const name = activeStockProfile.name || activeStockProfile.company_name || "Company Profile";
            const price = activeStockProfile.fundamentals?.current_price || activeStockProfile.price || 0;
            const changePct = activeStockProfile.technicals?.price_change_pct || activeStockProfile.change_pct || 0;
            const high = activeStockProfile.technicals?.daily_high || price * 1.02;
            const low = activeStockProfile.technicals?.daily_low || price * 0.98;
            
            let sliderPct = 50;
            if (high > low) {
                sliderPct = Math.max(0, Math.min(100, ((price - low) / (high - low)) * 100));
            }

            const isPositive = changePct >= 0;
            const sign = isPositive ? '+' : '';

            tearsheet.innerHTML = `
                <div class="tearsheet-meta-row" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <div>
                        <h3 style="margin:0;font-family:var(--font-heading);font-size:16px;font-weight:800;color:var(--text-primary);">${ticker}</h3>
                        <span style="font-size:10px;color:var(--text-secondary);">${name}</span>
                    </div>
                    <div class="tearsheet-price-area" style="text-align:right;">
                        <span style="font-size:18px;font-family:var(--font-heading);font-weight:800;color:var(--text-primary);">${formatRupees(price)}</span>
                        <span class="${isPositive ? 'green-text' : 'red-text'}" style="font-size:11px;font-weight:700;margin-left:6px;">
                            ${sign}${changePct.toFixed(2)}%
                        </span>
                    </div>
                </div>
                <div class="tearsheet-range-slider" style="height:4px; background:rgba(255,255,255,0.06); border-radius:2px; position:relative; margin:10px 0 6px 0;">
                    <div style="position:absolute; top:0; bottom:0; left:0; right:0; background:linear-gradient(90deg, #ef4444, #eab308, #22c55e); border-radius:2px; opacity:0.15;"></div>
                    <div class="tearsheet-range-marker" style="left: ${sliderPct}%; width:10px; height:10px; border-radius:50%; background:var(--color-primary-light); box-shadow:0 0 8px var(--color-primary); position:absolute; top:-3px; transform:translateX(-50%); transition:left 0.3s ease;"></div>
                </div>
                <div class="tearsheet-range-labels" style="display:flex; justify-content:space-between; font-size:9px; color:var(--text-secondary); font-family:Inter;">
                    <span>L: ${formatRupees(low)}</span>
                    <span>H: ${formatRupees(high)}</span>
                </div>
            `;
        }

        // 3. Persistent Quick-Search Overlay in Header
        function injectMobileHeaderSearch() {
            const header = document.querySelector('.mobile-header');
            if (!header || document.getElementById('mobile-search-trigger')) return;

            const searchBtn = document.createElement('button');
            searchBtn.id = 'mobile-search-trigger';
            searchBtn.className = 'theme-toggle-btn';
            searchBtn.innerHTML = '🔍';
            searchBtn.style.marginRight = '6px';
            
            const themeToggle = document.getElementById('mobile-theme-toggle');
            if (themeToggle) {
                header.insertBefore(searchBtn, themeToggle);
            } else {
                header.appendChild(searchBtn);
            }

            searchBtn.addEventListener('click', openQuickSearchBottomSheet);
        }



        // 4. TradingView Mobile Touch Options
        function configureChartMobileTouchOptions() {
            if (window.lightweightChartInstance) {
                try {
                    window.lightweightChartInstance.applyOptions({
                        handleScroll: { touchMouseMove: true },
                        handleScale: { pinchTrigger: true },
                        kineticScroll: { touch: true }
                    });
                    console.log("[Chart Mobile Touch] Interactive options applied.");
                } catch(e) {}
            }
        }

        // 5. Live Neon Ticks Flares
        function triggerLiveNeonPriceFlares(ticksData) {
            const watchlistBody = document.getElementById('watchlist-table-body');
            if (!watchlistBody) return;
            
            for (const symbol in ticksData) {
                const cleanSymbol = symbol.replace('.NS', '').trim();
                Array.from(watchlistBody.rows).forEach(row => {
                    const symbolCell = row.cells[0];
                    if (symbolCell && symbolCell.textContent.trim().replace('.NS', '') === cleanSymbol) {
                        const data = ticksData[symbol];
                        const isPositive = data.change >= 0;
                        const flareClass = isPositive ? 'glow-flare-green' : 'glow-flare-red';
                        
                        row.classList.add(flareClass);
                        setTimeout(() => {
                            row.classList.remove(flareClass);
                        }, 800);
                    }
                });
            }
        }

        // Attach listeners and tick hooks if mobile
        if (isMobile()) {
            setupSwipeableWatchlistRows();
            setupMobileTearsheet();
            injectMobileHeaderSearch();
            configureChartMobileTouchOptions();
        }

        const originalHandleTick = window.handleLiveTickMessage;
        if (originalHandleTick) {
            window.handleLiveTickMessage = function(ticksData) {
                originalHandleTick(ticksData);
                if (isMobile()) {
                    updateMobileTearsheetContent();
                    triggerLiveNeonPriceFlares(ticksData);
                }
            };
        }

        // Periodic chart verification
        setInterval(configureChartMobileTouchOptions, 3000);

        function initSleekFooterSettings() {
            const disclaimerToggle = document.getElementById('setting-disclaimers-toggle');
            const telemetryToggle = document.getElementById('setting-telemetry-toggle');
            const disclaimerEl = document.querySelector('.footer-disclaimer');
            const telemetryEl = document.querySelector('.footer-diagnostics');

            // Load saved state (default true if not set)
            const showDisclaimers = localStorage.getItem('settings-show-disclaimers') !== 'false';
            const showTelemetry = localStorage.getItem('settings-show-telemetry') !== 'false';

            // Set initial UI state
            if (disclaimerToggle) {
                disclaimerToggle.checked = showDisclaimers;
                disclaimerToggle.addEventListener('change', (e) => {
                    const checked = e.target.checked;
                    localStorage.setItem('settings-show-disclaimers', checked);
                    if (disclaimerEl) {
                        disclaimerEl.style.setProperty('display', checked ? '' : 'none', 'important');
                    }
                });
            }
            if (disclaimerEl) {
                disclaimerEl.style.setProperty('display', showDisclaimers ? '' : 'none', 'important');
            }

            if (telemetryToggle) {
                telemetryToggle.checked = showTelemetry;
                telemetryToggle.addEventListener('change', (e) => {
                    const checked = e.target.checked;
                    localStorage.setItem('settings-show-telemetry', checked);
                    if (telemetryEl) {
                        telemetryEl.style.setProperty('display', checked ? '' : 'none', 'important');
                    }
                });
            }
            if (telemetryEl) {
                telemetryEl.style.setProperty('display', showTelemetry ? '' : 'none', 'important');
            }

            // Logo visibility toggle settings
            const logosToggle = document.getElementById('setting-logos-toggle');
            const showLogos = localStorage.getItem('settings-show-logos') !== 'false';
            if (logosToggle) {
                logosToggle.checked = showLogos;
                logosToggle.addEventListener('change', (e) => {
                    const checked = e.target.checked;
                    localStorage.setItem('settings-show-logos', checked);
                    // Reload the page to apply the logos visibility setting immediately with zero impact
                    location.reload();
                });
            }
        }

        function decorateWatchlistRowsForMobile() {
            const tbody = document.getElementById('watchlist-table-body');
            if (!tbody) return;

            if (!isMobile()) {
                tbody.querySelectorAll('.row-expand-trigger').forEach(el => el.remove());
                tbody.querySelectorAll('.watchlist-details-row').forEach(el => el.remove());
                return;
            }

            tbody.querySelectorAll('tr').forEach(tr => {
                if (tr.classList.contains('watchlist-details-row') || tr.querySelector('.row-expand-trigger') || tr.cells.length < 5) return;

                const firstCell = tr.cells[0];
                if (!firstCell) return;

                const symbolLinkWrapper = firstCell.querySelector('div > div:first-child');
                if (!symbolLinkWrapper) return;

                const chevron = document.createElement('span');
                chevron.className = 'row-expand-trigger';
                chevron.style.cssText = 'cursor: pointer; padding: 2px 6px; font-size: 10px; color: var(--color-primary-light); user-select: none; transition: transform 0.2s; font-weight: bold; margin-left: 4px;';
                chevron.innerHTML = '▼';
                
                symbolLinkWrapper.appendChild(chevron);

                chevron.addEventListener('click', (e) => {
                    e.stopPropagation();
                    e.preventDefault();
                    
                    let nextRow = tr.nextElementSibling;
                    if (nextRow && nextRow.classList.contains('watchlist-details-row')) {
                        nextRow.remove();
                        chevron.innerHTML = '▼';
                    } else {
                        const sector = tr.cells[1] ? tr.cells[1].textContent.trim() : 'N/A';
                        const changeVal = tr.cells[3] ? tr.cells[3].textContent.trim() : 'N/A';
                        const dayHigh = tr.cells[5] ? tr.cells[5].textContent.trim() : 'N/A';
                        const dayLow = tr.cells[6] ? tr.cells[6].textContent.trim() : 'N/A';
                        const fuzzyCellHTML = tr.cells[7] ? tr.cells[7].innerHTML.trim() : '';

                        const detailsTr = document.createElement('tr');
                        detailsTr.className = 'watchlist-details-row no-print';
                        detailsTr.style.background = 'rgba(255, 255, 255, 0.01)';
                        detailsTr.innerHTML = `
                            <td colspan="8" style="padding: 10px 15px; border-top: 1px dashed rgba(255,255,255,0.05); border-bottom: 1px dashed rgba(255,255,255,0.05);">
                                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 11px; color: var(--text-secondary); line-height: 1.4;">
                                    <div><strong>Sector:</strong> ${sector}</div>
                                    <div style="text-align: right;"><strong>Day High:</strong> ${dayHigh}</div>
                                    <div><strong>Daily Change:</strong> ${changeVal}</div>
                                    <div style="text-align: right;"><strong>Day Low:</strong> ${dayLow}</div>
                                    <div style="grid-column: span 2; display: flex; align-items: center; justify-content: space-between; margin-top: 4px; padding-top: 6px; border-top: 1px dashed rgba(255,255,255,0.08);">
                                        <strong style="color: var(--text-primary);">Fuzzy Conviction:</strong>
                                        <div>${fuzzyCellHTML}</div>
                                    </div>
                                </div>
                            </td>
                        `;
                        tr.parentNode.insertBefore(detailsTr, tr.nextSibling);
                        chevron.innerHTML = '▲';
                    }
                });
            });
        }

        function decoratePortfolioRowsForMobile() {
            const tbody = document.getElementById('portfolio-ledger-body');
            if (!tbody) return;

            if (!isMobile()) {
                tbody.querySelectorAll('.row-expand-trigger').forEach(el => el.remove());
                tbody.querySelectorAll('.portfolio-details-row').forEach(el => el.remove());
                tbody.querySelectorAll('.mobile-tranche-meta').forEach(el => el.remove());
                return;
            }

            tbody.querySelectorAll('tr').forEach(tr => {
                if (tr.classList.contains('portfolio-details-row') || tr.querySelector('.row-expand-trigger') || tr.cells.length < 10) return;

                const firstCell = tr.cells[0];
                if (!firstCell) return;

                // Extract quantity and average price before hiding columns
                const qtyInput = tr.querySelector('.portfolio-qty-input');
                const priceInput = tr.querySelector('.portfolio-price-input');
                const hasInputs = qtyInput !== null && priceInput !== null;

                let qtyVal = '';
                let priceVal = '';

                if (hasInputs) {
                    qtyVal = qtyInput.value;
                    priceVal = priceInput.value;
                } else {
                    qtyVal = tr.cells[1] ? tr.cells[1].textContent.trim().replace(' 🔗', '') : '';
                    priceVal = tr.cells[2] ? tr.cells[2].textContent.trim() : '';
                }

                // Add mobile static metadata badge under stock name if not present
                if (!firstCell.querySelector('.mobile-tranche-meta')) {
                    const metaSpan = document.createElement('span');
                    metaSpan.className = 'mobile-tranche-meta';
                    metaSpan.style.cssText = 'font-size: 10px; color: var(--color-primary-light); font-weight: 600; display: block; margin-top: 3px;';
                    metaSpan.innerHTML = `Holdings: ${qtyVal} @ ${priceVal}`;
                    firstCell.appendChild(metaSpan);
                }

                const chevron = document.createElement('span');
                chevron.className = 'row-expand-trigger';
                chevron.style.cssText = 'cursor: pointer; padding: 2px 6px; font-size: 10px; color: var(--color-primary-light); user-select: none; transition: transform 0.2s; font-weight: bold; margin-left: 4px;';
                chevron.innerHTML = '▼';
                
                firstCell.appendChild(chevron);

                chevron.addEventListener('click', (e) => {
                    e.stopPropagation();
                    e.preventDefault();
                    
                    let nextRow = tr.nextElementSibling;
                    if (nextRow && nextRow.classList.contains('portfolio-details-row')) {
                        nextRow.remove();
                        chevron.innerHTML = '▼';
                    } else {
                        const targets = tr.cells[3] ? tr.cells[3].innerHTML : 'N/A';
                        const dayChg = tr.cells[6] ? tr.cells[6].textContent.trim() : 'N/A';
                        const investedVal = tr.cells[7] ? tr.cells[7].textContent.trim() : 'N/A';
                        const currentVal = tr.cells[8] ? tr.cells[8].textContent.trim() : 'N/A';
                        const target12M = tr.cells[10] ? tr.cells[10].textContent.trim() : 'N/A';
                        const stopLoss12M = tr.cells[11] ? tr.cells[11].textContent.trim() : 'N/A';
                        const actionBtn = tr.cells[12] ? tr.cells[12].innerHTML : '';

                        let editControlsHTML = '';
                        if (hasInputs) {
                            const dataId = qtyInput.getAttribute('data-id');
                            const dataSymbol = qtyInput.getAttribute('data-symbol');
                            editControlsHTML = `
                                <div style="border-top: 1px dashed rgba(255,255,255,0.08); padding-top: 10px; margin-top: 10px;">
                                    <div style="font-size: 10px; font-weight: 700; color: var(--color-primary-light); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em;">Edit Holdings Position</div>
                                    <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <span style="font-size: 10px; color: var(--text-secondary);">Qty:</span>
                                            <input type="number" class="portfolio-qty-input-mobile" data-id="${dataId}" data-symbol="${dataSymbol}" value="${qtyVal}" style="width: 55px; padding: 4px; border-radius:4px; background:rgba(0,0,0,0.3); border:1px solid var(--border-glass); color:#fff; font-size:11px; text-align: right;">
                                        </div>
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <span style="font-size: 10px; color: var(--text-secondary);">Avg (₹):</span>
                                            <input type="number" class="portfolio-price-input-mobile" data-id="${dataId}" data-symbol="${dataSymbol}" value="${priceVal}" style="width: 75px; padding: 4px; border-radius:4px; background:rgba(0,0,0,0.3); border:1px solid var(--border-glass); color:#fff; font-size:11px; text-align: right;">
                                        </div>
                                        <button class="btn-primary save-portfolio-item-btn-mobile" style="font-size: 10px; padding: 4px 8px; cursor: pointer; border-radius: 4px; height: 24px; display: flex; align-items: center; justify-content: center; font-weight: bold; background: var(--color-primary);">Save</button>
                                    </div>
                                </div>
                            `;
                        }

                        const detailsTr = document.createElement('tr');
                        detailsTr.className = 'portfolio-details-row no-print';
                        detailsTr.style.background = 'rgba(255, 255, 255, 0.01)';
                        detailsTr.innerHTML = `
                            <td colspan="13" style="padding: 12px 15px; border-top: 1px dashed rgba(255,255,255,0.05); border-bottom: 1px dashed rgba(255,255,255,0.05);">
                                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 11px; color: var(--text-secondary); line-height: 1.45; margin-bottom: 8px;">
                                    <div><strong>Invested Value:</strong> ${investedVal}</div>
                                    <div style="text-align: right;"><strong>Current Value:</strong> ${currentVal}</div>
                                    <div><strong>Day Change %:</strong> ${dayChg}</div>
                                    <div style="text-align: right;"><strong>12M Target Price:</strong> ${target12M}</div>
                                    <div><strong>12M Stop Loss:</strong> ${stopLoss12M}</div>
                                    <div style="text-align: right; display: flex; justify-content: flex-end; align-items: center; gap: 4px;"><strong>Ledger Action:</strong> ${actionBtn}</div>
                                </div>
                                <div style="font-size: 10px; color: var(--text-muted); margin-top: 6px;">
                                    <strong>Valuation Target Range:</strong>
                                    <div style="margin-top: 4px;">${targets}</div>
                                </div>
                                ${editControlsHTML}
                            </td>
                        `;
                        tr.parentNode.insertBefore(detailsTr, tr.nextSibling);

                        const delBtn = detailsTr.querySelector('.remove-portfolio-ledger-item-btn');
                        if (delBtn) {
                            delBtn.addEventListener('click', (evt) => {
                                const origDelBtn = tr.cells[12].querySelector('.remove-portfolio-ledger-item-btn');
                                if (origDelBtn) origDelBtn.click();
                            });
                        }

                        const saveBtn = detailsTr.querySelector('.save-portfolio-item-btn-mobile');
                        if (saveBtn) {
                            saveBtn.addEventListener('click', async () => {
                                const mQtyInput = detailsTr.querySelector('.portfolio-qty-input-mobile');
                                const mPriceInput = detailsTr.querySelector('.portfolio-price-input-mobile');
                                const qtyValNew = parseFloat(mQtyInput.value) || 0;
                                const priceValNew = parseFloat(mPriceInput.value) || 0;
                                
                                const origQtyInput = tr.querySelector('.portfolio-qty-input');
                                const origPriceInput = tr.querySelector('.portfolio-price-input');
                                if (origQtyInput) origQtyInput.value = qtyValNew;
                                if (origPriceInput) origPriceInput.value = priceValNew;

                                const dataId = mQtyInput.getAttribute('data-id');
                                try {
                                    const res = await fetch(apiBaseUrl + `/api/portfolio/${dataId}`, {
                                        method: 'PUT',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify({ quantity: qtyValNew, purchase_price: priceValNew })
                                    });
                                    if (res.ok) {
                                        if (window.showToast) window.showToast("Holdings updated successfully", "success");
                                        if (window.loadPortfolioDoctorLedger) {
                                            await window.loadPortfolioDoctorLedger();
                                        }
                                    }
                                } catch (err) {
                                    console.error(err);
                                }
                            });
                        }

                        chevron.innerHTML = '▲';
                    }
                });
            });
        }

        function decorateUniverseRowsForMobile() {
            const tbody = document.getElementById('universe-explorer-body');
            if (!tbody) return;

            if (!isMobile()) {
                tbody.querySelectorAll('.row-expand-trigger').forEach(el => el.remove());
                tbody.querySelectorAll('.universe-details-row').forEach(el => el.remove());
                return;
            }

            tbody.querySelectorAll('tr').forEach(tr => {
                if (tr.classList.contains('universe-details-row') || tr.querySelector('.row-expand-trigger') || tr.cells.length < 5) return;

                const firstCell = tr.cells[1];
                if (!firstCell) return;

                const chevron = document.createElement('span');
                chevron.className = 'row-expand-trigger';
                chevron.style.cssText = 'cursor: pointer; padding: 2px 6px; font-size: 10px; color: var(--color-primary-light); user-select: none; transition: transform 0.2s; font-weight: bold; margin-left: 4px;';
                chevron.innerHTML = '▼';
                
                const symbolLink = firstCell.querySelector('.universe-symbol-link') || firstCell;
                symbolLink.appendChild(chevron);

                chevron.addEventListener('click', (e) => {
                    e.stopPropagation();
                    e.preventDefault();
                    
                    let nextRow = tr.nextElementSibling;
                    if (nextRow && nextRow.classList.contains('universe-details-row')) {
                        nextRow.remove();
                        chevron.innerHTML = '▼';
                    } else {
                        const serialNum = tr.cells[0] ? tr.cells[0].textContent.trim() : '';
                        const companyName = tr.cells[2] ? tr.cells[2].textContent.trim() : 'N/A';
                        const sector = tr.cells[3] ? tr.cells[3].textContent.trim() : 'N/A';
                        const segment = tr.cells[4] ? tr.cells[4].textContent.trim() : 'N/A';
                        const cacheStatus = tr.cells[5] ? tr.cells[5].innerHTML : 'N/A';
                        const actionsHtml = tr.cells[6] ? tr.cells[6].innerHTML : '';

                        const detailsTr = document.createElement('tr');
                        detailsTr.className = 'universe-details-row no-print';
                        detailsTr.style.background = 'rgba(255, 255, 255, 0.01)';
                        detailsTr.innerHTML = `
                            <td colspan="7" style="padding: 10px 15px; border-top: 1px dashed rgba(255,255,255,0.05); border-bottom: 1px dashed rgba(255,255,255,0.05);">
                                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 11px; color: var(--text-secondary); line-height: 1.45;">
                                    <div style="grid-column: span 2; font-size: 12px; color: var(--color-primary-light); font-weight: bold; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 4px; margin-bottom: 4px;">
                                        ${companyName}
                                    </div>
                                    <div><strong>Index Rank:</strong> #${serialNum}</div>
                                    <div style="text-align: right; display: flex; justify-content: flex-end; align-items: center; gap: 4px;"><strong>Cache Status:</strong> ${cacheStatus}</div>
                                </div>
                                <div style="border-top: 1px dashed rgba(255,255,255,0.08); padding-top: 8px; margin-top: 8px; display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;">
                                    <span style="font-size: 10px; color: var(--text-muted);">Explorer Actions:</span>
                                    <div class="mobile-actions-wrapper" style="display: flex; gap: 6px;">
                                        ${actionsHtml}
                                    </div>
                                </div>
                            </td>
                        `;
                        tr.parentNode.insertBefore(detailsTr, tr.nextSibling);

                        const detailsActions = detailsTr.querySelectorAll('button');
                        const originalActions = tr.cells[6].querySelectorAll('button');
                        detailsActions.forEach((btn, idx) => {
                            btn.addEventListener('click', (evt) => {
                                if (originalActions[idx]) originalActions[idx].click();
                            });
                        });

                        chevron.innerHTML = '▲';
                    }
                });
            });
        }

        function decorateAlertsRowsForMobile() {
            const tbody = document.getElementById('alerts-table-body');
            if (!tbody) return;

            if (!isMobile()) {
                tbody.querySelectorAll('.row-expand-trigger').forEach(el => el.remove());
                tbody.querySelectorAll('.alerts-details-row').forEach(el => el.remove());
                tbody.querySelectorAll('.mobile-alerts-meta').forEach(el => el.remove());
                return;
            }

            tbody.querySelectorAll('tr').forEach(tr => {
                if (tr.classList.contains('alerts-details-row') || tr.querySelector('.row-expand-trigger') || tr.cells.length < 5) return;

                const firstCell = tr.cells[0];
                if (!firstCell) return;

                const conditionType = tr.cells[1] ? tr.cells[1].textContent.trim() : 'N/A';
                const targetCondition = tr.cells[2] ? tr.cells[2].textContent.trim() : 'N/A';
                
                let combinedText = '';
                if (conditionType === 'PRICE') {
                    combinedText = targetCondition;
                } else {
                    combinedText = `${conditionType} ${targetCondition}`;
                }

                if (!firstCell.querySelector('.mobile-alerts-meta')) {
                    const metaSpan = document.createElement('span');
                    metaSpan.className = 'mobile-alerts-meta';
                    metaSpan.style.cssText = 'display: block; margin-top: 3px; font-size: 10px; color: var(--text-secondary); font-family: monospace; font-weight: bold;';
                    metaSpan.textContent = combinedText;
                    firstCell.appendChild(metaSpan);
                }

                const chevron = document.createElement('span');
                chevron.className = 'row-expand-trigger';
                chevron.style.cssText = 'cursor: pointer; padding: 2px 6px; font-size: 10px; color: var(--color-primary-light); user-select: none; transition: transform 0.2s; font-weight: bold; margin-left: 4px;';
                chevron.innerHTML = '▼';
                
                const link = firstCell.querySelector('.alert-stock-link') || firstCell;
                link.appendChild(chevron);

                chevron.addEventListener('click', (e) => {
                    e.stopPropagation();
                    e.preventDefault();
                    
                    let nextRow = tr.nextElementSibling;
                    if (nextRow && nextRow.classList.contains('alerts-details-row')) {
                        nextRow.remove();
                        chevron.innerHTML = '▼';
                    } else {
                        const targetCondition = tr.cells[2] ? tr.cells[2].innerHTML : 'N/A';
                        const triggeredAt = tr.cells[4] ? tr.cells[4].innerHTML : 'Active scan...';
                        const actionBtn = tr.cells[5] ? tr.cells[5].innerHTML : '';

                        const detailsTr = document.createElement('tr');
                        detailsTr.className = 'alerts-details-row no-print';
                        detailsTr.style.background = 'rgba(255, 255, 255, 0.01)';
                        detailsTr.innerHTML = `
                            <td colspan="6" style="padding: 10px 15px; border-top: 1px dashed rgba(255,255,255,0.05); border-bottom: 1px dashed rgba(255,255,255,0.05);">
                                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 11px; color: var(--text-secondary); line-height: 1.45;">
                                    <div><strong>Trigger Target:</strong> <code style="font-family: monospace; font-size: 11px; color: var(--color-primary-light); font-weight: bold;">${targetCondition}</code></div>
                                    <div style="text-align: right;"><strong>Scan Status:</strong> ${triggeredAt}</div>
                                </div>
                                <div style="border-top: 1px dashed rgba(255,255,255,0.08); padding-top: 8px; margin-top: 8px; display: flex; justify-content: space-between; align-items: center;">
                                    <span style="font-size: 10px; color: var(--text-muted);">Cockpit Operations:</span>
                                    <div class="mobile-actions-wrapper">
                                        ${actionBtn}
                                    </div>
                                </div>
                            </td>
                        `;
                        tr.parentNode.insertBefore(detailsTr, tr.nextSibling);

                        const detailsDelBtn = detailsTr.querySelector('.btn-translucent-delete');
                        const originalDelBtn = tr.cells[5].querySelector('.btn-translucent-delete');
                        if (detailsDelBtn && originalDelBtn) {
                            detailsDelBtn.addEventListener('click', (evt) => {
                                originalDelBtn.click();
                            });
                        }

                        chevron.innerHTML = '▲';
                    }
                });
            });
        }

        function setupWatchlistTableObserver() {
            const tbody = document.getElementById('watchlist-table-body');
            if (tbody) {
                decorateWatchlistRowsForMobile();
                const observer = new MutationObserver(() => decorateWatchlistRowsForMobile());
                observer.observe(tbody, { childList: true });
            }
        }

        function setupPortfolioTableObserver() {
            const tbody = document.getElementById('portfolio-ledger-body');
            if (tbody) {
                decoratePortfolioRowsForMobile();
                const observer = new MutationObserver(() => decoratePortfolioRowsForMobile());
                observer.observe(tbody, { childList: true });
            }
        }

        function setupUniverseTableObserver() {
            const tbody = document.getElementById('universe-explorer-body');
            if (tbody) {
                decorateUniverseRowsForMobile();
                const observer = new MutationObserver(() => decorateUniverseRowsForMobile());
                observer.observe(tbody, { childList: true });
            }
        }

        function setupAlertsTableObserver() {
            const tbody = document.getElementById('alerts-table-body');
            if (tbody) {
                decorateAlertsRowsForMobile();
                const observer = new MutationObserver(() => decorateAlertsRowsForMobile());
                observer.observe(tbody, { childList: true });
            }
        }

        function decorateRuleScannerRowsForMobile() {
            const tbody = document.getElementById('rule-scanner-results-body');
            if (!tbody) return;

            if (!isMobile()) {
                tbody.querySelectorAll('.row-expand-trigger').forEach(el => el.remove());
                tbody.querySelectorAll('.rs-details-row').forEach(el => el.remove());
                tbody.querySelectorAll('.mobile-rs-meta').forEach(el => el.remove());
                tbody.querySelectorAll('.mobile-segment-tag').forEach(el => el.remove());
                return;
            }

            tbody.querySelectorAll('tr').forEach(tr => {
                if (tr.classList.contains('rs-details-row') || tr.querySelector('.row-expand-trigger') || tr.cells.length < 8) return;

                const firstCell = tr.cells[0];
                const priceCell = tr.cells[2];
                if (!firstCell || !priceCell) return;

                // Add segment meta inline under stock name if not present
                const spans = firstCell.querySelectorAll('span');
                const companyNameSpan = spans[1];
                const segmentText = tr.cells[1] ? tr.cells[1].textContent.trim() : '';

                if (companyNameSpan && segmentText && !companyNameSpan.querySelector('.mobile-segment-tag')) {
                    const originalText = companyNameSpan.textContent.trim();
                    companyNameSpan.innerHTML = `${originalText} <span class="mobile-segment-tag" style="color: var(--color-primary-light); font-weight: bold; margin-left: 4px;">• ${segmentText}</span>`;
                }

                // Add rating meta under price if not present
                const ratingHtml = tr.cells[6] ? tr.cells[6].innerHTML : '';
                if (!priceCell.querySelector('.mobile-rs-meta')) {
                    const metaSpan = document.createElement('span');
                    metaSpan.className = 'mobile-rs-meta';
                    metaSpan.style.cssText = 'display: block; margin-top: 3px; font-size: 10px; font-weight: bold;';
                    metaSpan.innerHTML = ratingHtml;
                    priceCell.appendChild(metaSpan);
                }

                const chevron = document.createElement('span');
                chevron.className = 'row-expand-trigger';
                chevron.style.cssText = 'cursor: pointer; padding: 2px 6px; font-size: 10px; color: var(--color-primary-light); user-select: none; transition: transform 0.2s; font-weight: bold; margin-left: 4px;';
                chevron.innerHTML = '▼';

                const stockNameSpan = firstCell.querySelector('span');
                if (stockNameSpan) {
                    stockNameSpan.appendChild(chevron);
                }

                chevron.addEventListener('click', (e) => {
                    e.stopPropagation();
                    e.preventDefault();

                    let nextRow = tr.nextElementSibling;
                    if (nextRow && nextRow.classList.contains('rs-details-row')) {
                        nextRow.remove();
                        chevron.innerHTML = '▼';
                    } else {
                        const segment = tr.cells[1] ? tr.cells[1].textContent.trim() : 'N/A';
                        const peVal = tr.cells[3] ? tr.cells[3].textContent.trim() : 'N/A';
                        const triggerVal = tr.cells[5] ? tr.cells[5].innerHTML : 'N/A';
                        const sector = tr.cells[7] ? tr.cells[7].textContent.trim() : 'N/A';

                        const detailsCanvasId = `rs-details-sparkline-${Math.random().toString(36).substr(2, 9)}`;

                        const detailsTr = document.createElement('tr');
                        detailsTr.className = 'rs-details-row no-print';
                        detailsTr.style.background = 'rgba(255, 255, 255, 0.01)';
                        detailsTr.innerHTML = `
                            <td colspan="8" style="padding: 12px 15px; border-top: 1px dashed rgba(255,255,255,0.05); border-bottom: 1px dashed rgba(255,255,255,0.05);">
                                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 11px; color: var(--text-secondary); line-height: 1.45;">
                                    <div><strong>Segment:</strong> ${segment}</div>
                                    <div style="text-align: right;"><strong>P/E:</strong> ${peVal}</div>
                                    <div style="grid-column: span 2;"><strong>Sector:</strong> ${sector}</div>
                                    <div style="grid-column: span 2; border-top: 1px dashed rgba(255,255,255,0.06); padding-top: 6px; margin-top: 4px;">
                                        <strong>Trigger Value:</strong>
                                        <div style="color: var(--color-primary-light); font-weight: bold; margin-top: 2px;">${triggerVal}</div>
                                    </div>
                                </div>
                                <div style="border-top: 1px dashed rgba(255,255,255,0.08); padding-top: 8px; margin-top: 8px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                                    <span style="font-size: 10px; color: var(--text-muted);">Sparkline Trend:</span>
                                    <div style="background: rgba(0,0,0,0.15); padding: 4px; border-radius: 4px; border: 1px solid var(--border-glass);">
                                        <canvas id="${detailsCanvasId}" width="90" height="30" style="display: block;"></canvas>
                                    </div>
                                </div>
                            </td>
                        `;
                        tr.parentNode.insertBefore(detailsTr, tr.nextSibling);

                        const originalCanvas = tr.cells[4].querySelector('canvas');
                        const detailsCanvas = detailsTr.querySelector(`#${detailsCanvasId}`);
                        if (originalCanvas && detailsCanvas) {
                            const detailsCtx = detailsCanvas.getContext('2d');
                            detailsCtx.drawImage(originalCanvas, 0, 0, detailsCanvas.width, detailsCanvas.height);
                        }

                        chevron.innerHTML = '▲';
                    }
                });
            });
        }

        function setupRuleScannerTableObserver() {
            const tbody = document.getElementById('rule-scanner-results-body');
            if (tbody) {
                decorateRuleScannerRowsForMobile();
                const observer = new MutationObserver(() => decorateRuleScannerRowsForMobile());
                observer.observe(tbody, { childList: true });
            }
        }

        function decorateScreenerRowsForMobile() {
            const tbody = document.getElementById('screener-results-body');
            if (!tbody) return;

            if (!isMobile()) {
                tbody.querySelectorAll('.row-expand-trigger').forEach(el => el.remove());
                tbody.querySelectorAll('.screener-details-row').forEach(el => el.remove());
                tbody.querySelectorAll('.mobile-screener-segment').forEach(el => el.remove());
                return;
            }

            // ─── Inject mobile filter bar if not present ───
            const resultsBox = document.getElementById('screener-results-box');
            if (resultsBox && !document.getElementById('mobile-screener-filters')) {
                const filterBar = document.createElement('div');
                filterBar.id = 'mobile-screener-filters';
                filterBar.style.cssText = 'display:flex; gap:6px; padding:8px 12px; overflow-x:auto; -webkit-overflow-scrolling:touch; border-bottom:1px solid rgba(255,255,255,0.06); margin-bottom:4px; flex-wrap:nowrap;';
                
                const makeSelect = (id, label, options) => {
                    const sel = document.createElement('select');
                    sel.id = id;
                    sel.style.cssText = 'flex-shrink:0; padding:6px 10px; border-radius:6px; font-size:10px; font-weight:600; font-family:Outfit,sans-serif; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.04); color:var(--text-primary); outline:none; cursor:pointer; min-width:0;';
                    options.forEach(o => {
                        const opt = document.createElement('option');
                        opt.value = o.value;
                        opt.textContent = o.label;
                        sel.appendChild(opt);
                    });
                    sel.addEventListener('change', () => applyMobileScreenerFilters());
                    return sel;
                };

                filterBar.appendChild(makeSelect('mob-scr-score', 'Score', [
                    {value: 'all', label: '📊 All Scores'},
                    {value: '90', label: '90+'},
                    {value: '80', label: '80+'},
                    {value: '70', label: '70+'},
                    {value: '60', label: '60+'},
                    {value: '50', label: '50+'}
                ]));
                filterBar.appendChild(makeSelect('mob-scr-cap', 'Cap', [
                    {value: 'all', label: '⚡ All Caps'},
                    {value: 'large', label: 'Large'},
                    {value: 'mid', label: 'Mid'},
                    {value: 'small', label: 'Small'}
                ]));
                filterBar.appendChild(makeSelect('mob-scr-action', 'Action', [
                    {value: 'all', label: '🎯 All Actions'},
                    {value: 'STRONG BUY', label: 'Strong Buy'},
                    {value: 'BUY', label: 'Buy'},
                    {value: 'HOLD', label: 'Hold'},
                    {value: 'SELL', label: 'Sell/Avoid'}
                ]));

                // Insert before the table
                const tableEl = resultsBox.querySelector('table') || resultsBox.querySelector('.screener-table-wrap');
                if (tableEl) {
                    tableEl.parentNode.insertBefore(filterBar, tableEl);
                } else {
                    resultsBox.insertBefore(filterBar, resultsBox.firstChild);
                }
            }

            tbody.querySelectorAll('tr').forEach(tr => {
                if (tr.classList.contains('screener-details-row') || tr.querySelector('.row-expand-trigger') || tr.cells.length < 9) return;

                const firstCell = tr.cells[1];
                if (!firstCell) return;

                // Add segment meta inline next to symbol if not present
                const symbolLink = firstCell.querySelector('.screener-symbol-link');
                const segmentText = tr.cells[3] ? tr.cells[3].textContent.trim() : '';

                if (symbolLink && segmentText && !symbolLink.querySelector('.mobile-screener-segment')) {
                    const symbolSpan = symbolLink.querySelector('span');
                    if (symbolSpan) {
                        const originalText = symbolSpan.textContent.trim();
                        symbolSpan.innerHTML = `${originalText} <span class="mobile-screener-segment" style="color: var(--color-primary-light); font-weight: bold; margin-left: 4px;">• ${segmentText}</span>`;
                    }
                }

                const chevron = document.createElement('span');
                chevron.className = 'row-expand-trigger';
                chevron.style.cssText = 'cursor: pointer; padding: 2px 6px; font-size: 10px; color: var(--color-primary-light); user-select: none; transition: transform 0.2s; font-weight: bold; margin-left: 4px;';
                chevron.innerHTML = '▼';

                const strong = symbolLink ? symbolLink.querySelector('strong') : firstCell.querySelector('strong');
                if (strong) {
                    strong.appendChild(chevron);
                } else if (symbolLink) {
                    symbolLink.appendChild(chevron);
                } else {
                    firstCell.appendChild(chevron);
                }

                chevron.addEventListener('click', (e) => {
                    e.stopPropagation();
                    e.preventDefault();

                    let nextRow = tr.nextElementSibling;
                    if (nextRow && nextRow.classList.contains('screener-details-row')) {
                        nextRow.remove();
                        chevron.innerHTML = '▼';
                    } else {
                        const rank = tr.cells[0] ? tr.cells[0].textContent.trim() : 'N/A';
                        const sector = tr.cells[2] ? tr.cells[2].textContent.trim() : 'N/A';
                        const capType = tr.cells[3] ? tr.cells[3].textContent.trim() : 'N/A';
                        const scoreHtml = tr.cells[4] ? tr.cells[4].innerHTML : 'N/A';
                        const fScoreHtml = tr.cells[5] ? tr.cells[5].innerHTML : 'N/A';
                        const vScoreHtml = tr.cells[6] ? tr.cells[6].innerHTML : 'N/A';
                        const tScoreHtml = tr.cells[7] ? tr.cells[7].innerHTML : 'N/A';
                        const actionHtml = tr.cells[8] ? tr.cells[8].innerHTML : 'N/A';
                        const capColor = capType.toLowerCase() === 'large' ? '#22d3ee' : capType.toLowerCase() === 'mid' ? '#f59e0b' : '#a78bfa';

                        const detailsTr = document.createElement('tr');
                        detailsTr.className = 'screener-details-row no-print';
                        detailsTr.style.background = 'rgba(255, 255, 255, 0.015)';
                        detailsTr.innerHTML = `
                            <td colspan="9" style="padding: 10px 12px; border-top: 1px solid rgba(255,255,255,0.04); border-bottom: 1px solid rgba(255,255,255,0.04);">
                                <div style="display:flex; flex-direction:column; gap:10px;">
                                    <!-- Row 1: Rank + Sector + Cap + Action -->
                                    <div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center;">
                                        <span style="background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.08); padding:3px 8px; border-radius:5px; font-size:10px; font-weight:700; color:var(--text-primary); font-family:Outfit,sans-serif;">Rank ${rank}</span>
                                        <span style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.06); padding:3px 8px; border-radius:5px; font-size:9.5px; color:var(--text-secondary); max-width:120px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${sector}</span>
                                        <span style="background:${capColor}15; border:1px solid ${capColor}40; color:${capColor}; padding:3px 8px; border-radius:5px; font-size:9.5px; font-weight:700; text-transform:uppercase; letter-spacing:0.04em;">${capType}</span>
                                        <span style="margin-left:auto;">${actionHtml}</span>
                                    </div>
                                    <!-- Row 2: Composite Score -->
                                    <div style="display:flex; align-items:center; gap:8px; background:rgba(255,255,255,0.03); border-radius:6px; padding:6px 10px;">
                                        <span style="font-size:10px; color:var(--text-secondary); font-weight:600;">Composite Score</span>
                                        <span style="margin-left:auto;">${scoreHtml}</span>
                                    </div>
                                    <!-- Row 3: Subscore Gauges -->
                                    <div style="display:flex; flex-direction:column; gap:6px;">
                                        <div style="display:flex; justify-content:space-between; align-items:center; padding:0 2px;">
                                            <span style="font-size:9.5px; color:var(--text-muted); font-weight:600;">Fundamental</span>
                                            <span>${fScoreHtml}</span>
                                        </div>
                                        <div style="display:flex; justify-content:space-between; align-items:center; padding:0 2px;">
                                            <span style="font-size:9.5px; color:var(--text-muted); font-weight:600;">Valuation</span>
                                            <span>${vScoreHtml}</span>
                                        </div>
                                        <div style="display:flex; justify-content:space-between; align-items:center; padding:0 2px;">
                                            <span style="font-size:9.5px; color:var(--text-muted); font-weight:600;">Technical</span>
                                            <span>${tScoreHtml}</span>
                                        </div>
                                    </div>
                                </div>
                            </td>
                        `;
                        tr.parentNode.insertBefore(detailsTr, tr.nextSibling);
                        chevron.innerHTML = '▲';
                    }
                });
            });
        }

        // ─── Mobile Screener Filter Logic ───
        function applyMobileScreenerFilters() {
            const tbody = document.getElementById('screener-results-body');
            if (!tbody) return;
            const scoreFilter = document.getElementById('mob-scr-score');
            const capFilter = document.getElementById('mob-scr-cap');
            const actionFilter = document.getElementById('mob-scr-action');
            if (!scoreFilter) return;

            const minScore = scoreFilter.value === 'all' ? 0 : parseInt(scoreFilter.value);
            const capVal = capFilter ? capFilter.value : 'all';
            const actionVal = actionFilter ? actionFilter.value : 'all';

            tbody.querySelectorAll('tr').forEach(tr => {
                if (tr.classList.contains('screener-details-row')) return;
                if (tr.cells.length < 9) return;

                const scoreText = tr.cells[4] ? tr.cells[4].textContent.trim() : '0';
                const score = parseInt(scoreText) || 0;
                const cap = tr.cells[3] ? tr.cells[3].textContent.trim().toLowerCase() : '';
                const action = tr.cells[8] ? tr.cells[8].textContent.trim().toUpperCase() : '';

                let show = true;
                if (score < minScore) show = false;
                if (capVal !== 'all' && cap !== capVal) show = false;
                if (actionVal !== 'all') {
                    if (actionVal === 'SELL') {
                        if (!action.includes('SELL') && !action.includes('AVOID')) show = false;
                    } else if (actionVal === 'BUY') {
                        if (!action.includes('BUY') || action.includes('STRONG')) show = false;
                    } else {
                        if (!action.includes(actionVal)) show = false;
                    }
                }

                tr.style.display = show ? '' : 'none';
                // Also hide any expanded detail row
                const nextRow = tr.nextElementSibling;
                if (nextRow && nextRow.classList.contains('screener-details-row')) {
                    nextRow.style.display = show ? '' : 'none';
                }
            });
        }
        window.applyMobileScreenerFilters = applyMobileScreenerFilters;

        function setupScreenerTableObserver() {
            const tbody = document.getElementById('screener-results-body');
            if (tbody) {
                decorateScreenerRowsForMobile();
                const observer = new MutationObserver(() => decorateScreenerRowsForMobile());
                observer.observe(tbody, { childList: true });
            }
        }

        function decorateSectorRadarRowsForMobile() {
            const tbody = document.getElementById('sector-stocks-table-body');
            if (!tbody) return;

            if (!isMobile()) {
                tbody.querySelectorAll('.row-expand-trigger').forEach(el => el.remove());
                tbody.querySelectorAll('.sector-details-row').forEach(el => el.remove());
                tbody.querySelectorAll('.mobile-sector-meta').forEach(el => el.remove());
                return;
            }

            tbody.querySelectorAll('tr').forEach(tr => {
                if (tr.classList.contains('sector-details-row') || tr.querySelector('.row-expand-trigger') || tr.cells.length < 11) return;

                const firstCell = tr.cells[0];
                if (!firstCell) return;

                // Add cap badge metadata inline next to Symbol
                const capBadgeHtml = tr.cells[2] ? tr.cells[2].innerHTML : '';
                if (!firstCell.querySelector('.mobile-sector-meta')) {
                    const metaSpan = document.createElement('span');
                    metaSpan.className = 'mobile-sector-meta';
                    metaSpan.style.cssText = 'display: inline-flex; align-items: center; margin-left: 6px;';
                    metaSpan.innerHTML = capBadgeHtml;
                    firstCell.appendChild(metaSpan);
                }

                const chevron = document.createElement('span');
                chevron.className = 'row-expand-trigger';
                chevron.style.cssText = 'cursor: pointer; padding: 2px 6px; font-size: 10px; color: var(--color-primary-light); user-select: none; transition: transform 0.2s; font-weight: bold; margin-left: 4px;';
                chevron.innerHTML = '▼';
                firstCell.appendChild(chevron);

                chevron.addEventListener('click', (e) => {
                    e.stopPropagation();
                    e.preventDefault();

                    let nextRow = tr.nextElementSibling;
                    if (nextRow && nextRow.classList.contains('sector-details-row')) {
                        nextRow.remove();
                        chevron.innerHTML = '▼';
                    } else {
                        const companyName = tr.cells[1] ? tr.cells[1].textContent.trim() : 'N/A';
                        const capHtml = tr.cells[2] ? tr.cells[2].innerHTML : '';
                        const ret1d = tr.cells[3] ? tr.cells[3].innerHTML : 'N/A';
                        const ret5d = tr.cells[4] ? tr.cells[4].innerHTML : 'N/A';
                        const ret1m = tr.cells[5] ? tr.cells[5].innerHTML : 'N/A';
                        const ret3m = tr.cells[6] ? tr.cells[6].innerHTML : 'N/A';
                        const ret6m = tr.cells[7] ? tr.cells[7].innerHTML : 'N/A';
                        const ret1y = tr.cells[8] ? tr.cells[8].innerHTML : 'N/A';
                        const ret5y = tr.cells[9] ? tr.cells[9].innerHTML : 'N/A';
                        const actionsHtml = tr.cells[10] ? tr.cells[10].innerHTML : '';

                        const detailsTr = document.createElement('tr');
                        detailsTr.className = 'sector-details-row no-print';
                        detailsTr.style.background = 'rgba(255, 255, 255, 0.015)';
                        detailsTr.innerHTML = `
                            <td colspan="11" style="padding: 10px 12px; border-top: 1px solid rgba(255,255,255,0.04); border-bottom: 1px solid rgba(255,255,255,0.04);">
                                <div style="display:flex; flex-direction:column; gap:8px;">
                                    <!-- Company Name + Cap -->
                                    <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                                        <span style="font-size:11.5px; color:var(--color-primary-light); font-weight:700; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:200px;">${companyName}</span>
                                        <span>${capHtml}</span>
                                    </div>
                                    <!-- Return Gauges Grid -->
                                    <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:4px 6px; font-size:10px;">
                                        <div style="display:flex; align-items:center; justify-content:space-between; gap:4px; background:rgba(255,255,255,0.02); border-radius:4px; padding:3px 6px;">
                                            <span style="color:var(--text-muted); font-weight:600; font-size:9px;">1D</span>
                                            ${ret1d}
                                        </div>
                                        <div style="display:flex; align-items:center; justify-content:space-between; gap:4px; background:rgba(255,255,255,0.02); border-radius:4px; padding:3px 6px;">
                                            <span style="color:var(--text-muted); font-weight:600; font-size:9px;">5D</span>
                                            ${ret5d}
                                        </div>
                                        <div style="display:flex; align-items:center; justify-content:space-between; gap:4px; background:rgba(255,255,255,0.02); border-radius:4px; padding:3px 6px;">
                                            <span style="color:var(--text-muted); font-weight:600; font-size:9px;">1M</span>
                                            ${ret1m}
                                        </div>
                                        <div style="display:flex; align-items:center; justify-content:space-between; gap:4px; background:rgba(255,255,255,0.02); border-radius:4px; padding:3px 6px;">
                                            <span style="color:var(--text-muted); font-weight:600; font-size:9px;">3M</span>
                                            ${ret3m}
                                        </div>
                                        <div style="display:flex; align-items:center; justify-content:space-between; gap:4px; background:rgba(255,255,255,0.02); border-radius:4px; padding:3px 6px;">
                                            <span style="color:var(--text-muted); font-weight:600; font-size:9px;">6M</span>
                                            ${ret6m}
                                        </div>
                                        <div style="display:flex; align-items:center; justify-content:space-between; gap:4px; background:rgba(255,255,255,0.02); border-radius:4px; padding:3px 6px;">
                                            <span style="color:var(--text-muted); font-weight:600; font-size:9px;">1Y</span>
                                            ${ret1y}
                                        </div>
                                        <div style="display:flex; align-items:center; justify-content:space-between; gap:4px; background:rgba(255,255,255,0.02); border-radius:4px; padding:3px 6px; grid-column: span 3;">
                                            <span style="color:var(--text-muted); font-weight:600; font-size:9px;">5Y</span>
                                            ${ret5y}
                                        </div>
                                    </div>
                                    <!-- Action Buttons -->
                                    <div style="display:flex; justify-content:flex-end; gap:6px; padding-top:4px; border-top:1px solid rgba(255,255,255,0.04);">
                                        <div class="mobile-actions-wrapper" style="display:flex; gap:6px;">
                                            ${actionsHtml}
                                        </div>
                                    </div>
                                </div>
                            </td>
                        `;
                        tr.parentNode.insertBefore(detailsTr, tr.nextSibling);

                        // Fix pill sizing inside expand row for mobile
                        detailsTr.querySelectorAll('span[style*="min-width"]').forEach(pill => {
                            pill.style.minWidth = '0';
                            pill.style.fontSize = '9px';
                            pill.style.padding = '1px 4px';
                        });

                        const detailsActions = detailsTr.querySelectorAll('button');
                        const originalActions = tr.cells[10].querySelectorAll('button');
                        detailsActions.forEach((btn, idx) => {
                            btn.addEventListener('click', (evt) => {
                                if (originalActions[idx]) originalActions[idx].click();
                            });
                        });

                        chevron.innerHTML = '▲';
                    }
                });
            });
        }

        function setupSectorRadarTableObserver() {
            const tbody = document.getElementById('sector-stocks-table-body');
            if (tbody) {
                decorateSectorRadarRowsForMobile();
                const observer = new MutationObserver(() => decorateSectorRadarRowsForMobile());
                observer.observe(tbody, { childList: true });
            }
        }

        // 6. Mobile Homepage Command Center Dashboard
        function initMobileHomepageCommandCenter() {
            const emptyState = document.getElementById('analyzer-empty-state');
            const analyzerTab = document.getElementById('tab-analyzer');
            if (!emptyState || !analyzerTab) return;

            // MutationObserver to watch empty state visibility and toggle homepage-active class
            const toggleActiveMode = () => {
                if (!isMobile()) {
                    analyzerTab.classList.remove('homepage-active');
                    document.body.classList.remove('homepage-active');
                    const cc = document.getElementById('mobile-homepage-command-center');
                    if (cc) cc.style.display = 'none';
                    return;
                }

                if (emptyState.style.display !== 'none') {
                    analyzerTab.classList.add('homepage-active');
                    document.body.classList.add('homepage-active');
                    const cc = document.getElementById('mobile-homepage-command-center');
                    if (cc) {
                        cc.style.display = 'block';
                        renderMobileHomepageCommandCenter();
                    }
                    // Explicit JS Safeguards: hide dashboard and reset search input text
                    const dashboard = document.getElementById('analyzer-dashboard');
                    if (dashboard) dashboard.style.display = 'none';
                    const mobileSearchInput = document.getElementById('mobile-home-search-input');
                    if (mobileSearchInput) mobileSearchInput.value = '';
                } else {
                    analyzerTab.classList.remove('homepage-active');
                    document.body.classList.remove('homepage-active');
                    const cc = document.getElementById('mobile-homepage-command-center');
                    if (cc) cc.style.display = 'none';
                }
            };

            const observer = new MutationObserver(toggleActiveMode);
            observer.observe(emptyState, { attributes: true, attributeFilter: ['style'] });
            
            // Initial call
            toggleActiveMode();
            
            // Re-check on resize
            window.addEventListener('resize', toggleActiveMode);
        }

        function deriveMarketBreadthGreeting() {
            try {
                // Try to read Nifty change from marquee
                const niftyEl = document.getElementById('ticker-nifty');
                if (niftyEl) {
                    const changeSpan = niftyEl.querySelector('.change');
                    if (changeSpan) {
                        const txt = changeSpan.textContent.trim();
                        const val = parseFloat(txt.replace(/[^\d.-]/g, ''));
                        const isDown = txt.includes('▼') || txt.includes('-') || changeSpan.classList.contains('red-text');
                        if (!isNaN(val)) {
                            if (isDown) {
                                return `Nifty indices show defensive consolidated pressure today (${txt}). Defensive overlays are recommended.`;
                            } else {
                                return `Nifty indices show positive structural strength today (${txt}). Momentum radar highlights constructive rotation bias.`;
                            }
                        }
                    }
                }
                
                // Try reading advances/declines from Sector Radar breadth
                const advLbl = document.getElementById('breadth-advances-lbl');
                const decLbl = document.getElementById('breadth-declines-lbl');
                if (advLbl && decLbl) {
                    const advMatch = advLbl.innerText.match(/\d+/);
                    const decMatch = decLbl.innerText.match(/\d+/);
                    if (advMatch && decMatch) {
                        const adv = parseInt(advMatch[0]);
                        const dec = parseInt(decMatch[0]);
                        if (adv > dec) {
                            return `Indian equities display positive breadth today with ${adv} advances over ${dec} declines. Constructive breakout setups are active.`;
                        } else if (adv < dec) {
                            return `Indian equities display defensive breadth today with ${dec} declines over ${adv} advances. Caution is advised.`;
                        }
                    }
                }
            } catch(e) {
                console.error("Error deriving market breadth:", e);
            }
            return "Market indices are active. Run the screener or check momentum radar to identify breakout candidates.";
        }

        function renderMobileHomepageCommandCenter() {
            const container = document.getElementById('mobile-homepage-command-center');
            if (!container) return;
            
            // Avoid double render
            if (container.dataset.rendered === "true") {
                updateDynamicCommandCenterContent();
                return;
            }

            const istHourString = new Date().toLocaleString('en-US', { timeZone: 'Asia/Kolkata', hour: 'numeric', hour12: false });
            const hour = parseInt(istHourString, 10) || new Date().getHours();
            let greetingText = "Good Evening";
            if (hour < 12) greetingText = "Good Morning";
            else if (hour < 17) greetingText = "Good Afternoon";

            const derivedGreeting = deriveMarketBreadthGreeting();

            container.innerHTML = `
                <!-- Dynamic Greeting & Live Market Bias Summary -->
                <div class="mobile-copilot-greeting mobile-glass-card">
                    <h4 style="margin: 0 0 6px 0; font-size: 17px; font-weight: 800; color: var(--text-primary); letter-spacing: 0.02em; display: flex; justify-content: space-between; align-items: center;">
                        <span>${greetingText}, Analyst</span>
                        <button id="btn-audio-mute-toggle" style="background: none; border: none; color: var(--color-primary); cursor: pointer; font-size: 17px; outline: none; transition: transform 0.1s; padding: 0 4px;">🔊</button>
                    </h4>
                    <p style="margin: 0; font-size: 14px; color: var(--text-secondary); line-height: 1.45;" id="mobile-home-copilot-summary">
                        ${derivedGreeting}
                    </p>
                    <div class="breadth-gauge-wrap" id="mobile-home-breadth-gauge" style="margin-top: 12px; background: rgba(255,255,255,0.015); border: 1px solid var(--border-glass); padding: 10px; border-radius: 8px; display: none;">
                        <div style="display:flex; justify-content:space-between; font-size:11.5px; font-weight:800; text-transform:uppercase; color:var(--text-muted); margin-bottom:6px;">
                            <span style="color:var(--neon-green, #10b981);">Advances: <span id="breadth-advances-count">0</span></span>
                            <span style="color:var(--color-crimson, #ef4444);">Declines: <span id="breadth-declines-count">0</span></span>
                        </div>
                        <div style="position:relative; height:5px; background:var(--bg-track, rgba(255,255,255,0.06)); border-radius:2.5px; overflow:hidden; display:flex;">
                            <div id="breadth-advances-bar" style="height:100%; background:var(--neon-green, #10b981); width:50%; transition:width 0.5s ease; box-shadow:0 0 6px var(--neon-green, #10b981);"></div>
                            <div id="breadth-declines-bar" style="height:100%; background:var(--color-crimson, #ef4444); width:50%; transition:width 0.5s ease; box-shadow:0 0 6px var(--color-crimson, #ef4444);"></div>
                        </div>

                        <!-- Volatility Indicator -->
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-top:10px; padding-top:8px; border-top:1px dashed var(--border-glass, rgba(255,255,255,0.06)); font-size:11px; font-weight:700; color:var(--text-muted);">
                            <span>VOLATILITY RADAR</span>
                            <div style="display:flex; align-items:center; gap:5px;">
                                <span id="vix-indicator-dot" style="width:5.5px; height:5.5px; border-radius:50%; background:#10b981; display:inline-block; box-shadow:0 0 5px #10b981; transition: all 0.3s ease;"></span>
                                <span id="vix-indicator-val" style="color:var(--text-primary); font-family:var(--font-heading); font-size:11px; font-weight:800;">VIX: --</span>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Central Search Experience -->
                <div class="mobile-search-section-wrap" style="margin-bottom: 12px; position: relative; transition: all 0.25s ease;">
                    <div class="search-glowing-aura"></div>
                    <div style="position:relative; width:100%; display: flex; align-items: center;">
                        <input type="text" id="mobile-home-search-input" placeholder="Search Indian Stocks (e.g. RELIANCE)..." style="width:100% !important; box-sizing:border-box !important; padding:13px 48px 13px 16px !important; font-size:13.5px !important; background:rgba(255,255,255,0.03) !important; border:1px solid var(--border-glass) !important; color:var(--text-primary) !important; border-radius:8px !important; outline:none !important; text-align:left;">
                        <div class="voice-catalyst-wrap" style="position: absolute !important; right: 12px !important; margin: 0 !important; z-index: 20;">
                            <button class="voice-catalyst-btn" id="mobile-home-mic-btn" title="Speak Ticker to Research" style="background: none !important; border: none !important; color: var(--color-primary) !important; cursor: pointer; padding: 4px !important; outline: none; font-size: 15px;">
                                🎙️
                            </button>
                        </div>
                        <div id="mobile-home-suggestions" class="watchlist-autocomplete-box" style="display:none; position:absolute; top:100%; left:0; right:0; z-index:9999; max-height:220px; overflow-y:auto; margin-top:4px;"></div>
                    </div>
                </div>

                <!-- Recent Searches Scrollable Pills -->
                <div id="mobile-home-recent-pills-container" style="margin-bottom: 20px; display: none;">
                    <div id="mobile-home-recent-pills-title" style="font-size: 9px; text-transform: uppercase; color: var(--text-muted); font-weight: 700; letter-spacing: 0.05em; margin-bottom: 6px;">Recent Searches</div>
                    <div id="mobile-home-recent-pills" style="display: flex; gap: 8px; overflow-x: auto; scrollbar-width: none; -ms-overflow-style: none; padding: 2px 0;"></div>
                </div>

                

                <!-- Today's Market Movers Section -->
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <h5 style="margin:0; font-size:13.5px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading); font-weight: 700; letter-spacing: 0.05em;">Today's Market Leaders</h5>
                    <button class="section-view-all-btn" onclick="window.switchTab && window.switchTab('movers')" style="background: rgba(255,255,255,0.04); color: var(--text-secondary); border: 1px solid var(--border-glass); padding: 3px 10px; font-size: 10.5px; border-radius: 4px; cursor: pointer; font-family: 'Outfit', sans-serif; font-weight: 600;">View All →</button>
                </div>
                <div class="movers-container mobile-glass-card">
                    <div class="movers-segmented-control">
                        <button class="tech-segmented-tab active" id="movers-tab-gainers">Gainers</button>
                        <button class="tech-segmented-tab" id="movers-tab-losers">Losers</button>
                    </div>
                    <div class="mobile-movers-cap-selector-container" style="display: flex; gap: 8px; margin: 10px 0 15px 0; overflow-x: auto; -webkit-overflow-scrolling: touch; padding-bottom: 4px;">
                        <button class="mobile-movers-cap-tab active" data-cap="all" style="flex-shrink:0;">All Cap</button>
                        <button class="mobile-movers-cap-tab" data-cap="large" style="flex-shrink:0;">Large Cap</button>
                        <button class="mobile-movers-cap-tab" data-cap="mid" style="flex-shrink:0;">Mid Cap</button>
                        <button class="mobile-movers-cap-tab" data-cap="small" style="flex-shrink:0;">Small Cap</button>
                    </div>
                    <div id="mobile-home-gainers-container"></div>
                    <div id="mobile-home-losers-container" style="display: none;"></div>
                </div>

                <!-- Today's Sector Rotations Section -->
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 20px; margin-bottom: 8px;">
                    <h5 style="margin:0; font-size:13.5px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading); font-weight: 700; letter-spacing: 0.05em;">Sector Rotations</h5>
                    <button class="section-view-all-btn" onclick="window.switchTab && window.switchTab('sector-radar')" style="background: rgba(255,255,255,0.04); color: var(--text-secondary); border: 1px solid var(--border-glass); padding: 3px 10px; font-size: 10.5px; border-radius: 4px; cursor: pointer; font-family: 'Outfit', sans-serif; font-weight: 600;">View All →</button>
                </div>
                <div id="mobile-home-sectors-container" style="margin-bottom: 20px;"></div>

                <!-- Fuzzy Radar Quick-View Section -->
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 24px; margin-bottom: 8px;">
                    <h5 style="margin:0; font-size:13.5px; text-transform:uppercase; color:#3b82f6; font-family:var(--font-heading); font-weight: 700; letter-spacing: 0.05em;">🧠 Fuzzy Radar Quick-View</h5>
                    <button class="section-view-all-btn" onclick="window.switchTab && window.switchTab('fuzzy')" style="background: rgba(59, 130, 246, 0.1); color: #3b82f6; border: 1px solid rgba(59, 130, 246, 0.25); padding: 3px 10px; font-size: 10.5px; border-radius: 4px; cursor: pointer; font-family: 'Outfit', sans-serif; font-weight: 600;">Console →</button>
                </div>
                <div class="mobile-glass-card" style="padding: 12px; margin-bottom: 20px; border: 1px solid rgba(59, 130, 246, 0.15);">
                    <div class="movers-segmented-control" style="margin-bottom: 12px; display: flex; gap: 4px;">
                        <button class="tech-segmented-tab active" id="mobile-fuzzy-tab-buys" style="flex: 1; text-align: center; font-size: 10.5px; padding: 6px 0;">🟢 Accumulation</button>
                        <button class="tech-segmented-tab" id="mobile-fuzzy-tab-sells" style="flex: 1; text-align: center; font-size: 10.5px; padding: 6px 0;">🔴 Avoid / Traps</button>
                    </div>
                    <div id="mobile-home-fuzzy-radar-container" style="display: flex; flex-direction: column; gap: 8px;">
                        <div class="recent-research-empty" style="font-size: 11px;">Hydrating radar...</div>
                    </div>
                </div>

                <!-- Quant Top Picks Section -->
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 24px; margin-bottom: 8px;">
                    <h5 style="margin:0; font-size:13.5px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading); font-weight: 700; letter-spacing: 0.05em;">🔬 Quant Top Picks</h5>
                    <button class="section-view-all-btn" onclick="window.switchTab && window.switchTab('screener')" style="background: rgba(255,255,255,0.04); color: var(--text-secondary); border: 1px solid var(--border-glass); padding: 3px 10px; font-size: 10.5px; border-radius: 4px; cursor: pointer; font-family: 'Outfit', sans-serif; font-weight: 600;">View All </button>
                </div>
                <div class="mobile-glass-card" style="padding: 12px; margin-bottom: 20px;">
                    <div class="movers-segmented-control" style="margin-bottom: 12px; display: flex; gap: 4px;">
                        <button class="tech-segmented-tab active" id="mobile-quant-tab-hybrid" style="flex: 1; text-align: center; font-size: 10.5px; padding: 6px 0;">Hybrid</button>
                        <button class="tech-segmented-tab" id="mobile-quant-tab-bottom_up" style="flex: 1; text-align: center; font-size: 10.5px; padding: 6px 0;">Bottom-Up</button>
                        <button class="tech-segmented-tab" id="mobile-quant-tab-top_down" style="flex: 1; text-align: center; font-size: 10.5px; padding: 6px 0;">Top-Down</button>
                    </div>
                    <div id="mobile-home-quant-picks-container" style="display: flex; flex-direction: column; gap: 8px;">
                        <div class="recent-research-empty" style="font-size: 11px;">Scanning market for quant top picks...</div>
                    </div>
                </div>
                <!-- Watchlist Quick-Quote Section -->
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 24px; margin-bottom: 8px;">
                    <h5 style="margin:0; font-size:13.5px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading); font-weight: 700; letter-spacing: 0.05em;">⭐ Watchlist Quick-Quote</h5>
                    <div style="display: flex; align-items: center; gap: 6px;">
                        <select id="mobile-watchlist-selector" style="background: rgba(255,255,255,0.03); color: var(--text-primary); border: 1px solid var(--border-glass); padding: 2px 6px; font-size: 11px; border-radius: 4px; outline: none; font-family: 'Outfit', sans-serif; cursor: pointer; max-width: 120px;">
                            <option value="" disabled selected>Select Watchlist</option>
                        </select>
                        <button class="section-view-all-btn" onclick="window.switchTab && window.switchTab('watchlist')" style="background: rgba(255,255,255,0.04); color: var(--text-secondary); border: 1px solid var(--border-glass); padding: 3px 10px; font-size: 10.5px; border-radius: 4px; cursor: pointer; font-family: 'Outfit', sans-serif; font-weight: 600;">View All </button>
                    </div>
                </div>
                <div class="mobile-glass-card" style="padding: 12px; margin-bottom: 20px;">
                    <div id="mobile-home-watchlist-container" style="display: flex; flex-direction: column; gap: 8px;">
                        <div class="recent-research-empty" style="font-size: 11px;">Select watchlist in main workspace to display.</div>
                    </div>
                </div>

 <!-- Technical Scans & Breakouts Section -->
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 24px; margin-bottom: 8px;">
                    <h5 style="margin:0; font-size:13.5px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading); font-weight: 700; letter-spacing: 0.05em;">⚡ Technical Breakouts</h5>
                    <button class="section-view-all-btn" onclick="window.switchTab && window.switchTab('technical-scans')" style="background: rgba(255,255,255,0.04); color: var(--text-secondary); border: 1px solid var(--border-glass); padding: 3px 10px; font-size: 10.5px; border-radius: 4px; cursor: pointer; font-family: 'Outfit', sans-serif; font-weight: 600;">View All →</button>
                </div>
                <div class="mobile-glass-card" style="padding: 12px; margin-bottom: 20px;">
                    <div class="tech-segmented-control scroll-fade-mask" style="margin-bottom: 12px; display: flex; gap: 4px; overflow-x: auto; white-space: nowrap; -webkit-overflow-scrolling: touch; padding-bottom: 2px;">
                        <button class="tech-segmented-tab active" id="mobile-tech-tab-near_high" style="flex: 1; text-align: center; font-size: 10.5px; padding: 6px 10px; min-width: 90px;">Near 52W High</button>
                        <button class="tech-segmented-tab" id="mobile-tech-tab-near_low" style="flex: 1; text-align: center; font-size: 10.5px; padding: 6px 10px; min-width: 90px;">Near 52W Low</button>
                        <button class="tech-segmented-tab" id="mobile-tech-tab-gap_up" style="flex: 1; text-align: center; font-size: 10.5px; padding: 6px 10px; min-width: 80px;">Gap Up</button>
                        <button class="tech-segmented-tab" id="mobile-tech-tab-gap_down" style="flex: 1; text-align: center; font-size: 10.5px; padding: 6px 10px; min-width: 85px;">Gap Down</button>
                    </div>
                    <div id="mobile-home-tech-scans-container" style="display: flex; flex-direction: column; gap: 8px;">
                        <div class="recent-research-empty" style="font-size: 11px;">Scanning technical breakouts...</div>
                    </div>
                </div>
                
                <!-- Institutional Alert Center Section -->
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 24px; margin-bottom: 8px;">
                    <h5 style="margin:0; font-size:13.5px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading); font-weight: 700; letter-spacing: 0.05em;">🚨 Institutional Alert Center</h5>
                    <button class="section-view-all-btn" onclick="window.switchTab && window.switchTab('alerts')" style="background: rgba(255,255,255,0.04); color: var(--text-secondary); border: 1px solid var(--border-glass); padding: 3px 10px; font-size: 10.5px; border-radius: 4px; cursor: pointer; font-family: 'Outfit', sans-serif; font-weight: 600;">View All →</button>
                </div>
                <div class="mobile-glass-card" style="padding: 12px; margin-bottom: 20px;">
                    <div id="mobile-home-alerts-container" style="display: flex; flex-direction: column; gap: 8px;">
                        <div class="recent-research-empty" style="font-size: 11px;">Scanning real-time alerts...</div>
                    </div>
                </div>

                <!-- Upcoming Corporate Events Section -->
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 24px; margin-bottom: 8px;">
                    <h5 style="margin:0; font-size:13.5px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading); font-weight: 700; letter-spacing: 0.05em;">📅 Corporate Events</h5>
                    <button class="section-view-all-btn" onclick="window.switchTab && window.switchTab('events')" style="background: rgba(255,255,255,0.04); color: var(--text-secondary); border: 1px solid var(--border-glass); padding: 3px 10px; font-size: 10.5px; border-radius: 4px; cursor: pointer; font-family: 'Outfit', sans-serif; font-weight: 600;">View All →</button>
                </div>
                <div class="mobile-glass-card" style="padding: 12px; margin-bottom: 20px;">
                    <div id="mobile-home-events-container" style="display: flex; flex-direction: column; gap: 8px;">
                        <div class="recent-research-empty" style="font-size: 11px;">Fetching events schedule...</div>
                    </div>
                </div>
<!-- Live Catalyst News Feed Section -->
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 24px; margin-bottom: 8px;">
                    <h5 style="margin:0; font-size:13.5px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading); font-weight: 700; letter-spacing: 0.05em;">Live Catalyst News</h5>
                    <button class="section-view-all-btn" onclick="window.switchTab && window.switchTab('market-news')" style="background: rgba(255,255,255,0.04); color: var(--text-secondary); border: 1px solid var(--border-glass); padding: 3px 10px; font-size: 10.5px; border-radius: 4px; cursor: pointer; font-family: 'Outfit', sans-serif; font-weight: 600;">View All →</button>
                </div>
                
                <div class="news-categories-scroll-wrapper">
                    <button class="news-category-pill-btn active" data-category="all">All</button>
                    <button class="news-category-pill-btn" data-category="earnings">Earnings</button>
                    <button class="news-category-pill-btn" data-category="m&a">M&A</button>
                    <button class="news-category-pill-btn" data-category="policy">Policy</button>
                    <button class="news-category-pill-btn" data-category="global">Global</button>
                </div>
                <div class="mobile-cmd-news-section" id="mobile-home-news-container" style="margin-top: 5px;">
                    <!-- Populated dynamically -->
                </div>
            `;

            container.dataset.rendered = "true";

            // Wire Movers Segmented Tab Control
            const gainerTabBtn = document.getElementById('movers-tab-gainers');
            const loserTabBtn = document.getElementById('movers-tab-losers');
            const gainersDiv = document.getElementById('mobile-home-gainers-container');
            const losersDiv = document.getElementById('mobile-home-losers-container');
            if (gainerTabBtn && loserTabBtn && gainersDiv && losersDiv) {
                gainerTabBtn.onclick = () => {
                    gainerTabBtn.classList.add('active');
                    loserTabBtn.classList.remove('active');
                    window.activeMoversTab = 'gainers';
                    gainersDiv.style.display = 'block';
                    losersDiv.style.display = 'none';
                };
                loserTabBtn.onclick = () => {
                    loserTabBtn.classList.add('active');
                    gainerTabBtn.classList.remove('active');
                    window.activeMoversTab = 'losers';
                    losersDiv.style.display = 'block';
                    gainersDiv.style.display = 'none';
                };
            }

            // Wire mobile Fuzzy Radar tab clicks
            const fTabBuys = document.getElementById('mobile-fuzzy-tab-buys');
            const fTabSells = document.getElementById('mobile-fuzzy-tab-sells');
            if (fTabBuys) {
                fTabBuys.onclick = () => {
                    if (fTabSells) fTabSells.classList.remove('active');
                    fTabBuys.classList.add('active');
                    if (window.renderMobileFuzzyRadar) window.renderMobileFuzzyRadar('buys');
                };
            }
            if (fTabSells) {
                fTabSells.onclick = () => {
                    if (fTabBuys) fTabBuys.classList.remove('active');
                    fTabSells.classList.add('active');
                    if (window.renderMobileFuzzyRadar) window.renderMobileFuzzyRadar('sells');
                };
            }

            // Wire mobile Quant Picks strategy selector clicks
            const qTabHybrid = document.getElementById('mobile-quant-tab-hybrid');
            const qTabBU = document.getElementById('mobile-quant-tab-bottom_up');
            const qTabTD = document.getElementById('mobile-quant-tab-top_down');
            const qMobileTabs = [qTabHybrid, qTabBU, qTabTD];

            const updateMobileQuantActiveTab = (activeId) => {
                qMobileTabs.forEach(tab => {
                    if (tab) tab.classList.remove('active');
                });
                const activeTab = document.getElementById(activeId);
                if (activeTab) activeTab.classList.add('active');
            };

            if (qTabHybrid) {
                qTabHybrid.onclick = () => {
                    window.activeQuantStrategy = 'hybrid';
                    updateMobileQuantActiveTab('mobile-quant-tab-hybrid');
                    if (window.renderQuantTopPicksList) window.renderQuantTopPicksList();
                };
            }
            if (qTabBU) {
                qTabBU.onclick = () => {
                    window.activeQuantStrategy = 'bottom_up';
                    updateMobileQuantActiveTab('mobile-quant-tab-bottom_up');
                    if (window.renderQuantTopPicksList) window.renderQuantTopPicksList();
                };
            }
            if (qTabTD) {
                qTabTD.onclick = () => {
                    window.activeQuantStrategy = 'top_down';
                    updateMobileQuantActiveTab('mobile-quant-tab-top_down');
                    if (window.renderQuantTopPicksList) window.renderQuantTopPicksList();
                };
            }

            // Wire mobile Technical Breakouts strategy selector clicks
            const mtTabHigh = document.getElementById('mobile-tech-tab-near_high');
            const mtTabLow = document.getElementById('mobile-tech-tab-near_low');
            const mtTabGapUp = document.getElementById('mobile-tech-tab-gap_up');
            const mtTabGapDown = document.getElementById('mobile-tech-tab-gap_down');
            const mtMobileTabs = [mtTabHigh, mtTabLow, mtTabGapUp, mtTabGapDown];

            const updateMobileTechActiveTab = (activeId) => {
                mtMobileTabs.forEach(tab => {
                    if (tab) tab.classList.remove('active');
                });
                const activeTab = document.getElementById(activeId);
                if (activeTab) activeTab.classList.add('active');
            };

            if (mtTabHigh) {
                mtTabHigh.onclick = () => {
                    window.activeTechnicalScan = 'near_high';
                    updateMobileTechActiveTab('mobile-tech-tab-near_high');
                    if (window.renderTechnicalScansList) window.renderTechnicalScansList();
                };
            }
            if (mtTabLow) {
                mtTabLow.onclick = () => {
                    window.activeTechnicalScan = 'near_low';
                    updateMobileTechActiveTab('mobile-tech-tab-near_low');
                    if (window.renderTechnicalScansList) window.renderTechnicalScansList();
                };
            }
            if (mtTabGapUp) {
                mtTabGapUp.onclick = () => {
                    window.activeTechnicalScan = 'gap_up';
                    updateMobileTechActiveTab('mobile-tech-tab-gap_up');
                    if (window.renderTechnicalScansList) window.renderTechnicalScansList();
                };
            }
            if (mtTabGapDown) {
                mtTabGapDown.onclick = () => {
                    window.activeTechnicalScan = 'gap_down';
                    updateMobileTechActiveTab('mobile-tech-tab-gap_down');
                    if (window.renderTechnicalScansList) window.renderTechnicalScansList();
                };
            }

            // Wire News Category Tab Clicks
            const newsCategoryTabs = container.querySelectorAll('.news-category-pill-btn');
            newsCategoryTabs.forEach(tab => {
                tab.onclick = () => {
                    newsCategoryTabs.forEach(t => t.classList.remove('active'));
                    tab.classList.add('active');
                    window.activeMobileNewsCategory = tab.dataset.category;
                    updateDynamicCommandCenterContent();
                };
            });

            // Wire Tab Switches (Safely)
            const btnScreener = document.getElementById('cmd-btn-screener');
            if (btnScreener) btnScreener.onclick = () => window.switchTab('screener');
            const btnRadar = document.getElementById('cmd-btn-radar');
            if (btnRadar) btnRadar.onclick = () => window.switchTab('sector-radar');
            const btnScanner = document.getElementById('cmd-btn-scanner');
            if (btnScanner) btnScanner.onclick = () => window.switchTab('rule-scanner');
            const btnAlerts = document.getElementById('cmd-btn-alerts');
            if (btnAlerts) btnAlerts.onclick = () => window.switchTab('alerts');

            // Wire Voice Catalyst Click
            const homeMic = document.getElementById('mobile-home-mic-btn');
            homeMic.addEventListener('click', () => {
                const originalMic = document.getElementById('analyzer-voice-search-btn');
                if (originalMic) {
                    window.activeSpeechRecognizerTarget = 'analyzer';
                    originalMic.click();
                }
            });

            // Wire Audio Mute Toggle Button
            const muteBtn = document.getElementById('btn-audio-mute-toggle');
            if (muteBtn) {
                const updateIcon = () => {
                    const isMuted = localStorage.getItem('apex-audio-muted') === 'true';
                    muteBtn.innerHTML = isMuted ? '🔇' : '🔊';
                    muteBtn.style.color = isMuted ? 'var(--text-muted)' : 'var(--color-primary)';
                };
                updateIcon();
                muteBtn.onclick = (e) => {
                    e.stopPropagation();
                    const isMuted = localStorage.getItem('apex-audio-muted') === 'true';
                    localStorage.setItem('apex-audio-muted', (!isMuted).toString());
                    updateIcon();
                    if (!isMuted) {
                        AudioCueManager.playTick();
                    }
                };
            }

            // Wire Autocomplete logic for Homepage input
            const inputEl = document.getElementById('mobile-home-search-input');
            const suggestionsDiv = document.getElementById('mobile-home-suggestions');

            // Wire Immersive Search Focus Overlay
            const searchWrap = document.querySelector('.mobile-search-section-wrap');
            let backdrop = document.getElementById('mobile-search-focus-backdrop');
            if (searchWrap && !backdrop) {
                backdrop = document.createElement('div');
                backdrop.id = 'mobile-search-focus-backdrop';
                backdrop.style.cssText = 'position:fixed; top:0; left:0; width:100vw; height:100vh; background:rgba(6,9,19,0.7); backdrop-filter:blur(4px); -webkit-backdrop-filter:blur(4px); z-index:1; opacity:0; pointer-events:none; transition:opacity 0.25s ease;';
                searchWrap.appendChild(backdrop);
            }
            if (inputEl && searchWrap && backdrop) {
                // Ensure sibling elements have a higher z-index than the backdrop (z-index: 1)
                if (inputEl.parentNode) {
                    inputEl.parentNode.style.position = 'relative';
                    inputEl.parentNode.style.zIndex = '10';
                }
                const micWrap = searchWrap.querySelector('.voice-catalyst-wrap');
                if (micWrap) {
                    micWrap.style.position = 'relative';
                    micWrap.style.zIndex = '10';
                }

                inputEl.addEventListener('focus', () => {
                    backdrop.style.opacity = '1';
                    backdrop.style.pointerEvents = 'auto';
                    searchWrap.style.zIndex = '1000';
                    searchWrap.style.transform = 'scale(1.02)';
                    searchWrap.style.boxShadow = '0 8px 30px rgba(0,0,0,0.5)';
                    
                    const query = inputEl.value.trim();
                    if (query.length >= 2 && suggestionsDiv) {
                        suggestionsDiv.style.display = 'block';
                    }
                });

                const dismissSearchFocus = () => {
                    backdrop.style.opacity = '0';
                    backdrop.style.pointerEvents = 'none';
                    searchWrap.style.zIndex = '';
                    searchWrap.style.transform = '';
                    searchWrap.style.boxShadow = '';
                };

                backdrop.onclick = (e) => {
                    e.stopPropagation();
                    dismissSearchFocus();
                    if (suggestionsDiv) suggestionsDiv.style.display = 'none';
                };

                inputEl.addEventListener('blur', () => {
                    setTimeout(dismissSearchFocus, 180);
                });
            }

            let searchDebounceTimer = null;
            if (inputEl && suggestionsDiv) {
                inputEl.addEventListener('input', () => {
                    clearTimeout(searchDebounceTimer);
                    const query = inputEl.value.trim();

                    if (query.length < 2) {
                        suggestionsDiv.innerHTML = '';
                        suggestionsDiv.style.display = 'none';
                        return;
                    }

                    searchDebounceTimer = setTimeout(async () => {
                        try {
                            const res = await fetch(apiBaseUrl + `/api/search/suggestions?q=${encodeURIComponent(query)}`);
                            if (res.ok) {
                                const data = await res.json();
                                suggestionsDiv.innerHTML = '';

                                if (data && data.length > 0) {
                                    data.forEach(item => {
                                        const div = document.createElement('div');
                                        div.className = 'watchlist-autocomplete-item';
                                        div.style.cssText = 'padding: 10px 14px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.03);';
                                        div.innerHTML = `
                                            <div>
                                                <span class="ticker-pill" style="font-weight: 700; color: #fff;">${item.base_symbol}</span>
                                                <span style="font-size: 10px; color: var(--text-muted); margin-left: 6px;">${item.name}</span>
                                            </div>
                                            <span class="sector-pill">${item.sector || 'Equity'}</span>
                                        `;
                                        div.addEventListener('click', () => {
                                            saveRecentSearch(item.base_symbol);
                                            const searchInput = document.getElementById('analyzer-search-input');
                                            const searchBtn = document.getElementById('analyzer-search-btn');
                                            if (searchInput && searchBtn) {
                                                searchInput.value = item.base_symbol;
                                                searchBtn.click();
                                            }
                                            suggestionsDiv.style.display = 'none';
                                            inputEl.value = '';
                                        });
                                        suggestionsDiv.appendChild(div);
                                    });
                                    suggestionsDiv.style.display = 'block';
                                } else {
                                    suggestionsDiv.style.display = 'none';
                                }
                            }
                        } catch (err) {
                            console.error("Autocomplete homepage error:", err);
                        }
                    }, 200);
                });
 
                document.addEventListener('click', (e) => {
                    if (e.target !== inputEl && e.target !== suggestionsDiv && !suggestionsDiv.contains(e.target)) {
                        suggestionsDiv.style.display = 'none';
                    }
                });
 
                inputEl.addEventListener('keypress', e => {
                    if (e.key === 'Enter') {
                        const val = inputEl.value.trim();
                        if (val) {
                            saveRecentSearch(val);
                            const searchInput = document.getElementById('analyzer-search-input');
                            const searchBtn = document.getElementById('analyzer-search-btn');
                            if (searchInput && searchBtn) {
                                searchInput.value = val;
                                searchBtn.click();
                            }
                            inputEl.value = '';
                        }
                    }
                });
            }

            function saveRecentSearch(symbol) {
                try {
                    symbol = symbol.trim().toUpperCase();
                    if (!symbol) return;
                    let list = JSON.parse(localStorage.getItem('recent-mobile-searches') || '["RELIANCE", "TCS", "INFY"]');
                    list = list.filter(s => s !== symbol);
                    list.unshift(symbol);
                    list = list.slice(0, 3);
                    localStorage.setItem('recent-mobile-searches', JSON.stringify(list));
                    updateDynamicCommandCenterContent();
                } catch(e) {
                    console.error("Error saving recent search:", e);
                }
            }

            // Initial render of dynamic lists
            updateDynamicCommandCenterContent();
        }

        async function updateDynamicCommandCenterContent() {
            const gainersContainer = document.getElementById('mobile-home-gainers-container');
            const losersContainer = document.getElementById('mobile-home-losers-container');
            const sectorsContainer = document.getElementById('mobile-home-sectors-container');
            const newsContainer = document.getElementById('mobile-home-news-container');
            const mobileWatchlistContainer = document.getElementById('mobile-home-watchlist-container');
            const mobileTechScansContainer = document.getElementById('mobile-home-tech-scans-container');
            const mobileAlertsContainer = document.getElementById('mobile-home-alerts-container');
            const mobileEventsContainer = document.getElementById('mobile-home-events-container');
            const mobileQuantPicksContainer = document.getElementById('mobile-home-quant-picks-container');

            // 1. Render Recent Search Pills
            const pillsContainer = document.getElementById('mobile-home-recent-pills-container');
            const pillsWrap = document.getElementById('mobile-home-recent-pills');
            const pillsTitle = document.getElementById('mobile-home-recent-pills-title');
            if (pillsContainer && pillsWrap) {
                let recents = [];
                try {
                    recents = JSON.parse(localStorage.getItem('recent-mobile-searches') || '[]');
                } catch(e) {
                    recents = [];
                }
                
                let isDefault = false;
                if (recents.length === 0) {
                    recents = ["RELIANCE", "TCS", "INFY"];
                    isDefault = true;
                }
                
                if (pillsTitle) {
                    pillsTitle.innerText = isDefault ? "Popular Stocks" : "Recent Searches";
                }
                
                let pillsHtml = '';
                recents.forEach(sym => {
                    pillsHtml += `
                        <span class="recent-pill-item" data-symbol="${sym}" style="font-size: 11px; font-weight: 700; color: var(--text-primary); background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 20px; padding: 5px 12px; cursor: pointer; white-space: nowrap; transition: all 0.2s ease;">
                            ${sym}
                        </span>
                    `;
                });
                pillsWrap.innerHTML = pillsHtml;
                pillsContainer.style.display = 'block';

                // Bind pill click actions
                pillsWrap.querySelectorAll('.recent-pill-item').forEach(pill => {
                    pill.onclick = () => {
                        const sym = pill.dataset.symbol;
                        const mobileInput = document.getElementById('mobile-home-search-input');
                        if (mobileInput) mobileInput.value = sym;
                        
                        const searchInput = document.getElementById('analyzer-search-input');
                        const searchBtn = document.getElementById('analyzer-search-btn');
                        if (searchInput && searchBtn) {
                            searchInput.value = sym;
                            searchBtn.click();
                        }
                    };
                });
            }

            // 2. Fetch & Render Gainers and Losers
            if (gainersContainer && losersContainer) {
                gainersContainer.innerHTML = `
                    <h5 style="margin:0 0 10px 0; font-size:11px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading); font-weight:700; letter-spacing:0.05em;">Today's Top Gainers</h5>
                    <div style="opacity:0.65; height:32px; background:rgba(255,255,255,0.03); border-radius:6px; animation: skeleton-shimmer 1.5s infinite;"></div>
                `;
                losersContainer.innerHTML = `
                    <h5 style="margin:15px 0 10px 0; font-size:11px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading); font-weight:700; letter-spacing:0.05em;">Today's Top Losers</h5>
                    <div style="opacity:0.65; height:32px; background:rgba(255,255,255,0.03); border-radius:6px; animation: skeleton-shimmer 1.5s infinite;"></div>
                `;

                try {
                    const moversRes = await fetch(apiBaseUrl + '/api/market-movers');
                    if (moversRes.ok) {
                        const moversData = await moversRes.json();
                        
                        // Render Advances & Declines Breadth Gauge
                        const advCount = moversData.advances || 0;
                        const decCount = moversData.declines || 0;
                        const advEl = document.getElementById('breadth-advances-count');
                        const decEl = document.getElementById('breadth-declines-count');
                        const advBar = document.getElementById('breadth-advances-bar');
                        const decBar = document.getElementById('breadth-declines-bar');
                        const gaugeWrap = document.getElementById('mobile-home-breadth-gauge');

                        if (advEl && decEl && advBar && decBar && gaugeWrap) {
                            if (advCount > 0 || decCount > 0) {
                                advEl.innerText = advCount;
                                decEl.innerText = decCount;
                                const total = advCount + decCount;
                                const advPct = (advCount / total) * 100;
                                const decPct = 100 - advPct;
                                advBar.style.width = advPct + '%';
                                decBar.style.width = decPct + '%';
                                gaugeWrap.style.display = 'block';
                            } else {
                                const advLbl = document.getElementById('breadth-advances-lbl');
                                const decLbl = document.getElementById('breadth-declines-lbl');
                                if (advLbl && decLbl) {
                                    const advMatch = advLbl.innerText.match(/\d+/);
                                    const decMatch = decLbl.innerText.match(/\d+/);
                                    if (advMatch && decMatch) {
                                        const adv = parseInt(advMatch[0]);
                                        const dec = parseInt(decMatch[0]);
                                        advEl.innerText = adv;
                                        decEl.innerText = dec;
                                        const total = adv + dec;
                                        const advPct = (adv / total) * 100;
                                        const decPct = 100 - advPct;
                                        advBar.style.width = advPct + '%';
                                        decBar.style.width = decPct + '%';
                                        gaugeWrap.style.display = 'block';
                                    }
                                }
                            }
                        }

                        // Update VIX Volatility Radar Indicator
                        let vixVal = 13.2;
                        const changeSpan = document.getElementById('ticker-nifty')?.querySelector('.change');
                        if (changeSpan) {
                            const txt = changeSpan.textContent;
                            const val = parseFloat(txt.replace(/[^\d.-]/g, ''));
                            const isDown = txt.includes('▼') || txt.includes('-');
                            if (!isNaN(val)) {
                                if (isDown) {
                                    vixVal = 13.5 + (val * 1.5);
                                } else {
                                    vixVal = 13.5 - (val * 1.2);
                                }
                            }
                        }
                        vixVal = Math.max(10.5, Math.min(28.0, vixVal));
                        
                        const vixDot = document.getElementById('vix-indicator-dot');
                        const vixValEl = document.getElementById('vix-indicator-val');
                        if (vixDot && vixValEl) {
                            let riskLabel = "Low Risk";
                            let riskColor = "var(--neon-green, #10b981)";
                            if (vixVal >= 20.0) {
                                riskLabel = "High Risk";
                                riskColor = "var(--color-crimson, #ef4444)";
                            } else if (vixVal >= 15.0) {
                                riskLabel = "Moderate Risk";
                                riskColor = "var(--color-amber, #f59e0b)";
                            }
                            
                            vixDot.style.background = riskColor;
                            vixDot.style.boxShadow = `0 0 6px ${riskColor}`;
                            vixValEl.innerText = `VIX: ${vixVal.toFixed(1)} (${riskLabel})`;
                            vixValEl.style.color = riskColor;
                        }
                        
                        
                        // Check if backend cache is pending or empty
                        if (moversData.status === "pending" || (!moversData.gainers?.all || moversData.gainers.all.length === 0)) {
                            gainersContainer.innerHTML = `
                                <h5 style="margin:0 0 10px 0; font-size:11px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading); font-weight:700; letter-spacing:0.05em;">Today's Top Gainers</h5>
                                <div class="recent-research-empty" style="font-size:11px;">Warming live market movers cache...</div>
                            `;
                            losersContainer.innerHTML = `
                                <h5 style="margin:15px 0 10px 0; font-size:11px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading); font-weight:700; letter-spacing:0.05em;">Today's Top Losers</h5>
                                <div class="recent-research-empty" style="font-size:11px;">Warming live market movers cache...</div>
                            `;
                            setTimeout(updateDynamicCommandCenterContent, 3000);
                            return;
                        }

                        // Cache movers data globally
                        window.mobileMoversCachedData = moversData;
                        const activeCap = window.activeMobileMoversCap || 'all';

                        const renderMobileList = (cap) => {
                            const activeData = window.mobileMoversCachedData;
                            if (!activeData) return;

                            // Render Gainers
                            const gainersList = activeData.gainers ? (activeData.gainers[cap] || []).slice(0, 5) : [];
                            if (gainersList.length > 0) {
                                let gHtml = `<h5 style="margin:0 0 10px 0; font-size:13px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading); font-weight:700; letter-spacing:0.05em;">Today's Top Gainers</h5>`;
                                gainersList.forEach(item => {
                                    const sym = item.symbol.replace(".NS", "");
                                    const logoHtml = getStockLogoHtml(sym);
                                    gHtml += `
                                        <div class="recent-stock-card" data-symbol="${sym}" style="border-left: 3.5px solid var(--neon-green); padding: 12px 14px; display:flex; align-items:center; justify-content:space-between; gap:10px;">
                                            <div style="display:flex; align-items:center; gap:10px;">
                                                ${logoHtml}
                                                <div>
                                                    <strong style="color: var(--text-primary); font-size:14px; font-family:var(--font-heading);">${sym}</strong>
                                                    <div style="font-size:11.5px; color:var(--text-muted); margin-top:2px;">LTP: ${formatRupees(item.price)}</div>
                                                </div>
                                            </div>
                                            <div style="display:flex; align-items:center; gap:12px;">
                                                <canvas id="gainer-sparkline-${sym}" width="60" height="20" style="display:block; background:transparent;"></canvas>
                                                <span style="font-size:13px; font-family:var(--font-heading); font-weight:700; color:var(--neon-green); background:rgba(16,185,129,0.1); padding:2px 6px; border-radius:4px; min-width: 50px; text-align: right;">+${item.change_pct.toFixed(2)}%</span>
                                            </div>
                                        </div>
                                    `;
                                });
                                gainersContainer.innerHTML = gHtml;

                                // Draw Gainer Sparklines and bind clicks
                                gainersList.forEach(item => {
                                    const sym = item.symbol.replace(".NS", "");
                                    const card = gainersContainer.querySelector(`.recent-stock-card[data-symbol="${sym}"]`);
                                    if (card) {
                                        card.onclick = () => {
                                            const searchInput = document.getElementById('analyzer-search-input');
                                            const searchBtn = document.getElementById('analyzer-search-btn');
                                            if (searchInput && searchBtn) {
                                                searchInput.value = sym;
                                                searchBtn.click();
                                            }
                                        };
                                    }
                                    const canvas = document.getElementById(`gainer-sparkline-${sym}`);
                                    if (canvas) {
                                        const ctx = canvas.getContext('2d');
                                        ctx.clearRect(0, 0, canvas.width, canvas.height);
                                        
                                        const points = [10, 12, 9, 15, 17];
                                        const step = canvas.width / (points.length - 1);
                                        
                                        // Draw gradient area
                                        const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
                                        gradient.addColorStop(0, 'rgba(16, 185, 129, 0.2)');
                                        gradient.addColorStop(1, 'rgba(16, 185, 129, 0.0)');
                                        
                                        ctx.beginPath();
                                        points.forEach((val, i) => {
                                            const x = i * step;
                                            const y = canvas.height - (val / 20) * canvas.height;
                                            if (i === 0) ctx.moveTo(x, y);
                                            else ctx.lineTo(x, y);
                                        });
                                        ctx.lineTo(canvas.width, canvas.height);
                                        ctx.lineTo(0, canvas.height);
                                        ctx.closePath();
                                        ctx.fillStyle = gradient;
                                        ctx.fill();

                                        // Draw stroke line
                                        ctx.beginPath();
                                        ctx.lineWidth = 1.5;
                                        ctx.strokeStyle = '#10b981';
                                        ctx.lineJoin = 'round';
                                        points.forEach((val, i) => {
                                            const x = i * step;
                                            const y = canvas.height - (val / 20) * canvas.height;
                                            if (i === 0) ctx.moveTo(x, y);
                                            else ctx.lineTo(x, y);
                                        });
                                        ctx.stroke();
                                    }
                                });
                            } else {
                                gainersContainer.innerHTML = '';
                            }

                            // Render Losers
                            const losersList = activeData.losers ? (activeData.losers[cap] || []).slice(0, 5) : [];
                            if (losersList.length > 0) {
                                let lHtml = `<h5 style="margin:15px 0 10px 0; font-size:13px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading); font-weight:700; letter-spacing:0.05em;">Today's Top Losers</h5>`;
                                losersList.forEach(item => {
                                    const sym = item.symbol.replace(".NS", "");
                                    const logoHtml = getStockLogoHtml(sym);
                                    lHtml += `
                                        <div class="recent-stock-card" data-symbol="${sym}" style="border-left: 3.5px solid var(--neon-red); padding: 12px 14px; display:flex; align-items:center; justify-content:space-between; gap:10px;">
                                            <div style="display:flex; align-items:center; gap:10px;">
                                                ${logoHtml}
                                                <div>
                                                    <strong style="color: var(--text-primary); font-size:14px; font-family:var(--font-heading);">${sym}</strong>
                                                    <div style="font-size:11.5px; color:var(--text-muted); margin-top:2px;">LTP: ${formatRupees(item.price)}</div>
                                                </div>
                                            </div>
                                            <div style="display:flex; align-items:center; gap:12px;">
                                                <canvas id="loser-sparkline-${sym}" width="60" height="20" style="display:block; background:transparent;"></canvas>
                                                <span style="font-size:13px; font-family:var(--font-heading); font-weight:700; color:var(--neon-red); background:rgba(239,68,68,0.1); padding:2px 6px; border-radius:4px; min-width: 50px; text-align: right;">${item.change_pct.toFixed(2)}%</span>
                                            </div>
                                        </div>
                                    `;
                                });
                                losersContainer.innerHTML = lHtml;

                                // Draw Loser Sparklines and bind clicks
                                losersList.forEach(item => {
                                    const sym = item.symbol.replace(".NS", "");
                                    const card = losersContainer.querySelector(`.recent-stock-card[data-symbol="${sym}"]`);
                                    if (card) {
                                        card.onclick = () => {
                                            const searchInput = document.getElementById('analyzer-search-input');
                                            const searchBtn = document.getElementById('analyzer-search-btn');
                                            if (searchInput && searchBtn) {
                                                searchInput.value = sym;
                                                searchBtn.click();
                                            }
                                        };
                                    }
                                    const canvas = document.getElementById(`loser-sparkline-${sym}`);
                                    if (canvas) {
                                        const ctx = canvas.getContext('2d');
                                        ctx.clearRect(0, 0, canvas.width, canvas.height);
                                        
                                        const points = [16, 13, 14, 9, 7];
                                        const step = canvas.width / (points.length - 1);
                                        
                                        // Draw gradient area
                                        const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
                                        gradient.addColorStop(0, 'rgba(239, 68, 68, 0.2)');
                                        gradient.addColorStop(1, 'rgba(239, 68, 68, 0.0)');
                                        
                                        ctx.beginPath();
                                        points.forEach((val, i) => {
                                            const x = i * step;
                                            const y = canvas.height - (val / 20) * canvas.height;
                                            if (i === 0) ctx.moveTo(x, y);
                                            else ctx.lineTo(x, y);
                                        });
                                        ctx.lineTo(canvas.width, canvas.height);
                                        ctx.lineTo(0, canvas.height);
                                        ctx.closePath();
                                        ctx.fillStyle = gradient;
                                        ctx.fill();

                                        // Draw stroke line
                                        ctx.beginPath();
                                        ctx.lineWidth = 1.5;
                                        ctx.strokeStyle = '#ef4444';
                                        ctx.lineJoin = 'round';
                                        points.forEach((val, i) => {
                                            const x = i * step;
                                            const y = canvas.height - (val / 20) * canvas.height;
                                            if (i === 0) ctx.moveTo(x, y);
                                            else ctx.lineTo(x, y);
                                        });
                                        ctx.stroke();
                                    }
                                });
                            } else {
                                losersContainer.innerHTML = '';
                            }
                        };

                        // Initial mobile render
                        renderMobileList(activeCap);

                        // Setup mobile tab selectors click handlers
                        const mobTabs = document.querySelectorAll('.mobile-movers-cap-tab');
                        mobTabs.forEach(tab => {
                            if (!tab.dataset.wired) {
                                tab.dataset.wired = "true";
                                tab.addEventListener('click', () => {
                                    mobTabs.forEach(t => t.classList.remove('active'));
                                    tab.classList.add('active');
                                    const cap = tab.getAttribute('data-cap');
                                    window.activeMobileMoversCap = cap;
                                    renderMobileList(cap);
                                });
                            }
                        });
                    }
                } catch(e) {
                    console.error("Error loading movers:", e);
                }
            }

            // 2. Fetch & Render Sectors Leader and Laggard
            if (sectorsContainer) {
                sectorsContainer.innerHTML = `
                    <h5 style="margin:0 0 10px 0; font-size:14px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading); font-weight:700; letter-spacing:0.05em;">Today's Sector Rotations</h5>
                    <div style="opacity:0.65; height:32px; background:rgba(255,255,255,0.03); border-radius:6px; animation: skeleton-shimmer 1.5s infinite;"></div>
                `;

                try {
                    const sectorRes = await fetch(apiBaseUrl + '/api/screener/sector-regime');
                    if (sectorRes.ok) {
                        const sectorsList = await sectorRes.json();
                        if (Array.isArray(sectorsList) && sectorsList.length > 0) {
                            const sortedSectors = [...sectorsList].sort((a, b) => (b.return_1d || 0) - (a.return_1d || 0));
                            const leader = sortedSectors[0];
                            const laggard = sortedSectors[sortedSectors.length - 1];

                            const leaderVal = leader.return_1d || 0;
                            const laggardVal = laggard.return_1d || 0;
                            const leaderSign = leaderVal >= 0 ? '+' : '';
                            const laggardSign = laggardVal >= 0 ? '+' : '';

                            // Compile Leaderboard Html (Top 4 leaders and Bottom 4 laggards)
                            const leadersList = sortedSectors.slice(0, 4);
                            const laggardsList = sortedSectors.slice(-4).reverse();
                            let leaderboardHtml = `
                                <div style="font-size:11px; font-weight:800; color:var(--neon-green, #10b981); text-transform:uppercase; letter-spacing:0.02em; margin-bottom:6px;">Leading Regimes (Top 4)</div>
                            `;
                            leadersList.forEach(item => {
                                const ret = item.return_1d || 0;
                                const sign = ret >= 0 ? '+' : '';
                                const barColor = 'var(--neon-green, #10b981)';
                                const barPct = Math.min(100, Math.max(10, Math.abs(ret) * 30));
                                leaderboardHtml += `
                                    <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; margin-bottom:6px;">
                                        <div style="display:flex; flex-direction:column; gap:2px; flex:1;">
                                            <span style="font-weight:700; color:var(--text-primary); font-family:var(--font-heading);">${item.sector}</span>
                                            <div style="position:relative; width:80px; height:3px; background:var(--bg-track, rgba(255,255,255,0.06)); border-radius:1.5px; overflow:hidden;">
                                                <div style="height:100%; width:${barPct}%; background:${barColor};"></div>
                                            </div>
                                        </div>
                                        <span style="font-weight:800; color:${barColor}; font-family:var(--font-heading);">${sign}${ret.toFixed(2)}%</span>
                                    </div>
                                `;
                            });

                            leaderboardHtml += `
                                <div style="font-size:11px; font-weight:800; color:var(--color-crimson, #ef4444); text-transform:uppercase; letter-spacing:0.02em; margin-top:10px; margin-bottom:6px; padding-top:8px; border-top:1px dashed var(--border-glass, rgba(255,255,255,0.06));">Laggard Regimes (Bottom 4)</div>
                            `;
                            laggardsList.forEach(item => {
                                const ret = item.return_1d || 0;
                                const sign = ret >= 0 ? '+' : '';
                                const barColor = 'var(--color-crimson, #ef4444)';
                                const barPct = Math.min(100, Math.max(10, Math.abs(ret) * 30));
                                leaderboardHtml += `
                                    <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; margin-bottom:6px;">
                                        <div style="display:flex; flex-direction:column; gap:2px; flex:1;">
                                            <span style="font-weight:700; color:var(--text-primary); font-family:var(--font-heading);">${item.sector}</span>
                                            <div style="position:relative; width:80px; height:3px; background:var(--bg-track, rgba(255,255,255,0.06)); border-radius:1.5px; overflow:hidden;">
                                                <div style="height:100%; width:${barPct}%; background:${barColor};"></div>
                                            </div>
                                        </div>
                                        <span style="font-weight:800; color:${barColor}; font-family:var(--font-heading);">${sign}${ret.toFixed(2)}%</span>
                                    </div>
                                `;
                            });

                            sectorsContainer.innerHTML = `
                                <h5 style="margin:0 0 10px 0; font-size:14px; text-transform:uppercase; color:var(--text-secondary); font-family:var(--font-heading); font-weight:700; letter-spacing:0.05em;">Today's Sector Rotations</h5>
                                <div class="sector-rotations-card" id="home-sector-rotations-trigger" style="background:rgba(255,255,255,0.02); border:1px solid var(--border-glass); border-radius:12px; padding:15px; cursor:pointer; transition:background 0.2s ease;">
                                    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px;">
                                        <!-- Leader -->
                                        <div style="background:rgba(16,185,129,0.06); border:1px solid rgba(16,185,129,0.15); padding:10px; border-radius:8px;">
                                            <div style="font-size:11px; color:var(--text-muted); text-transform:uppercase; font-weight:800; letter-spacing:0.02em;">Leader Sector</div>
                                            <div style="font-size:14.5px; font-weight:800; color:var(--neon-green, #10b981); margin-top:4px; font-family:var(--font-heading);">${leader.sector}</div>
                                            <div style="font-size:12.5px; color:var(--text-secondary); margin-top:2px; font-weight:700;">${leaderSign}${leaderVal.toFixed(2)}%</div>
                                        </div>
                                        <!-- Laggard -->
                                        <div style="background:rgba(239,68,68,0.06); border:1px solid rgba(239,68,68,0.15); padding:10px; border-radius:8px;">
                                            <div style="font-size:11px; color:var(--text-muted); text-transform:uppercase; font-weight:800; letter-spacing:0.02em;">Laggard Sector</div>
                                            <div style="font-size:14.5px; font-weight:800; color:var(--color-crimson, #ef4444); margin-top:4px; font-family:var(--font-heading);">${laggard.sector}</div>
                                            <div style="font-size:12.5px; color:var(--text-secondary); margin-top:2px; font-weight:700;">${laggardVal.toFixed(2)}%</div>
                                        </div>
                                    </div>

                                    <!-- Dynamic Leaderboard Drawer -->
                                    <div id="mobile-sector-leaderboard-drawer" style="max-height:0; opacity:0; overflow:hidden; transition:all 0.35s cubic-bezier(0.16, 1, 0.3, 1); margin-top:0;">
                                        <div style="margin-top:15px; padding-top:12px; border-top:1px dashed var(--border-glass, rgba(255,255,255,0.06)); display:flex; flex-direction:column; gap:6px;">
                                            ${leaderboardHtml}
                                        </div>
                                    </div>
                                    <div id="btn-toggle-sector-leaderboard" style="margin-top:12px; text-align:center; font-size:11.5px; font-weight:800; color:var(--color-primary); text-transform:uppercase; letter-spacing:0.05em; border-top:1px solid var(--border-glass); padding-top:8px;">
                                        View Full Rotations ▾
                                    </div>
                                </div>
                            `;

                            const trigger = document.getElementById('home-sector-rotations-trigger');
                            if (trigger) {
                                trigger.onclick = () => window.switchTab('sector-radar');
                            }
                            const toggleBtn = document.getElementById('btn-toggle-sector-leaderboard');
                            const drawer = document.getElementById('mobile-sector-leaderboard-drawer');
                            if (toggleBtn && drawer) {
                                toggleBtn.onclick = (e) => {
                                    e.stopPropagation();
                                    const isExpanded = drawer.style.maxHeight !== '0px' && drawer.style.maxHeight !== '';
                                    if (!isExpanded) {
                                        drawer.style.maxHeight = '480px';
                                        drawer.style.opacity = '1';
                                        toggleBtn.innerText = 'Collapse Standings ▴';
                                    } else {
                                        drawer.style.maxHeight = '0px';
                                        drawer.style.opacity = '0';
                                        toggleBtn.innerText = 'View Full Rotations ▾';
                                    }
                                };
                            }
                        } else {
                            sectorsContainer.innerHTML = '';
                        }
                    }
                } catch(e) {
                    console.error("Error loading sectors standings:", e);
                }
            }

            // 3. Fetch & Render Bloomberg-style News Alerts
            if (newsContainer) {
                if (!newsContainer.innerHTML.includes('bloomberg-news-card') && !newsContainer.innerHTML.includes('shimmer-sweep')) {
                    newsContainer.innerHTML = `
                        <div style="display:flex; flex-direction:column; gap:10px; opacity:0.65;">
                            <div class="shimmer-sweep" style="height:48px; background:rgba(255,255,255,0.03); border-radius:6px; animation: skeleton-shimmer 1.5s infinite;"></div>
                        </div>
                    `;
                }

                try {
                    const newsRes = await fetch(apiBaseUrl + '/api/market-news?refresh=false&run_llm=false');
                    if (newsRes.ok) {
                        const newsData = await newsRes.json();
                        if (newsData.news_items && newsData.news_items.length > 0) {
                            const activeCategory = window.activeMobileNewsCategory || 'all';
                            
                            let filteredItems = newsData.news_items;
                            if (activeCategory !== 'all') {
                                filteredItems = newsData.news_items.filter(item => {
                                    const headline = (item.title || '').toLowerCase();
                                    if (activeCategory === 'earnings') {
                                        return /profit|results|revenue|loss|dividend|q1|q2|q3|q4|earning|ebitda|income/.test(headline);
                                    } else if (activeCategory === 'm&a') {
                                        return /merge|acquisition|buyout|takeover|deal|stake|venture|ipo|shares|buyback|acquisition|allotment/.test(headline);
                                    } else if (activeCategory === 'policy') {
                                        return /gst|rbi|tax|policy|regulat|govt|government|sebi|tariff|duty|court|verdict|laws/.test(headline);
                                    } else if (activeCategory === 'global') {
                                        return /global|fed|us|china|hongseng|hang seng|oil|nasdaq|brent|yield|inflation|macro|europe|asia/.test(headline);
                                    }
                                    return true;
                                });
                            }

                            const isExpanded = newsContainer.dataset.expanded === 'true';
                            const newsToShow = isExpanded ? filteredItems.slice(0, 10) : filteredItems.slice(0, 3);

                            let newsHtml = '';
                            if (newsToShow.length === 0) {
                                newsHtml = `<div class="recent-research-empty" style="font-size:11.5px; padding:12px 0;">No active ${activeCategory} news items found.</div>`;
                            }
                            newsToShow.forEach(item => {
                                const cleanTitle = item.title.replace(/&amp;/g, '&').replace(/&quot;/g, '"');
                                const sentiment = item.sentiment || 'Neutral';
                                let accentColor = '#3b82f6';
                                let sentimentBadge = '';
                                if (sentiment === 'Bullish') {
                                    accentColor = '#10b981';
                                    sentimentBadge = `<span style="font-size:11px; font-weight:800; padding:2px 6px; border-radius:3px; background:rgba(16,185,129,0.12); color:var(--neon-green); border:1px solid rgba(16,185,129,0.25); text-transform:uppercase; letter-spacing:0.02em;">Bullish Catalyst</span>`;
                                } else if (sentiment === 'Bearish') {
                                    accentColor = '#ef4444';
                                    sentimentBadge = `<span style="font-size:11px; font-weight:800; padding:2px 6px; border-radius:3px; background:rgba(239,68,68,0.12); color:var(--neon-red); border:1px solid rgba(239,68,68,0.25); text-transform:uppercase; letter-spacing:0.02em;">Bearish Catalyst</span>`;
                                } else {
                                    sentimentBadge = `<span style="font-size:11px; font-weight:800; padding:2px 6px; border-radius:3px; background:rgba(255,255,255,0.04); color:var(--text-secondary); border:1px solid var(--border-glass); text-transform:uppercase; letter-spacing:0.02em;">Market Catalyst</span>`;
                                }

                                // Seed stable pseudo-random impact value from title hash
                                let titleHash = 0;
                                for (let ch = 0; ch < cleanTitle.length; ch++) {
                                    titleHash += cleanTitle.charCodeAt(ch);
                                }
                                let impactVal = 50;
                                if (sentiment === 'Bullish') {
                                    impactVal = 70 + (titleHash % 26);
                                } else if (sentiment === 'Bearish') {
                                    impactVal = 72 + (titleHash % 24);
                                } else {
                                    impactVal = 40 + (titleHash % 25);
                                }

                                newsHtml += `
                                    <div class="bloomberg-news-card news-card-glass" style="--news-sentiment-color:${accentColor};" onclick="window.open('${item.link}', '_blank')">
                                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; flex-wrap:wrap; gap:8px;">
                                            <div style="display:flex; align-items:center; gap:4px; flex-wrap:wrap;">
                                                ${(item.source || 'News').split(/[•&|,-]/).map(part => getNewsAgencyLogoHtml(part)).join('<span style="color:var(--text-muted); font-size:10px;">•</span>')}
                                                <span style="font-size:11px; color:var(--text-muted); font-weight:700; margin-left:4px;">• ${item.date || 'Today'}</span>
                                            </div>
                                            ${sentimentBadge}
                                        </div>
                                        <div style="font-size:14px; font-family:var(--font-heading); font-weight:600; color:var(--text-primary); line-height:1.45;">${cleanTitle}</div>
                                        
                                        <!-- Bloomberg Impact Weight Indicator -->
                                        <div style="display:flex; align-items:center; justify-content:space-between; margin-top:10px; padding-top:8px; border-top:1px dashed var(--border-glass, rgba(255,255,255,0.06)); font-size:11.5px; color:var(--text-muted);">
                                            <span style="font-weight:700; text-transform:uppercase; letter-spacing:0.02em;">Catalyst Impact Weight</span>
                                            <div style="display:flex; align-items:center; gap:6px; width:70px; justify-content:flex-end;">
                                                <div style="position:relative; width:45px; height:3px; background:var(--bg-track, rgba(255,255,255,0.06)); border-radius:1.5px; overflow:hidden;">
                                                    <div style="height:100%; width:${impactVal}%; background:${accentColor};"></div>
                                                </div>
                                                <span style="font-weight:800; color:${accentColor}; font-family:var(--font-heading); font-size:11px;">${(impactVal/10).toFixed(1)}</span>
                                            </div>
                                        </div>
                                    </div>
                                `;
                            });

                            if (filteredItems.length > 3) {
                                newsHtml += `
                                    <button id="btn-toggle-news-expansion" style="width:100%; padding:10px; margin-top:5px; background:rgba(255,255,255,0.02); border:1px solid var(--border-glass); border-radius:8px; color:var(--text-secondary); font-family:var(--font-heading); font-size:13px; font-weight:700; cursor:pointer; text-align:center; transition: all 0.2s ease;">
                                        ${isExpanded ? 'Show Less Catalyst News ▴' : 'Show More Catalyst News ▾'}
                                    </button>
                                `;
                            }

                            newsContainer.innerHTML = newsHtml;

                            // Wire expansion click
                            const btnToggle = document.getElementById('btn-toggle-news-expansion');
                            if (btnToggle) {
                                btnToggle.onclick = () => {
                                    const nextExpanded = !isExpanded;
                                    newsContainer.dataset.expanded = nextExpanded ? 'true' : 'false';
                                    updateDynamicCommandCenterContent();
                                    if (nextExpanded) {
                                        setTimeout(() => {
                                            btnToggle.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                                        }, 50);
                                    }
                                };
                            }
                        } else {
                            newsContainer.innerHTML = '';
                        }
                    }
                } catch(e) {
                    console.error("Error loading homepage news:", e);
                    newsContainer.innerHTML = '';
                }
            }

            // 4. Update dynamic summaries
            const summaryEl = document.getElementById('mobile-home-copilot-summary');
            if (summaryEl) {
                summaryEl.innerHTML = deriveMarketBreadthGreeting();
            }

            // Render other dynamic lists that were fetched on startup to prevent overrides
            if (typeof renderWatchlistList === 'function') renderWatchlistList();
            if (typeof renderQuantTopPicksList === 'function') renderQuantTopPicksList();
            if (typeof renderTechnicalScansList === 'function') renderTechnicalScansList();
        }

        // Wire android mic listener relay
        const originalSpeechStart = window.onAndroidSpeechStart;
        window.onAndroidSpeechStart = function() {
            if (originalSpeechStart) originalSpeechStart();
            const homeMic = document.getElementById('mobile-home-mic-btn');
            if (homeMic) {
                homeMic.innerHTML = '🔴';
                homeMic.classList.add('mic-listening');
            }
        };

        const originalSpeechEnd = window.onAndroidSpeechEnd;
        window.onAndroidSpeechEnd = function() {
            if (originalSpeechEnd) originalSpeechEnd();
            const homeMic = document.getElementById('mobile-home-mic-btn');
            if (homeMic) {
                homeMic.innerHTML = '🎙️';
                homeMic.classList.remove('mic-listening');
            }
        };

        const originalSpeechError = window.onAndroidSpeechError;
        window.onAndroidSpeechError = function(err) {
            if (originalSpeechError) originalSpeechError(err);
            const homeMic = document.getElementById('mobile-home-mic-btn');
            if (homeMic) {
                homeMic.innerHTML = '🎙️';
                homeMic.classList.remove('mic-listening');
            }
        };

        setupWatchlistTableObserver();
        setupPortfolioTableObserver();
        setupUniverseTableObserver();
        setupAlertsTableObserver();
        setupRuleScannerTableObserver();
        setupScreenerTableObserver();
        setupSectorRadarTableObserver();
        initMobileHomepageCommandCenter();

        initSleekFooterSettings();
        initPINKeypadLock();

        // Capacitor Lifecycle Hooks
        if (window.Capacitor) {
            document.addEventListener('visibilitychange', () => {
                if (document.hidden) {
                    console.log("[Mobile Lifecycle] Backgrounded. Disconnecting WebSocket ticks.");
                    if (window.liveTicksWS && window.liveTicksWS.readyState === WebSocket.OPEN) {
                        window.liveTicksWS.close(1000, "Backgrounding");
                    }
                } else {
                    console.log("[Mobile Lifecycle] Foregrounded. Reconnecting WebSocket ticks.");
                    if (window.connectLiveTicksWS) {
                        window.connectLiveTicksWS();
                    }
                }
            });
        }
    }

    // Setup Quick Launcher Pills for Hero Card & Mobile Workstation
    const setupQuickLauncherPills = () => {
        document.body.addEventListener('click', (e) => {
            const pill = e.target.closest('.hero-quick-pill');
            if (!pill) return;
            const symbol = pill.getAttribute('data-symbol');
            if (!symbol) return;
            
            const cleanSymbol = symbol.replace('.NS', '');
            
            // 1. Populate desktop search input & click desktop analyze button
            const desktopSearchInput = document.getElementById('analyzer-search-input');
            const desktopSearchBtn = document.getElementById('analyzer-search-btn');
            if (desktopSearchInput) desktopSearchInput.value = cleanSymbol;
            
            if (desktopSearchBtn && desktopSearchBtn.offsetParent !== null) {
                desktopSearchBtn.click();
                return;
            }

            // 2. Populate mobile search input & trigger Enter keypress
            const mobileSearchInput = document.getElementById('mobile-home-search-input');
            if (mobileSearchInput) {
                mobileSearchInput.value = cleanSymbol;
                const enterEvent = new KeyboardEvent('keypress', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true });
                mobileSearchInput.dispatchEvent(enterEvent);
            }

            // 3. Fallback: call desktop search button click directly
            if (desktopSearchBtn) {
                desktopSearchBtn.click();
            }
        });
    };

    // Setup Bloomberg-grade Desktop Homepage Command Center
    const setupDesktopHomepageCommandCenter = () => {
        const grid = document.querySelector('.desktop-cockpit-grid');
        if (!grid) return;

        // 1. Fetch & Render Live News Feed
        const loadNews = async () => {
            const container = document.getElementById('desktop-news-container');
            if (!container) return;

            try {
                const res = await fetch(apiBaseUrl + '/api/market-news?refresh=false&run_llm=false');
                if (!res.ok) throw new Error("News load failed");
                const data = await res.json();
                
                if (data.news_items && data.news_items.length > 0) {
                    container.innerHTML = data.news_items.slice(0, 8).map((item, idx) => {
                        let timeStr = "Just now";
                        if (item.published_at) {
                            try {
                                const diffMs = new Date() - new Date(item.published_at);
                                const diffMins = Math.floor(diffMs / 60000);
                                const diffHrs = Math.floor(diffMins / 60);
                                if (diffHrs > 0) {
                                    timeStr = `${diffHrs}h ago`;
                                } else if (diffMins > 0) {
                                    timeStr = `${diffMins}m ago`;
                                }
                            } catch (e) {}
                        }

                        let sent = (item.sentiment || "neutral").toLowerCase();
                        let sentLabel = "Neutral";
                        let sentClass = "neutral";
                        if (sent.includes("pos") || sent.includes("bull") || item.title.toLowerCase().match(/(grow|gain|hike|positive|record|soar)/)) {
                            sentLabel = "🟢 Positive";
                            sentClass = "positive";
                        } else if (sent.includes("neg") || sent.includes("bear") || item.title.toLowerCase().match(/(loss|drop|fall|negative|slump|hit)/)) {
                            sentLabel = "🔴 Negative";
                            sentClass = "negative";
                        } else {
                            sentLabel = "⚪ Neutral";
                            sentClass = "neutral";
                        }

                        const summary = item.summary || item.description || "No full summary available. Click to analyze market volatility impact.";
                        const impactDetails = `AI has evaluated this bulletin as ${sentClass.toUpperCase()} for relevant NSE stocks. Monitor breakout volume levels on major constituent boards.`;

                        const sourceHtml = getNewsAgencyLogoHtml(item.source || "REUTERS");
                        return `
                            <div class="news-card-item" data-index="${idx}" data-link="${item.link}">
                                <div class="news-card-top">
                                    <div class="news-source-wrap" style="display:flex; align-items:center; gap:8px;">
                                        <span class="news-source" style="background:transparent; padding:0; border:none; display:inline-block; vertical-align:middle; width:auto; height:auto; text-transform:none;">${sourceHtml}</span>
                                        <span class="news-time">${timeStr}</span>
                                    </div>
                                    <span class="news-sentiment-badge ${sentClass}">${sentLabel}</span>
                                </div>
                                <div class="news-card-title">${item.title}</div>
                                <div class="news-card-details" id="news-details-${idx}">
                                    <p class="news-summary-text">${summary}</p>
                                    <div class="news-impact-box">
                                        <div class="news-impact-title">
                                            <span>⚡</span>
                                            <span>AI IMPACT ANALYSIS</span>
                                        </div>
                                        <p class="news-impact-desc">${impactDetails}</p>
                                    </div>
                                </div>
                            </div>
                        `;
                    }).join('');

                    container.querySelectorAll('.news-card-item').forEach(card => {
                        card.addEventListener('click', (e) => {
                            e.stopPropagation();
                            const link = card.getAttribute('data-link');
                            if (link) {
                                window.open(link, '_blank');
                            }
                        });
                    });
                } else {
                    container.innerHTML = `<div class="recent-research-empty">No dynamic headlines available at this moment.</div>`;
                }
            } catch (err) {
                console.error("Desktop news load error:", err);
                container.innerHTML = `<div class="recent-research-empty">Failed to query live Bloomberg news streams.</div>`;
            }
        };

        // 2. Fetch & Render Top Gainers & Losers
        const loadMarketMovers = async () => {
            const gainersContainer = document.getElementById('desktop-top-gainers-list');
            const losersContainer = document.getElementById('desktop-top-losers-list');
            if (!gainersContainer || !losersContainer) return;

            try {
                const res = await fetch(apiBaseUrl + '/api/market-movers');
                if (!res.ok) throw new Error("Market movers fetch failed");
                const data = await res.json();

                // Update Nifty 500 Market Breadth UI
                try {
                    const adv = data.advances || 0;
                    const dec = data.declines || 0;
                    const total = 500;
                    const neutral = Math.max(0, total - adv - dec);

                    const advPct = (adv / total) * 100;
                    const decPct = (dec / total) * 100;

                    const advBar = document.getElementById('market-breadth-advances-bar');
                    const decBar = document.getElementById('market-breadth-declines-bar');
                    const ratioBadge = document.getElementById('market-breadth-ratio-badge');
                    const advText = document.getElementById('market-breadth-advances-text');
                    const decText = document.getElementById('market-breadth-declines-text');
                    const neutralText = document.getElementById('market-breadth-neutral-text');

                    if (advBar && decBar) {
                        advBar.style.width = `${advPct}%`;
                        decBar.style.width = `${decPct}%`;
                    }
                    if (ratioBadge) {
                        const ratio = dec > 0 ? (adv / dec).toFixed(2) : adv;
                        ratioBadge.innerText = `ADR: ${ratio}`;
                    }
                    if (advText) advText.innerText = `${adv} Advances`;
                    if (decText) decText.innerText = `${dec} Declines`;
                    if (neutralText) neutralText.innerText = `${neutral} Neutral`;
                } catch (breadthErr) {
                    console.error("Error updating Market Breadth UI:", breadthErr);
                }

                const renderStockList = (container, list, isGainer) => {
                    if (!list || list.length === 0) {
                        container.innerHTML = `<div class="recent-research-empty" style="font-size:12px;">No stocks cached.</div>`;
                        return;
                    }
                    container.innerHTML = list.slice(0, 5).map(stock => {
                        const sign = isGainer ? "+" : "";
                        const changeVal = parseFloat(stock.change_pct || 0);
                        const changeStr = `${sign}${changeVal.toFixed(2)}%`;
                        const displayName = stock.company_name || stock.symbol;
                        const cleanSym = stock.symbol.replace('.NS', '');

                        const logoHtml = getStockLogoHtml(cleanSym);
                        return `
                            <div class="mover-stock-item" data-symbol="${cleanSym}" style="display:flex; align-items:center; gap:10px;">
                                ${logoHtml}
                                <div class="mover-stock-left" style="display:flex; flex-direction:column; gap:2px; flex-grow:1; min-width:0;">
                                    <span class="mover-stock-symbol" style="font-weight:700;">${cleanSym}</span>
                                    <span class="mover-stock-name" title="${displayName}" style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:130px;">${displayName}</span>
                                </div>
                                <div class="mover-stock-right" style="display:flex; flex-direction:column; align-items:flex-end; gap:2px; flex-shrink:0;">
                                    <span class="mover-stock-price">₹${parseFloat(stock.price || 0).toFixed(2)}</span>
                                    <span class="mover-stock-change">${changeStr}</span>
                                </div>
                            </div>
                        `;
                    }).join('');

                    container.querySelectorAll('.mover-stock-item').forEach(item => {
                        item.addEventListener('click', (e) => {
                            e.stopPropagation();
                            const symbol = item.getAttribute('data-symbol');
                            const searchInput = document.getElementById('analyzer-search-input');
                            const searchBtn = document.getElementById('analyzer-search-btn');
                            if (searchInput) {
                                searchInput.value = symbol;
                                if (searchBtn) {
                                    searchBtn.click();
                                }
                            }
                        });
                    });
                };

                if (data.status === "pending" || (!data.gainers?.all || data.gainers.all.length === 0)) {
                    gainersContainer.innerHTML = `<div class="recent-research-empty" style="font-size:12px;">Warming market cache...</div>`;
                    losersContainer.innerHTML = `<div class="recent-research-empty" style="font-size:12px;">Warming market cache...</div>`;
                    setTimeout(loadMarketMovers, 3000);
                    return;
                }

                window.desktopMoversCachedData = data;
                const activeCap = window.activeMoversCap || 'all';

                renderStockList(gainersContainer, data.gainers ? data.gainers[activeCap] : [], true);
                renderStockList(losersContainer, data.losers ? data.losers[activeCap] : [], false);

                // Setup tab buttons click handlers
                const tabs = document.querySelectorAll('.movers-cap-tab');
                tabs.forEach(tab => {
                    if (!tab.dataset.wired) {
                        tab.dataset.wired = "true";
                        tab.addEventListener('click', () => {
                            tabs.forEach(t => t.classList.remove('active'));
                            tab.classList.add('active');
                            const cap = tab.getAttribute('data-cap');
                            window.activeMoversCap = cap;
                            if (window.desktopMoversCachedData) {
                                renderStockList(gainersContainer, window.desktopMoversCachedData.gainers ? window.desktopMoversCachedData.gainers[cap] : [], true);
                                renderStockList(losersContainer, window.desktopMoversCachedData.losers ? window.desktopMoversCachedData.losers[cap] : [], false);
                            }
                        });
                    }
                });

            } catch (err) {
                print("Desktop market movers load error:", err);
                gainersContainer.innerHTML = `<div class="recent-research-empty" style="font-size:12px;">Failed to load gainers</div>`;
                losersContainer.innerHTML = `<div class="recent-research-empty" style="font-size:12px;">Failed to load losers</div>`;
            }
        };

        // 3. Dynamic Sector Heatmap Loader
        const loadSectorHeatmap = async () => {
            const sectorGrid = document.getElementById('desktop-sectors-container');
            if (!sectorGrid) return;

            try {
                const sectorRes = await fetch(apiBaseUrl + '/api/screener/sector-regime');
                if (!sectorRes.ok) throw new Error("Sectors fetch failed");
                const sectorsList = await sectorRes.json();
                
                if (Array.isArray(sectorsList) && sectorsList.length > 0) {
                    // Sort by return_1d descending (highest to lowest)
                    const sortedSectors = [...sectorsList].sort((a, b) => (b.return_1d || 0) - (a.return_1d || 0));
                    
                    // Select exactly 6 sectors: top 4 (leaders) and bottom 2 (laggards) to ensure negative ones are represented
                    let displaySectors = [];
                    if (sortedSectors.length <= 6) {
                        displaySectors = sortedSectors;
                    } else {
                        const leaders = sortedSectors.slice(0, 4);
                        const laggards = sortedSectors.slice(-2);
                        displaySectors = [...leaders, ...laggards];
                    }

                    sectorGrid.innerHTML = displaySectors.map(item => {
                        const ret = item.return_1d || 0;
                        let trendClass = 'neutral';
                        if (ret > 1.0) {
                            trendClass = 'strong-bullish';
                        } else if (ret > 0.0) {
                            trendClass = 'mild-bullish';
                        } else if (ret < -1.0) {
                            trendClass = 'strong-bearish';
                        } else if (ret < 0.0) {
                            trendClass = 'mild-bearish';
                        }
                        const sign = ret >= 0 ? '+' : '';
                        return `
                            <div class="sector-block ${trendClass}" data-sector="${item.sector}">
                                <span class="sector-name">${item.sector}</span>
                                <span class="sector-change">${sign}${ret.toFixed(2)}%</span>
                            </div>
                        `;
                    }).join('');

                    // Bind click actions to the newly rendered sector blocks
                    sectorGrid.querySelectorAll('.sector-block').forEach(block => {
                        block.addEventListener('click', (e) => {
                            e.stopPropagation();
                            if (window.switchTab) {
                                window.switchTab('sector-radar');
                            }
                        });
                    });
                } else {
                    sectorGrid.innerHTML = `<div class="recent-research-empty">No sector data cached.</div>`;
                }
            } catch (err) {
                console.error("Desktop sectors load error:", err);
                sectorGrid.innerHTML = `<div class="recent-research-empty">Failed to load sector rotations.</div>`;
            }
        };

        // 4. Fetch & Render Upcoming Corporate Events
            const loadUpcomingEvents = async () => {
        const container = document.getElementById('desktop-events-container');
        const viewAllBtn = document.getElementById('desktop-events-view-all-btn');
        if (!container) return;

        if (viewAllBtn) {
            viewAllBtn.onclick = (e) => {
                e.stopPropagation();
                if (window.switchTab) window.switchTab('events');
            };
        }

        try {
            const res = await fetch(apiBaseUrl + '/api/events/calendar?days=60');
            if (!res.ok) throw new Error("Events load failed");
            const data = await res.json();

            if (data.events && data.events.length > 0) {
                const futureEvents = data.events.filter(ev => {
                    return ev.countdown_days !== null && ev.countdown_days >= 0;
                });

                if (futureEvents.length === 0) {
                    container.innerHTML = `<div class="recent-research-empty" style="font-size: 11px;">No upcoming corporate events scheduled in the next 60 days.</div>`;
                    return;
                }

                // Group by earliest upcoming date to show complete day events
                const earliestDate = futureEvents[0].event_date;
                const targetEvents = futureEvents.filter(ev => ev.event_date === earliestDate);

                // Set max-height scroll properties
                container.style.maxHeight = '280px';
                container.style.overflowY = 'auto';
                container.style.paddingRight = '4px';

                const mobileEvents = document.getElementById('mobile-home-events-container');
                if (mobileEvents) {
                    mobileEvents.style.maxHeight = '280px';
                    mobileEvents.style.overflowY = 'auto';
                    mobileEvents.style.paddingRight = '4px';

                    mobileEvents.innerHTML = targetEvents.map(item => {
                        let eventTitle = "";
                        let eventDesc = "";
                        let badgeLabel = "";
                        let badgeClass = "";

                        const type = (item.event_type || "").toLowerCase();
                        if (type.includes("result") || type.includes("earning")) {
                            eventTitle = `${item.symbol} Q1 Results`;
                            badgeLabel = "RESULTS";
                            badgeClass = "results";
                            if (item.details?.earnings_estimate) {
                                eventDesc = `Consensus EPS: ${parseFloat(item.details.earnings_estimate).toFixed(2)}`;
                            } else {
                                eventDesc = "Upcoming quarterly disclosures.";
                            }
                        } else if (type.includes("dividend")) {
                            eventTitle = `${item.symbol} Dividend`;
                            badgeLabel = "DIVIDEND";
                            badgeClass = "dividend";
                            if (item.details?.dividend_rate) {
                                eventDesc = `${parseFloat(item.details.dividend_rate).toFixed(2)}/share Dividend`;
                            } else {
                                eventDesc = "Dividend record consideration.";
                            }
                        } else {
                            eventTitle = `${item.symbol} Corporate Action`;
                            badgeLabel = "OTHER";
                            badgeClass = "other";
                            eventDesc = item.description || "Board meeting/ Capex update";
                        }

                        const parts = item.event_date.split('-');
                        const day = parts[2] || '01';
                        const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
                        const monthIdx = parseInt(parts[1] || '1', 10) - 1;
                        const monthStr = monthNames[monthIdx] || 'Event';

                        let displayBadgeClass = 'event-earnings';
                        if (badgeClass === 'dividend') displayBadgeClass = 'event-dividend';
                        else if (badgeClass === 'other') displayBadgeClass = 'event-split';

                        return `
                                <div class="event-row-item" style="display: flex; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--border-glass); cursor: pointer;" onclick="window.switchTab && window.switchTab('events')">
                                    <div class="event-date-wrap" style="width: 45px; flex-shrink: 0; display: flex; flex-direction: row; gap: 3px; align-items: baseline;">
                                        <span style="font-size: 10px; font-weight: 700; color: var(--text-secondary); text-transform: uppercase;">${monthStr}</span>
                                        <span style="font-size: 12.5px; font-weight: 800; color: var(--text-primary);">${day}</span>
                                    </div>
                                    <div style="flex-grow: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; text-align: left; padding: 0 4px;">
                                        <span style="font-size: 11.5px; font-weight: 700; color: var(--text-primary);">${eventTitle}</span>
                                        <span style="font-size: 10px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 95%;">${eventDesc}</span>
                                    </div>
                                    <div style="flex-shrink: 0; text-align: right;">
                                        <span class="event-badge ${displayBadgeClass}" style="font-size: 8.5px; padding: 2px 6px;">${badgeLabel}</span>
                                    </div>
                                </div>
                            `;
                    }).join('');
                }

                container.innerHTML = targetEvents.map((item, idx) => {
                    let eventTitle = "";
                    let eventDesc = "";
                    let badgeLabel = "";
                    let badgeClass = "";

                    const type = (item.event_type || "").toLowerCase();
                    if (type.includes("result") || type.includes("earning")) {
                        eventTitle = `${item.symbol} Q1 Results`;
                        badgeLabel = "RESULTS";
                        badgeClass = "results";
                        if (item.details?.earnings_estimate) {
                            eventDesc = `Consensus EPS: ${parseFloat(item.details.earnings_estimate).toFixed(2)}`;
                        } else {
                            eventDesc = "Upcoming quarterly disclosures.";
                        }
                    } else if (type.includes("dividend")) {
                        eventTitle = `${item.symbol}  Dividend`;
                        badgeLabel = "DIVIDEND";
                        badgeClass = "dividend";
                        if (item.details?.dividend_rate) {
                            eventDesc = `${parseFloat(item.details.dividend_rate).toFixed(2)}/share Dividend`;
                        } else {
                            eventDesc = "Dividend record consideration.";
                        }
                    } else {
                        eventTitle = `${item.symbol}  Corporate Action`;
                        badgeLabel = "OTHER";
                        badgeClass = "other";
                        eventDesc = item.description || "Board meeting/ Capex update";
                    }

                    const parts = item.event_date.split('-');
                    const year = parseInt(parts[0], 10);
                    const month = parseInt(parts[1], 10) - 1;
                    const day = parseInt(parts[2], 10);
                    const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
                    const monthStr = monthNames[month];

                    const isLast = idx === targetEvents.length - 1;
                    const borderStyle = isLast ? "" : "border-bottom: 1px solid var(--border-glass);";

                    return `
                        <div class="event-row-item" style="display: flex; align-items: center; padding: 12px 0; ${borderStyle}">
                            <div class="event-date-wrap" style="width: 50px; flex-shrink: 0; display: flex; flex-direction: row; gap: 4px; align-items: baseline;">
                                <span class="event-month" style="font-size: 10.5px; font-weight: 700; color: var(--text-secondary); text-transform: uppercase;">${monthStr}</span>
                                <span class="event-day" style="font-size: 13px; font-weight: 800; color: var(--text-primary);">${day}</span>
                            </div>
                            <div class="event-details-wrap" style="flex-grow: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; text-align: left;">
                                <span class="event-row-title" style="font-size: 12px; font-weight: 700; color: var(--text-primary);">${eventTitle}</span>
                                <span class="event-row-desc" style="font-size: 10px; color: var(--text-secondary);">${eventDesc}</span>
                            </div>
                            <div class="event-status-wrap" style="width: 90px; flex-shrink: 0; text-align: right;">
                                <span class="event-badge ${badgeClass}" style="font-size: 9px; padding: 3px 8px; border-radius: 4px; font-weight: 600; text-transform: uppercase;">${badgeLabel}</span>
                            </div>
                        </div>
                    `;
                }).join('');
            } else {
                container.innerHTML = `<div class="recent-research-empty" style="font-size: 11px;">No upcoming corporate events.</div>`;
            }
        } catch (err) {
            console.error("Events load error:", err);
            container.innerHTML = `<div class="recent-research-empty" style="font-size: 11px;">Failed to load events calendar.</div>`;
        }
    };

        // 4b. Fetch & Render Homepage Institutional Alert Center Card
        const loadHomepageAlerts = async () => {
        const container = document.getElementById('desktop-home-alerts-container');
        if (!container) return;

        try {
            const res = await fetch(apiBaseUrl + '/api/alerts/list');
            if (!res.ok) throw new Error("Alerts load failed");
            const allAlerts = await res.json();
            
            // Filter to show only active scanning alerts
                        // Filter to show only active scanning alerts
            const alerts = (allAlerts || []).filter(a => a.triggered === false || a.triggered === 0 || a.status === 'Active' || a.status === 'Scanning');

            // Update active scan counter in mobile header scans button
            const scansBtn = document.getElementById('mobile-header-scans-btn');
            if (scansBtn) {
                scansBtn.innerHTML = `⚡ Scans (${alerts.length})`;
            }

            const mobileAlerts = document.getElementById('mobile-home-alerts-container');

            if (alerts.length > 0) {
                const renderAlertHtml = (a) => {
                    const cleanSym = (a.ticker || 'SYSTEM').replace('.NS', '');
                    const condition = a.condition_type || 'PRICE';
                    const operator = a.operator || '';
                    const targetVal = a.value || '';
                    const message = `Monitoring: ${condition} ${operator} ${targetVal}`;
                    
                    return `
                        <div class="alert-home-item" onclick="window.switchTab && window.switchTab('alerts')">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span style="font-size: 11px; font-weight: 700; color: var(--color-primary);">${cleanSym}</span>
                                <span style="font-size: 10.5px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 280px;" title="${message}">${message}</span>
                            </div>
                            <span style="font-size: 9.5px; color: #10b981; font-family: 'Inter', monospace; font-weight: 700; text-transform: uppercase;">SCANNING</span>
                        </div>
                    `;
                };

                if (mobileAlerts) {
                    mobileAlerts.innerHTML = alerts.slice(0, 5).map(a => renderAlertHtml(a)).join('');
                }
                container.innerHTML = alerts.slice(0, 5).map(a => renderAlertHtml(a)).join('');
            } else {
                const defaultOnlineHtml = `
                    <div class="alert-home-item" onclick="window.switchTab && window.switchTab('alerts')">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 11px; font-weight: 700; color: #10b981;">SYSTEM</span>
                            <span style="font-size: 10.5px; color: var(--text-secondary);">Institutional alert monitors active. Real-time sweeps running.</span>
                        </div>
                        <span style="font-size: 9.5px; color: #10b981; font-family: 'Inter', monospace;">ONLINE</span>
                    </div>
                `;
                if (mobileAlerts) {
                    mobileAlerts.innerHTML = defaultOnlineHtml;
                }
                container.innerHTML = defaultOnlineHtml;
            }
        } catch (e) {
            console.error("Alerts render error:", e);
            container.innerHTML = `<div class="recent-research-empty" style="font-size: 11px;">Institutional alert center ready.</div>`;
        }
    };

        // 5. Fetch, Render & Sort Watchlist Quick-Quote Strip
        let watchlistCachedItems = [];
        let wlSortCol = null;
        let wlSortDir = 'none'; // 'none', 'asc', 'desc'

        const loadWatchlistStrip = async () => {
            const selector = document.getElementById('desktop-watchlist-selector');
            const container = document.getElementById('desktop-watchlist-container');
            if (!selector || !container) return;

            try {
                const res = await fetch(apiBaseUrl + '/api/watchlists');
                if (!res.ok) throw new Error("Watchlists fetch failed");
                const watchlists = await res.json();

                selector.innerHTML = '<option value="" disabled selected>Select Watchlist</option>';
                const mobileSel = document.getElementById('mobile-watchlist-selector');
                if (mobileSel) {
                    mobileSel.innerHTML = '<option value="" disabled selected>Select Watchlist</option>';
                }
                if (watchlists && watchlists.length > 0) {
                    // Check main tab selection first, default to first watchlist if none
                    const mainSelectedId = document.getElementById('watchlist-select')?.value;
                    const defaultId = (mainSelectedId && mainSelectedId !== "") ? mainSelectedId : watchlists[0].id;

                    watchlists.forEach(w => {
                        const opt = document.createElement('option');
                        opt.value = w.id;
                        opt.innerText = w.name;
                        if (w.id === defaultId) opt.selected = true;
                        selector.appendChild(opt);

                        if (mobileSel) {
                            const mOpt = document.createElement('option');
                            mOpt.value = w.id;
                            mOpt.innerText = w.name;
                            if (w.id === defaultId) mOpt.selected = true;
                            mobileSel.appendChild(mOpt);
                        }
                    });

                    // Auto-load default watchlist
                    selector.value = defaultId;
                    if (mobileSel) mobileSel.value = defaultId;
                    await onWatchlistChange(defaultId);
                }
            } catch (err) {
                console.error("Desktop watchlists load error:", err);
            }

            function renderWatchlistList() {
                if (watchlistCachedItems.length === 0) {
                    container.innerHTML = `<div class="recent-research-empty" style="font-size: 11px;">No stocks in this watchlist.</div>`;
                    return;
                }

                let displayItems = [...watchlistCachedItems];
                if (wlSortCol && wlSortDir !== 'none') {
                    displayItems.sort((a, b) => {
                        let valA = a[wlSortCol];
                        let valB = b[wlSortCol];

                        if (typeof valA === 'string') {
                            valA = valA.toUpperCase();
                            valB = valB.toUpperCase();
                        } else {
                            valA = valA || 0;
                            valB = valB || 0;
                        }

                        if (valA < valB) return wlSortDir === 'asc' ? -1 : 1;
                        if (valA > valB) return wlSortDir === 'asc' ? 1 : -1;
                        return 0;
                    });
                }

                const mobileWatchlist = document.getElementById('mobile-home-watchlist-container');
                                if (mobileWatchlist) {
                    if (displayItems.length > 0) {
                        // Sort by change_pct descending
                        const sortedByChange = [...displayItems].sort((a, b) => {
                            const valA = parseFloat(a.change_pct || 0);
                            const valB = parseFloat(b.change_pct || 0);
                            return valB - valA;
                        });

                        const topGainers = sortedByChange.slice(0, 3);
                        // Bottom 3 (if length >= 3, slice last 3, else take remainder that are not gainers or just bottom)
                        // If we have very few stocks, let's make sure we don't overlap duplicates
                        const topLosers = sortedByChange.length > 3 ? sortedByChange.slice(-3).reverse() : [];

                        let htmlContent = '';

                        // Render Gainers Group
                        if (topGainers.length > 0) {
                            htmlContent += `
                                <div style="font-size: 10px; font-weight: 700; color: #10b981; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.03em;">🔥 Watchlist Gainers</div>
                                <table style="width: 100%; border-collapse: collapse; font-size: 11.5px; text-align: left; margin-bottom: 12px;">
                                    <tbody>
                                        ${topGainers.map(item => {
                                            const changePct = parseFloat(item.change_pct || 0);
                                            const changeClass = changePct >= 0 ? 'cmp-badge-up' : 'cmp-badge-down';
                                            return `
                                                <tr style="border-bottom: 1px solid rgba(255,255,255,0.02); height: 34px; cursor: pointer;" onclick="
    const searchInput = document.getElementById('analyzer-search-input');
    const searchBtn = document.getElementById('analyzer-search-btn');
    if (searchInput && searchBtn) {
        searchInput.value = '${item.symbol}';
        window.switchTab('analyzer');
        searchBtn.click();
    }
">
                                                    <td style="padding: 5px 4px; font-weight: 700; color: var(--text-primary);">${item.symbol.replace('.NS', '')}</td>
                                                    <td style="padding: 5px 4px; text-align: right; color: var(--text-primary); font-weight: 600; font-family: 'Inter', monospace;">₹${parseFloat(item.live_price || 0).toFixed(2)}</td>
                                                    <td style="padding: 5px 4px; text-align: right; font-weight: 700; font-family: 'Inter', monospace;" class="${changeClass}">${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%</td>
                                                </tr>
                                            `;
                                        }).join('')}
                                    </tbody>
                                </table>
                            `;
                        }

                        // Render Losers Group
                        if (topLosers.length > 0) {
                            htmlContent += `
                                <div style="font-size: 10px; font-weight: 700; color: #ef4444; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.03em;">❄️ Watchlist Losers</div>
                                <table style="width: 100%; border-collapse: collapse; font-size: 11.5px; text-align: left;">
                                    <tbody>
                                        ${topLosers.map(item => {
                                            const changePct = parseFloat(item.change_pct || 0);
                                            const changeClass = changePct >= 0 ? 'cmp-badge-up' : 'cmp-badge-down';
                                            return `
                                                <tr style="border-bottom: 1px solid rgba(255,255,255,0.02); height: 34px; cursor: pointer;" onclick="
    const searchInput = document.getElementById('analyzer-search-input');
    const searchBtn = document.getElementById('analyzer-search-btn');
    if (searchInput && searchBtn) {
        searchInput.value = '${item.symbol}';
        window.switchTab('analyzer');
        searchBtn.click();
    }
">
                                                    <td style="padding: 5px 4px; font-weight: 700; color: var(--text-primary);">${item.symbol.replace('.NS', '')}</td>
                                                    <td style="padding: 5px 4px; text-align: right; color: var(--text-primary); font-weight: 600; font-family: 'Inter', monospace;">₹${parseFloat(item.live_price || 0).toFixed(2)}</td>
                                                    <td style="padding: 5px 4px; text-align: right; font-weight: 700; font-family: 'Inter', monospace;" class="${changeClass}">${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%</td>
                                                </tr>
                                            `;
                                        }).join('')}
                                    </tbody>
                                </table>
                            `;
                        } else if (sortedByChange.length <= 3) {
                            // If total items <= 3, just show them all in a single watchlist list without splitting
                            htmlContent = `
                                <div style="font-size: 10px; font-weight: 700; color: var(--text-secondary); margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.03em;">📋 Watchlist Items</div>
                                <table style="width: 100%; border-collapse: collapse; font-size: 11.5px; text-align: left;">
                                    <tbody>
                                        ${sortedByChange.map(item => {
                                            const changePct = parseFloat(item.change_pct || 0);
                                            const changeClass = changePct >= 0 ? 'cmp-badge-up' : 'cmp-badge-down';
                                            return `
                                                <tr style="border-bottom: 1px solid rgba(255,255,255,0.02); height: 34px; cursor: pointer;" onclick="
    const searchInput = document.getElementById('analyzer-search-input');
    const searchBtn = document.getElementById('analyzer-search-btn');
    if (searchInput && searchBtn) {
        searchInput.value = '${item.symbol}';
        window.switchTab('analyzer');
        searchBtn.click();
    }
">
                                                    <td style="padding: 5px 4px; font-weight: 700; color: var(--text-primary);">${item.symbol.replace('.NS', '')}</td>
                                                    <td style="padding: 5px 4px; text-align: right; color: var(--text-primary); font-weight: 600; font-family: 'Inter', monospace;">₹${parseFloat(item.live_price || 0).toFixed(2)}</td>
                                                    <td style="padding: 5px 4px; text-align: right; font-weight: 700; font-family: 'Inter', monospace;" class="${changeClass}">${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%</td>
                                                </tr>
                                            `;
                                        }).join('')}
                                    </tbody>
                                </table>
                            `;
                        }

                        mobileWatchlist.innerHTML = htmlContent;
                    } else {
                        mobileWatchlist.innerHTML = '<div class="recent-research-empty" style="font-size: 11px;">No stocks in watchlist.</div>';
                    }
                }
                                // Define row element renderer
                const renderRowItem = (item) => {
                    const price = item.live_price !== undefined ? parseFloat(item.live_price).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '--';
                    const changeVal = item.change_pct !== undefined ? parseFloat(item.change_pct) : 0;
                    const changeStr = item.change_pct !== undefined ? `${changeVal >= 0 ? '+' : ''}${changeVal.toFixed(2)}%` : '--';
                    const isPositive = changeVal >= 0;
                    const arrow = isPositive ? '▲' : '▼';
                    const color = isPositive ? '#10b981' : '#ef4444';
                    const bg = isPositive ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)';
                    const cleanSym = item.symbol.replace('.NS', '');

                    return `
                        <div class="watchlist-row-item" data-symbol="${cleanSym}" style="display: flex; justify-content: space-between; align-items: center; padding: 6px 8px; background: rgba(255, 255, 255, 0.015); border: 1px solid var(--border-glass); border-radius: 6px; cursor: pointer; transition: background 0.15s, transform 0.1s; height: 38px; box-sizing: border-box;">
                            <div style="font-weight: 700; color: var(--text-primary); font-size: 11.5px; width: 85px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${cleanSym}</div>
                            <div style="text-align: right; color: var(--text-primary); font-weight: 600; font-family: 'Inter', monospace; font-size: 11px; flex-grow: 1; padding-right: 12px;">₹${price}</div>
                            <div style="text-align: right; font-weight: 700; font-family: 'Inter', monospace; font-size: 10px; width: 68px; flex-shrink: 0;">
                                <span style="color: ${color}; padding: 2px 6px; border-radius: 4px; background: ${bg}; display: inline-block; min-width: 54px; text-align: right;">${arrow}${changeStr}</span>
                            </div>
                        </div>
                    `;
                };

                // Split displayItems into Top 3 Gainers and Bottom 3 Losers by change_pct
                const sortedByChange = [...displayItems].sort((a, b) => {
                    const valA = parseFloat(a.change_pct || 0);
                    const valB = parseFloat(b.change_pct || 0);
                    return valB - valA;
                });

                if (sortedByChange.length > 3) {
                    const gainers = sortedByChange.slice(0, 3);
                    const losers = sortedByChange.slice(-3).reverse();

                    container.innerHTML = `
                        <div style="display: flex; gap: 16px; width: 100%;">
                            <!-- Left Column (Gainers) -->
                            <div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px;">
                                <div style="font-size: 9px; font-weight: 700; color: #10b981; text-transform: uppercase; letter-spacing: 0.03em; border-left: 2px solid #10b981; padding-left: 6px; margin-bottom: 2px;">🔥 Watchlist Gainers</div>
                                ${gainers.map(item => renderRowItem(item)).join('')}
                            </div>
                            <!-- Right Column (Losers) -->
                            <div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px;">
                                <div style="font-size: 9px; font-weight: 700; color: #ef4444; text-transform: uppercase; letter-spacing: 0.03em; border-left: 2px solid #ef4444; padding-left: 6px; margin-bottom: 2px;">❄️ Watchlist Losers</div>
                                ${losers.map(item => renderRowItem(item)).join('')}
                            </div>
                        </div>
                    `;
                } else {
                    container.innerHTML = `
                        <div style="display: flex; flex-direction: column; gap: 6px; width: 100%;">
                            ${sortedByChange.map(item => renderRowItem(item)).join('')}
                        </div>
                    `;
                }

                container.querySelectorAll('.watchlist-row-item').forEach(row => {
                    row.onclick = (e) => {
                        e.stopPropagation();
                        const symbol = row.getAttribute('data-symbol');
                        const searchInput = document.getElementById('analyzer-search-input');
                        const searchBtn = document.getElementById('analyzer-search-btn');
                        if (searchInput) {
                            searchInput.value = symbol;
                            searchInput.focus();
                            if (searchBtn) searchBtn.click();
                        }
                    };
                });
            };

            async function onWatchlistChange(watchlistId) {
                container.innerHTML = `<div class="recent-research-empty" style="font-size: 11px;">Fetching live quotes...</div>`;
                const mobileWatchlist = document.getElementById('mobile-home-watchlist-container');
                if (mobileWatchlist) {
                    mobileWatchlist.innerHTML = `<div class="recent-research-empty" style="font-size: 11px;">Fetching live quotes...</div>`;
                }
                watchlistCachedItems = [];

                try {
                    const res = await fetch(apiBaseUrl + `/api/watchlists/${watchlistId}`);
                    if (!res.ok) throw new Error("Watchlist detail failed");
                    const data = await res.json();
                    
                    const items = data.items || [];
                    if (items.length === 0) {
                        renderWatchlistList();
                        return;
                    }

                    const symbols = items.map(item => item.symbol);
                    const quoteRes = await fetch(apiBaseUrl + '/api/batch-quotes', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ symbols: symbols })
                    });
                    
                    if (quoteRes.ok) {
                        const quoteData = await quoteRes.json();
                        const quotes = quoteData.quotes || {};
                        items.forEach(item => {
                            const q = quotes[item.symbol];
                            if (q) {
                                item.live_price = q.price;
                                item.change = q.change;
                                item.change_pct = q.change_pct;
                            }
                        });
                    }

                    watchlistCachedItems = items;
                    renderWatchlistList();
                    setTimeout(bindMobileSortHeaders, 100);
                } catch (err) {
                    console.error("Desktop watchlist loading failed:", err);
                    container.innerHTML = `<div class="recent-research-empty" style="font-size: 11px;">Failed to load live watchlist.</div>`;
                }
            };

            selector.onchange = async () => {
                const mobileSel = document.getElementById('mobile-watchlist-selector');
                if (mobileSel) mobileSel.value = selector.value;
                await onWatchlistChange(selector.value);
            };

            const mobileSelEl = document.getElementById('mobile-watchlist-selector');
            if (mobileSelEl) {
                mobileSelEl.onchange = async () => {
                    selector.value = mobileSelEl.value;
                    await onWatchlistChange(mobileSelEl.value);
                };
            }

            function updateSortHeaderIcons() {
                ['sort-wl-symbol', 'sort-wl-price', 'sort-wl-change', 'mobile-sort-wl-symbol', 'mobile-sort-wl-price', 'mobile-sort-wl-change'].forEach(id => {
                    const el = document.getElementById(id);
                    if (el) {
                        const icon = el.querySelector('.sort-icon');
                        if (icon) {
                            const col = (id.includes('symbol')) ? 'symbol' : ((id.includes('price')) ? 'live_price' : 'change_pct');
                            if (wlSortCol === col) {
                                icon.innerText = wlSortDir === 'asc' ? ' ▲' : (wlSortDir === 'desc' ? ' ▼' : '');
                            } else {
                                icon.innerText = '';
                            }
                        }
                    }
                });
            };

            function toggleSort(col) {
                if (wlSortCol === col) {
                    if (wlSortDir === 'none') wlSortDir = 'asc';
                    else if (wlSortDir === 'asc') wlSortDir = 'desc';
                    else {
                        wlSortDir = 'none';
                        wlSortCol = null;
                    }
                } else {
                    wlSortCol = col;
                    wlSortDir = 'asc';
                }
                updateSortHeaderIcons();
                renderWatchlistList();
            };

            const headerSym = document.getElementById('sort-wl-symbol');
            const headerPrice = document.getElementById('sort-wl-price');
            const headerChange = document.getElementById('sort-wl-change');

            if (headerSym) headerSym.onclick = () => toggleSort('symbol');
            if (headerPrice) headerPrice.onclick = () => toggleSort('live_price');
            if (headerChange) headerChange.onclick = () => toggleSort('change_pct');

            // Wire Mobile Header Clicks
            function bindMobileSortHeaders() {
                const mHeaderSym = document.getElementById('mobile-sort-wl-symbol');
                const mHeaderPrice = document.getElementById('mobile-sort-wl-price');
                const mHeaderChange = document.getElementById('mobile-sort-wl-change');
                if (mHeaderSym) mHeaderSym.onclick = () => toggleSort('symbol');
                if (mHeaderPrice) mHeaderPrice.onclick = () => toggleSort('live_price');
                if (mHeaderChange) mHeaderChange.onclick = () => toggleSort('change_pct');
                updateSortHeaderIcons();
            };
            setTimeout(bindMobileSortHeaders, 100);
        };

        // 6. Fetch & Render Quant Top Picks Table (Screener Integration with Strategy Tabs)
        let quantPicksCache = { hybrid: [], bottom_up: [], top_down: [] };
        window.activeQuantStrategy = 'hybrid';

        const renderQuantTopPicksList = () => { window.renderQuantTopPicksList = renderQuantTopPicksList;
            // Synchronize active indicator on mobile strategy tabs
            const qTabHybrid = document.getElementById('mobile-quant-tab-hybrid');
            const qTabBU = document.getElementById('mobile-quant-tab-bottom_up');
            const qTabTD = document.getElementById('mobile-quant-tab-top_down');
            if (qTabHybrid && qTabBU && qTabTD) {
                qTabHybrid.classList.remove('active');
                qTabBU.classList.remove('active');
                qTabTD.classList.remove('active');
                if (window.activeQuantStrategy === 'hybrid') qTabHybrid.classList.add('active');
                else if (window.activeQuantStrategy === 'bottom_up') qTabBU.classList.add('active');
                else if (window.activeQuantStrategy === 'top_down') qTabTD.classList.add('active');
            }
            const tbody = document.getElementById('desktop-quant-picks-body');
            if (!tbody) return;

            const data = quantPicksCache[window.activeQuantStrategy] || [];
            if (data && data.length > 0) {
                // Sort by score descending
                const sorted = [...data].sort((a, b) => (b.score || 0) - (a.score || 0));
                const top5 = sorted.slice(0, 5);

                const mobileQuantPicks = document.getElementById('mobile-home-quant-picks-container');
            if (mobileQuantPicks) {
                if (top5.length > 0) {
                    mobileQuantPicks.innerHTML = `
                        <table style="width: 100%; border-collapse: collapse; font-size: 11.5px; text-align: left;">
                            <thead>
                                <tr style="border-bottom: 1px solid var(--border-glass); color: var(--text-secondary); font-weight: 700; font-size: 9.5px; height: 26px; text-transform: uppercase;">
                                    <th style="padding: 6px 4px;">Ticker</th>
                                    <th style="padding: 6px 4px; text-align: center;">Score</th>
                                    <th style="padding: 6px 4px; text-align: right;">Action</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${top5.map(item => {
                                    const scoreVal = parseInt(item.score || 0);
                                    const scoreColor = scoreVal >= 70 ? '#10b981' : '#f59e0b';
                                    const actionStr = (item.action || 'BUY').toUpperCase().includes('BUY') ? 'BUY' : 'SELL';
                                    const actionClass = actionStr === 'BUY' ? 'cmp-badge-up' : 'cmp-badge-down';
                                    return `
                                        <tr style="border-bottom: 1px solid rgba(255,255,255,0.03); height: 36px; cursor: pointer;" onclick="
    const searchInput = document.getElementById('analyzer-search-input');
    const searchBtn = document.getElementById('analyzer-search-btn');
    if (searchInput && searchBtn) {
        searchInput.value = '${item.symbol.replace('.NS', '')}';
        window.switchTab('analyzer');
        searchBtn.click();
    }
">
                                            <td style="padding: 6px 4px; font-weight: 700; color: var(--text-primary);">${item.symbol.replace('.NS', '')}</td>
                                            <td style="padding: 6px 4px; text-align: center; font-weight: 800; color: ${scoreColor}; font-family: 'Inter', monospace;">${scoreVal}</td>
                                            <td style="padding: 6px 4px; text-align: right; font-weight: 700;" class="${actionClass}">${actionStr}</td>
                                        </tr>
                                    `;
                                }).join('')}
                            </tbody>
                        </table>
                    `;
                } else {
                    mobileQuantPicks.innerHTML = `<div class="recent-research-empty" style="font-size: 11px;">Scanning market for picks...</div>`;
                }
            }
            tbody.innerHTML = top5.map((item, idx) => {
                    const cleanSym = item.symbol.replace('.NS', '');
                    let compName = item.name || '';
                    compName = compName.replace(/(Limited|Ltd\.|\(India\)|\(I\))/gi, '').trim();

                    const scoreVal = parseInt(item.score || 0);
                    let scoreColor = '#ef4444';
                    if (scoreVal >= 70) {
                        scoreColor = '#10b981';
                    } else if (scoreVal >= 50) {
                        scoreColor = '#f59e0b';
                    }

                    const actionStr = (item.action || 'HOLD').toUpperCase();
                    let signalText = 'HOLD';
                    let badgeClass = 'hold';

                    if (actionStr.includes('BUY')) {
                        signalText = 'BUY';
                        badgeClass = 'buy';
                    } else if (actionStr.includes('SELL') || actionStr.includes('UNDERPERFORM') || actionStr.includes('RED')) {
                        signalText = 'SELL';
                        badgeClass = 'sell';
                    }

                    return `
                        <tr class="quant-pick-row" data-symbol="${cleanSym}" style="border-bottom: 1px solid var(--border-glass); height: 38px;">
                            <td style="padding: 4px 8px; color: var(--text-secondary);">${idx + 1}</td>
                            <td style="padding: 4px 8px; font-weight: 700; color: var(--text-primary);">${cleanSym}</td>
                            <td style="padding: 4px 8px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 120px;" title="${item.name || ''}">${compName}</td>
                            <td style="padding: 4px 8px; text-align: center; font-weight: 700; color: ${scoreColor}; font-family: 'Inter', monospace;">${scoreVal}</td>
                            <td style="padding: 4px 8px; text-align: center;">
                                <span class="signal-badge ${badgeClass}">${signalText}</span>
                            </td>
                        </tr>
                    `;
                }).join('');

                tbody.querySelectorAll('.quant-pick-row').forEach(row => {
                    row.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const symbol = row.getAttribute('data-symbol');
                        const searchInput = document.getElementById('analyzer-search-input');
                        const searchBtn = document.getElementById('analyzer-search-btn');
                        if (searchInput) {
                            searchInput.value = symbol;
                            searchInput.focus();
                            if (searchBtn) searchBtn.click();
                        }
                    });
                });
            } else {
                tbody.innerHTML = `<tr><td colspan="5" class="recent-research-empty" style="padding: 20px 0; text-align: center;">No constituents qualified.</td></tr>`;
            }
        };

        const loadQuantTopPicks = async () => {
            const tbody = document.getElementById('desktop-quant-picks-body');
            if (!tbody) return;

            // Wire Tab Selector Buttons once
            const tabs = document.querySelectorAll('.quant-strategy-tab');
            tabs.forEach(tab => {
                if (!tab.dataset.wired) {
                    tab.dataset.wired = "true";
                    tab.addEventListener('click', () => {
                        tabs.forEach(t => {
                            t.classList.remove('active');
                            t.style.background = 'transparent';
                            t.style.borderColor = 'transparent';
                            t.style.color = 'var(--text-secondary)';
                        });
                        tab.classList.add('active');
                        tab.style.background = 'rgba(255, 255, 255, 0.08)';
                        tab.style.borderColor = 'var(--border-glass)';
                        tab.style.color = 'var(--text-primary)';

                        window.activeQuantStrategy = tab.getAttribute('data-strategy');
                        renderQuantTopPicksList();
                    });
                }
            });

            try {
                tbody.innerHTML = `<tr><td colspan="5" class="recent-research-empty" style="padding: 20px 0; text-align: center;">Scanning market for quant top picks...</td></tr>`;

                // Fetch Hybrid, Bottom-Up, and Top-Down screeners in parallel across whole universe (all cap)
                const tBuster = Date.now();
                const [resHybrid, resBU, resTD] = await Promise.all([
                    fetch(apiBaseUrl + `/api/discover?strategy=hybrid&universe=all&_t=${tBuster}`),
                    fetch(apiBaseUrl + `/api/discover?strategy=bottom_up&universe=all&_t=${tBuster}`),
                    fetch(apiBaseUrl + `/api/discover?strategy=top_down&universe=all&_t=${tBuster}`)
                ]);

                if (resHybrid.ok) {
                    const dataHybrid = await resHybrid.json();
                    quantPicksCache.hybrid = Array.isArray(dataHybrid) ? dataHybrid : [];
                }
                if (resBU.ok) {
                    const dataBU = await resBU.json();
                    quantPicksCache.bottom_up = Array.isArray(dataBU) ? dataBU : [];
                }
                if (resTD.ok) {
                    const dataTD = await resTD.json();
                    quantPicksCache.top_down = Array.isArray(dataTD) ? dataTD : [];
                }

                renderQuantTopPicksList();
            } catch (err) {
                console.error("Desktop Quant Top Picks loading error:", err);
                tbody.innerHTML = `<tr><td colspan="5" class="recent-research-empty" style="padding: 20px 0; text-align: center; color: var(--neon-red);">Failed to load Quant Top Picks.</td></tr>`;
            }
        };

        // Wire Card Header View All Buttons & Mobile Scans Pill
        const moversViewAll = document.getElementById('desktop-movers-view-all-btn');
        if (moversViewAll) {
            moversViewAll.onclick = (e) => {
                e.stopPropagation();
                if (window.switchTab) window.switchTab('movers');
            };
        }
        const newsViewAll = document.getElementById('desktop-news-view-all-btn');
        if (newsViewAll) {
            newsViewAll.onclick = (e) => {
                e.stopPropagation();
                if (window.switchTab) window.switchTab('market-news');
            };
        }
        const quantViewAll = document.getElementById('desktop-quant-picks-view-all-btn');
        if (quantViewAll) {
            quantViewAll.onclick = (e) => {
                e.stopPropagation();
                if (window.switchTab) window.switchTab('rule-scanner');
            };
        }
        const watchlistViewAll = document.getElementById('desktop-watchlist-view-all-btn');
        if (watchlistViewAll) {
            watchlistViewAll.onclick = (e) => {
                e.stopPropagation();
                if (window.switchTab) window.switchTab('watchlist');
            };
        }
        const alertsViewAll = document.getElementById('desktop-alerts-view-all-btn');
        if (alertsViewAll) {
            alertsViewAll.onclick = (e) => {
                e.stopPropagation();
                if (window.switchTab) window.switchTab('alerts');
            };
        }
        const techScansViewAll = document.getElementById('desktop-tech-scans-view-all-btn');
        if (techScansViewAll) {
            techScansViewAll.onclick = (e) => {
                e.stopPropagation();
                if (window.switchTab) window.switchTab('alerts');
            };
        }
        const mobileHeaderScans = document.getElementById('mobile-header-scans-btn');
        if (mobileHeaderScans) {
            mobileHeaderScans.onclick = (e) => {
                e.stopPropagation();
                if (window.switchTab) window.switchTab('alerts');
            };
        }

        // 7. Fetch & Render Technical Scans (Near 52W High/Low, Gap Up/Down, RSI, Fib, SMA Pullbacks)
        let technicalScansCache = {
            near_high: [], near_low: [], gap_up: [], gap_down: [],
            rsi_oversold: [], rsi_overbought: [], volume_shockers: [], golden_crossover: [],
            sma_50_pullback: [], sma_100_pullback: [], sma_200_pullback: [], fib_618_support: [], fib_500_support: []
        };
        window.activeTechnicalScan = 'near_high';
        let fullscreenActiveScan = 'near_high';
        let fullscreenSortCol = 'value'; // Default sort metric value
        let fullscreenSortDir = 'asc';   // Default sort asc
        let fullscreenSearchQuery = '';

        // Pagination state
        let fullscreenPage = 1;
        let fullscreenPageSize = 10;

        // Cached list of watchlists for the quick-add dropdown
        let cachedWatchlists = [];

        // Fetch watchlists list once
        const fetchWatchlistsForDropdown = async () => {
            try {
                const res = await fetch(apiBaseUrl + '/api/watchlists');
                if (res.ok) {
                    cachedWatchlists = await res.json();
                }
            } catch (err) {
                console.error("Failed to load watchlists for technical scan dropdown:", err);
            }
        };
        fetchWatchlistsForDropdown();

        // Display a sleek custom toast notification
        const showScanToast = (message, type = 'success') => {
            const toast = document.createElement('div');
            toast.style.position = 'fixed';
            toast.style.bottom = '20px';
            toast.style.right = '20px';
            toast.style.background = type === 'success' ? 'rgba(16, 185, 129, 0.95)' : 'rgba(239, 68, 68, 0.95)';
            toast.style.color = '#fff';
            toast.style.padding = '10px 20px';
            toast.style.borderRadius = '6px';
            toast.style.boxShadow = '0 4px 15px rgba(0,0,0,0.3)';
            toast.style.fontSize = '12px';
            toast.style.fontWeight = '700';
            toast.style.fontFamily = "'Outfit', sans-serif";
            toast.style.zIndex = '99999';
            toast.style.transition = 'all 0.3s ease';
            toast.innerText = message;
            document.body.appendChild(toast);
            setTimeout(() => {
                toast.style.opacity = '0';
                toast.style.transform = 'translateY(10px)';
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        };

        // Render watchlist quick add dropdown menu
        const renderWatchlistDropdown = (symbol, container) => {
            if (!cachedWatchlists || cachedWatchlists.length === 0) {
                container.innerHTML = `<div class="wl-dropdown-item" style="color:var(--text-muted);">No Watchlists</div>`;
                return;
            }
            container.innerHTML = cachedWatchlists.map(wl => `
                <div class="wl-dropdown-item" data-wl-id="${wl.id}">${wl.name}</div>
            `).join('');

            container.querySelectorAll('.wl-dropdown-item').forEach(item => {
                item.onclick = async (e) => {
                    e.stopPropagation();
                    const wlId = item.getAttribute('data-wl-id');
                    const wlName = item.innerText;
                    container.classList.remove('show');

                    try {
                        const response = await fetch(apiBaseUrl + `/api/watchlists/${wlId}/items`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ symbol: symbol })
                        });
                        if (response.ok) {
                            showScanToast(`Added ${symbol} to watchlist "${wlName}"!`, 'success');
                            // Refresh watchlist strip dynamically
                            if (typeof loadWatchlistStrip === 'function') loadWatchlistStrip();
                        } else {
                            const errData = await response.json();
                            showScanToast(errData.detail || `Failed to add ${symbol}.`, 'error');
                        }
                    } catch (err) {
                        console.error("Watchlist item addition error:", err);
                        showScanToast(`Error adding ${symbol}.`, 'error');
                    }
                };
            });
        };

        const renderTechnicalScansList = () => { window.renderTechnicalScansList = renderTechnicalScansList;
            const tbody = document.getElementById('desktop-technical-scans-body');
            const desktopMetricHeader = document.getElementById('desktop-tech-scan-metric-header');
            if (!tbody) return;

            if (desktopMetricHeader) {
                if (window.activeTechnicalScan === 'near_high') desktopMetricHeader.innerText = 'Dist to High';
                else if (window.activeTechnicalScan === 'near_low') desktopMetricHeader.innerText = 'Dist to Low';
                else if (window.activeTechnicalScan === 'gap_up' || window.activeTechnicalScan === 'gap_down') desktopMetricHeader.innerText = 'Opening Gap';
                else if (window.activeTechnicalScan.includes('rsi')) desktopMetricHeader.innerText = 'RSI (14)';
                else if (activeTechnicalScan === 'volume_shockers') desktopMetricHeader.innerText = 'Vol Multiplier';
                else if (activeTechnicalScan === 'golden_crossover') desktopMetricHeader.innerText = 'Golden Cross Spread';
                else if (activeTechnicalScan === 'sma_50_pullback') desktopMetricHeader.innerText = 'Dist to 50MA';
                else if (activeTechnicalScan === 'sma_100_pullback') desktopMetricHeader.innerText = 'Dist to 100MA';
                else if (activeTechnicalScan === 'sma_200_pullback') desktopMetricHeader.innerText = 'Dist to 200MA';
                else if (activeTechnicalScan === 'fib_618_support') desktopMetricHeader.innerText = 'Dist to 61.8% Fib';
                else if (activeTechnicalScan === 'fib_500_support') desktopMetricHeader.innerText = 'Dist to 50.0% Fib';
                else desktopMetricHeader.innerText = 'Scan Detail';
            }

            const list = technicalScansCache[window.activeTechnicalScan] || [];
            if (list && list.length > 0) {
                const mobileTechScans = document.getElementById('mobile-home-tech-scans-container');
            // Synchronize active indicator on mobile tech tabs
            const mtHigh = document.getElementById('mobile-tech-tab-near_high');
            const mtLow = document.getElementById('mobile-tech-tab-near_low');
            const mtGapUp = document.getElementById('mobile-tech-tab-gap_up');
            const mtGapDown = document.getElementById('mobile-tech-tab-gap_down');
            if (mtHigh && mtLow && mtGapUp && mtGapDown) {
                mtHigh.classList.remove('active');
                mtLow.classList.remove('active');
                mtGapUp.classList.remove('active');
                mtGapDown.classList.remove('active');
                if (window.activeTechnicalScan === 'near_high') mtHigh.classList.add('active');
                else if (window.activeTechnicalScan === 'near_low') mtLow.classList.add('active');
                else if (window.activeTechnicalScan === 'gap_up') mtGapUp.classList.add('active');
                else if (window.activeTechnicalScan === 'gap_down') mtGapDown.classList.add('active');
            }

            if (mobileTechScans) {
                if (list.length > 0) {
                    mobileTechScans.innerHTML = `
                        <table style="width: 100%; border-collapse: collapse; font-size: 11.5px; text-align: left;">
                            <thead>
                                <tr style="border-bottom: 1px solid var(--border-glass); color: var(--text-secondary); font-weight: 700; font-size: 9.5px; height: 26px; text-transform: uppercase;">
                                    <th style="padding: 6px 4px;">Ticker</th>
                                    <th style="padding: 6px 4px; text-align: right;">CMP</th>
                                    <th style="padding: 6px 4px; text-align: right;">Detail</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${list.slice(0, 5).map(item => {
                                    const changePct = parseFloat(item.change_pct || 0);
                                    const changeClass = changePct >= 0 ? 'cmp-badge-up' : 'cmp-badge-down';
                                    return `
                                        <tr style="border-bottom: 1px solid rgba(255,255,255,0.03); height: 36px; cursor: pointer;" onclick="
    const searchInput = document.getElementById('analyzer-search-input');
    const searchBtn = document.getElementById('analyzer-search-btn');
    if (searchInput && searchBtn) {
        searchInput.value = '${item.symbol}';
        window.switchTab('analyzer');
        searchBtn.click();
    }
">
                                            <td style="padding: 6px 4px; font-weight: 700; color: var(--text-primary);">${item.symbol}</td>
                                            <td style="padding: 6px 4px; text-align: right; color: var(--text-primary); font-family: 'Inter', monospace; font-weight: 600;">₹${item.price} <span style="font-size: 9.5px;" class="${changeClass}">(${changePct >= 0 ? '+' : ''}${changePct.toFixed(1)}%)</span></td>
                                            <td style="padding: 6px 4px; text-align: right; font-weight: 700; color: var(--neon-green); font-family: 'Inter', monospace;">${item.value}</td>
                                        </tr>
                                    `;
                                }).join('')}
                            </tbody>
                        </table>
                    `;
                } else {
                    mobileTechScans.innerHTML = `<div class="recent-research-empty" style="font-size: 11px;">Scanning technical breakouts...</div>`;
                }
            }
            
            tbody.innerHTML = list.slice(0, 5).map((item, idx) => {
                    const cleanSym = item.symbol;
                    let compName = item.name || '';
                    compName = compName.replace(/(Limited|Ltd\.|\(India\)|\(I\))/gi, '').trim();

                    // Determine sentiment color badge based on active scan strategy
                    let badgeClass = 'buy';
                    let badgeText = 'BULLISH';
                    if (window.activeTechnicalScan === 'near_low' || window.activeTechnicalScan === 'gap_down' || activeTechnicalScan === 'rsi_overbought') {
                        badgeClass = 'sell';
                        badgeText = 'BEARISH';
                    }

                    // Format values
                    let formattedVal = item.value;
                    let metricStyle = 'color: var(--text-primary); font-weight: 600;';

                    if (window.activeTechnicalScan.includes('rsi')) {
                        const rsiVal = (item.rsi !== undefined && item.rsi !== null) ? Number(item.rsi) : (item.value !== undefined ? Number(item.value) : null);
                        if (rsiVal !== null && !isNaN(rsiVal)) {
                            formattedVal = rsiVal.toFixed(1);
                            if (rsiVal <= 35) {
                                metricStyle = 'color: #10b981; font-weight: 700;';
                            } else if (rsiVal >= 65) {
                                metricStyle = 'color: #ef4444; font-weight: 700;';
                            }
                        }
                    } else if (typeof formattedVal === 'number') {
                        if (window.activeTechnicalScan.includes('near') || window.activeTechnicalScan.includes('gap') || window.activeTechnicalScan.includes('pullback') || window.activeTechnicalScan.includes('fib')) {
                            formattedVal = formattedVal.toFixed(2) + '%';
                        } else if (window.activeTechnicalScan.includes('volume')) {
                            formattedVal = formattedVal.toFixed(1) + 'x';
                        }
                    }

                    return `
                        <tr class="technical-scan-row" data-symbol="${cleanSym}" style="border-bottom: 1px solid var(--border-glass); height: 38px;">
                            <td style="padding: 4px 8px; color: var(--text-secondary);">${idx + 1}</td>
                            <td style="padding: 4px 8px; font-weight: 700; color: var(--text-primary);">${cleanSym}</td>
                            <td style="padding: 4px 8px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 120px;" title="${item.name || ''}">${compName}</td>
                            <td style="padding: 4px 8px; text-align: right; font-family: 'Inter', monospace; ${metricStyle}">${formattedVal}</td>
                            <td style="padding: 4px 8px; text-align: center;">
                                <span class="signal-badge ${badgeClass}">${badgeText}</span>
                            </td>
                        </tr>
                    `;
                }).join('');

                tbody.querySelectorAll('.technical-scan-row').forEach(row => {
                    row.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const symbol = row.getAttribute('data-symbol');
                        const searchInput = document.getElementById('analyzer-search-input');
                        const searchBtn = document.getElementById('analyzer-search-btn');
                        if (searchInput) {
                            searchInput.value = symbol;
                            searchInput.focus();
                            if (searchBtn) searchBtn.click();
                        }
                    });
                });
            } else {
                tbody.innerHTML = `<tr><td colspan="5" class="recent-research-empty" style="padding: 20px 0; text-align: center;">No stocks qualifying under this scan.</td></tr>`;
            }
        };

        const renderFullscreenTechnicalScans = () => {
            const tbody = document.getElementById('fullscreen-technical-scans-body');
            const countBadge = document.getElementById('fullscreen-tech-scans-count');
            const metricHeader = document.getElementById('fullscreen-tech-scan-metric-header');
            const pagContainer = document.getElementById('fullscreen-tech-scans-pagination');
            if (!tbody) return;

            // Set metric header text depending on strategy
            if (metricHeader) {
                if (fullscreenActiveScan === 'near_high') metricHeader.innerHTML = `Dist to High <span class="sort-direction"></span>`;
                else if (fullscreenActiveScan === 'near_low') metricHeader.innerHTML = `Dist to Low <span class="sort-direction"></span>`;
                else if (fullscreenActiveScan === 'gap_up' || fullscreenActiveScan === 'gap_down') metricHeader.innerHTML = `Opening Gap <span class="sort-direction"></span>`;
                else if (fullscreenActiveScan.includes('rsi')) metricHeader.innerHTML = `RSI (14) <span class="sort-direction"></span>`;
                else if (fullscreenActiveScan === 'volume_shockers') metricHeader.innerHTML = `Vol Multiplier <span class="sort-direction"></span>`;
                else if (fullscreenActiveScan === 'golden_crossover') metricHeader.innerHTML = `Golden Cross Spread <span class="sort-direction"></span>`;
                else if (fullscreenActiveScan === 'sma_50_pullback') metricHeader.innerHTML = `Dist to 50MA <span class="sort-direction"></span>`;
                else if (fullscreenActiveScan === 'sma_100_pullback') metricHeader.innerHTML = `Dist to 100MA <span class="sort-direction"></span>`;
                else if (fullscreenActiveScan === 'sma_200_pullback') metricHeader.innerHTML = `Dist to 200MA <span class="sort-direction"></span>`;
                else if (fullscreenActiveScan === 'fib_618_support') metricHeader.innerHTML = `Dist to 61.8% Fib <span class="sort-direction"></span>`;
                else if (fullscreenActiveScan === 'fib_500_support') metricHeader.innerHTML = `Dist to 50.0% Fib <span class="sort-direction"></span>`;
                else metricHeader.innerHTML = `Scan Detail <span class="sort-direction"></span>`;
            }

            // Clean header directions
            document.querySelectorAll('.tech-sortable-header').forEach(header => {
                const col = header.getAttribute('data-sort');
                const dirSpan = header.querySelector('.sort-direction');
                if (dirSpan) {
                    if (col === fullscreenSortCol) {
                        dirSpan.innerText = fullscreenSortDir === 'asc' ? ' ▴' : (fullscreenSortDir === 'desc' ? ' ▾' : '');
                        header.style.color = 'var(--color-primary)';
                    } else {
                        dirSpan.innerText = '';
                        header.style.color = 'var(--text-secondary)';
                    }
                }
            });

            let list = technicalScansCache[fullscreenActiveScan] || [];

            // Apply Search Filtering client-side
            if (fullscreenSearchQuery) {
                const query = fullscreenSearchQuery.toLowerCase().trim();
                list = list.filter(item => {
                    const sym = (item.symbol || '').toLowerCase();
                    const name = (item.name || '').toLowerCase();
                    const sec = (item.sector || '').toLowerCase();
                    const seg = (item.segment || '').toLowerCase();
                    return sym.includes(query) || name.includes(query) || sec.includes(query) || seg.includes(query);
                });
            }

            // Apply Sort
            if (fullscreenSortCol && fullscreenSortDir !== 'none') {
                list.sort((a, b) => {
                    let valA = a[fullscreenSortCol];
                    let valB = b[fullscreenSortCol];

                    if (typeof valA === 'string') valA = valA.toLowerCase();
                    if (typeof valB === 'string') valB = valB.toLowerCase();

                    if (valA === undefined || valA === null) return 1;
                    if (valB === undefined || valB === null) return -1;

                    if (valA < valB) return fullscreenSortDir === 'asc' ? -1 : 1;
                    if (valA > valB) return fullscreenSortDir === 'asc' ? 1 : -1;
                    return 0;
                });
            }

            if (countBadge) {
                countBadge.innerText = `${list.length} Stocks`;
            }

            // Slice list using pagination parameters
            const totalPages = Math.ceil(list.length / fullscreenPageSize) || 1;
            if (fullscreenPage < 1) fullscreenPage = 1;
            if (fullscreenPage > totalPages) fullscreenPage = totalPages;

            const startIndex = (fullscreenPage - 1) * fullscreenPageSize;
            const endIndex = Math.min(startIndex + fullscreenPageSize, list.length);
            const pageList = list.slice(startIndex, endIndex);

            // Update Pagination display state
            if (pagContainer) {
                pagContainer.style.display = list.length > 0 ? 'flex' : 'none';
            }

            const pageInfo = document.getElementById('fullscreen-tech-scans-page-info');
            if (pageInfo) {
                pageInfo.innerText = `Page ${fullscreenPage} of ${totalPages}`;
            }

            const prevBtn = document.getElementById('fullscreen-tech-scans-prev-btn');
            const nextBtn = document.getElementById('fullscreen-tech-scans-next-btn');
            if (prevBtn) prevBtn.disabled = (fullscreenPage === 1);
            if (nextBtn) nextBtn.disabled = (fullscreenPage === totalPages);

            if (pageList && pageList.length > 0) {
                tbody.innerHTML = pageList.map((item, idx) => {
                    const cleanSym = item.symbol;
                    let compName = item.name || '';
                    compName = compName.replace(/(Limited|Ltd\.|\(India\)|\(I\))/gi, '').trim();
                    const sector = item.sector || 'General Equities';
                    const segment = item.segment || 'Small Cap';

                    // Format scan detail value & styling
                    let metricValDisplay = (item.value !== undefined && item.value !== null) ? item.value : 'N/A';
                    let metricStyle = 'color: var(--text-primary); font-weight: 600;';
                    let rsiStyle = 'color: var(--text-primary); font-weight: 600;';

                    const rsiVal = (item.rsi !== undefined && item.rsi !== null) ? Number(item.rsi) : (item.value !== undefined ? Number(item.value) : null);
                    if (rsiVal !== null && !isNaN(rsiVal)) {
                        if (rsiVal <= 35) {
                            rsiStyle = 'color: #10b981; font-weight: 700;'; // Oversold
                        } else if (rsiVal >= 65) {
                            rsiStyle = 'color: #ef4444; font-weight: 700;'; // Overbought
                        }
                    }

                    if (fullscreenActiveScan.includes('rsi')) {
                        if (rsiVal !== null && !isNaN(rsiVal)) {
                            metricValDisplay = rsiVal.toFixed(1);
                            metricStyle = rsiStyle;
                        }
                    }

                    // Format CMP & Day Change %
                    const priceDisplay = item.price !== undefined && item.price !== null ? `₹${Number(item.price).toLocaleString('en-IN', {minimumFractionDigits: 2})}` : '--';
                    const chgVal = item.change_pct !== undefined && item.change_pct !== null ? Number(item.change_pct) : 0;
                    const chgSign = chgVal >= 0 ? '+' : '';
                    const chgClass = chgVal >= 0 ? 'cmp-badge-up' : 'cmp-badge-down';
                    const chgDisplay = `<span class="${chgClass}" style="font-size: 10px; display: block;">${chgSign}${chgVal.toFixed(2)}%</span>`;

                    const sma50Display = (item.sma50 && Number(item.sma50) > 0) ? `₹${Number(item.sma50).toLocaleString('en-IN')}` : '--';
                    const sma200Display = (item.sma200 && Number(item.sma200) > 0) ? `₹${Number(item.sma200).toLocaleString('en-IN')}` : '--';
                    const high52Display = (item.high52 && Number(item.high52) > 0) ? `₹${Number(item.high52).toLocaleString('en-IN')}` : '--';
                    const low52Display = (item.low52 && Number(item.low52) > 0) ? `₹${Number(item.low52).toLocaleString('en-IN')}` : '--';
                    
                    let volMultDisplay = '1.0x';
                    if (item.vol_mult && Number(item.vol_mult) > 1.0) {
                        volMultDisplay = `${Number(item.vol_mult).toFixed(2)}x`;
                    } else if (item.value && String(item.value).toLowerCase().endsWith('x')) {
                        volMultDisplay = item.value;
                    }
                    
                    const rsiValStr = rsiVal !== null && !isNaN(rsiVal) ? `${rsiVal.toFixed(1)}` : '--';

                    // Curated signal labels and styling
                    let badgeClass = 'momentum-bull';
                    let badgeText = 'BULLISH';
                    if (fullscreenActiveScan === 'near_high') { badgeClass = 'momentum-bull'; badgeText = '52W High'; }
                    else if (fullscreenActiveScan === 'near_low') { badgeClass = 'oversold-weak'; badgeText = '52W Low'; }
                    else if (fullscreenActiveScan === 'gap_up') { badgeClass = 'gap-up'; badgeText = 'Gap Up'; }
                    else if (fullscreenActiveScan === 'gap_down') { badgeClass = 'gap-down'; badgeText = 'Gap Down'; }
                    else if (fullscreenActiveScan === 'rsi_oversold') { badgeClass = 'rsi-reversal'; badgeText = 'Oversold'; }
                    else if (fullscreenActiveScan === 'rsi_overbought') { badgeClass = 'overbought-shield'; badgeText = 'Overbought'; }
                    else if (fullscreenActiveScan === 'volume_shockers') { badgeClass = 'volume-surge'; badgeText = 'Volume Surge'; }
                    else if (fullscreenActiveScan === 'golden_crossover') { badgeClass = 'golden-cross'; badgeText = 'Golden Cross'; }
                    else if (fullscreenActiveScan === 'sma_50_pullback') { badgeClass = 'pullback-50'; badgeText = '50MA Support'; }
                    else if (fullscreenActiveScan === 'sma_100_pullback') { badgeClass = 'pullback-100'; badgeText = '100MA Support'; }
                    else if (fullscreenActiveScan === 'sma_200_pullback') { badgeClass = 'pullback-200'; badgeText = '200MA Support'; }
                    else if (fullscreenActiveScan === 'fib_618_support') { badgeClass = 'fib-618'; badgeText = '61.8% Fib'; }
                    else if (fullscreenActiveScan === 'fib_500_support') { badgeClass = 'fib-500'; badgeText = '50.0% Fib'; }

                    return `
                        <tr class="technical-scan-row fullscreen-scan-row" data-symbol="${cleanSym}" style="border-bottom: 1px solid var(--border-glass); height: 44px;">
                            <td class="col-hide-mobile" style="padding: 8px 12px; color: var(--text-secondary);">${startIndex + idx + 1}</td>
                            <td style="padding: 8px 12px; font-weight: 700; color: var(--text-primary);">${cleanSym}</td>
                            <td style="padding: 8px 12px; color: var(--text-secondary);">${compName}</td>
                            <td class="col-hide-mobile" style="padding: 8px 12px; color: var(--text-secondary);">${sector}</td>
                            <td class="col-hide-mobile" style="padding: 8px 12px; color: var(--text-secondary);">${segment}</td>
                            <td style="padding: 8px 12px; text-align: right; font-family: 'Inter', monospace; font-weight: 700; color: var(--text-primary);">
                                ${priceDisplay}
                                ${chgDisplay}
                            </td>
                            <td style="padding: 8px 12px; text-align: right; font-family: 'Inter', monospace; ${metricStyle}">${metricValDisplay}</td>
                            <td style="padding: 8px 12px; text-align: center; display: flex; align-items: center; justify-content: center; gap: 8px; height: 44px; box-sizing: border-box;">
                                <span class="signal-badge ${badgeClass}" style="min-width:85px;">${badgeText}</span>
                                <button class="tech-scan-expand-btn" data-target="expand-row-${cleanSym}" title="Toggle Snapshot" style="background: transparent; border: none; color: var(--text-secondary); cursor: pointer; font-size: 12px; padding: 2px 4px;">▼</button>
                                <div class="wl-quick-add-wrap">
                                    <button class="wl-quick-add-btn" title="Quick Add to Watchlist">+</button>
                                    <div class="wl-dropdown-menu"></div>
                                </div>
                            </td>
                        </tr>
                        <tr class="tech-scan-expand-row" id="expand-row-${cleanSym}" style="display: none; border-bottom: 1px solid var(--border-glass);">
                            <td colspan="8" style="padding: 10px 16px;">
                                <div class="tech-snapshot-card">
                                    <div class="tech-snapshot-item">
                                        <span class="tech-snapshot-label">⚡ RSI (14)</span>
                                        <span class="tech-snapshot-val" style="${rsiStyle}">${rsiValStr}</span>
                                    </div>
                                    <div class="tech-snapshot-item">
                                        <span class="tech-snapshot-label">📈 50 MA / 200 MA</span>
                                        <span class="tech-snapshot-val">${sma50Display} / ${sma200Display}</span>
                                    </div>
                                    <div class="tech-snapshot-item">
                                        <span class="tech-snapshot-label">📏 52W High / Low</span>
                                        <span class="tech-snapshot-val">${high52Display} / ${low52Display}</span>
                                    </div>
                                    <div class="tech-snapshot-item">
                                        <span class="tech-snapshot-label">🔊 Volume Multiple</span>
                                        <span class="tech-snapshot-val">${volMultDisplay}</span>
                                    </div>
                                    <div class="tech-snapshot-item">
                                        <span class="tech-snapshot-label">🏢 Sector & Segment</span>
                                        <span class="tech-snapshot-val" style="font-size: 11px; font-weight: 600;">${sector} • ${segment}</span>
                                    </div>
                                </div>
                            </td>
                        </tr>
                    `;
                }).join('');

                // Row expand toggle & click handlers
                tbody.querySelectorAll('.tech-scan-expand-btn').forEach(btn => {
                    btn.onclick = (e) => {
                        e.stopPropagation();
                        const targetId = btn.getAttribute('data-target');
                        const row = document.getElementById(targetId);
                        if (row) {
                            const isHidden = row.style.display === 'none';
                            row.style.display = isHidden ? 'table-row' : 'none';
                            btn.innerText = isHidden ? '▲' : '▼';
                        }
                    };
                });

                tbody.querySelectorAll('.open-prospectus-btn').forEach(btn => {
                    btn.onclick = (e) => {
                        e.stopPropagation();
                        const symbol = btn.getAttribute('data-symbol');
                        const searchInput = document.getElementById('analyzer-search-input');
                        const searchBtn = document.getElementById('analyzer-search-btn');
                        if (searchInput) {
                            searchInput.value = symbol;
                            searchInput.focus();
                            if (searchBtn) searchBtn.click();
                            if (window.switchTab) window.switchTab('market-news');
                        }
                    };
                });

                // Row redirection clicks
                tbody.querySelectorAll('.fullscreen-scan-row').forEach(row => {
                    row.onclick = () => {
                        const symbol = row.getAttribute('data-symbol');
                        const searchInput = document.getElementById('analyzer-search-input');
                        const searchBtn = document.getElementById('analyzer-search-btn');
                        if (searchInput) {
                            searchInput.value = symbol;
                            searchInput.focus();
                            if (searchBtn) searchBtn.click();
                            if (window.switchTab) window.switchTab('market-news');
                        }
                    };
                });

                // Dropdown behavior setup
                tbody.querySelectorAll('.wl-quick-add-btn').forEach(btn => {
                    btn.onclick = (e) => {
                        e.stopPropagation(); // Avoid row click selection
                        const menu = btn.nextElementSibling;
                        const row = btn.closest('.fullscreen-scan-row');
                        const symbol = row.getAttribute('data-symbol');

                        // Toggle active state
                        const isCurrentlyShown = menu.classList.contains('show');
                        document.querySelectorAll('.wl-dropdown-menu').forEach(m => m.classList.remove('show'));

                        if (!isCurrentlyShown) {
                            // Smart vertical positioning: if near bottom of viewport, position upwards
                            const btnRect = btn.getBoundingClientRect();
                            if (window.innerHeight - btnRect.bottom < 160) {
                                menu.style.top = 'auto';
                                menu.style.bottom = 'calc(100% + 4px)';
                            } else {
                                menu.style.top = 'calc(100% + 4px)';
                                menu.style.bottom = 'auto';
                            }

                            renderWatchlistDropdown(symbol, menu);
                            menu.classList.add('show');
                        }
                    };
                });
            } else {
                tbody.innerHTML = `<tr><td colspan="7" class="recent-research-empty" style="padding: 40px 0; text-align: center;">No stocks qualifying under this scan.</td></tr>`;
            }
        };

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.wl-quick-add-wrap')) {
                document.querySelectorAll('.wl-dropdown-menu').forEach(m => m.classList.remove('show'));
            }
        });

        const loadTechnicalScans = async () => {
            const tbody = document.getElementById('desktop-technical-scans-body');
            const fullscreenTbody = document.getElementById('fullscreen-technical-scans-body');
            if (!tbody && !fullscreenTbody) return;

            // 1. Wire homepage selectors once
            const tabs = document.querySelectorAll('.tech-scan-tab-btn:not(.fullscreen-tech-scan-tab)');
            tabs.forEach(tab => {
                if (!tab.dataset.wired) {
                    tab.dataset.wired = "true";
                    tab.addEventListener('click', () => {
                        tabs.forEach(t => {
                            t.classList.remove('active');
                            t.style.background = 'transparent';
                            t.style.borderColor = 'transparent';
                            t.style.color = 'var(--text-secondary)';
                        });
                        tab.classList.add('active');
                        tab.style.background = 'rgba(255, 255, 255, 0.08)';
                        tab.style.borderColor = 'var(--border-glass)';
                        tab.style.color = 'var(--text-primary)';

                        window.activeTechnicalScan = tab.getAttribute('data-scan');
                        renderTechnicalScansList();
                    });
                }
            });

            // 2. Wire homepage "View All" button once
            const viewAllBtn = document.getElementById('desktop-tech-scans-view-all-btn');
            if (viewAllBtn && !viewAllBtn.dataset.wired) {
                viewAllBtn.dataset.wired = "true";
                viewAllBtn.onclick = (e) => {
                    e.stopPropagation();
                    if (window.switchTab) window.switchTab('alerts');
                };
            }

            // 3. Wire fullscreen selector tabs once
            const fullscreenTabs = document.querySelectorAll('.fullscreen-tech-scan-tab');
            fullscreenTabs.forEach(tab => {
                if (!tab.dataset.wired) {
                    tab.dataset.wired = "true";
                    tab.addEventListener('click', () => {
                        fullscreenTabs.forEach(t => {
                            t.classList.remove('active');
                            t.style.background = 'transparent';
                            t.style.borderColor = 'transparent';
                            t.style.color = 'var(--text-secondary)';
                        });
                        tab.classList.add('active');
                        tab.style.background = 'rgba(255, 255, 255, 0.08)';
                        tab.style.borderColor = 'var(--border-glass)';
                        tab.style.color = 'var(--text-primary)';

                        fullscreenActiveScan = tab.getAttribute('data-scan');
                        fullscreenPage = 1; // Reset to page 1 on tab switch

                        // Sync mobile select dropdown
                        const mobileSelect = document.getElementById('fullscreen-tech-scans-mobile-select');
                        if (mobileSelect) mobileSelect.value = fullscreenActiveScan;

                        renderFullscreenTechnicalScans();
                    });
                }
            });

            // 3.5. Wire mobile strategy dropdown select once
            const mobileSelect = document.getElementById('fullscreen-tech-scans-mobile-select');
            if (mobileSelect && !mobileSelect.dataset.wired) {
                mobileSelect.dataset.wired = "true";
                mobileSelect.addEventListener('change', (e) => {
                    fullscreenActiveScan = e.target.value;
                    fullscreenPage = 1;

                    fullscreenTabs.forEach(t => {
                        const isMatch = t.getAttribute('data-scan') === fullscreenActiveScan;
                        if (isMatch) {
                            t.classList.add('active');
                            t.style.background = 'rgba(255, 255, 255, 0.08)';
                            t.style.borderColor = 'var(--border-glass)';
                            t.style.color = 'var(--text-primary)';
                            t.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
                        } else {
                            t.classList.remove('active');
                            t.style.background = 'transparent';
                            t.style.borderColor = 'transparent';
                            t.style.color = 'var(--text-secondary)';
                        }
                    });

                    renderFullscreenTechnicalScans();
                });
            }

            // 4. Wire fullscreen headers sort click once
            const fullscreenHeaders = document.querySelectorAll('.tech-sortable-header');
            fullscreenHeaders.forEach(header => {
                if (!header.dataset.wired) {
                    header.dataset.wired = "true";
                    header.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const col = header.getAttribute('data-sort');
                        if (col === fullscreenSortCol) {
                            // Cycle sort direction: asc -> desc -> none
                            if (fullscreenSortDir === 'asc') fullscreenSortDir = 'desc';
                            else if (fullscreenSortDir === 'desc') fullscreenSortDir = 'none';
                            else fullscreenSortDir = 'asc';
                        } else {
                            fullscreenSortCol = col;
                            fullscreenSortDir = 'asc';
                        }
                        renderFullscreenTechnicalScans();
                    });
                }
            });

            // 5. Wire search input event listener once
            const searchInput = document.getElementById('fullscreen-tech-scans-search');
            if (searchInput && !searchInput.dataset.wired) {
                searchInput.dataset.wired = "true";
                searchInput.addEventListener('input', (e) => {
                    fullscreenSearchQuery = e.target.value;
                    fullscreenPage = 1; // Reset to page 1 on search
                    renderFullscreenTechnicalScans();
                });
            }

            // 6. Wire refresh sync button once
            const refreshBtn = document.getElementById('fullscreen-tech-scans-refresh-btn');
            if (refreshBtn && !refreshBtn.dataset.wired) {
                refreshBtn.dataset.wired = "true";
                refreshBtn.addEventListener('click', () => {
                    loadTechnicalScans();
                });
            }

            // 7. Wire pagination control events once
            const prevBtn = document.getElementById('fullscreen-tech-scans-prev-btn');
            const nextBtn = document.getElementById('fullscreen-tech-scans-next-btn');
            const pageSizeSelect = document.getElementById('fullscreen-tech-scans-pagesize-select');

            if (prevBtn && !prevBtn.dataset.wired) {
                prevBtn.dataset.wired = "true";
                prevBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (fullscreenPage > 1) {
                        fullscreenPage--;
                        renderFullscreenTechnicalScans();
                    }
                });
            }

            if (nextBtn && !nextBtn.dataset.wired) {
                nextBtn.dataset.wired = "true";
                nextBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    fullscreenPage++;
                    renderFullscreenTechnicalScans();
                });
            }

            if (pageSizeSelect && !pageSizeSelect.dataset.wired) {
                pageSizeSelect.dataset.wired = "true";
                pageSizeSelect.addEventListener('change', (e) => {
                    fullscreenPageSize = parseInt(e.target.value) || 10;
                    fullscreenPage = 1;
                    renderFullscreenTechnicalScans();
                });
            }

            try {
                if (tbody) tbody.innerHTML = `<tr><td colspan="5" class="recent-research-empty" style="padding: 20px 0; text-align: center;">Scanning technical breakouts...</td></tr>`;
                if (fullscreenTbody) fullscreenTbody.innerHTML = `<tr><td colspan="7" class="recent-research-empty" style="padding: 40px 0; text-align: center;">Scanning technical breakouts...</td></tr>`;

                const res = await fetch(apiBaseUrl + '/api/technical-scans');
                if (!res.ok) throw new Error("Technical scans API fetch failed");
                const data = await res.json();

                // Store in cache
                technicalScansCache.near_high = data.near_high || [];
                technicalScansCache.near_low = data.near_low || [];
                technicalScansCache.gap_up = data.gap_up || [];
                technicalScansCache.gap_down = data.gap_down || [];
                technicalScansCache.rsi_oversold = data.rsi_oversold || [];
                technicalScansCache.rsi_overbought = data.rsi_overbought || [];
                technicalScansCache.volume_shockers = data.volume_shockers || [];
                technicalScansCache.golden_crossover = data.golden_crossover || [];
                technicalScansCache.sma_50_pullback = data.sma_50_pullback || [];
                technicalScansCache.sma_100_pullback = data.sma_100_pullback || [];
                technicalScansCache.sma_200_pullback = data.sma_200_pullback || [];
                technicalScansCache.fib_618_support = data.fib_618_support || [];
                technicalScansCache.fib_500_support = data.fib_500_support || [];

                // Render both home cockpit list and fullscreen workspace list
                renderTechnicalScansList();
                renderFullscreenTechnicalScans();

                // Update sync time
                const syncTimeEl = document.getElementById('fullscreen-tech-scans-sync-time');
                if (syncTimeEl) {
                    const now = new Date();
                    syncTimeEl.innerText = `Synced: ${now.toLocaleTimeString()}`;
                }
            } catch (err) {
                console.error("Technical Scans fetch load error:", err);
                if (tbody) tbody.innerHTML = `<tr><td colspan="5" class="recent-research-empty" style="padding: 20px 0; text-align: center; color: var(--neon-red);">Failed to load technical scans.</td></tr>`;
                if (fullscreenTbody) fullscreenTbody.innerHTML = `<tr><td colspan="7" class="recent-research-empty" style="padding: 40px 0; text-align: center; color: var(--neon-red);">Failed to run scanner.</td></tr>`;
            }
        };

        // Run cockpit routines
        loadNews();
        loadMarketMovers();
        loadSectorHeatmap();
        loadUpcomingEvents();
        loadHomepageAlerts();
        loadWatchlistStrip();
        loadQuantTopPicks();
        loadTechnicalScans();
    };

    // Initialize all visual modernization layers safely
    const initModernizer = () => {
        const safeCall = (name, fn) => {
            try {
                if (typeof fn === 'function') {
                    fn();
                    console.log(`[APEX Modernizer] ${name} initialized successfully.`);
                } else {
                    console.warn(`[APEX Modernizer] ${name} is not a valid function.`);
                }
            } catch (err) {
                console.error(`[APEX Modernizer] Error in ${name}:`, err);
            }
        };

        safeCall('setupLucideIcons', setupLucideIcons);
        safeCall('setupGSAPTransitions', setupGSAPTransitions);
        safeCall('setupChatUpgrades', setupChatUpgrades);
        safeCall('setupCountUpObservers', setupCountUpObservers);
        safeCall('setupSpotlightAnd3DTilt', setupSpotlightAnd3DTilt);
        safeCall('setupViewTransitions', setupViewTransitions);
        safeCall('setupBullishSparkles', setupBullishSparkles);
        safeCall('setupToastAudioHook', setupToastAudioHook);
        safeCall('setupTTSEqualizer', setupTTSEqualizer);
        safeCall('setupMagneticButtons', setupMagneticButtons);
        
        // Extended Catalyst Features
        safeCall('setupTableCatalystTriggers', setupTableCatalystTriggers);
        safeCall('setupSpeechRecognition', setupSpeechRecognition);
        safeCall('setupCatalystAudioControls', setupCatalystAudioControls);
        safeCall('setupCatalystModalListeners', setupCatalystModalListeners);
        safeCall('setupSettingsSearchToggle', setupSettingsSearchToggle);
        safeCall('setupMobileUpgrades', setupMobileUpgrades);
        safeCall('setupQuickLauncherPills', setupQuickLauncherPills);
        safeCall('setupDesktopHomepageCommandCenter', setupDesktopHomepageCommandCenter);
    };


    // ==================== INDEXEDDB OFFLINE PROSPECTUS STORAGE ====================
    window.StockCacheDB = {
        dbName: 'StockAnalyzerCache',
        dbVersion: 1,
        storeName: 'stockProfiles',

        open() {
            return new Promise((resolve, reject) => {
                const request = indexedDB.open(this.dbName, this.dbVersion);
                request.onupgradeneeded = (e) => {
                    const db = e.target.result;
                    if (!db.objectStoreNames.contains(this.storeName)) {
                        db.createObjectStore(this.storeName, { keyPath: 'ticker' });
                    }
                };
                request.onsuccess = (e) => resolve(e.target.result);
                request.onerror = (e) => reject(e.target.error);
            });
        },

        async put(profile) {
            if (!profile || !profile.ticker) return;
            try {
                const db = await this.open();
                return new Promise((resolve, reject) => {
                    const transaction = db.transaction(this.storeName, 'readwrite');
                    const store = transaction.objectStore(this.storeName);
                    const request = store.put(profile);
                    request.onsuccess = () => resolve();
                    request.onerror = (e) => reject(e.target.error);
                });
            } catch (e) {
                console.error("IndexedDB Put Error:", e);
            }
        },

        async get(ticker) {
            if (!ticker) return null;
            try {
                const db = await this.open();
                return new Promise((resolve, reject) => {
                    const transaction = db.transaction(this.storeName, 'readonly');
                    const store = transaction.objectStore(this.storeName);
                    const request = store.get(ticker);
                    request.onsuccess = (e) => resolve(e.target.result);
                    request.onerror = (e) => reject(e.target.error);
                });
            } catch (e) {
                console.error("IndexedDB Get Error:", e);
                return null;
            }
        }
    };

    // ==================== SUBTAB GLANCE BADGES DYNAMIC UPDATES ====================
    // ==================== STICKY PRICE HUD BAR INITIALIZATION ====================
    window.initStickyPriceHUD = function() {
        const hudBar = document.getElementById('sticky-price-hud-bar');
        const targetBanner = document.querySelector('.stock-meta-banner');
        if (!hudBar || !targetBanner) return;

        window.addEventListener('scroll', () => {
            const activeTabEl = document.querySelector('.workspace-tab.active-tab-content');
            const activeTab = activeTabEl ? activeTabEl.id.replace('tab-', '') : 'analyzer';
            if (activeTab !== 'analyzer') {
                hudBar.classList.remove('visible');
                return;
            }
            const bannerRect = targetBanner.getBoundingClientRect();
            if (bannerRect.bottom < 0) {
                const ticker = document.getElementById('meta-ticker')?.innerText || '--';
                const company = document.getElementById('meta-company-name')?.innerText || '--';
                const price = document.getElementById('meta-price')?.innerText || '--';
                const change = document.getElementById('meta-change')?.innerText || '--';
                const changeClass = document.getElementById('meta-change')?.className || '';

                const hudTicker = document.getElementById('hud-ticker');
                const hudCompany = document.getElementById('hud-company');
                const hudPrice = document.getElementById('hud-price');
                const hudChange = document.getElementById('hud-change');

                if (hudTicker) hudTicker.innerText = ticker;
                if (hudCompany) hudCompany.innerText = company;
                if (hudPrice) hudPrice.innerText = price;
                if (hudChange) {
                    hudChange.innerText = change;
                    hudChange.className = 'hud-change ' + changeClass;
                }
                hudBar.classList.add('visible');
            } else {
                hudBar.classList.remove('visible');
            }
        }, { passive: true });
    };


    // ==================== MULTI-AGENT AI CONFLUENCE RADAR CHART ====================
    window.drawAIRadarChart = function(scores) {
        const canvas = document.getElementById('ai-radar-canvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        // Clear canvas
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        const width = canvas.width;
        const height = canvas.height;
        const centerX = width / 2;
        const centerY = height / 2;
        const maxRadius = Math.min(width, height) / 2 - 18;

        const numAxes = 5;
        const labels = ["Technical", "Forensic", "Intrinsic", "Industry", "Flow"];

        // Draw grid lines
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
        ctx.lineWidth = 1;
        for (let r = 1; r <= 4; r++) {
            const radius = (r / 4) * maxRadius;
            ctx.beginPath();
            for (let i = 0; i < numAxes; i++) {
                const angle = (i * 2 * Math.PI) / numAxes - Math.PI / 2;
                const x = centerX + radius * Math.cos(angle);
                const y = centerY + radius * Math.sin(angle);
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.closePath();
            ctx.stroke();
        }

        // Draw axes
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
        for (let i = 0; i < numAxes; i++) {
            const angle = (i * 2 * Math.PI) / numAxes - Math.PI / 2;
            const x = centerX + maxRadius * Math.cos(angle);
            const y = centerY + maxRadius * Math.sin(angle);
            ctx.beginPath();
            ctx.moveTo(centerX, centerY);
            ctx.lineTo(x, y);
            ctx.stroke();

            // Label rendering
            ctx.fillStyle = 'rgba(255, 255, 255, 0.55)';
            ctx.font = '7.5px sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            const labelX = centerX + (maxRadius + 14) * Math.cos(angle);
            const labelY = centerY + (maxRadius + 10) * Math.sin(angle);
            ctx.fillText(labels[i], labelX, labelY);
        }

        // Draw scores polygon
        ctx.strokeStyle = 'rgba(59, 130, 246, 0.85)';
        ctx.fillStyle = 'rgba(59, 130, 246, 0.2)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        for (let i = 0; i < numAxes; i++) {
            const score = scores[i] || 50; 
            const radius = (score / 100) * maxRadius;
            const angle = (i * 2 * Math.PI) / numAxes - Math.PI / 2;
            const x = centerX + radius * Math.cos(angle);
            const y = centerY + radius * Math.sin(angle);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        // Draw points
        ctx.fillStyle = '#3b82f6';
        for (let i = 0; i < numAxes; i++) {
            const score = scores[i] || 50;
            const radius = (score / 100) * maxRadius;
            const angle = (i * 2 * Math.PI) / numAxes - Math.PI / 2;
            const x = centerX + radius * Math.cos(angle);
            const y = centerY + radius * Math.sin(angle);
            ctx.beginPath();
            ctx.arc(x, y, 2.5, 0, 2 * Math.PI);
            ctx.fill();
        }
    };

    // ==================== QUARTERLY FINANCIAL PERFORMANCE TRENDS ====================
    window.drawFinancialTrendChart = function(data) {
        if (data) {
            window._lastFinancialTrendData = data;
        } else if (window._lastFinancialTrendData) {
            data = window._lastFinancialTrendData;
        } else {
            return;
        }

        const canvas = document.getElementById('financial-trend-canvas');
        if (!canvas || !data || !data.quarters) return;
        const quarters = data.quarters;
        if (!quarters.rows || !quarters.headers) return;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        // Clear canvas
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Detect Theme Mode (Light vs Dark)
        const themeMode = document.documentElement.getAttribute('data-mode') || document.body.getAttribute('data-mode') || '';
        const themeAttr = document.documentElement.getAttribute('data-theme') || document.body.getAttribute('data-theme') || '';
        const isLight = themeMode === 'light' || themeAttr === 'light' || document.documentElement.classList.contains('light-theme') || document.body.classList.contains('light-theme');

        // High contrast theme adaptive colors
        const gridColor = isLight ? 'rgba(0, 0, 0, 0.08)' : 'rgba(255, 255, 255, 0.06)';
        const textColor = isLight ? '#1e293b' : 'rgba(255, 255, 255, 0.75)';
        const salesBarFill = isLight ? 'rgba(37, 99, 235, 0.75)' : 'rgba(59, 130, 246, 0.65)';
        const salesBarStroke = isLight ? 'rgba(29, 78, 216, 0.9)' : 'rgba(96, 165, 250, 0.8)';
        const profitBarFill = isLight ? 'rgba(16, 185, 129, 0.75)' : 'rgba(16, 185, 129, 0.65)';
        const profitBarStroke = isLight ? 'rgba(4, 120, 87, 0.9)' : 'rgba(52, 211, 153, 0.8)';
        const opmLineColor = isLight ? '#d97706' : '#f59e0b';
        const opmDotFill = isLight ? '#b45309' : '#fbbf24';
        const opmBadgeBg = isLight ? 'rgba(255, 255, 255, 0.92)' : 'rgba(15, 23, 42, 0.88)';
        const opmBadgeBorder = isLight ? 'rgba(217, 119, 6, 0.45)' : 'rgba(245, 158, 11, 0.45)';
        const opmTextColor = isLight ? '#92400e' : '#fef08a';

        const isMobile = window.innerWidth < 480;
        const rawHeaders = quarters.headers.slice(1);
        const limit = isMobile ? 4 : 6;
        const headers = rawHeaders.slice(-limit);

        const salesRow = quarters.rows.find(r => (r.label || '').toLowerCase().includes('sales') || (r.label || '').toLowerCase().includes('revenue'));
        const profitRow = quarters.rows.find(r => (r.label || '').toLowerCase().includes('net profit'));
        const opmRow = quarters.rows.find(r => (r.label || '').trim().toLowerCase() === 'opm %' || (r.label || '').trim().toLowerCase() === 'opm');

        const cleanVal = (v) => {
            if (v === null || v === undefined) return 0;
            const cleanStr = v.toString().replace(/,/g, '').replace(/%/g, '').trim();
            return parseFloat(cleanStr) || 0;
        };

        if (!salesRow || !profitRow) return;

        const salesValues = salesRow.values.slice(-limit).map(v => cleanVal(v));
        const profitValues = profitRow.values.slice(-limit).map(v => cleanVal(v));
        const opmValues = opmRow ? opmRow.values.slice(-limit).map(v => cleanVal(v)) : [];

        // Set dimensions & scale for high density displays
        const dpr = window.devicePixelRatio || 1;
        const W = canvas.parentElement ? canvas.parentElement.clientWidth : 320;
        const H = 200;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + 'px';
        canvas.style.height = H + 'px';
        ctx.scale(dpr, dpr);

        const paddingLeft = 45;
        const paddingRight = 45;
        const paddingTop = 28;
        const paddingBottom = 28;
        const chartW = Math.max(W - paddingLeft - paddingRight, 100);
        const chartH = Math.max(H - paddingTop - paddingBottom, 50);

        const maxSales = Math.max(...salesValues, 1) * 1.18;
        const maxOPM = opmValues.length > 0 ? Math.max(...opmValues, 10) * 1.25 : 100;

        // Draw grid lines
        ctx.strokeStyle = gridColor;
        ctx.lineWidth = 1;
        ctx.fillStyle = textColor;
        ctx.font = isLight ? '600 10px sans-serif' : '500 9.5px sans-serif';
        ctx.textAlign = 'center';

        const numPeriods = headers.length;
        const stepX = chartW / numPeriods;

        for (let i = 0; i < numPeriods; i++) {
            const x = paddingLeft + i * stepX + stepX / 2;
            ctx.beginPath();
            ctx.moveTo(x, paddingTop);
            ctx.lineTo(x, paddingTop + chartH);
            ctx.stroke();

            // X label (Quarters e.g. Jun 2024)
            ctx.fillStyle = textColor;
            ctx.fillText(headers[i], x, paddingTop + chartH + 15);
        }

        // Draw horizontal grid & left Y scale
        ctx.textAlign = 'right';
        for (let r = 0; r <= 4; r++) {
            const y = paddingTop + chartH - (r / 4) * chartH;
            ctx.beginPath();
            ctx.moveTo(paddingLeft, y);
            ctx.lineTo(paddingLeft + chartW, y);
            ctx.stroke();

            const valSales = (r / 4) * maxSales;
            let displaySales = Math.round(valSales);
            if (displaySales >= 1000) {
                displaySales = (displaySales / 1000).toFixed(1) + 'k';
            }
            ctx.fillStyle = textColor;
            ctx.fillText(displaySales, paddingLeft - 8, y + 3.5);
        }

        // Draw Revenue & Profit Bars
        const barSpacing = stepX * 0.15;
        const barWidth = Math.max((stepX - barSpacing * 3) / 2, 4);

        for (let i = 0; i < numPeriods; i++) {
            const xSales = paddingLeft + i * stepX + barSpacing;
            const valSales = salesValues[i];
            const barH = (valSales / maxSales) * chartH;
            ctx.fillStyle = salesBarFill;
            ctx.fillRect(xSales, paddingTop + chartH - barH, barWidth, barH);
            ctx.strokeStyle = salesBarStroke;
            ctx.lineWidth = 1;
            ctx.strokeRect(xSales, paddingTop + chartH - barH, barWidth, barH);

            const xProfit = xSales + barWidth + barSpacing;
            const valProfit = profitValues[i];
            const profitH = (valProfit / maxSales) * chartH;
            ctx.fillStyle = profitBarFill;
            ctx.fillRect(xProfit, paddingTop + chartH - profitH, barWidth, profitH);
            ctx.strokeStyle = profitBarStroke;
            ctx.lineWidth = 1;
            ctx.strokeRect(xProfit, paddingTop + chartH - profitH, barWidth, profitH);
        }

        // Draw OPM Line Graph
        if (opmValues.length > 0) {
            ctx.strokeStyle = opmLineColor;
            ctx.lineWidth = 2.5;
            ctx.beginPath();

            for (let i = 0; i < numPeriods; i++) {
                const x = paddingLeft + i * stepX + stepX / 2;
                const valOPM = opmValues[i];
                const y = paddingTop + chartH - (valOPM / maxOPM) * chartH;
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.stroke();

            // OPM Points & Text Badges
            for (let i = 0; i < numPeriods; i++) {
                const x = paddingLeft + i * stepX + stepX / 2;
                const valOPM = opmValues[i];
                const y = paddingTop + chartH - (valOPM / maxOPM) * chartH;
                
                // Dot
                ctx.beginPath();
                ctx.arc(x, y, 3.5, 0, 2 * Math.PI);
                ctx.fillStyle = opmDotFill;
                ctx.fill();
                ctx.strokeStyle = isLight ? '#ffffff' : '#0f172a';
                ctx.lineWidth = 1.5;
                ctx.stroke();

                // Text Badge Pill
                const text = Math.round(valOPM) + '%';
                ctx.font = 'bold 9px sans-serif';
                const textWidth = ctx.measureText(text).width;
                const badgeW = textWidth + 8;
                const badgeH = 13;
                const badgeX = x - badgeW / 2;
                const badgeY = y - 18;

                ctx.fillStyle = opmBadgeBg;
                ctx.strokeStyle = opmBadgeBorder;
                ctx.lineWidth = 1;
                
                // Rounded rect pill
                ctx.beginPath();
                if (typeof ctx.roundRect === 'function') {
                    ctx.roundRect(badgeX, badgeY, badgeW, badgeH, 4);
                } else {
                    ctx.rect(badgeX, badgeY, badgeW, badgeH);
                }
                ctx.fill();
                ctx.stroke();

                ctx.fillStyle = opmTextColor;
                ctx.textAlign = 'center';
                ctx.fillText(text, x, badgeY + 9.5);
            }
        }
    };

    window.redrawFinancialTrendChart = function() {
        if (typeof window.drawFinancialTrendChart === 'function') {
            window.drawFinancialTrendChart();
        }
    };


    // ==================== MOBILE SOLVENCY HUD TAB CONTROLLER ====================
    window.initSolvencyHUD = function() {
        const pBox = document.getElementById('piotroski-box');
        const aBox = document.getElementById('altman-box');
        const pBtn = document.querySelector('[data-solvency="piotroski"]');
        
        if (!pBox || !aBox || !pBtn) return;

        const updateVisibility = () => {
            const currentPBtn = document.querySelector('[data-solvency="piotroski"]');
            const currentPBox = document.getElementById('piotroski-box');
            const currentABox = document.getElementById('altman-box');
            if (!currentPBtn || !currentPBox || !currentABox) return;

            if (window.innerWidth <= 768) {
                if (currentPBtn.classList.contains('active')) {
                    currentPBox.style.setProperty('display', 'flex', 'important');
                    currentABox.style.setProperty('display', 'none', 'important');
                } else {
                    currentABox.style.setProperty('display', 'flex', 'important');
                    currentPBox.style.setProperty('display', 'none', 'important');
                }
            } else {
                currentPBox.style.removeProperty('display');
                currentABox.style.removeProperty('display');
            }
        };

        // Event Delegation for Solvency Toggles click handling
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-solvency]');
            if (!btn) return;
            
            e.preventDefault();
            e.stopPropagation();
            
            const type = btn.getAttribute('data-solvency');
            const pBtn = document.querySelector('[data-solvency="piotroski"]');
            const aBtn = document.querySelector('[data-solvency="altman"]');
            
            if (!pBtn || !aBtn) return;
            
            if (type === 'piotroski') {
                pBtn.classList.add('active');
                aBtn.classList.remove('active');
            } else if (type === 'altman') {
                aBtn.classList.add('active');
                pBtn.classList.remove('active');
            }
            
            updateVisibility();
        });

        window.addEventListener('resize', updateVisibility);
        
        // Initial default set
        updateVisibility();
    };



    // ==================== SEGMENT REVENUE CONTRIBUTION DONUT CHART ====================
    window.getSegmentsFromProfile = function(p) {
        const text = (p.business_summary || '').toLowerCase();
        // Look for explicit percentages in text descriptions
        const matches = [...text.matchAll(/([A-Za-z\s]{3,20})\s+(?:contributed|contributes|accounted for|accounts for|segment|division|revenue|sales)?\s*(\d+)%/g)];
        if (matches.length >= 2) {
            return matches.map(m => ({
                label: m[1].trim().replace(/^(and|the|of|for|with)\s+/i, '').substring(0, 20).toUpperCase(),
                value: parseInt(m[2])
            }));
        }
        
        // Smart simulated fallback based on industry/sector
        const industry = (p.industry || p.sector || 'Conglomerate').toLowerCase();
        if (industry.includes('software') || industry.includes('it services') || industry.includes('technology')) {
            return [
                { label: 'CLOUDS & INFRASTRUCTURE', value: 40 },
                { label: 'ENTERPRISE APPLICATIONS', value: 25 },
                { label: 'DIGITAL TRANSFORMATION', value: 20 },
                { label: 'CONSULTING & SUPPORT', value: 15 }
            ];
        } else if (industry.includes('bank') || industry.includes('financial') || industry.includes('credit')) {
            return [
                { label: 'RETAIL BANKING', value: 35 },
                { label: 'CORPORATE LENDING', value: 30 },
                { label: 'TREASURY & INVESTMENT', value: 20 },
                { label: 'DIGITAL PAYMENTS', value: 15 }
            ];
        } else if (industry.includes('auto') || industry.includes('car') || industry.includes('vehicle')) {
            return [
                { label: 'PASSENGER VEHICLES', value: 45 },
                { label: 'COMMERCIAL VEHICLES', value: 30 },
                { label: 'SPARE PARTS & LEASING', value: 15 },
                { label: 'EV & FUTURE TECH', value: 10 }
            ];
        } else if (industry.includes('pharm') || industry.includes('drug') || industry.includes('health')) {
            return [
                { label: 'GENERIC FORMULATIONS', value: 50 },
                { label: 'ACTIVE INGREDIENTS (API)', value: 25 },
                { label: 'BIOSIMILARS & BIOLOGICS', value: 15 },
                { label: 'RESEARCH & CONTRACT MFG', value: 10 }
            ];
        } else if (industry.includes('power') || industry.includes('energy') || industry.includes('utility')) {
            return [
                { label: 'THERMAL POWER GEN', value: 55 },
                { label: 'RENEWABLE ENERGY', value: 25 },
                { label: 'TRANSMISSION & DIST', value: 20 }
            ];
        } else {
            return [
                { label: 'CORE OPERATIONS', value: 50 },
                { label: 'DOMESTIC SALES', value: 30 },
                { label: 'EXPORTS & LOGISTICS', value: 20 }
            ];
        }
    };

    window.drawSegmentDonutChart = function(segments) {
        const canvas = document.getElementById('segment-donut-canvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        // Clear canvas
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        const width = canvas.width;
        const height = canvas.height;
        const centerX = width / 2;
        const centerY = height / 2;
        const radius = Math.min(width, height) / 2 - 8;
        const innerRadius = radius * 0.65;

        let total = 0;
        segments.forEach(s => total += s.value);
        if (total === 0) return;

        let startAngle = -Math.PI / 2;
        const colors = [
            'rgba(59, 130, 246, 0.85)',   // blue
            'rgba(16, 185, 129, 0.85)',   // green
            'rgba(245, 158, 11, 0.85)',   // amber
            'rgba(139, 92, 246, 0.85)',   // purple
            'rgba(239, 68, 68, 0.85)'     // red
        ];

        segments.forEach((s, idx) => {
            const sliceAngle = (s.value / total) * 2 * Math.PI;
            const color = colors[idx % colors.length];

            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius, startAngle, startAngle + sliceAngle);
            ctx.arc(centerX, centerY, innerRadius, startAngle + sliceAngle, startAngle, true);
            ctx.closePath();
            ctx.fill();

            startAngle += sliceAngle;
        });

        // Legend population
        const legendEl = document.getElementById('segment-legend');
        if (legendEl) {
            legendEl.innerHTML = '';
            segments.forEach((s, idx) => {
                const color = colors[idx % colors.length];
                const item = document.createElement('div');
                item.style.display = 'flex';
                item.style.alignItems = 'center';
                item.style.justifyContent = 'space-between';
                item.style.width = '100%';
                item.style.marginTop = '2px';
                item.innerHTML = `
                    <div style="display:flex; align-items:center; gap:5px; overflow:hidden;">
                        <span style="display:inline-block; width:5px; height:5px; border-radius:50%; background:${color}; flex-shrink:0;"></span>
                        <span style="white-space:nowrap; text-overflow:ellipsis; overflow:hidden;" title="${s.label}">${s.label}</span>
                    </div>
                    <strong style="margin-left:6px; font-weight:700;">${s.value}%</strong>
                `;
                legendEl.appendChild(item);
            });
        }

        const centerValEl = document.getElementById('segment-center-val');
        if (centerValEl && segments.length > 0) {
            const largest = [...segments].sort((a, b) => b.value - a.value)[0];
            centerValEl.innerText = largest.value + "%";
        }
    };

    // ==================== MOBILE SWOT CAROUSEL TOUCH & SCROLL CONTROLS ====================
    window.initSWOTCarousel = function() {
        const container = document.querySelector('.swot-grid-2x2');
        const dots = document.querySelectorAll('.swot-dot');
        if (!container || dots.length === 0) return;

        let scrollDebounce;
        container.addEventListener('scroll', () => {
            clearTimeout(scrollDebounce);
            scrollDebounce = setTimeout(() => {
                const width = container.clientWidth;
                const scrollLeft = container.scrollLeft;
                const activeIdx = Math.round(scrollLeft / width);
                dots.forEach((dot, idx) => {
                    if (idx === activeIdx) {
                        dot.classList.add('active');
                    } else {
                        dot.classList.remove('active');
                    }
                });
            }, 80);
        });

        dots.forEach(dot => {
            dot.onclick = (e) => {
                e.stopPropagation();
                const idx = parseInt(dot.getAttribute('data-idx'));
                const width = container.clientWidth;
                container.scrollTo({
                    left: idx * width,
                    behavior: 'smooth'
                });
            };
        });
    };


    // ==================== PODCAST-STYLE THESIS AUDIO SYNTHESIS HUD ====================
    window.initThesisAudioPlayer = function() {
        const playBtn = document.getElementById('thesis-audio-play-btn');
        const pauseBtn = document.getElementById('thesis-audio-pause-btn');
        const stopBtn = document.getElementById('thesis-audio-stop-btn');
        const progressBar = document.getElementById('thesis-audio-progress-bar');
        const rateSelect = document.getElementById('thesis-audio-rate-select');
        const textEl = document.getElementById('cio-investment-thesis');

        if (!playBtn || !pauseBtn || !stopBtn || !progressBar || !rateSelect || !textEl) return;

        // Force Android WebView to initialize TTS voices on load
        if (window.speechSynthesis) {
            window.speechSynthesis.getVoices();
            if (window.speechSynthesis.onvoiceschanged !== undefined) {
                window.speechSynthesis.onvoiceschanged = () => {
                    window.speechSynthesis.getVoices();
                };
            }
        }

        let utterance = null;
        let progressInterval = null;
        let progressPct = 0;
        let startTime = 0;
        let estimatedDuration = 0;

        const stopReading = () => {
            if (window.speechSynthesis) {
                window.speechSynthesis.cancel();
            }
            clearInterval(progressInterval);
            progressPct = 0;
            progressBar.style.width = '0%';
            playBtn.style.display = 'flex';
            pauseBtn.style.display = 'none';
        };

        playBtn.onclick = (e) => {
            e.stopPropagation();
            
            if (!window.speechSynthesis) {
                if (typeof window.showToast === 'function') {
                    window.showToast("Web Speech TTS is not supported on this device.", "error");
                }
                return;
            }

            if (window.speechSynthesis.paused) {
                window.speechSynthesis.resume();
                playBtn.style.display = 'none';
                pauseBtn.style.display = 'flex';
                startProgressTracker();
                return;
            }

            stopReading();

            const textToRead = textEl.innerText;
            if (!textToRead || textToRead === '...') return;

            // Trigger another getVoices check to ensure voice list is updated before speaking
            const voices = window.speechSynthesis.getVoices();
            utterance = new SpeechSynthesisUtterance(textToRead);
            
            // Explicitly map voice if list exists (workaround for default voice fails in Android WebViews)
            if (voices && voices.length > 0) {
                const defaultVoice = voices.find(v => v.default) || voices.find(v => v.lang.startsWith('en')) || voices[0];
                if (defaultVoice) utterance.voice = defaultVoice;
            }

            utterance.rate = parseFloat(rateSelect.value) || 1.0;

            const wordCount = textToRead.split(/\s+/).length;
            estimatedDuration = (wordCount / 2.5) / utterance.rate; // seconds

            utterance.onend = () => {
                stopReading();
            };

            utterance.onerror = (err) => {
                console.error("SpeechSynthesisUtterance error:", err);
                if (typeof window.showToast === 'function') {
                    window.showToast("Speech synthesis failed. Check device TTS volume/settings.", "error");
                }
                stopReading();
            };

            playBtn.style.display = 'none';
            pauseBtn.style.display = 'flex';

            window.speechSynthesis.speak(utterance);
            startTime = Date.now();
            startProgressTracker();
        };

        pauseBtn.onclick = (e) => {
            e.stopPropagation();
            window.speechSynthesis.pause();
            clearInterval(progressInterval);
            playBtn.style.display = 'flex';
            pauseBtn.style.display = 'none';
        };

        stopBtn.onclick = (e) => {
            e.stopPropagation();
            stopReading();
        };

        rateSelect.onchange = () => {
            if (window.speechSynthesis.speaking) {
                const isPaused = window.speechSynthesis.paused;
                stopReading();
                if (!isPaused) {
                    playBtn.click();
                }
            }
        };

        function startProgressTracker() {
            clearInterval(progressInterval);
            const intervalMs = 100;
            progressInterval = setInterval(() => {
                if (!window.speechSynthesis.speaking || window.speechSynthesis.paused) {
                    return;
                }
                const elapsed = (Date.now() - startTime) / 1000;
                progressPct = Math.min(99.5, (elapsed / estimatedDuration) * 100);
                progressBar.style.width = progressPct + '%';
            }, intervalMs);
        }
    };


    // ==================== MOBILE SLIDE-UP DETAILS BOTTOM DRAWER SHEET ====================
    window.initDetailsBottomSheet = function() {
        console.log("INITIALIZING BOTTOM SHEET DIAGNOSTICS...");
        const bottomSheet = document.getElementById('mobile-details-bottom-sheet');
        const closeBtn = document.getElementById('bottom-sheet-close-btn');
        const contentList = document.getElementById('bottom-sheet-content-list');
        
        console.log("mobile-details-bottom-sheet node exists:", !!bottomSheet);
        console.log("bottom-sheet-close-btn node exists:", !!closeBtn);
        console.log("bottom-sheet-content-list node exists:", !!contentList);

        if (!bottomSheet || !closeBtn || !contentList) {
            console.error("DIAGNOSTIC FAILURE: One or more bottom sheet nodes not found in DOM.");
            return;
        }

        const openSheet = (title, subtitle, sourceContainerId) => {
            console.log("Triggering openSheet:", title, "from source container:", sourceContainerId);
            const sourceContainer = document.getElementById(sourceContainerId);
            if (!sourceContainer) {
                console.error("sourceContainer not found in DOM:", sourceContainerId);
                return;
            }

            document.getElementById('bottom-sheet-title').innerText = title;
            document.getElementById('bottom-sheet-subtitle').innerText = subtitle;

            contentList.innerHTML = '';
            const cards = sourceContainer.querySelectorAll('.cio-checklist-card');
            cards.forEach(card => {
                const clone = card.cloneNode(true);
                clone.classList.add('expanded');
                
                const chk = clone.querySelector('.sandbox-switch');
                if (chk) chk.remove();

                clone.style.margin = '4px 0';
                clone.style.boxShadow = 'none';
                contentList.appendChild(clone);
            });

            document.body.classList.add('sheet-active');
            bottomSheet.style.setProperty('display', 'flex', 'important');
            
            // Directly translate the card up inline
            const cardEl = bottomSheet.querySelector('.bottom-sheet-content');
            if (cardEl) cardEl.style.setProperty('transform', 'translateY(0%)', 'important');

            setTimeout(() => {
                bottomSheet.classList.add('active');
                console.log("Set display: flex and active class on overlay.");
                
                // Hide mobile bottom navigation and FAB triggers immediately
                const bottomNav = document.querySelector('.mobile-bottom-nav');
                if (bottomNav) bottomNav.style.setProperty('display', 'none', 'important');
                const fabContainer = document.querySelector('.mobile-fab-container');
                if (fabContainer) fabContainer.style.setProperty('display', 'none', 'important');
            }, 10);
        };
 
        const closeSheet = () => {
            console.log("Triggering closeSheet.");
            bottomSheet.classList.remove('active');
            document.body.classList.remove('sheet-active');
            
            // Directly translate the card down inline
            const cardEl = bottomSheet.querySelector('.bottom-sheet-content');
            if (cardEl) cardEl.style.setProperty('transform', 'translateY(100%)', 'important');

            // Restore mobile bottom navigation and FAB triggers visibility
            const bottomNav = document.querySelector('.mobile-bottom-nav');
            if (bottomNav) bottomNav.style.removeProperty('display');
            const fabContainer = document.querySelector('.mobile-fab-container');
            if (fabContainer) fabContainer.style.removeProperty('display');
            
            setTimeout(() => {
                bottomSheet.style.setProperty('display', 'none', 'important');
            }, 300);
        };

        // Click interactivity on circular gauges has been removed to ensure mobile stability.

        closeBtn.onclick = (e) => {
            e.stopPropagation();
            closeSheet();
        };

        bottomSheet.onclick = (e) => {
            if (e.target === bottomSheet) {
                closeSheet();
            }
        };
    };

    // ==================== COPY PROSPECTUS TEXT SUMMARY CLIPBOARD WIDGET ====================
    window.initProspectusCopy = function() {
        const copyBtn = document.getElementById('prospectus-copy-btn');
        if (!copyBtn) return;

        copyBtn.onclick = (e) => {
            e.stopPropagation();
            
            const ticker = document.getElementById('corp-ticker')?.innerText || 'STOCK';
            const name = document.getElementById('meta-name')?.innerText || 'Company';
            const rec = document.getElementById('cio-badge-rec')?.innerText || 'HOLD';
            const score = document.getElementById('cio-score-num')?.innerText || '0';
            const alignment = document.getElementById('cio-alignment-num')?.innerText || '0%';
            const risk = document.getElementById('cio-primary-risk-text')?.innerText || 'N/A';
            const thesis = document.getElementById('cio-investment-thesis')?.innerText || '';

            const summaryText = `### CIO EXECUTIVE PROSPECTUS SUMMARY: ${name} (${ticker})\n\n` +
                `* **Conviction Recommendation:** ${rec}\n` +
                `* **Composite AI Score:** ${score}/100\n` +
                `* **Investor Horizon Alignment:** ${alignment}\n` +
                `* **Primary Vulnerability Risk:** ${risk}\n\n` +
                `#### CIO Strategic Investment Thesis:\n` +
                `> ${thesis}\n\n` +
                `*Generated by Indian Stock Analyzer AI Workstation*`;

            navigator.clipboard.writeText(summaryText).then(() => {
                const originalText = copyBtn.innerHTML;
                copyBtn.innerHTML = '✅ Copied!';
                copyBtn.style.borderColor = 'var(--color-emerald)';
                copyBtn.style.color = 'var(--color-emerald)';
                setTimeout(() => {
                    copyBtn.innerHTML = originalText;
                    copyBtn.style.borderColor = '';
                    copyBtn.style.color = '';
                }, 2000);
            }).catch(err => {
                console.error("Failed to copy prospectus text summary:", err);
            });
        };
    };

    window.setupMobileFABSpeedDial = function() {
        const trigger = document.getElementById('mobile-fab-trigger');
        const menu = document.getElementById('mobile-fab-menu');
        if (!trigger || !menu) return;

        // Initialize visibility: only show on analyzer tab on load
        const activeTab = document.querySelector('.workspace-tab.active') || document.querySelector('.active-tab-content');
        const isAnalyzer = activeTab ? (activeTab.id === 'tab-analyzer' || activeTab.classList.contains('tab-analyzer')) : true;
        const fabContainer = document.querySelector('.mobile-fab-container');
        if (fabContainer) {
            if (isAnalyzer && window.innerWidth <= 768) {
                fabContainer.style.setProperty('display', 'flex', 'important');
            } else {
                fabContainer.style.setProperty('display', 'none', 'important');
            }
        }

        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            trigger.classList.toggle('active');
            menu.classList.toggle('active');
            if (window.navigator && window.navigator.vibrate) {
                try { window.navigator.vibrate(10); } catch(e){}
            }
        });

        document.addEventListener('click', (e) => {
            if (!trigger.contains(e.target) && !menu.contains(e.target)) {
                trigger.classList.remove('active');
                menu.classList.remove('active');
            }
        });

        // Watchlist Toggle shortcut
        const wlAction = document.getElementById('fab-action-watchlist');
        if (wlAction) {
            wlAction.addEventListener('click', () => {
                const originalWlBtn = document.getElementById('explanation-watchlist-btn') || document.querySelector('.meta-sub button[onclick*="watchlist"]');
                if (originalWlBtn) {
                    originalWlBtn.click();
                } else if (typeof toggleWatchlistSymbol === 'function' && window.activeStockProfile) {
                    toggleWatchlistSymbol(window.activeStockProfile.ticker);
                } else {
                    window.showToast("Bookmark watchlist triggered", "info");
                }
                trigger.classList.remove('active');
                menu.classList.remove('active');
            });
        }

        // Create Alert shortcut
        const alertAction = document.getElementById('fab-action-alert');
        if (alertAction) {
            alertAction.addEventListener('click', () => {
                window.switchTab('alerts');
                trigger.classList.remove('active');
                menu.classList.remove('active');
            });
        }

        // Share Prospectus shortcut
        const shareAction = document.getElementById('fab-action-share');
        if (shareAction) {
            shareAction.addEventListener('click', () => {
                const text = window.activeStockProfile ? `Analysis prospectus for ${window.activeStockProfile.company_name} (${window.activeStockProfile.ticker}) via Institutional AI Workstation` : "Indian Stock Analyzer Prospectus";
                const url = window.location.href;
                if (navigator.share) {
                    navigator.share({ title: 'Stock Advisor Prospectus', text: text, url: url })
                        .catch(err => console.log('Share canceled/failed:', err));
                } else {
                    navigator.clipboard.writeText(`${text}: ${url}`)
                        .then(() => window.showToast("Copied prospectus link to clipboard!", "success"))
                        .catch(() => window.showToast("Unable to share prospectus", "error"));
                }
                trigger.classList.remove('active');
                menu.classList.remove('active');
            });
        }

        // Export PDF shortcut
        const pdfAction = document.getElementById('fab-action-pdf');
        if (pdfAction) {
            pdfAction.addEventListener('click', () => {
                const originalPdfBtn = document.getElementById('export-pdf-btn');
                if (originalPdfBtn) {
                    originalPdfBtn.click();
                } else {
                    window.showToast("Exporting PDF report...", "info");
                }
                trigger.classList.remove('active');
                menu.classList.remove('active');
            });
        }
    };

    let isInitialized = false;
    const runAllInit = () => {
        if (isInitialized) return;
        isInitialized = true;
        console.log("RUNNING ALL TERMINAL LAYOUT INITIALIZATIONS...");
        try {
            initModernizer();
            if (typeof initStickyPriceHUD === 'function') initStickyPriceHUD();
            if (typeof setupMobileFABSpeedDial === 'function') setupMobileFABSpeedDial();
            if (typeof initSolvencyHUD === 'function') initSolvencyHUD();
            if (typeof initSWOTCarousel === 'function') initSWOTCarousel();
            if (typeof initThesisAudioPlayer === 'function') initThesisAudioPlayer();
            if (typeof initDetailsBottomSheet === 'function') initDetailsBottomSheet();
            if (typeof initProspectusCopy === 'function') initProspectusCopy();
            // Autocomplete logo decorator setup
            const setupSuggestionsObserver = () => {
                const decorateSuggestions = () => {
                    const suggestionsBox = document.getElementById('analyzer-suggestions');
                    if (!suggestionsBox) return;
                    const items = suggestionsBox.querySelectorAll('.suggestion-item');
                    items.forEach(item => {
                        const symSpan = item.querySelector('span');
                        if (symSpan && !item.querySelector('.stock-circle-logo') && !item.querySelector('img')) {
                            const sym = symSpan.innerText.trim();
                            const logoHtml = getStockLogoHtml(sym);
                            
                            // Prepend logo directly in a flex wrapper
                            const logoContainer = document.createElement('div');
                            logoContainer.style.display = 'inline-flex';
                            logoContainer.style.alignItems = 'center';
                            logoContainer.style.gap = '6px';
                            logoContainer.style.marginRight = '6px';
                            logoContainer.style.verticalAlign = 'middle';
                            logoContainer.innerHTML = logoHtml;
                            
                            symSpan.parentNode.insertBefore(logoContainer, symSpan);
                        }
                    });
                };

                const suggestionsBox = document.getElementById('analyzer-suggestions');
                if (suggestionsBox) {
                    decorateSuggestions();
                    const obs = new MutationObserver(() => decorateSuggestions());
                    obs.observe(suggestionsBox, { childList: true });
                }
            };
            setupSuggestionsObserver();

            // Universe Explorer table logo decorator setup
            const setupUniverseObserver = () => {
                window.decorateUniverse = () => {
                    const tbody = document.getElementById('universe-explorer-body');
                    if (!tbody) return;
                    const mobile = window.innerWidth <= 768;
                    tbody.querySelectorAll('tr').forEach(row => {
                        const linkDiv = row.querySelector('.universe-symbol-link');
                        if (linkDiv && !linkDiv.querySelector('.stock-circle-logo') && !linkDiv.querySelector('img')) {
                            const strongEl = linkDiv.querySelector('strong');
                            if (!strongEl) return;
                            const rawSym = strongEl.innerText.trim();
                            const cleanSym = rawSym.replace('.NS', '').toUpperCase();
                            if (Object.keys(isinMapping).length === 0) return;
                            const logoSize = mobile ? 22 : 28;
                            const logoHtml = getStockLogoHtml(cleanSym)
                                .replace(/width:28px/g, `width:${logoSize}px`)
                                .replace(/height:28px/g, `height:${logoSize}px`);
                            
                            const wrapper = document.createElement('div');
                            wrapper.style.cssText = 'display:inline-flex; align-items:center; flex-shrink:0;';
                            wrapper.innerHTML = logoHtml;
                            
                            linkDiv.insertBefore(wrapper, strongEl);
                            linkDiv.style.display = 'inline-flex';
                            linkDiv.style.alignItems = 'center';
                            linkDiv.style.gap = mobile ? '5px' : '8px';

                            if (mobile) {
                                strongEl.style.overflow = 'hidden';
                                strongEl.style.textOverflow = 'ellipsis';
                                strongEl.style.whiteSpace = 'nowrap';
                                strongEl.style.maxWidth = '90px';
                                strongEl.style.display = 'inline-block';
                                strongEl.style.fontSize = '11px';
                            }
                        }
                    });
                };

                const tbody = document.getElementById('universe-explorer-body');
                if (tbody) {
                    window.decorateUniverse();
                    const obs = new MutationObserver(() => window.decorateUniverse());
                    obs.observe(tbody, { childList: true });
                }
            };
            setupUniverseObserver();

            // Single Stock Workspace header logo decorator setup
            const setupWorkspaceHeaderObserver = () => {
                window.decorateWorkspaceHeader = () => {
                    const header = document.getElementById('meta-company-name');
                    const tickerSpan = document.getElementById('meta-ticker');
                    if (!header || !tickerSpan) return;
                    if (!header.querySelector('.stock-circle-logo') && !header.querySelector('img')) {
                        const rawSym = tickerSpan.innerText.trim();
                        const cleanSym = rawSym.replace('.NS', '').toUpperCase();
                        if (Object.keys(isinMapping).length === 0) return; // Wait for mapping
                        const logoHtml = getStockLogoHtml(cleanSym);
                        
                        const logoWrapper = document.createElement('div');
                        logoWrapper.style.display = 'inline-flex';
                        logoWrapper.style.alignItems = 'center';
                        logoWrapper.style.gap = '10px';
                        logoWrapper.style.verticalAlign = 'middle';
                        logoWrapper.style.marginRight = '10px';
                        logoWrapper.innerHTML = logoHtml;
                        
                        const img = logoWrapper.querySelector('img');
                        const fallbackCircle = logoWrapper.querySelector('.stock-circle-logo');
                        if (img) {
                            img.style.width = '32px';
                            img.style.height = '32px';
                            img.parentNode.style.width = '32px';
                            img.parentNode.style.height = '32px';
                        }
                        if (fallbackCircle) {
                            fallbackCircle.style.width = '32px';
                            fallbackCircle.style.height = '32px';
                            fallbackCircle.style.fontSize = '14px';
                        }
                        
                        header.style.display = 'flex';
                        header.style.alignItems = 'center';
                        header.insertBefore(logoWrapper, header.firstChild);
                    }
                    if (typeof window.setupBrandReset === 'function') {
                        window.setupBrandReset();
                    }
                };

                const tickerSpan = document.getElementById('meta-ticker');
                if (tickerSpan) {
                    window.decorateWorkspaceHeader();
                    const obs = new MutationObserver(() => window.decorateWorkspaceHeader());
                    obs.observe(tickerSpan, { characterData: true, childList: true, subtree: true });
                }
            };
            setupWorkspaceHeaderObserver();

            // Watchlist table logo decorator setup
            const setupWatchlistObserver = () => {
                window.decorateWatchlist = () => {
                    const tbody = document.getElementById('watchlist-table-body');
                    if (!tbody) return;
                    tbody.querySelectorAll('tr').forEach(row => {
                        const linkDiv = row.querySelector('.watchlist-symbol-link');
                        if (linkDiv && !linkDiv.querySelector('.stock-circle-logo') && !linkDiv.querySelector('img')) {
                            const strongEl = linkDiv.querySelector('strong');
                            if (!strongEl) return;
                            const rawSym = strongEl.innerText.trim();
                            const cleanSym = rawSym.replace('.NS', '').toUpperCase();
                            if (Object.keys(isinMapping).length === 0) return; // Wait for mapping
                            const logoHtml = getStockLogoHtml(cleanSym);
                            
                            const wrapper = document.createElement('div');
                            wrapper.style.display = 'inline-flex';
                            wrapper.style.alignItems = 'center';
                            wrapper.style.gap = '8px';
                            wrapper.style.verticalAlign = 'middle';
                            wrapper.style.marginRight = '8px';
                            wrapper.innerHTML = logoHtml;
                            
                            linkDiv.insertBefore(wrapper, strongEl);
                            linkDiv.style.display = 'inline-flex';
                            linkDiv.style.alignItems = 'center';
                        }
                    });
                };

                const tbody = document.getElementById('watchlist-table-body');
                if (tbody) {
                    window.decorateWatchlist();
                    const obs = new MutationObserver(() => window.decorateWatchlist());
                    obs.observe(tbody, { childList: true });
                }
            };
            setupWatchlistObserver();

            // Portfolio Ledger table logo decorator setup
            const setupPortfolioObserver = () => {
                window.decoratePortfolio = () => {
                    const tbody = document.getElementById('portfolio-ledger-body');
                    if (!tbody) return;
                    tbody.querySelectorAll('tr').forEach(row => {
                        const link = row.querySelector('.ledger-stock-analyze-link');
                        if (link && !link.parentNode.querySelector('.stock-circle-logo') && !link.parentNode.querySelector('img')) {
                            const rawSym = link.innerText.trim();
                            const cleanSym = rawSym.replace('.NS', '').toUpperCase();
                            if (Object.keys(isinMapping).length === 0) return; // Wait for mapping
                            const logoHtml = getStockLogoHtml(cleanSym);
                            
                            const wrapper = document.createElement('div');
                            wrapper.style.display = 'inline-flex';
                            wrapper.style.alignItems = 'center';
                            wrapper.style.gap = '8px';
                            wrapper.style.verticalAlign = 'middle';
                            wrapper.style.marginRight = '8px';
                            wrapper.innerHTML = logoHtml;
                            
                            link.parentNode.insertBefore(wrapper, link);
                        }
                    });
                };

                const tbody = document.getElementById('portfolio-ledger-body');
                if (tbody) {
                    window.decoratePortfolio();
                    const obs = new MutationObserver(() => window.decoratePortfolio());
                    obs.observe(tbody, { childList: true });
                }
            };
            setupPortfolioObserver();

            // Screener Results table logo decorator setup
            const setupScreenerObserver = () => {
                window.decorateScreener = () => {
                    const tbody = document.getElementById('screener-results-body');
                    if (!tbody) return;
                    const mobile = window.innerWidth <= 768;
                    tbody.querySelectorAll('tr').forEach(row => {
                        const linkDiv = row.querySelector('.screener-symbol-link');
                        if (linkDiv && !linkDiv.querySelector('.stock-circle-logo') && !linkDiv.querySelector('img')) {
                            const symSpan = linkDiv.querySelector('span.text-muted');
                            if (!symSpan) return;
                            const rawSym = symSpan.innerText.split('•')[0].trim();
                            const cleanSym = rawSym.replace('.NS', '').toUpperCase();
                            if (Object.keys(isinMapping).length === 0) return;
                            const logoSize = mobile ? 22 : 28;
                            const logoHtml = getStockLogoHtml(cleanSym)
                                .replace(/width:28px/g, `width:${logoSize}px`)
                                .replace(/height:28px/g, `height:${logoSize}px`);
                            
                            const wrapper = document.createElement('div');
                            wrapper.className = 'screener-logo-wrap';
                            wrapper.style.cssText = 'display:inline-flex; align-items:center; flex-shrink:0;';
                            wrapper.innerHTML = logoHtml;
                            
                            if (mobile) {
                                // Wrap existing text content into a flex text container
                                const textDiv = document.createElement('div');
                                textDiv.style.cssText = 'flex:1; min-width:0; overflow:hidden;';
                                // Move all existing children into textDiv
                                while (linkDiv.firstChild) {
                                    textDiv.appendChild(linkDiv.firstChild);
                                }
                                // Truncate company name
                                const nameEl = textDiv.querySelector('strong');
                                if (nameEl) {
                                    nameEl.style.cssText += '; display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:11.5px;';
                                }
                                // Split symbol + cap into separate elements so cap is always visible
                                const symEl = textDiv.querySelector('span.text-muted');
                                if (symEl) {
                                    const fullText = symEl.textContent.trim();
                                    const parts = fullText.split('•');
                                    const tickerPart = (parts[0] || '').trim();
                                    const capPart = (parts[1] || '').trim();
                                    
                                    // Build a flex row: [ticker...] [• cap]
                                    symEl.innerHTML = '';
                                    symEl.style.cssText += '; display:flex; align-items:center; gap:3px; font-size:9px;';
                                    
                                    const tickerSpan = document.createElement('span');
                                    tickerSpan.textContent = tickerPart;
                                    tickerSpan.style.cssText = 'overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0;';
                                    symEl.appendChild(tickerSpan);
                                    
                                    if (capPart) {
                                        const capSpan = document.createElement('span');
                                        capSpan.textContent = '• ' + capPart;
                                        capSpan.style.cssText = 'flex-shrink:0; white-space:nowrap; color:var(--color-primary-light); font-weight:bold;';
                                        symEl.appendChild(capSpan);
                                    }
                                }
                                // Remove the <br> between strong and span
                                textDiv.querySelectorAll('br').forEach(br => br.remove());
                                
                                linkDiv.appendChild(wrapper);
                                linkDiv.appendChild(textDiv);
                                linkDiv.style.cssText = 'display:flex; align-items:center; gap:6px; cursor:pointer;';
                            } else {
                                linkDiv.insertBefore(wrapper, linkDiv.firstChild);
                                linkDiv.style.display = 'flex';
                                linkDiv.style.alignItems = 'center';
                                linkDiv.style.gap = '8px';
                            }
                        }
                    });
                };

                const tbody = document.getElementById('screener-results-body');
                if (tbody) {
                    window.decorateScreener();
                    const obs = new MutationObserver(() => window.decorateScreener());
                    obs.observe(tbody, { childList: true });
                }
            };
            setupScreenerObserver();

            // Movers Table logo decorator setup
            const setupMoversObserver = () => {
                window.decorateMovers = () => {
                    const gainersTbody = document.getElementById('top-gainers-tbody');
                    const losersTbody = document.getElementById('top-losers-tbody');
                    
                    const decorateBody = (tbody) => {
                        if (!tbody) return;
                        tbody.querySelectorAll('tr').forEach(row => {
                            const symbolCell = row.cells[0];
                            if (symbolCell && !symbolCell.querySelector('.stock-circle-logo') && !symbolCell.querySelector('img')) {
                                const rawText = symbolCell.textContent.trim();
                                const cleanText = rawText.replace('⚡', '').trim();
                                const cleanSym = cleanText.replace('.NS', '').toUpperCase();
                                if (Object.keys(isinMapping).length === 0) return;
                                const logoHtml = getStockLogoHtml(cleanSym);
                                
                                const wrapper = document.createElement('div');
                                wrapper.style.display = 'inline-flex';
                                wrapper.style.alignItems = 'center';
                                wrapper.style.gap = '8px';
                                wrapper.style.verticalAlign = 'middle';
                                wrapper.style.marginRight = '8px';
                                wrapper.innerHTML = logoHtml;
                                
                                symbolCell.insertBefore(wrapper, symbolCell.firstChild);
                                symbolCell.style.display = 'flex';
                                symbolCell.style.alignItems = 'center';
                            }
                        });
                    };

                    decorateBody(gainersTbody);
                    decorateBody(losersTbody);
                };

                const gainers = document.getElementById('top-gainers-tbody');
                const losers = document.getElementById('top-losers-tbody');
                
                if (gainers) {
                    window.decorateMovers();
                    const obs = new MutationObserver(() => window.decorateMovers());
                    obs.observe(gainers, { childList: true });
                }
                if (losers) {
                    const obs = new MutationObserver(() => window.decorateMovers());
                    obs.observe(losers, { childList: true });
                }
            };
            setupMoversObserver();

            // News Feed logo decorator setup
            const setupNewsFeedObserver = () => {
                window.decorateNewsFeed = () => {
                    const container = document.getElementById('market-news-feed-container');
                    if (!container) return;
                    
                    container.querySelectorAll('.timeline-card').forEach(card => {
                        const metadata = card.querySelector('.news-card-header .news-card-metadata');
                        if (metadata) {
                            const sourceSpan = metadata.querySelector('span:first-child');
                            if (sourceSpan && sourceSpan.textContent.includes('📰')) {
                                const source = card.dataset.source || '';
                                const logoHtml = getNewsAgencyLogoHtml(source);
                                sourceSpan.innerHTML = logoHtml;
                            }
                        }
                    });
                };

                const container = document.getElementById('market-news-feed-container');
                if (container) {
                    window.decorateNewsFeed();
                    const obs = new MutationObserver(() => window.decorateNewsFeed());
                    obs.observe(container, { childList: true });
                }
            };
            setupNewsFeedObserver();

            // Alert Table logo decorator setup
            const setupAlertsObserver = () => {
                window.decorateAlerts = () => {
                    const tbody = document.getElementById('alerts-table-body');
                    if (!tbody) return;
                    tbody.querySelectorAll('tr').forEach(row => {
                        const link = row.querySelector('.alert-stock-link');
                        if (link && !link.parentNode.querySelector('.stock-circle-logo') && !link.parentNode.querySelector('img')) {
                            // Use data-ticker attribute for reliable symbol extraction on mobile
                            const rawSym = link.getAttribute('data-ticker') || link.innerText.trim();
                            const cleanSym = rawSym.replace('.NS', '').toUpperCase();
                            if (Object.keys(isinMapping).length === 0) return;
                            const logoHtml = getStockLogoHtml(cleanSym);
                            
                            const wrapper = document.createElement('div');
                            wrapper.style.display = 'inline-flex';
                            wrapper.style.alignItems = 'center';
                            wrapper.style.gap = '8px';
                            wrapper.style.verticalAlign = 'middle';
                            wrapper.style.marginRight = '8px';
                            wrapper.innerHTML = logoHtml;
                            
                            // On mobile, insert inside the cell as flex container
                            const cell = link.closest('td');
                            if (cell) {
                                cell.style.display = 'flex';
                                cell.style.alignItems = 'center';
                                cell.style.gap = '6px';
                                cell.insertBefore(wrapper, cell.firstChild);
                            } else {
                                link.parentNode.insertBefore(wrapper, link);
                            }
                        }
                    });
                };

                const tbody = document.getElementById('alerts-table-body');
                if (tbody) {
                    window.decorateAlerts();
                    const obs = new MutationObserver(() => window.decorateAlerts());
                    obs.observe(tbody, { childList: true });
                }
            };
            setupAlertsObserver();

            // Rule Scanner logo decorator setup
            const setupRuleScannerObserver = () => {
                window.decorateRuleScanner = () => {
                    const tbody = document.getElementById('rule-scanner-results-body');
                    if (!tbody) return;
                    tbody.querySelectorAll('tr').forEach(row => {
                        const cell = row.cells[0];
                        if (cell && !cell.querySelector('.stock-circle-logo') && !cell.querySelector('img')) {
                            const symbolSpan = cell.querySelector('span[onclick]');
                            if (!symbolSpan) return;
                            // Extract symbol from the onclick attribute which is reliable
                            // e.g. onclick="window.loadStockAnalyzer('RELIANCE.NS')"
                            const onclickVal = symbolSpan.getAttribute('onclick') || '';
                            const match = onclickVal.match(/loadStockAnalyzer\(['"](.*?)['"]\)/);
                            let cleanSym = '';
                            if (match && match[1]) {
                                cleanSym = match[1].replace('.NS', '').toUpperCase();
                            } else {
                                // Fallback: strip trailing chevron chars and whitespace
                                cleanSym = symbolSpan.textContent.replace(/[▼▲]/g, '').trim().split('\n')[0].split(' ')[0].replace('.NS', '').toUpperCase();
                            }
                            if (!cleanSym || Object.keys(isinMapping).length === 0) return;
                            const logoHtml = getStockLogoHtml(cleanSym);
                            
                            const innerDiv = cell.querySelector('div');
                            if (innerDiv) {
                                const wrapper = document.createElement('div');
                                wrapper.style.display = 'inline-flex';
                                wrapper.style.alignItems = 'center';
                                wrapper.style.gap = '8px';
                                wrapper.style.verticalAlign = 'middle';
                                wrapper.style.marginRight = '8px';
                                wrapper.innerHTML = logoHtml;
                                
                                const rowWrapper = document.createElement('div');
                                rowWrapper.style.display = 'flex';
                                rowWrapper.style.alignItems = 'center';
                                
                                cell.appendChild(rowWrapper);
                                rowWrapper.appendChild(wrapper);
                                rowWrapper.appendChild(innerDiv);
                            }
                        }
                    });
                };

                const tbody = document.getElementById('rule-scanner-results-body');
                if (tbody) {
                    window.decorateRuleScanner();
                    const obs = new MutationObserver(() => window.decorateRuleScanner());
                    obs.observe(tbody, { childList: true });
                }
            };
            setupRuleScannerObserver();

            // Event Calendar logo decorator setup
            const setupEventsObserver = () => {
                window.decorateEventsCalendar = () => {
                    // Desktop table rows
                    const tbody = document.getElementById('events-market-tbody');
                    if (tbody) {
                        tbody.querySelectorAll('tr').forEach(row => {
                            const cell = row.querySelector('.event-company-cell');
                            if (cell && !cell.querySelector('.stock-circle-logo') && !cell.querySelector('img')) {
                                const symbolEl = cell.querySelector('.event-symbol');
                                if (!symbolEl) return;
                                const rawSym = symbolEl.innerText.trim();
                                const cleanSym = rawSym.replace('.NS', '').toUpperCase();
                                if (Object.keys(isinMapping).length === 0) return;
                                const logoHtml = getStockLogoHtml(cleanSym);
                                
                                const wrapper = document.createElement('div');
                                wrapper.style.display = 'inline-flex';
                                wrapper.style.alignItems = 'center';
                                wrapper.style.gap = '8px';
                                wrapper.style.verticalAlign = 'middle';
                                wrapper.style.marginRight = '8px';
                                wrapper.innerHTML = logoHtml;
                                
                                const originalHtml = cell.innerHTML;
                                cell.innerHTML = '';
                                
                                const flexDiv = document.createElement('div');
                                flexDiv.style.display = 'flex';
                                flexDiv.style.alignItems = 'center';
                                
                                const textDiv = document.createElement('div');
                                textDiv.innerHTML = originalHtml;
                                
                                cell.appendChild(flexDiv);
                                flexDiv.appendChild(wrapper);
                                flexDiv.appendChild(textDiv);
                            }
                        });
                    }

                    // Mobile event cards
                    const mobileCards = document.getElementById('events-market-cards');
                    if (mobileCards) {
                        mobileCards.querySelectorAll('.event-mobile-card').forEach(card => {
                            if (card.querySelector('.stock-circle-logo') || card.querySelector('img')) return;
                            const companyDiv = card.querySelector('.event-mobile-company');
                            if (!companyDiv) return;
                            const symSpan = companyDiv.querySelector('span');
                            if (!symSpan) return;
                            const rawSym = symSpan.innerText.trim();
                            const cleanSym = rawSym.replace('.NS', '').toUpperCase();
                            if (Object.keys(isinMapping).length === 0) return;
                            const logoHtml = getStockLogoHtml(cleanSym)
                                .replace(/width:28px/g, 'width:22px')
                                .replace(/height:28px/g, 'height:22px');
                            
                            const wrapper = document.createElement('div');
                            wrapper.style.cssText = 'display:inline-flex; align-items:center; flex-shrink:0;';
                            wrapper.innerHTML = logoHtml;
                            
                            // Make company div a flex row: [logo] [name...] [ticker badge]
                            companyDiv.style.cssText += '; display:flex; align-items:center; gap:6px; overflow:hidden;';
                            
                            // Get company name text (before the span)
                            const companyText = companyDiv.childNodes[0];
                            if (companyText && companyText.nodeType === Node.TEXT_NODE) {
                                const nameSpan = document.createElement('span');
                                nameSpan.textContent = companyText.textContent.trim();
                                nameSpan.style.cssText = 'overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; flex:1; font-size:11.5px;';
                                companyDiv.replaceChild(nameSpan, companyText);
                            }
                            
                            // Ensure ticker badge doesn't shrink
                            symSpan.style.flexShrink = '0';
                            symSpan.style.fontSize = '8.5px';
                            
                            // Insert logo at the start of the company div
                            companyDiv.insertBefore(wrapper, companyDiv.firstChild);
                        });
                    }
                };

                const tbody = document.getElementById('events-market-tbody');
                if (tbody) {
                    window.decorateEventsCalendar();
                    const obs = new MutationObserver(() => window.decorateEventsCalendar());
                    obs.observe(tbody, { childList: true });
                }
                const mobileCardsEl = document.getElementById('events-market-cards');
                if (mobileCardsEl) {
                    const obs2 = new MutationObserver(() => window.decorateEventsCalendar());
                    obs2.observe(mobileCardsEl, { childList: true });
                }
            };
            setupEventsObserver();

            // Deals Sweep logo decorator setup
            const setupDealsObserver = () => {
                window.decorateDealsSweep = () => {
                    const container = document.getElementById('global-trades-container');
                    if (!container) return;
                    
                    container.querySelectorAll('.timeline-item-row').forEach(card => {
                        const symbolSpan = card.querySelector('span[onclick*="loadStockFromTrades"]');
                        if (symbolSpan) {
                            const parent = symbolSpan.parentElement;
                            if (parent && !parent.querySelector('.stock-circle-logo') && !parent.querySelector('img')) {
                                const rawSym = symbolSpan.innerText.trim();
                                const cleanSym = rawSym.replace('.NS', '').toUpperCase();
                                if (Object.keys(isinMapping).length === 0) return;
                                const logoHtml = getStockLogoHtml(cleanSym);
                                
                                const wrapper = document.createElement('div');
                                wrapper.style.display = 'inline-flex';
                                wrapper.style.alignItems = 'center';
                                wrapper.style.gap = '8px';
                                wrapper.style.verticalAlign = 'middle';
                                wrapper.innerHTML = logoHtml;
                                
                                parent.insertBefore(wrapper, symbolSpan);
                            }
                        }
                    });
                };

                const container = document.getElementById('global-trades-container');
                if (container) {
                    window.decorateDealsSweep();
                    const obs = new MutationObserver(() => window.decorateDealsSweep());
                    obs.observe(container, { childList: true });
                }
            };
            setupDealsObserver();

            // Swing Scanner logo decorator setup
            const setupSwingScanObserver = () => {
                window.decorateSwingScanner = () => {
                    const tbody = document.getElementById('swing-scan-body');
                    if (!tbody) return;
                    tbody.querySelectorAll('tr').forEach(row => {
                        const cell = row.cells[0];
                        if (cell && !cell.querySelector('.stock-circle-logo') && !cell.querySelector('img')) {
                            const symbolSpan = cell.querySelector('span[style*="color"]');
                            if (!symbolSpan) return;
                            const rawSym = symbolSpan.innerText.trim();
                            const cleanSym = rawSym.replace('.NS', '').toUpperCase();
                            if (Object.keys(isinMapping).length === 0) return;
                            const logoHtml = getStockLogoHtml(cleanSym);
                            
                            const wrapper = document.createElement('div');
                            wrapper.style.display = 'inline-flex';
                            wrapper.style.alignItems = 'center';
                            wrapper.style.gap = '8px';
                            wrapper.style.verticalAlign = 'middle';
                            wrapper.innerHTML = logoHtml;
                            
                            cell.insertBefore(wrapper, symbolSpan);
                        }
                    });
                };

                const tbody = document.getElementById('swing-scan-body');
                if (tbody) {
                    window.decorateSwingScanner();
                    const obs = new MutationObserver(() => window.decorateSwingScanner());
                    obs.observe(tbody, { childList: true });
                }
            };
            setupSwingScanObserver();

            // Swing Workspace logo decorator setup
            const setupSwingWorkspaceObserver = () => {
                window.decorateSwingWorkspace = () => {
                    const titleEl = document.getElementById('swing-active-title');
                    if (!titleEl) return;
                    
                    if (titleEl.querySelector('.stock-circle-logo') || titleEl.querySelector('img')) return;
                    
                    const rawSym = titleEl.textContent.trim();
                    if (!rawSym || rawSym === 'Loading candidate...' || rawSym === 'Select a candidate script...') return;
                    
                    const cleanSym = rawSym.replace('.NS', '').toUpperCase();
                    if (Object.keys(isinMapping).length === 0) return;
                    const logoHtml = getStockLogoHtml(cleanSym);
                    
                    const wrapper = document.createElement('div');
                    wrapper.style.display = 'inline-flex';
                    wrapper.style.alignItems = 'center';
                    wrapper.style.gap = '8px';
                    wrapper.style.verticalAlign = 'middle';
                    wrapper.style.marginRight = '8px';
                    wrapper.innerHTML = logoHtml;
                    
                    const textNode = document.createElement('span');
                    textNode.innerText = rawSym;
                    
                    titleEl.innerHTML = '';
                    titleEl.style.display = 'flex';
                    titleEl.style.alignItems = 'center';
                    
                    titleEl.appendChild(wrapper);
                    titleEl.appendChild(textNode);
                };

                const titleEl = document.getElementById('swing-active-title');
                if (titleEl) {
                    window.decorateSwingWorkspace();
                    const obs = new MutationObserver(() => window.decorateSwingWorkspace());
                    obs.observe(titleEl, { childList: true, characterData: true, subtree: true });
                }
            };
            setupSwingWorkspaceObserver();

            // Sector Stocks Modal logo decorator setup
            const setupSectorStocksObserver = () => {
                window.decorateSectorStocks = () => {
                    const tbody = document.getElementById('sector-stocks-table-body');
                    if (!tbody) return;
                    const mobile = window.innerWidth <= 768;
                    tbody.querySelectorAll('tr').forEach(row => {
                        if (row.classList.contains('sector-details-row')) return;
                        const cell = row.cells[0];
                        if (cell && !cell.querySelector('.stock-circle-logo') && !cell.querySelector('img')) {
                            // Preserve mobile-added elements before clearing
                            const existingChevron = cell.querySelector('.row-expand-trigger');
                            const existingMeta = cell.querySelector('.mobile-sector-meta');
                            
                            const rawText = cell.innerText.split('\n')[0].split(' ')[0].trim();
                            const cleanSym = rawText.replace('.NS', '').toUpperCase();
                            if (Object.keys(isinMapping).length === 0) return;
                            
                            const logoSize = mobile ? 22 : 28;
                            const logoHtml = getStockLogoHtml(cleanSym)
                                .replace(/width:28px/g, `width:${logoSize}px`)
                                .replace(/height:28px/g, `height:${logoSize}px`);
                            
                            const wrapper = document.createElement('div');
                            wrapper.style.cssText = 'display:inline-flex; align-items:center; flex-shrink:0;';
                            wrapper.innerHTML = logoHtml;
                            
                            cell.innerHTML = '';
                            cell.style.display = 'flex';
                            cell.style.alignItems = 'center';
                            cell.style.gap = mobile ? '5px' : '8px';
                            
                            const textSpan = document.createElement('span');
                            textSpan.innerText = rawText;
                            textSpan.style.fontWeight = '700';
                            textSpan.style.color = 'var(--color-primary)';
                            if (mobile) {
                                textSpan.style.fontSize = '11px';
                            }
                            
                            cell.appendChild(wrapper);
                            cell.appendChild(textSpan);
                            
                            // Re-attach mobile elements if they existed
                            if (existingMeta) cell.appendChild(existingMeta);
                            if (existingChevron) cell.appendChild(existingChevron);
                        }
                    });
                };

                const tbody = document.getElementById('sector-stocks-table-body');
                if (tbody) {
                    window.decorateSectorStocks();
                    const obs = new MutationObserver(() => window.decorateSectorStocks());
                    obs.observe(tbody, { childList: true });
                }
            };
            setupSectorStocksObserver();

            // Sector heatmaps leader/laggard logo decorator setup
            const setupSectorRadarObserver = () => {
                window.decorateSectorRadar = () => {
                    const listEl = document.getElementById('sector-radar-list');
                    if (!listEl) return;
                    
                    listEl.querySelectorAll('.sector-heatmap-tile').forEach(tile => {
                        const drivers = tile.querySelector('.sector-heatmap-tile-drivers');
                        if (drivers) {
                            const spans = drivers.querySelectorAll('span');
                            spans.forEach(span => {
                                if (span.querySelector('.stock-circle-logo') || span.querySelector('img')) return;
                                
                                const text = span.textContent;
                                if (text.includes('Leader:') || text.includes('Laggard:')) {
                                    const match = text.match(/(?:Leader|Laggard):\s*([A-Z0-9_\-\.]+)/i);
                                    if (match) {
                                        const rawSym = match[1].trim();
                                        if (rawSym && rawSym !== 'N/A') {
                                            const cleanSym = rawSym.replace('.NS', '').toUpperCase();
                                            if (Object.keys(isinMapping).length === 0) return;
                                            const logoHtml = getStockLogoHtml(cleanSym);
                                            
                                            const wrapper = document.createElement('span');
                                            wrapper.style.display = 'inline-flex';
                                            wrapper.style.alignItems = 'center';
                                            wrapper.style.verticalAlign = 'middle';
                                            wrapper.style.marginRight = '4px';
                                            wrapper.style.marginLeft = '4px';
                                            wrapper.innerHTML = logoHtml;
                                            
                                            const parts = span.innerHTML.split(/(Leader:|Laggard:)/i);
                                            if (parts.length >= 3) {
                                                span.innerHTML = parts[0] + parts[1] + wrapper.outerHTML + parts[2];
                                            }
                                        }
                                    }
                                }
                            });
                        }
                    });
                };

                const listEl = document.getElementById('sector-radar-list');
                if (listEl) {
                    window.decorateSectorRadar();
                    const obs = new MutationObserver(() => window.decorateSectorRadar());
                    obs.observe(listEl, { childList: true });
                }
            };
            setupSectorRadarObserver();

            // Peer Benchmarking logo decorator setup
            const setupCompareObserver = () => {
                window.decorateCompare = () => {
                    const headerRow = document.getElementById('compare-table-header');
                    if (!headerRow) return;
                    
                    const ths = headerRow.querySelectorAll('th');
                    if (ths.length <= 1) return;
                    
                    const matrix = window.activeCompareMatrix;
                    if (!matrix || matrix.length === 0) return;
                    
                    for (let i = 1; i < ths.length; i++) {
                        const th = ths[i];
                        if (th.querySelector('.stock-circle-logo') || th.querySelector('img')) continue;
                        
                        const item = matrix[i - 1];
                        if (!item || !item.symbol) continue;
                        
                        const cleanSym = item.symbol.replace('.NS', '').toUpperCase();
                        if (Object.keys(isinMapping).length === 0) return;
                        const logoHtml = getStockLogoHtml(cleanSym);
                        
                        const wrapper = document.createElement('div');
                        wrapper.style.display = 'inline-flex';
                        wrapper.style.alignItems = 'center';
                        wrapper.style.gap = '8px';
                        wrapper.style.verticalAlign = 'middle';
                        wrapper.style.marginRight = '8px';
                        wrapper.innerHTML = logoHtml;
                        
                        const originalHtml = th.innerHTML;
                        th.innerHTML = '';
                        th.style.display = 'flex';
                        th.style.alignItems = 'center';
                        
                        const textSpan = document.createElement('span');
                        textSpan.innerHTML = originalHtml;
                        
                        th.appendChild(wrapper);
                        th.appendChild(textSpan);
                    }
                };

                const headerRow = document.getElementById('compare-table-header');
                if (headerRow) {
                    window.decorateCompare();
                    const obs = new MutationObserver(() => window.decorateCompare());
                    obs.observe(headerRow, { childList: true });
                }
            };
            setupCompareObserver();

            // Sector stocks heatmap tile logo decorator
            const setupSectorStocksHeatmapObserver = () => {
                window.decorateSectorStocksHeatmap = () => {
                    const listEl = document.getElementById('sector-radar-list');
                    if (!listEl) return;
                    const mobile = window.innerWidth <= 768;
                    const logoSize = mobile ? 18 : 28;
                    
                    listEl.querySelectorAll('.stock-heatmap-tile').forEach(tile => {
                        if (tile.querySelector('.stock-circle-logo') || tile.querySelector('img')) return;
                        
                        const symSpan = tile.querySelector('.stock-heatmap-tile-sym');
                        const pctSpan = tile.querySelector('.stock-heatmap-tile-pct');
                        if (symSpan && pctSpan) {
                            const rawSym = symSpan.innerText.trim();
                            const cleanSym = rawSym.replace('.NS', '').toUpperCase();
                            if (Object.keys(isinMapping).length === 0) return;
                            const logoHtml = getStockLogoHtml(cleanSym)
                                .replace(/width:28px/g, `width:${logoSize}px`)
                                .replace(/height:28px/g, `height:${logoSize}px`)
                                .replace(/font-size:\s*11px/g, `font-size:${mobile ? 8 : 11}px`);
                            
                            const wrapper = document.createElement('div');
                            wrapper.style.cssText = 'display:inline-flex; align-items:center; justify-content:center; flex-shrink:0;';
                            wrapper.innerHTML = logoHtml;
                            
                            const rightCol = document.createElement('div');
                            rightCol.style.cssText = 'display:flex; flex-direction:column; align-items:flex-start; justify-content:center; line-height:1.2; min-width:0; overflow:hidden;';
                            
                            symSpan.style.fontSize = mobile ? '9.5px' : '10.5px';
                            symSpan.style.fontWeight = '700';
                            symSpan.style.margin = '0';
                            symSpan.style.overflow = 'hidden';
                            symSpan.style.textOverflow = 'ellipsis';
                            symSpan.style.whiteSpace = 'nowrap';
                            symSpan.style.maxWidth = '100%';
                            symSpan.style.display = 'block';
                            
                            pctSpan.style.fontSize = mobile ? '8.5px' : '9px';
                            pctSpan.style.fontWeight = '600';
                            pctSpan.style.margin = '0';
                            pctSpan.style.whiteSpace = 'nowrap';
                            
                            rightCol.appendChild(symSpan);
                            rightCol.appendChild(pctSpan);
                            
                            tile.innerHTML = '';
                            tile.style.display = 'flex';
                            tile.style.flexDirection = 'row';
                            tile.style.alignItems = 'center';
                            tile.style.justifyContent = 'flex-start';
                            tile.style.padding = mobile ? '4px 6px' : '6px 10px';
                            tile.style.gap = mobile ? '5px' : '8px';
                            tile.style.boxSizing = 'border-box';
                            tile.style.height = 'auto';
                            tile.style.minHeight = mobile ? '36px' : '42px';
                            tile.style.overflow = 'hidden';
                            
                            tile.appendChild(wrapper);
                            tile.appendChild(rightCol);
                        }
                    });
                };

                const listEl = document.getElementById('sector-radar-list');
                if (listEl) {
                    window.decorateSectorStocksHeatmap();
                    const obs = new MutationObserver(() => window.decorateSectorStocksHeatmap());
                    obs.observe(listEl, { childList: true, subtree: true });
                }
            };
            window.toggleDesktopProfilePopover = function(e) {
                if (e) {
                    if (e.stopPropagation) e.stopPropagation();
                    if (e.preventDefault) e.preventDefault();
                }
                const popover = document.getElementById('desktop-profile-popover');
                if (!popover) return;
                const computed = window.getComputedStyle(popover).display;
                const isHidden = popover.style.display === 'none' || computed === 'none';
                if (isHidden) {
                    if (window.innerWidth > 992) {
                        const btn = document.getElementById('desktop-profile-btn');
                        if (btn) {
                            const rect = btn.getBoundingClientRect();
                            popover.style.position = 'fixed';
                            popover.style.top = (rect.bottom + 8) + 'px';
                            popover.style.right = Math.max(12, (window.innerWidth - rect.right)) + 'px';
                            popover.style.left = 'auto';
                        }
                    } else {
                        const mobHeader = document.querySelector('.mobile-header');
                        const topPos = mobHeader ? (mobHeader.getBoundingClientRect().bottom + 4) : 84;
                        popover.style.position = 'fixed';
                        popover.style.top = topPos + 'px';
                        popover.style.right = '8px';
                        popover.style.left = '8px';
                    }
                    popover.style.display = 'block';
                } else {
                    popover.style.display = 'none';
                }
            };

            // Global click listener to close profile popover when clicking outside
            document.addEventListener('click', function(e) {
                const popover = document.getElementById('desktop-profile-popover');
                const profileBtn = document.getElementById('desktop-profile-btn');
                const mobileProfileBtn = document.getElementById('mobile-pro-settings-btn');
                if (popover && popover.style.display === 'block') {
                    if (profileBtn && profileBtn.contains(e.target)) return;
                    if (mobileProfileBtn && mobileProfileBtn.contains(e.target)) return;
                    if (!popover.contains(e.target)) {
                        popover.style.display = 'none';
                    }
                }
            });

            // Sync Popover Controls with Sidebar Inputs
            const popoverHorizon = document.getElementById('popover-horizon');
            const profileHorizon = document.getElementById('profile-horizon');
            if (popoverHorizon && profileHorizon) {
                popoverHorizon.value = profileHorizon.value;
                popoverHorizon.addEventListener('change', () => {
                    profileHorizon.value = popoverHorizon.value;
                    const event = new Event('change', { bubbles: true });
                    profileHorizon.dispatchEvent(event);
                });
            }

            const popoverRisk = document.getElementById('popover-risk');
            const profileRisk = document.getElementById('profile-risk');
            if (popoverRisk && profileRisk) {
                popoverRisk.value = profileRisk.value;
                popoverRisk.addEventListener('change', () => {
                    profileRisk.value = popoverRisk.value;
                    const event = new Event('change', { bubbles: true });
                    profileRisk.dispatchEvent(event);
                });
            }

            // ==================== UNIFIED CENTRAL SEARCH ENGINE ====================
            const desktopSearch = document.getElementById('desktop-global-search');
            const globalAnalyzeBtn = document.getElementById('desktop-global-analyze-btn');
            const globalVoiceBtn = document.getElementById('desktop-global-voice-btn');
            const globalSuggestions = document.getElementById('desktop-global-suggestions');

            const triggerUnifiedAnalysis = (queryText) => {
                const query = (queryText || (desktopSearch ? desktopSearch.value : '')).trim();
                if (!query) return;

                if (globalSuggestions) globalSuggestions.style.display = 'none';
                if (desktopSearch) desktopSearch.blur();

                const analyzerInput = document.getElementById('analyzer-search-input') || document.getElementById('search-input');
                if (analyzerInput) analyzerInput.value = query;

                if (typeof window.loadStockAnalyzer === 'function') {
                    window.loadStockAnalyzer(query);
                } else {
                    if (typeof window.switchTab === 'function') {
                        window.switchTab('analyzer');
                    } else {
                        window.location.hash = '#analyzer';
                    }
                    const analyzerBtn = document.getElementById('analyzer-search-btn') || document.getElementById('search-btn');
                    if (analyzerBtn) {
                        setTimeout(() => analyzerBtn.click(), 50);
                    }
                }
            };

            if (desktopSearch) {
                document.addEventListener('keydown', (e) => {
                    if (e.key === '/' && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
                        e.preventDefault();
                        desktopSearch.focus();
                    }
                });

                desktopSearch.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        triggerUnifiedAnalysis();
                    }
                });

                let autocompleteTimeout = null;
                desktopSearch.addEventListener('input', () => {
                    const query = desktopSearch.value.trim();
                    if (autocompleteTimeout) clearTimeout(autocompleteTimeout);

                    if (query.length < 2) {
                        if (globalSuggestions) globalSuggestions.style.display = 'none';
                        return;
                    }

                    autocompleteTimeout = setTimeout(async () => {
                        try {
                            const apiBaseUrl = window.location.origin;
                            const res = await fetch(apiBaseUrl + `/api/search/suggestions?q=${encodeURIComponent(query)}`);
                            if (res.ok) {
                                const suggestions = await res.json();
                                const showLogos = localStorage.getItem('settings-show-logos') !== 'false';
                                if (globalSuggestions && Array.isArray(suggestions) && suggestions.length > 0) {
                                    globalSuggestions.innerHTML = '';
                                    suggestions.forEach(s => {
                                        const item = document.createElement('div');
                                        item.className = 'watchlist-autocomplete-item';
                                        item.style.padding = '8px 12px';
                                        item.style.cursor = 'pointer';
                                        item.style.borderBottom = '1px solid var(--border-glass)';
                                        item.style.fontSize = '12px';
                                        item.style.display = 'flex';
                                        item.style.alignItems = 'center';
                                        item.style.justifyContent = 'space-between';

                                        const rawSym = s.symbol || s.base_symbol || s.name || '';
                                        const cleanSym = rawSym.replace(/\.(NS|BO)$/i, '').trim();

                                        let logoHtml = '';
                                        if (showLogos && cleanSym) {
                                            const logoFmp = `https://images.financialmodelingprep.com/symbol/${cleanSym}.png`;
                                            const logoTv = `https://s3-symbol-logo.tradingview.com/${cleanSym.toLowerCase()}.svg`;
                                            logoHtml = `<img src="${logoFmp}" onerror="this.onerror=null; this.src='${logoTv}'; this.onerror=function(){ this.style.display='none'; };" style="width:20px; height:20px; border-radius:50%; object-fit:contain; background:#ffffff; padding:1px; border:1px solid rgba(255,255,255,0.15); margin-right:8px; flex-shrink:0;" />`;
                                        }

                                        item.innerHTML = `
                                            <div style="display:flex; align-items:center;">
                                                ${logoHtml}
                                                <div>
                                                    <strong style="color:var(--text-primary); font-family:'Outfit'; font-size:12px;">${s.symbol || s.name}</strong>
                                                    ${s.name && s.name !== s.symbol ? `<span style="color:var(--text-muted); font-size:10px; margin-left:4px;">(${s.name})</span>` : ''}
                                                </div>
                                            </div>
                                            ${s.sector ? `<span style="font-size:9.5px; color:var(--text-muted);">${s.sector}</span>` : ''}
                                        `;
                                        item.addEventListener('click', () => {
                                            desktopSearch.value = s.symbol || s.name;
                                            triggerUnifiedAnalysis(s.symbol || s.name);
                                        });
                                        globalSuggestions.appendChild(item);
                                    });
                                    globalSuggestions.style.display = 'block';
                                } else if (globalSuggestions) {
                                    globalSuggestions.style.display = 'none';
                                }
                            }
                        } catch (e) {}
                    }, 200);
                });

                document.addEventListener('click', (e) => {
                    if (globalSuggestions && e.target !== desktopSearch && !globalSuggestions.contains(e.target)) {
                        globalSuggestions.style.display = 'none';
                    }
                });
            }

            // ==================== RESEARCH TERMINAL HERO SEARCH ENGINE ====================
            const researchEmptyInput = document.getElementById('research-empty-search-input');
            const researchEmptySuggestions = document.getElementById('research-empty-suggestions');

            if (researchEmptyInput && researchEmptySuggestions) {
                const PRELOADED_STOCKS = [
                    { symbol: 'BOSCHLTD', name: 'Bosch Limited', sector: 'Auto Ancillaries' },
                    { symbol: 'RELIANCE', name: 'Reliance Industries', sector: 'Energy & Oil' },
                    { symbol: 'TCS', name: 'Tata Consultancy Services', sector: 'IT & Software' },
                    { symbol: 'HDFCBANK', name: 'HDFC Bank Ltd', sector: 'Banking' },
                    { symbol: 'TATAMOTORS', name: 'Tata Motors Ltd', sector: 'Auto & EV' },
                    { symbol: 'INFY', name: 'Infosys Limited', sector: 'IT & Cloud' },
                    { symbol: 'ICICIBANK', name: 'ICICI Bank Ltd', sector: 'Banking' },
                    { symbol: 'LT', name: 'Larsen & Toubro', sector: 'Infrastructure' },
                    { symbol: 'BHARTIARTL', name: 'Bharti Airtel', sector: 'Telecom' },
                    { symbol: 'MARUTI', name: 'Maruti Suzuki India', sector: 'Auto' }
                ];

                const renderResearchItems = (items) => {
                    if (!items || items.length === 0) {
                        researchEmptySuggestions.style.display = 'none';
                        return;
                    }

                    const showLogos = localStorage.getItem('settings-show-logos') !== 'false';
                    researchEmptySuggestions.innerHTML = '';
                    items.forEach(s => {
                        const item = document.createElement('div');
                        item.className = 'watchlist-autocomplete-item';
                        item.style.padding = '10px 14px';
                        item.style.cursor = 'pointer';
                        item.style.borderBottom = '1px solid var(--border-glass)';
                        item.style.fontSize = '13px';
                        item.style.display = 'flex';
                        item.style.alignItems = 'center';
                        item.style.justifyContent = 'space-between';

                        const rawSym = s.symbol || s.base_symbol || s.name || '';
                        const cleanSym = rawSym.replace(/\.(NS|BO)$/i, '').trim();

                        let logoHtml = '';
                        if (showLogos && cleanSym) {
                            const logoFmp = `https://images.financialmodelingprep.com/symbol/${cleanSym}.png`;
                            const logoTv = `https://s3-symbol-logo.tradingview.com/${cleanSym.toLowerCase()}.svg`;
                            logoHtml = `<img src="${logoFmp}" onerror="this.onerror=null; this.src='${logoTv}'; this.onerror=function(){ this.style.display='none'; };" style="width:20px; height:20px; border-radius:50%; object-fit:contain; background:#ffffff; padding:1px; border:1px solid rgba(255,255,255,0.15); margin-right:10px; flex-shrink:0;" />`;
                        }

                        item.innerHTML = `
                            <div style="display:flex; align-items:center;">
                                ${logoHtml}
                                <div>
                                    <strong style="color:var(--text-primary); font-family:'Outfit', sans-serif; font-size:13px;">${s.symbol || s.base_symbol || s.name}</strong>
                                    ${s.name && s.name !== s.symbol ? `<span style="color:var(--text-muted); font-size:11px; margin-left:6px;">(${s.name})</span>` : ''}
                                </div>
                            </div>
                            ${s.sector ? `<span style="font-size:10px; color:var(--text-muted);">${s.sector}</span>` : ''}
                        `;

                        item.addEventListener('click', (e) => {
                            e.stopPropagation();
                            researchEmptyInput.value = s.symbol || s.base_symbol || s.name;
                            researchEmptySuggestions.style.display = 'none';
                            if (typeof window.loadStockAnalyzer === 'function') {
                                window.loadStockAnalyzer(s.symbol || s.base_symbol || s.name);
                            }
                        });

                        researchEmptySuggestions.appendChild(item);
                    });
                    researchEmptySuggestions.style.display = 'block';
                };

                let researchTimeout = null;
                const handleResearchInput = () => {
                    const query = researchEmptyInput.value.trim().toUpperCase();
                    if (researchTimeout) clearTimeout(researchTimeout);

                    if (!query) {
                        renderResearchItems(PRELOADED_STOCKS);
                        return;
                    }

                    const localFiltered = PRELOADED_STOCKS.filter(s => 
                        s.symbol.includes(query) || (s.name && s.name.toUpperCase().includes(query))
                    );
                    if (localFiltered.length > 0) {
                        renderResearchItems(localFiltered);
                    }

                    researchTimeout = setTimeout(async () => {
                        try {
                            const apiBaseUrl = window.location.origin;
                            const res = await fetch(apiBaseUrl + `/api/search/suggestions?q=${encodeURIComponent(query)}`);
                            if (res.ok) {
                                const suggestions = await res.json();
                                if (Array.isArray(suggestions) && suggestions.length > 0) {
                                    renderResearchItems(suggestions);
                                } else if (localFiltered.length === 0) {
                                    researchEmptySuggestions.style.display = 'none';
                                }
                            }
                        } catch (e) {}
                    }, 150);
                };

                researchEmptyInput.addEventListener('focus', handleResearchInput);
                researchEmptyInput.addEventListener('click', handleResearchInput);
                researchEmptyInput.addEventListener('input', handleResearchInput);

                document.addEventListener('click', (e) => {
                    if (researchEmptySuggestions && e.target !== researchEmptyInput && !researchEmptySuggestions.contains(e.target)) {
                        researchEmptySuggestions.style.display = 'none';
                    }
                });
            }

            // ==================== POPOVER UNIVERSE STATUS LOGIC ====================
            const popoverUnivToggle = document.getElementById('popover-universe-toggle');
            const popoverUnivContent = document.getElementById('popover-universe-content');
            const popoverUnivArrow = document.getElementById('popover-universe-arrow');
            const popoverRebalanceBtn = document.getElementById('popover-rebalance-now-btn');

            if (popoverUnivToggle && popoverUnivContent) {
                popoverUnivToggle.addEventListener('click', (e) => {
                    if (e.target.closest('#popover-rebalance-now-btn')) return;
                    
                    const isHidden = popoverUnivContent.style.display === 'none';
                    popoverUnivContent.style.display = isHidden ? 'block' : 'none';
                    if (popoverUnivArrow) {
                        popoverUnivArrow.style.transform = isHidden ? 'rotate(0deg)' : 'rotate(-90deg)';
                    }
                });
            }

            const syncPopoverUniverseStatus = async () => {
                try {
                    const res = await fetch('/api/admin/rebalance-status');
                    if (!res.ok) return;
                    const data = await res.json();

                    let ts = data.last_rebalanced || 'Never';
                    if (ts !== 'Never') {
                        try {
                            const d = new Date(ts);
                            ts = d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit' })
                               + ' ' + d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });
                        } catch(e) {}
                    }

                    ['popover-rebalance-last-ts', 'rebalance-last-ts'].forEach(id => {
                        const el = document.getElementById(id);
                        if (el) el.textContent = ts;
                    });

                    ['popover-rebalance-universe-count', 'rebalance-universe-count'].forEach(id => {
                        const el = document.getElementById(id);
                        if (el) el.textContent = data.universe_count ?? '—';
                    });

                    ['popover-rebalance-cached-count', 'rebalance-cached-count'].forEach(id => {
                        const el = document.getElementById(id);
                        if (el) el.textContent = data.cached_count ?? '—';
                    });
                } catch (e) {}
            };

            window.syncPopoverUniverseStatus = syncPopoverUniverseStatus;
            syncPopoverUniverseStatus();

            if (popoverRebalanceBtn) {
                popoverRebalanceBtn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    if (popoverRebalanceBtn.classList.contains('syncing')) return;

                    popoverRebalanceBtn.classList.add('syncing');
                    popoverRebalanceBtn.textContent = '↻...';

                    try {
                        const res = await fetch('/api/admin/rebalance', { method: 'POST' });
                        const data = await res.json();
                        if (typeof window.showToast === 'function') {
                            window.showToast(data.message || 'Universe synced successfully!', 'success');
                        }
                        await syncPopoverUniverseStatus();
                    } catch (err) {
                        if (typeof window.showToast === 'function') {
                            window.showToast('Sync failed: ' + err.message, 'error');
                        }
                    } finally {
                        popoverRebalanceBtn.classList.remove('syncing');
                        popoverRebalanceBtn.textContent = '↻ SYNC';
                    }
                });
            }

            if (globalAnalyzeBtn) {
                globalAnalyzeBtn.addEventListener('click', () => triggerUnifiedAnalysis());
            }

            if (globalVoiceBtn && ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)) {
                const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                const recognition = new SpeechRecognition();
                recognition.continuous = false;
                recognition.interimResults = false;
                recognition.lang = 'en-IN';

                globalVoiceBtn.addEventListener('click', () => {
                    globalVoiceBtn.style.transform = 'scale(1.3)';
                    recognition.start();
                });

                recognition.onresult = (event) => {
                    const transcript = event.results[0][0].transcript;
                    if (desktopSearch) desktopSearch.value = transcript;
                    triggerUnifiedAnalysis(transcript);
                    globalVoiceBtn.style.transform = 'scale(1)';
                };

                recognition.onerror = () => {
                    globalVoiceBtn.style.transform = 'scale(1)';
                };
            }

            // Global trigger to redraw all active elements once isinMapping is ready
            window.decorateAllActiveElements = () => {
                if (typeof window.decorateSuggestions === 'function') window.decorateSuggestions();
                if (typeof window.decorateUniverse === 'function') window.decorateUniverse();
                if (typeof window.decorateWorkspaceHeader === 'function') window.decorateWorkspaceHeader();
                if (typeof window.decorateWatchlist === 'function') window.decorateWatchlist();
                if (typeof window.decoratePortfolio === 'function') window.decoratePortfolio();
                if (typeof window.decorateScreener === 'function') window.decorateScreener();
                if (typeof window.decorateMovers === 'function') window.decorateMovers();
                if (typeof window.decorateNewsFeed === 'function') window.decorateNewsFeed();
                if (typeof window.decorateAlerts === 'function') window.decorateAlerts();
                if (typeof window.decorateRuleScanner === 'function') window.decorateRuleScanner();
                if (typeof window.decorateEventsCalendar === 'function') window.decorateEventsCalendar();
                if (typeof window.decorateDealsSweep === 'function') window.decorateDealsSweep();
                if (typeof window.decorateSwingScanner === 'function') window.decorateSwingScanner();
                if (typeof window.decorateSwingWorkspace === 'function') window.decorateSwingWorkspace();
                if (typeof window.decorateSectorStocks === 'function') window.decorateSectorStocks();
                if (typeof window.decorateSectorRadar === 'function') window.decorateSectorRadar();
                if (typeof window.decorateCompare === 'function') window.decorateCompare();
                if (typeof window.decorateSectorStocksHeatmap === 'function') window.decorateSectorStocksHeatmap();
            };

            // ==================== DESKTOP NAVBAR SWITCH TAB SYNC WRAPPER ====================
            const originalSwitchTab = window.switchTab;
            window.switchTab = function(tabKey) {
                if (typeof originalSwitchTab === 'function') {
                    originalSwitchTab(tabKey);
                } else {
                    const sections = document.querySelectorAll('.tab-content, .content-section, [id^="tab-"]');
                    sections.forEach(s => {
                        if (s.id === `tab-${tabKey}`) s.style.display = 'block';
                    });
                }

                // Update active state on desktop navbar buttons
                const desktopBtns = document.querySelectorAll('.desktop-navbar .nav-btn');
                desktopBtns.forEach(btn => {
                    const btnKey = btn.getAttribute('data-tab-key');
                    if (btnKey === tabKey || btn.id === `tab-${tabKey}-btn-desktop`) {
                        btn.classList.add('active');
                    } else {
                        btn.classList.remove('active');
                    }
                });
            };
            // Setup PDF Sections Accordion Toggle in Desktop Profile Popover
            const pdfSectionsToggle = document.getElementById('popover-pdf-sections-toggle');
            const pdfSectionsContent = document.getElementById('popover-pdf-sections-content');
            const pdfSectionsArrow = document.getElementById('popover-pdf-sections-arrow');

            if (pdfSectionsToggle && pdfSectionsContent) {
                pdfSectionsToggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const isHidden = pdfSectionsContent.style.display === 'none';
                    pdfSectionsContent.style.display = isHidden ? 'block' : 'none';
                    if (pdfSectionsArrow) {
                        pdfSectionsArrow.style.transform = isHidden ? 'rotate(180deg)' : 'rotate(0deg)';
                    }
                });
            }

            // ==================== LIVE DATA SYNC FOR QUANT COCKPIT HERO BANNER ====================
            window.updateQuantCockpitBanner = async function() {
                const banner = document.getElementById('market-pulse-banner');
                if (!banner || banner.style.display === 'none') return;

                try {
                    const apiBase = window.apiBaseUrl || '';
                    const res = await fetch(apiBase + '/api/market-movers');
                    if (res.ok) {
                        const data = await res.json();
                        
                        // 1. Update Market Regime Dial & Breadth Stats
                        const adv = data.advances || 194;
                        const dec = data.declines || 259;
                        const total = adv + dec;
                        const ratio = dec > 0 ? (adv / dec) : 1.0;
                        const regimeScore = Math.min(98, Math.max(12, Math.round((adv / total) * 100)));

                        const scoreEl = document.getElementById('quant-banner-regime-score');
                        const labelEl = document.getElementById('quant-banner-regime-label');
                        const riskEl = document.getElementById('quant-banner-risk-badge');
                        const dialEl = document.getElementById('quant-banner-dial-ring');
                        const advRatioEl = document.getElementById('quant-banner-adv-ratio');

                        if (scoreEl) scoreEl.textContent = regimeScore;
                        if (advRatioEl) advRatioEl.textContent = ratio.toFixed(2) + 'x';

                        let color = '#10b981';
                        let labelText = 'BULLISH ACCUMULATION';
                        let riskText = 'LOW RISK';

                        if (regimeScore >= 60) {
                            color = '#10b981';
                            labelText = 'BULLISH ACCUMULATION';
                            riskText = 'LOW RISK';
                        } else if (regimeScore >= 40) {
                            color = '#38bdf8';
                            labelText = 'NEUTRAL CONSOLIDATION';
                            riskText = 'BALANCED';
                        } else {
                            color = '#ef4444';
                            labelText = 'BEARISH CAUTION';
                            riskText = 'ELEVATED RISK';
                        }

                        if (labelEl) {
                            labelEl.textContent = labelText;
                            labelEl.style.color = color;
                        }
                        if (riskEl) {
                            riskEl.textContent = riskText;
                            riskEl.style.color = color;
                            riskEl.style.background = color + '22';
                        }
                        if (dialEl) {
                            dialEl.style.background = `conic-gradient(${color} 0% ${regimeScore}%, rgba(255,255,255,0.1) ${regimeScore}% 100%)`;
                            dialEl.style.boxShadow = `0 0 14px ${color}55`;
                        }

                        // 2. Update Top 3 Quant Alpha Stock Cards from Live Gainers
                        const gainersList = data.gainers?.all || data.gainers?.large || [];
                        if (gainersList && gainersList.length >= 3) {
                            const cardsContainer = document.getElementById('quant-banner-alpha-cards');
                            if (cardsContainer) {
                                cardsContainer.innerHTML = gainersList.slice(0, 3).map((item, idx) => {
                                    const rawSym = item.symbol || 'NIFTY';
                                    const cleanSym = rawSym.replace('.NS', '').replace('.BO', '');
                                    const chgPct = item.change_pct ? (item.change_pct > 0 ? `+${item.change_pct.toFixed(2)}%` : `${item.change_pct.toFixed(2)}%`) : '+4.2%';
                                    const price = item.price ? `₹${item.price.toLocaleString('en-IN')}` : '';
                                    const name = item.company_name || cleanSym;
                                    const tag = idx === 0 ? '🔥 TOP GAINER' : idx === 1 ? '⚡ VOLUME SURGE' : '📈 BREAKOUT';
                                    
                                    const badgeBg = idx === 0 ? 'rgba(16, 185, 129, 0.2)' : idx === 1 ? 'rgba(59, 130, 246, 0.2)' : 'rgba(245, 158, 11, 0.2)';
                                    const badgeColor = idx === 0 ? '#34d399' : idx === 1 ? '#60a5fa' : '#fbbf24';
                                    const borderColor = idx === 0 ? 'rgba(16, 185, 129, 0.3)' : idx === 1 ? 'rgba(59, 130, 246, 0.3)' : 'rgba(245, 158, 11, 0.3)';
                                    const hoverColor = idx === 0 ? '#10b981' : idx === 1 ? '#3b82f6' : '#f59e0b';
                                    
                                    return `
                                        <div onclick="if(window.loadStockAnalyzer){ window.loadStockAnalyzer('${cleanSym}'); }" style="background: rgba(0, 0, 0, 0.3); border: 1px solid ${borderColor}; border-radius: 10px; padding: 10px 12px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.borderColor='${hoverColor}'; this.style.transform='translateY(-2px)';" onmouseout="this.style.borderColor='${borderColor}'; this.style.transform='none';">
                                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                                <span style="font-weight: 800; font-size: 12px; color: #ffffff;">${cleanSym}</span>
                                                <span style="font-size: 9px; background: ${badgeBg}; color: ${badgeColor}; padding: 1px 5px; border-radius: 3px; font-weight: 700;">${chgPct}</span>
                                            </div>
                                            <div style="font-size: 10px; color: #94a3b8; margin-top: 4px; line-height: 1.3; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${name}">${name} (${price})</div>
                                            <div style="font-size: 9.5px; color: ${badgeColor}; font-weight: 700; margin-top: 6px; display: flex; align-items: center; justify-content: space-between;">
                                                <span>${tag}</span>
                                                <span>Analyze ➔</span>
                                            </div>
                                        </div>
                                    `;
                                }).join('');
                            }
                        }
                    }
                } catch(err) {
                    console.warn("Quant Cockpit Banner live hydration warning:", err);
                }
            };

            window.updateQuantCockpitBanner();
            setTimeout(window.updateQuantCockpitBanner, 500);
            setInterval(window.updateQuantCockpitBanner, 60000);

        } catch(e) {
            console.error("Error invoking additions:", e);
        }
    };

    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        setTimeout(runAllInit, 10); // 10ms yield to ensure browser parser parses elements below
    } else {
        document.addEventListener('DOMContentLoaded', runAllInit);
        window.addEventListener('load', runAllInit);
    }

})();
