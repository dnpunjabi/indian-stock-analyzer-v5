import sys

with open('backend/static/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update appendTvChatMessage
target1 = "contentDiv.innerHTML = html;\n        history.appendChild(div);"
repl1 = "contentDiv.innerHTML = html;\n        if (llmMeta) div.innerHTML += `<div class=\"ai-footer-meta-wrap\">${window.renderLLMExecutionBadgeHtml(llmMeta)}</div>`;\n        history.appendChild(div);"

if target1 in content:
    content = content.replace(target1, repl1)
    print('Updated appendTvChatMessage')

# 2. Update appendFsChatMessage
target2 = "messageDiv.appendChild(contentDiv);"
repl2 = """messageDiv.appendChild(contentDiv);
    if (sender !== 'user' && llmMeta) {
        const metaWrap = document.createElement('div');
        metaWrap.className = 'ai-footer-meta-wrap';
        metaWrap.innerHTML = window.renderLLMExecutionBadgeHtml(llmMeta);
        messageDiv.appendChild(metaWrap);
    }"""

if target2 in content:
    content = content.replace(target2, repl2, 1)
    print('Updated appendFsChatMessage')

# 3. Update appendAuditChatMessage & appendMarginChatMessage
target3 = """if (sender === 'bot') {
        contentDiv.appendChild(pTag);
    } else {
        contentDiv.innerText = text;
    }

    messageDiv.appendChild(contentDiv);"""

repl3 = """if (sender === 'bot') {
        contentDiv.appendChild(pTag);
    } else {
        contentDiv.innerText = text;
    }

    messageDiv.appendChild(contentDiv);
    if (sender !== 'user' && llmMeta) {
        const metaWrap = document.createElement('div');
        metaWrap.className = 'ai-footer-meta-wrap';
        metaWrap.innerHTML = window.renderLLMExecutionBadgeHtml(llmMeta);
        messageDiv.appendChild(metaWrap);
    }"""

if target3 in content:
    content = content.replace(target3, repl3)
    print('Updated appendAuditChatMessage and appendMarginChatMessage')

with open('backend/static/app.js', 'w', encoding='utf-8') as f:
    f.write(content)

print('Successfully finished updates in app.js!')
