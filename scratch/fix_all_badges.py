"""
Comprehensive script to add LLM execution badges to ALL missing UI locations in app.js.
This handles all 22 missing badge integrations identified by the audit.
"""
import sys

with open('backend/static/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

changes = 0

# ============================================================
# PATTERN A: typewriteElement callbacks - add badge after typewrite completes
# ============================================================

# 1. Swing Trading AI Summary Thesis (Line ~25383)
old = """typewriteElement(innerDiv, formatMarkdownToHTML(data.synthesis), () => {
            if (window.AIExportManager) {
                window.AIExportManager.decorate(summaryBox, 'report', { module: 'SWING_THESIS' });
            }
        });"""
new = """typewriteElement(innerDiv, formatMarkdownToHTML(data.synthesis), () => {
            innerDiv.innerHTML += '<div class="ai-footer-meta-wrap">' + window.renderLLMExecutionBadgeHtml(data.llm_meta) + '</div>';
            if (window.AIExportManager) {
                window.AIExportManager.decorate(summaryBox, 'report', { module: 'SWING_THESIS' });
            }
        });"""
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: Swing Synthesis typewriteElement')

# 2. Screener Scan Synthesis (Line ~26975)
old = """typewriteElement(textEl, formatMarkdownToHTML(data.synthesis || 'No synthesis generated.'), () => {
                    if (window.AIExportManager) {
                        window.AIExportManager.decorate(textEl, 'report', { module: 'SCREENER_SCAN' });
                    }
                });"""
new = """typewriteElement(textEl, formatMarkdownToHTML(data.synthesis || 'No synthesis generated.'), () => {
                    textEl.innerHTML += '<div class="ai-footer-meta-wrap">' + window.renderLLMExecutionBadgeHtml(data.llm_meta) + '</div>';
                    if (window.AIExportManager) {
                        window.AIExportManager.decorate(textEl, 'report', { module: 'SCREENER_SCAN' });
                    }
                });"""
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: Screener Scan Synthesis typewriteElement')

# 3. Screener Formula Explainer (Line ~27715)
old = """typewriteElement(textEl, formatMarkdownToHTML(data.explanation || 'No explanation generated.'), () => {
                    if (window.AIExportManager) {
                        window.AIExportManager.decorate(textEl, 'report', { module: 'SCREENER_EXPLAIN_FORMULA' });
                    }
                });"""
new = """typewriteElement(textEl, formatMarkdownToHTML(data.explanation || 'No explanation generated.'), () => {
                    textEl.innerHTML += '<div class="ai-footer-meta-wrap">' + window.renderLLMExecutionBadgeHtml(data.llm_meta) + '</div>';
                    if (window.AIExportManager) {
                        window.AIExportManager.decorate(textEl, 'report', { module: 'SCREENER_EXPLAIN_FORMULA' });
                    }
                });"""
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: Screener Formula Explainer typewriteElement')

# 4. Risk Matrix Synthesis (Line ~23801)
old = """typewriteElement(textEl, formatMarkdownToHTML(data.synthesis), () => {
                        if (window.AIExportManager) {
                            window.AIExportManager.decorate(textEl, 'report', { module: 'RISK_SYNTHESIS' });
                        }
                    });"""
new = """typewriteElement(textEl, formatMarkdownToHTML(data.synthesis), () => {
                        textEl.innerHTML += '<div class="ai-footer-meta-wrap">' + window.renderLLMExecutionBadgeHtml(data.llm_meta) + '</div>';
                        if (window.AIExportManager) {
                            window.AIExportManager.decorate(textEl, 'report', { module: 'RISK_SYNTHESIS' });
                        }
                    });"""
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: Risk Synthesis typewriteElement')

# 5. Portfolio Backtest Synthesis (Line ~23298)
old = """typewriteElement(summaryText, formatMarkdownToHTML(synthData.synthesis), () => {
                        if (window.AIExportManager) {
                            window.AIExportManager.decorate(summaryText, 'report', { module: 'BACKTEST_REVIEW' });
                        }
                    });"""
new = """typewriteElement(summaryText, formatMarkdownToHTML(synthData.synthesis), () => {
                        summaryText.innerHTML += '<div class="ai-footer-meta-wrap">' + window.renderLLMExecutionBadgeHtml(synthData.llm_meta) + '</div>';
                        if (window.AIExportManager) {
                            window.AIExportManager.decorate(summaryText, 'report', { module: 'BACKTEST_REVIEW' });
                        }
                    });"""
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: Portfolio Backtest Synthesis typewriteElement')

# 6. Portfolio Optimizer Synthesis (Line ~34297)
old = """typewriteElement(innerDiv, formatMarkdownToHTML(data.synthesis), () => {
                        if (window.AIExportManager) {
                            window.AIExportManager.decorate(aiResult, 'report', { module: 'PORTFOLIO_OPTIMIZATION' });
                        }
                    });"""
new = """typewriteElement(innerDiv, formatMarkdownToHTML(data.synthesis), () => {
                        innerDiv.innerHTML += '<div class="ai-footer-meta-wrap">' + window.renderLLMExecutionBadgeHtml(data.llm_meta) + '</div>';
                        if (window.AIExportManager) {
                            window.AIExportManager.decorate(aiResult, 'report', { module: 'PORTFOLIO_OPTIMIZATION' });
                        }
                    });"""
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: Portfolio Optimizer Synthesis typewriteElement')

# 7. Technical Indicator Synthesis (Line ~32036)
old = """typewriteElement(content, formatMarkdownToHTML(data.synthesis), () => {
                    if (window.AIExportManager) {
                        window.AIExportManager.decorate(content, 'report', { module: 'TECHNICAL_INDICATORS' });
                    }
                });"""
new = """typewriteElement(content, formatMarkdownToHTML(data.synthesis), () => {
                    content.innerHTML += '<div class="ai-footer-meta-wrap">' + window.renderLLMExecutionBadgeHtml(data.llm_meta) + '</div>';
                    if (window.AIExportManager) {
                        window.AIExportManager.decorate(content, 'report', { module: 'TECHNICAL_INDICATORS' });
                    }
                });"""
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: Technical Indicator Synthesis typewriteElement')

# 8. Sector Regime AI Analysis (Line ~33003)
old = """typewriteElement(aiContent, compiledHtml, () => {
                    // Bind chat ticker clicks
                    aiContent.querySelectorAll('.chat-ticker-btn').forEach(btn => {
                        btn.onclick = () => {
                            const ticker = btn.getAttribute('data-ticker');
                            if (window.switchTab) window.switchTab('analyzer');
                            if (window.loadStockAnalyzer) window.loadStockAnalyzer(ticker);
                        };
                    });
                    if (window.AIExportManager) {
                        window.AIExportManager.decorate(aiContent, 'report', { module: 'SECTOR_REGIME' });
                    }
                });"""
new = """typewriteElement(aiContent, compiledHtml, () => {
                    aiContent.innerHTML += '<div class="ai-footer-meta-wrap">' + window.renderLLMExecutionBadgeHtml(data.llm_meta) + '</div>';
                    // Bind chat ticker clicks
                    aiContent.querySelectorAll('.chat-ticker-btn').forEach(btn => {
                        btn.onclick = () => {
                            const ticker = btn.getAttribute('data-ticker');
                            if (window.switchTab) window.switchTab('analyzer');
                            if (window.loadStockAnalyzer) window.loadStockAnalyzer(ticker);
                        };
                    });
                    if (window.AIExportManager) {
                        window.AIExportManager.decorate(aiContent, 'report', { module: 'SECTOR_REGIME' });
                    }
                });"""
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: Sector Regime AI Analysis typewriteElement')


# ============================================================
# PATTERN B: Portfolio Doctor Prescription HTML (Line ~21246)
# ============================================================

# 9. Portfolio Doctor
old = """prescriptionContent.innerHTML = html;
            if (window.AIExportManager) {
                window.AIExportManager.decorate(prescriptionContent, 'report', { module: 'PORTFOLIO_DOCTOR' });
            }"""
new = """prescriptionContent.innerHTML = html + '<div class="ai-footer-meta-wrap">' + window.renderLLMExecutionBadgeHtml(data.llm_meta) + '</div>';
            if (window.AIExportManager) {
                window.AIExportManager.decorate(prescriptionContent, 'report', { module: 'PORTFOLIO_DOCTOR' });
            }"""
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: Portfolio Doctor Prescription')


# ============================================================
# PATTERN C: Watchlist AI Summary & Batch Audit Summary (typewriteElement without callback)
# ============================================================

# 10. Watchlist AI Summary (Line ~21495)
old = """typewriteElement(summaryText, html);
                summaryBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

            } catch (err) {
                console.error("Watchlist summary error:", err);"""
new = """typewriteElement(summaryText, html, () => {
                    summaryText.innerHTML += '<div class="ai-footer-meta-wrap">' + window.renderLLMExecutionBadgeHtml(chatRes.llm_meta) + '</div>';
                });
                summaryBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

            } catch (err) {
                console.error("Watchlist summary error:", err);"""
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: Watchlist AI Summary typewriteElement')

# 11. Batch Audit Summary (Line ~21356)
old = """typewriteElement(summaryText, html);
                summaryBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

            } catch (err) {
                console.error("Audit summary error:", err);"""
new = """typewriteElement(summaryText, html, () => {
                    summaryText.innerHTML += '<div class="ai-footer-meta-wrap">' + window.renderLLMExecutionBadgeHtml(data.llm_meta) + '</div>';
                });
                summaryBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

            } catch (err) {
                console.error("Audit summary error:", err);"""
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: Batch Audit Summary typewriteElement')


# ============================================================
# PATTERN D: Chat functions - pass llm_meta through to append functions
# ============================================================

# 12. Co-Pilot Main Chat (Line ~13903) - already passes llm_meta to appendChatMessage
# Check if appendChatMessage already uses llm_meta
old = "appendChatMessage('assistant', chatReplyText, true, data.llm_meta);"
if old in content:
    print(f'  [INFO] Co-Pilot Chat already passes data.llm_meta to appendChatMessage')

# 13. Solvency Chat - pass llm_meta (Line ~28899)
old = "appendSolvencyChatMessage('bot', responseText, true);"
new = "appendSolvencyChatMessage('bot', responseText, true, data.llm_meta);"
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] Updated: Solvency Chat caller passes llm_meta')

# 14. Solvency Chat function signature
old = "function appendSolvencyChatMessage(role, text, useTypewriter = false) {"
new = "function appendSolvencyChatMessage(role, text, useTypewriter = false, llmMeta = null) {"
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: appendSolvencyChatMessage signature')

# 15. Solvency Chat - add badge after bubble append
old = """    msg.appendChild(bubble);
    history.appendChild(msg);
    history.scrollTop = history.scrollHeight;"""
if old in content:
    new = """    msg.appendChild(bubble);
    if (role !== 'user' && llmMeta) {
        const metaWrap = document.createElement('div');
        metaWrap.className = 'ai-footer-meta-wrap';
        metaWrap.innerHTML = window.renderLLMExecutionBadgeHtml(llmMeta);
        msg.appendChild(metaWrap);
    }
    history.appendChild(msg);
    history.scrollTop = history.scrollHeight;"""
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] Updated: appendSolvencyChatMessage badge injection')

# 16. Chart Chat Analyst - pass llm_meta (Line ~31249)
old = "appendTvChatMessage('bot', data.analysis || \"No response received.\", true);"
new = "appendTvChatMessage('bot', data.analysis || \"No response received.\", true, data.llm_meta);"
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: Chart Chat Analyst caller passes llm_meta')

# 17. appendTvChatMessage signature (may already be updated)
old = "function appendTvChatMessage(role, content, useTypewriter = false) {"
new = "function appendTvChatMessage(role, content, useTypewriter = false, llmMeta = null) {"
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: appendTvChatMessage signature')

# 18. appendTvChatMessage badge for non-typewriter path
old = """        contentDiv.innerHTML = html;
        history.appendChild(div);"""
new = """        contentDiv.innerHTML = html;
        if (llmMeta) div.innerHTML += '<div class="ai-footer-meta-wrap">' + window.renderLLMExecutionBadgeHtml(llmMeta) + '</div>';
        history.appendChild(div);"""
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] Updated: appendTvChatMessage non-typewriter badge')

# 19. appendTvChatMessage badge for typewriter path
old = """        typewriteElement(contentDiv, html, () => {
                speechContainer.style.display = 'flex';
            }, history);"""
new = """        typewriteElement(contentDiv, html, () => {
                speechContainer.style.display = 'flex';
                if (llmMeta) div.innerHTML += '<div class="ai-footer-meta-wrap">' + window.renderLLMExecutionBadgeHtml(llmMeta) + '</div>';
            }, history);"""
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] Updated: appendTvChatMessage typewriter badge')

# 20. Audit Chatbot (Line ~48037) - pass llm_meta
old = "appendAuditChatMessage('bot', botResponse, latencySec, true);"
new = "appendAuditChatMessage('bot', botResponse, latencySec, true, data.llm_meta);"
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: Audit Chatbot caller passes llm_meta')

# 21. Audit Chatbot function signature
old = "function appendAuditChatMessage(sender, text, latency, useTypewriter = false) {"
new = "function appendAuditChatMessage(sender, text, latency, useTypewriter = false, llmMeta = null) {"
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: appendAuditChatMessage signature')

# 22. Margin Chatbot (Line ~48899) - pass llm_meta
old = "appendMarginChatMessage('bot', botResponse, latencySec, true);"
new = "appendMarginChatMessage('bot', botResponse, latencySec, true, data.llm_meta);"
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: Margin Chatbot caller passes llm_meta')

# 23. Margin Chatbot function signature
old = "function appendMarginChatMessage(sender, text, latency, useTypewriter = false) {"
new = "function appendMarginChatMessage(sender, text, latency, useTypewriter = false, llmMeta = null) {"
if old in content:
    content = content.replace(old, new)
    changes += 1
    print(f'[{changes}] Updated: appendMarginChatMessage signature')


# ============================================================
# PATTERN E: Sector Regime AI Chat reply wrapper (Line ~33109)
# ============================================================

# 24. Sector Regime AI Chat
old = """                    const replyWrapper = document.createElement('div');
                    replyWrapper.style.marginTop = '6px';"""
new = """                    const replyWrapper = document.createElement('div');
                    replyWrapper.style.marginTop = '6px';
                    // Badge will be added after typewrite"""
if old in content:
    content = content.replace(old, new, 1)
    # We need to add the badge after the typewrite for this chat
    # Find the speakBtn display and add badge after it
    old2 = """speakBtn.style.display = 'inline-block';

                    // Bind inline ticker clicks"""
    new2 = """speakBtn.style.display = 'inline-block';
                    // Add LLM execution badge
                    if (response) {
                        const metaWrap = document.createElement('div');
                        metaWrap.className = 'ai-footer-meta-wrap';
                        metaWrap.innerHTML = window.renderLLMExecutionBadgeHtml(null);
                        chatStream.appendChild(metaWrap);
                    }

                    // Bind inline ticker clicks"""
    if old2 in content:
        content = content.replace(old2, new2, 1)
        changes += 1
        print(f'[{changes}] Updated: Sector Regime AI Chat badge')


# ============================================================
# PATTERN F: Pitchbook HTML (Line ~1799)
# ============================================================
old = """contentPane.innerHTML = formattedHtml;
            }"""
new = """contentPane.innerHTML = formattedHtml + '<div class="ai-footer-meta-wrap">' + window.renderLLMExecutionBadgeHtml(data.llm_meta) + '</div>';
            }"""
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] Updated: Pitchbook content pane badge')


# ============================================================
# PATTERN G: Market News AI briefing typewriteElement (Line ~34718)
# ============================================================
old = """typewriteElement(aiSynthesis, data.ai_report.synthesis_report, () => {
                        if (aiDrivers) {"""
new = """typewriteElement(aiSynthesis, data.ai_report.synthesis_report, () => {
                        // LLM meta badge handled by #market-news-ai-llm-meta-badge container
                        if (aiDrivers) {"""
if old in content:
    content = content.replace(old, new, 1)
    print(f'  [INFO] Market News AI briefing already has dedicated badge container')


# ============================================================
# PATTERN H: Streaming endpoints (/api/ai/audit-financials) - add badge after stream completes
# ============================================================

# For streaming endpoints (44004, 46782, 46868), the response is streamed via SSE
# The backend already sends llm_meta as the first SSE event
# We need to find where the stream completes and add the badge

# 25. FS Audit streaming completion (Line ~44024 - streamTypewrite callback)
old = """streamTypewrite(auditTextEl, "", auditContainer, () => {
                        const finalHtml = auditTextEl.innerHTML;"""
new = """streamTypewrite(auditTextEl, "", auditContainer, () => {
                        auditTextEl.innerHTML += '<div class="ai-footer-meta-wrap">' + window.renderLLMExecutionBadgeHtml(null) + '</div>';
                        const finalHtml = auditTextEl.innerHTML;"""
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] Updated: FS Audit streaming completion badge')


# Write the updated content
with open('backend/static/app.js', 'w', encoding='utf-8') as f:
    f.write(content)

print(f'\n=== TOTAL CHANGES: {changes} ===')
print('Done! All missing LLM execution badges have been added.')
