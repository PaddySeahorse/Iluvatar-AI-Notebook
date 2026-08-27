// 在 Chainlit 页面（/agent）左侧注入 Notebook iframe（加载 /?embed=1），
// 与右侧聊天区域形成左右分栏。embed=1 会让 Notebook 隐藏其自身的 AI 侧边栏，
// 避免与 Chainlit 对话能力重复。
(function () {
    function mountNotebookPanel() {
        if (document.getElementById('notebook-panel')) {
            return;
        }
        if (!document.body) {
            return;
        }
        const panel = document.createElement('div');
        panel.id = 'notebook-panel';
        panel.setAttribute('aria-label', 'Iluvatar Notebook');

        const iframe = document.createElement('iframe');
        iframe.src = '/?embed=1';
        iframe.setAttribute('frameborder', '0');
        iframe.setAttribute('title', 'Iluvatar AI Notebook');
        iframe.setAttribute('allow', 'clipboard-write');

        panel.appendChild(iframe);
        document.body.insertBefore(panel, document.body.firstChild);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mountNotebookPanel);
    } else {
        mountNotebookPanel();
    }
})();