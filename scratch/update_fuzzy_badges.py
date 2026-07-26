import sys

with open('backend/static/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

target_comm = """        bodyEl.innerHTML = `
            <div style="display: flex; flex-direction: column; gap: 5px;">
                <div><strong style="color: #3b82f6;">📌 Overview:</strong> ${s.thesis || ''}</div>
                <div><strong style="color: #10b981;">🚀 Main Growth Driver:</strong> ${s.key_driver || ''}</div>
                <div><strong style="color: #f59e0b;">⚠️ Watchout / Risk:</strong> ${s.main_risk || ''}</div>
            </div>
        `;"""

repl_comm = """        bodyEl.innerHTML = `
            <div style="display: flex; flex-direction: column; gap: 5px;">
                <div><strong style="color: #3b82f6;">📌 Overview:</strong> ${s.thesis || ''}</div>
                <div><strong style="color: #10b981;">🚀 Main Growth Driver:</strong> ${s.key_driver || ''}</div>
                <div><strong style="color: #f59e0b;">⚠️ Watchout / Risk:</strong> ${s.main_risk || ''}</div>
                <div class="ai-footer-meta-wrap">${window.renderLLMExecutionBadgeHtml(data.llm_meta)}</div>
            </div>
        `;"""

if target_comm in content:
    content = content.replace(target_comm, repl_comm)
    print('Successfully replaced target_comm in app.js!')
else:
    print('target_comm NOT found in app.js')

with open('backend/static/app.js', 'w', encoding='utf-8') as f:
    f.write(content)

print('Finished updating app.js!')
