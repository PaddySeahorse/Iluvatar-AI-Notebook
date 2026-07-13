// CompletionManager: Tab-triggered code completion popup for CodeMirror — P3.
//
// Wraps a CodeMirror editor instance. On Tab, requests completions from the
// kernel via /api/complete and shows a popup with keyboard navigation
// (Up/Down/Enter/Esc). If no completion trigger is present or no matches are
// returned, Tab falls through to the default indent behaviour (insert spaces)
// by returning CodeMirror.Pass from the key handler.
//
// Pure helpers (shouldTriggerCompletion, clampIndex, wordPrefixAt) are
// exported so they can be unit-tested without a DOM or CodeMirror instance.

// CodeMirror is loaded as a UMD global via <script> in index.html. Accessed
// lazily so the pure helpers below stay importable in a DOM-less test env.
function _cmPass() {
    const CM = (typeof window !== 'undefined') ? window.CodeMirror : null;
    return (CM && CM.Pass) ? CM.Pass : '__cm_pass__';
}

/**
 * Decide whether the text immediately before the cursor is a viable
 * completion trigger. Mirrors the heuristics in
 * docs/plan/frontend-adaptation-plan.md §3.1:
 *   - trigger characters: '.', '(', '['
 *   - otherwise, a trailing word of length >= 2
 *
 * @param {string} textBeforeCursor
 * @returns {boolean}
 */
export function shouldTriggerCompletion(textBeforeCursor) {
    if (!textBeforeCursor) return false;
    const lastChar = textBeforeCursor.slice(-1);
    if (lastChar === '.' || lastChar === '(' || lastChar === '[') return true;
    const lastWord = textBeforeCursor.match(/(\w+)$/);
    return !!(lastWord && lastWord[1].length >= 2);
}

/**
 * Clamp a cursor index into [0, length]. Non-numeric / NaN values become 0.
 * @param {number} index
 * @param {number} length
 * @returns {number}
 */
export function clampIndex(index, length) {
    if (typeof index !== 'number' || !isFinite(index) || index < 0) return 0;
    if (index > length) return length;
    return Math.floor(index);
}

/**
 * Extract the word prefix at the given cursor position in `code`.
 * Returns the substring of `code` from the start of the current word up to
 * `cursorPos`. Used to filter matches client-side when the kernel's
 * cursor_start is unavailable.
 *
 * @param {string} code
 * @param {number} cursorPos
 * @returns {string}
 */
export function wordPrefixAt(code, cursorPos) {
    if (!code) return '';
    const pos = clampIndex(cursorPos, code.length);
    const before = code.substring(0, pos);
    const m = before.match(/(\w+)$/);
    return m ? m[1] : '';
}

/**
 * Code completion popup manager bound to one CodeMirror editor.
 *
 * @example
 *   const cm = CodeMirror(...);
 *   const mgr = new CompletionManager(cm, { onComplete: completeOnBackend });
 *   // Wire into extraKeys:
 *   extraKeys: {
 *     "Tab":       () => mgr.handleTab(),
 *     "Shift-Tab": () => inspectMgr.handleInspect(cm),
 *     "Up":        () => mgr.handleUp(),
 *     "Down":      () => mgr.handleDown(),
 *     "Enter":     () => mgr.handleEnter(),
 *     "Esc":       () => mgr.handleEsc(),
 *   }
 */
export class CompletionManager {
    /**
     * @param {object} editor - CodeMirror editor instance.
     * @param {object} [options]
     * @param {function} [options.onComplete] - async (code, cursorPos) => {matches, cursor_start, cursor_end}
     */
    constructor(editor, options = {}) {
        this.editor = editor;
        this._onComplete = options.onComplete || null;
        this._box = null;
        this._items = [];
        this._selectedIndex = -1;
        this._cursorStart = 0;
        this._cursorEnd = 0;
        this._inFlight = false;
        this._createBox();
        this._attachEditorListeners();
    }

    /** Whether the popup is currently visible. */
    isOpen() {
        return this._box !== null && this._box.style.display !== 'none';
    }

    /**
     * Tab handler. Returns CodeMirror.Pass to fall through to the default
     * indent (insert spaces) when completion is not applicable.
     */
    handleTab() {
        // If a popup is already open, Tab applies the selected completion.
        if (this.isOpen() && this._selectedIndex >= 0) {
            this._applySelected();
            return;
        }

        const cm = this.editor;
        const code = cm.getValue();
        const cursorPos = cm.indexFromPos(cm.getCursor());
        const textBeforeCursor = code.substring(0, cursorPos);

        if (!shouldTriggerCompletion(textBeforeCursor)) {
            return _cmPass(); // fall through to default indent
        }

        // Fire async request; don't fall through (Tab is "handled" while we wait).
        this._fetchAndShow(code, cursorPos);
    }

    /** Up arrow: move selection up when popup is open. */
    handleUp() {
        if (!this.isOpen()) return _cmPass();
        this._moveSelection(-1);
    }

    /** Down arrow: move selection down when popup is open. */
    handleDown() {
        if (!this.isOpen()) return _cmPass();
        this._moveSelection(1);
    }

    /** Enter: apply the selected completion when popup is open. */
    handleEnter() {
        if (!this.isOpen()) return _cmPass();
        this._applySelected();
    }

    /** Escape: close the popup when open. */
    handleEsc() {
        if (!this.isOpen()) return _cmPass();
        this.hide();
    }

    /** Hide and clear the popup. */
    hide() {
        if (this._box) {
            this._box.style.display = 'none';
            this._box.innerHTML = '';
        }
        this._items = [];
        this._selectedIndex = -1;
    }

    // ---- internal ----

    async _fetchAndShow(code, cursorPos) {
        if (this._inFlight) return;
        if (!this._onComplete) {
            this._insertIndent();
            return;
        }
        this._inFlight = true;
        try {
            const data = await this._onComplete(code, cursorPos);
            const matches = (data && Array.isArray(data.matches)) ? data.matches : [];
            if (matches.length > 0) {
                this._show(
                    matches,
                    clampIndex(data.cursor_start, code.length),
                    clampIndex(data.cursor_end, code.length)
                );
            } else {
                // No matches: fall back to indent so Tab isn't a no-op.
                this._insertIndent();
            }
        } catch (e) {
            console.warn('Completion request failed:', e);
            this._insertIndent();
        } finally {
            this._inFlight = false;
        }
    }

    _show(matches, cursorStart, cursorEnd) {
        this._items = matches.slice(0, 50); // cap popup size
        this._cursorStart = cursorStart;
        this._cursorEnd = cursorEnd;
        this._selectedIndex = 0;

        this._box.innerHTML = '';
        this._items.forEach((match, index) => {
            const item = document.createElement('div');
            item.className = 'completion-item';
            item.textContent = match;
            item.setAttribute('role', 'option');
            item.addEventListener('mousedown', (e) => {
                e.preventDefault(); // keep editor focus
                this._selectedIndex = index;
                this._applySelected();
            });
            item.addEventListener('mouseenter', () => {
                this._setSelectedIndex(index);
            });
            this._box.appendChild(item);
        });

        this._positionBox();
        this._box.style.display = 'block';
        this._highlightSelected();
    }

    _positionBox() {
        const cm = this.editor;
        const cursor = cm.getCursor();
        const coords = cm.cursorCoords(cursor, 'page');
        // Position below the cursor line; if not enough room, the CSS
        // (max-height + overflow) handles the overflow.
        this._box.style.left = `${Math.round(coords.left)}px`;
        this._box.style.top = `${Math.round(coords.bottom + 2)}px`;
    }

    _moveSelection(delta) {
        if (this._items.length === 0) return;
        let idx = this._selectedIndex + delta;
        if (idx < 0) idx = this._items.length - 1;
        if (idx >= this._items.length) idx = 0;
        this._setSelectedIndex(idx);
    }

    _setSelectedIndex(index) {
        this._selectedIndex = index;
        this._highlightSelected();
    }

    _highlightSelected() {
        const items = this._box.querySelectorAll('.completion-item');
        items.forEach((el, i) => {
            el.classList.toggle('selected', i === this._selectedIndex);
        });
        // Scroll the selected item into view within the popup.
        const sel = items[this._selectedIndex];
        if (sel && sel.scrollIntoView) {
            sel.scrollIntoView({ block: 'nearest' });
        }
    }

    _applySelected() {
        const idx = this._selectedIndex;
        if (idx < 0 || idx >= this._items.length) {
            this.hide();
            return;
        }
        const match = this._items[idx];
        const cm = this.editor;
        try {
            const from = cm.posFromIndex(this._cursorStart);
            const to = cm.posFromIndex(this._cursorEnd);
            cm.replaceRange(match, from, to);
        } catch (e) {
            // Defensive: if cursor indices are stale (editor changed), bail.
            console.warn('Completion apply failed:', e);
        }
        this.hide();
        cm.focus();
    }

    _insertIndent() {
        const cm = this.editor;
        const indentUnit = cm.getOption('indentUnit') || 4;
        const spaces = new Array(indentUnit + 1).join(' ');
        cm.replaceSelection(spaces);
    }

    _attachEditorListeners() {
        // Close the popup when the editor content changes, so stale popups
        // don't linger after the user navigates away. Called after the editor
        // is bound (may be deferred if the manager was created before the
        // CodeMirror instance — see renderer.js renderCodeEditor).
        const cm = this.editor;
        if (!cm || !cm.on) return;
        cm.on('change', () => {
            if (this.isOpen()) this.hide();
        });
        cm.on('blur', () => {
            // Small delay so a mousedown on a popup item can fire first.
            setTimeout(() => {
                if (this.isOpen()) this.hide();
            }, 150);
        });
    }

    /** Bind (or rebind) the CodeMirror editor instance and attach listeners. */
    bindEditor(editor) {
        this.editor = editor;
        this._attachEditorListeners();
    }

    _createBox() {
        const box = document.createElement('div');
        box.className = 'completion-box';
        box.style.display = 'none';
        box.setAttribute('role', 'listbox');
        document.body.appendChild(box);
        this._box = box;

        // Click-outside to close.
        document.addEventListener('click', (e) => {
            if (this.isOpen() && !this._box.contains(e.target)) {
                this.hide();
            }
        });
    }
}
