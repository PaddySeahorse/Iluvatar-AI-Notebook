// Kernel status indicator for Iluvatar AI Notebook (P2 frontend adaptation).
//
// Wraps the top-nav `.kernel-status` block (a status dot + status text) and
// exposes a small setState() API so callers (main.js) don't poke the DOM
// directly. State names follow docs/plan/frontend-adaptation-plan.md and are
// mapped onto the existing CSS classes from style.css:
//   idle         -> .status-dot.online   (kernel ready)
//   busy         -> .status-dot.busy     (executing)
//   error        -> .status-dot.error    (execution / connection error)
//   disconnected -> .status-dot.disconnected (kernel not running)
//
// `idle` is the canonical "ready" state from the design doc; `online` is kept
// as an alias used by the legacy status string in index.html so the initial
// render stays consistent without touching the markup.

const STATE_TO_CSS_CLASS = {
    idle: 'online',
    online: 'online',
    busy: 'busy',
    error: 'error',
    disconnected: 'disconnected',
};

/**
 * Kernel status indicator.
 *
 * @example
 *   const indicator = new KernelIndicator();
 *   indicator.setState('busy', '正在执行 Python 代码…');
 *   indicator.setState('idle', 'Python 3 (天数智芯 BI-150)');
 */
export class KernelIndicator {
    /**
     * @param {string|HTMLElement} [root] - selector or element for the
     *   `.kernel-status` container. Defaults to the top-nav block.
     */
    constructor(root = '.kernel-status') {
        this._root = typeof root === 'string'
            ? document.querySelector(root)
            : root;
        this._dot = this._root ? this._root.querySelector('.status-dot') : null;
        this._text = this._root ? this._root.querySelector('.status-text') : null;
        this._state = 'idle';
    }

    /**
     * Update the indicator state and label.
     *
     * @param {('idle'|'online'|'busy'|'error'|'disconnected')} state
     * @param {string} [text] - optional status text; omitted keeps the previous label.
     */
    setState(state, text) {
        this._state = state;
        const cssClass = STATE_TO_CSS_CLASS[state] || 'disconnected';
        if (this._dot) {
            this._dot.className = `status-dot ${cssClass}`;
        }
        if (this._text && typeof text === 'string') {
            this._text.innerText = text;
        }
    }

    /** @returns {string} current canonical state name */
    getState() {
        return this._state;
    }

    /** Whether the underlying DOM was found at construction time. */
    isBound() {
        return this._dot !== null;
    }
}
