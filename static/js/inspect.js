// InspectManager: ? / ?? documentation viewer for CodeMirror — P3.
//
// Triggered by Shift+Tab on the word at the cursor. Calls /api/inspect and
// shows a floating panel with the object's docstring / source, rendered from
// the highest-priority MIME type in the inspect reply's `data` dict.
//
// Pure helpers (wordAtCursor, pickInspectMime, renderInspectContent) are
// exported so they can be unit-tested without a DOM or CodeMirror instance.

/**
 * Extract the word at the given flat cursor position in `code`.
 * Includes a leading dotted prefix (e.g. "np.array" -> "np.array") so
 * inspect works on attribute accesses, not just bare names.
 *
 * @param {string} code
 * @param {number} cursorPos
 * @returns {string}
 */
export function wordAtCursor(code, cursorPos) {
    if (!code) return '';
    const pos = (typeof cursorPos === 'number' && cursorPos >= 0)
        ? Math.min(cursorPos, code.length)
        : 0;
    const before = code.substring(0, pos);
    const after = code.substring(pos);
    // Left side: word chars and dots (for obj.attr.attr)
    const leftMatch = before.match(/([\w.]+)$/);
    const rightMatch = after.match(/^([\w]*)/);
    const left = leftMatch ? leftMatch[1] : '';
    const right = rightMatch ? rightMatch[1] : '';
    return (left + right).replace(/^[.]+/, '');
}

// MIME priority for inspect replies. Differs slightly from the output
// renderer: inspect docstrings are most useful as plain text or markdown,
// so text/markdown outranks text/html here (Jupyter convention).
const INSPECT_MIME_PRIORITY = [
    'text/markdown',
    'text/html',
    'text/latex',
    'text/plain',
];

/**
 * Pick the highest-priority MIME type present in an inspect `data` dict.
 * @param {object} data
 * @returns {string|null}
 */
export function pickInspectMime(data) {
    if (!data) return null;
    for (const mime of INSPECT_MIME_PRIORITY) {
        if (data[mime]) return mime;
    }
    return null;
}

/**
 * Render inspect content to an HTML string based on MIME type.
 * Escapes all input except for text/html (which is trusted, mirroring the
 * output renderer's behaviour for display_data).
 *
 * @param {string} mime
 * @param {string} content
 * @returns {string}
 */
export function renderInspectContent(mime, content) {
    const text = String(content == null ? '' : content);
    switch (mime) {
        case 'text/html':
            return text; // trusted, like display_data
        case 'text/markdown':
            return _renderMarkdown(text);
        case 'text/latex':
            return `<pre class="inspect-latex">${_escapeHtml(text)}</pre>`;
        case 'text/plain':
        default:
            return `<pre class="inspect-plain">${_escapeHtml(text)}</pre>`;
    }
}

// ---- minimal markdown renderer (inline subset, no external deps) ----
function _renderMarkdown(text) {
    // Escape first so injected markdown text can't introduce HTML.
    let html = _escapeHtml(text);
    // Fenced code blocks
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, _lang, code) =>
        `<pre class="inspect-code">${code}</pre>`);
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Headers
    html = html.replace(/^### (.*)$/gim, '<h4>$1</h4>');
    html = html.replace(/^## (.*)$/gim, '<h3>$1</h3>');
    html = html.replace(/^# (.*)$/gim, '<h2>$1</h2>');
    // Bold & italic
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    // Paragraph breaks
    html = html.split(/\n{2,}/).map(block => {
        if (/^<(h\d|pre|ul|ol|blockquote)/.test(block.trim())) return block;
        return `<p>${block.replace(/\n/g, '<br>')}</p>`;
    }).join('\n');
    return html;
}

function _escapeHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * Inspect documentation panel manager. One instance is shared across all
 * editors (the panel is a singleton anchored to the bottom-right).
 *
 * @example
 *   const mgr = new InspectManager({ onInspect: inspectOnBackend });
 *   // In CodeMirror extraKeys:
 *   "Shift-Tab": () => mgr.handleInspect(cm);
 */
export class InspectManager {
    /**
     * @param {object} [options]
     * @param {function} [options.onInspect] - async (code, cursorPos, detailLevel) => {found, data, metadata}
     */
    constructor(options = {}) {
        this._onInspect = options.onInspect || null;
        this._panel = null;
        this._createPanel();
    }

    /**
     * Shift+Tab handler. Inspects the word at the editor's cursor.
     * @param {object} editor - CodeMirror instance
     */
    async handleInspect(editor) {
        const cm = editor;
        const code = cm.getValue();
        const cursorPos = cm.indexFromPos(cm.getCursor());
        const word = wordAtCursor(code, cursorPos);
        if (!word) return;

        // Default detail level 0 (?). The kernel's IPython inspector returns
        // the docstring for level 0 and source for level 1 (??). We don't have
        // a ?? trigger yet (no double-Shift+Tab), so level 0 is the default.
        const detailLevel = 0;

        if (!this._onInspect) {
            this._showNotFound(word);
            return;
        }
        try {
            const data = await this._onInspect(code, cursorPos, detailLevel);
            if (data && data.found) {
                this._show(data.data || {}, word);
            } else {
                this._showNotFound(word);
            }
        } catch (e) {
            console.warn('Inspect request failed:', e);
            this._showError(word, e.message || String(e));
        }
    }

    /** Hide the panel. */
    hide() {
        if (this._panel) this._panel.style.display = 'none';
    }

    /** Whether the panel is visible. */
    isOpen() {
        return this._panel !== null && this._panel.style.display !== 'none';
    }

    // ---- internal ----

    _show(data, word) {
        const mime = pickInspectMime(data);
        if (!mime) {
            this._showNotFound(word);
            return;
        }
        const body = renderInspectContent(mime, data[mime]);
        this._render(word, body, mime);
    }

    _showNotFound(word) {
        const body = `<p class="inspect-empty">未找到 <code>${_escapeHtml(word)}</code> 的文档。</p>`;
        this._render(word, body, 'text/plain');
    }

    _showError(word, message) {
        const body = `<p class="inspect-error">内省 <code>${_escapeHtml(word)}</code> 失败: ${_escapeHtml(message)}</p>`;
        this._render(word, body, 'text/plain');
    }

    _render(word, bodyHtml, mime) {
        this._panel.innerHTML = `
            <div class="inspect-header">
                <span class="inspect-title"><i class="fa-solid fa-circle-info" aria-hidden="true"></i> 文档: <code>${_escapeHtml(word)}</code></span>
                <button class="inspect-close" aria-label="关闭">&times;</button>
            </div>
            <div class="inspect-body" data-mime="${_escapeHtml(mime)}">${bodyHtml}</div>
        `;
        this._panel.style.display = 'block';
        const closeBtn = this._panel.querySelector('.inspect-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.hide());
        }
    }

    _createPanel() {
        const panel = document.createElement('div');
        panel.className = 'inspect-panel';
        panel.style.display = 'none';
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-label', '对象文档');
        document.body.appendChild(panel);
        this._panel = panel;

        // Close on Escape anywhere when the panel is open.
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen()) {
                this.hide();
            }
        });
    }
}
