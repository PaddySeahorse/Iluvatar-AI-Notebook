(function () {
    function findChainlitInput() {
        const selectors = [
            'textarea[placeholder]',
            'textarea',
            '[contenteditable="true"]',
            'div[contenteditable="true"]'
        ];
        for (const sel of selectors) {
            const els = document.querySelectorAll(sel);
            for (const el of els) {
                if (el.offsetParent !== null || el.isContentEditable) {
                    const style = window.getComputedStyle(el);
                    if (style.display !== 'none' && style.visibility !== 'hidden') return el;
                }
            }
        }
        const root = document.getElementById('root');
        if (root) {
            const ta = root.querySelector('textarea');
            if (ta) return ta;
            const ce = root.querySelector('[contenteditable]');
            if (ce) return ce;
        }
        return null;
    }

    function findSendButton(input) {
        if (input) {
            const form = input.closest('form');
            if (form) {
                const btn = form.querySelector('button[type="submit"]') || form.querySelector('button');
                if (btn) return btn;
            }
            const container = input.parentElement;
            if (container) {
                const siblingBtn = container.querySelector('button');
                if (siblingBtn) return siblingBtn;
            }
        }
        const candidates = document.querySelectorAll('button');
        for (const b of candidates) {
            if (b.querySelector('svg') && b.closest('#root')) return b;
            const t = (b.getAttribute('aria-label') || '').toLowerCase();
            if (t.includes('send') || t.includes('发送')) return b;
        }
        return null;
    }

    function fillAndSend(text) {
        function attempt(retries) {
            const input = findChainlitInput();
            if (!input) {
                if (retries > 0) setTimeout(() => attempt(retries - 1), 500);
                return;
            }
            input.focus();
            try {
                if (input.tagName === 'TEXTAREA' || input.tagName === 'INPUT') {
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set
                        || Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), 'value')?.set;
                    if (setter) setter.call(input, text);
                    else input.value = text;
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                } else if (input.isContentEditable) {
                    input.textContent = text;
                    input.dispatchEvent(new InputEvent('input', { bubbles: true, data: text }));
                }
            } catch (e) {}
            setTimeout(() => {
                const btn = findSendButton(input);
                if (btn) {
                    btn.click();
                } else {
                    try {
                        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
                        input.dispatchEvent(new KeyboardEvent('keypress', { key: 'Enter', code: 'Enter', bubbles: true }));
                    } catch (e) {}
                }
            }, 120);
        }
        attempt(12);
    }

    window.addEventListener('message', (event) => {
        if (!event.data || event.data.type !== 'iluvatar:ask') return;
        const text = event.data.text;
        if (!text || typeof text !== 'string') return;
        fillAndSend(text);
    });

    const seenCodes = new Set();
    function notifyParentCreate(code, cellType, idx, ok) {
        const key = code + '|' + (cellType||'code') + '|' + (idx ?? '');
        if (seenCodes.has(key)) return;
        seenCodes.add(key);
        try { window.parent.postMessage({ type: 'iluvatar:agent_cell', source: 'create_cell', code, cell_type: cellType, index: idx, ok }, '*'); } catch(e) {}
    }
    const observer = new MutationObserver((mutations) => {
        for (const m of mutations) {
            for (const node of m.addedNodes) {
                if (!(node instanceof HTMLElement)) continue;
                const text = node.innerText || node.textContent || '';
                if (text.includes('__AGENT_CELL_CREATE__')) {
                    try {
                        const idx = text.indexOf('__AGENT_CELL_CREATE__');
                        const jsonStr = text.slice(idx + '__AGENT_CELL_CREATE__'.length).trim();
                        const obj = JSON.parse(jsonStr);
                        notifyParentCreate(obj.code || '', obj.cell_type || 'code', obj.index, obj.ok);
                    } catch(e) {}
                }
            }
        }
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
})();
