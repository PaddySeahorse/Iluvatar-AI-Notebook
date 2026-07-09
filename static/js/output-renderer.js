// StreamOutputRenderer: incremental DOM renderer for SSE kernel messages.
//
// Mounts into a cell's output container and appends stdout/stderr/display
// output as messages arrive WITHOUT rebuilding the DOM — so CodeMirror
// editors elsewhere in the cell keep their state and focus.
//
// Accumulates output in the legacy cell.output shape ({stdout, stderr, html,
// plots}) so persistence (.ipynb export/import) and the saved-output renderer
// (renderCellOutput) stay backward-compatible.

const MIME_PRIORITY = [
    'image/png',
    'image/jpeg',
    'image/svg+xml',
    'text/html',
    'text/markdown',
    'text/latex',
    'application/javascript',
    'text/plain',
];

// Canonical left-to-right order of output sections inside the container.
// Sections are created lazily and inserted at the right position regardless
// of arrival order, matching the legacy renderCellOutput layout.
const SECTION_ORDER = ['html', 'stdout', 'stderr', 'plots', 'result', 'error'];

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function stripAnsi(s) {
    return s.replace(/\x1b\[[0-9;]*m/g, '');
}

// Treat \r as "replace current line": for each \n-delimited line, keep only
// the segment after the last \r. This renders tqdm progress bars (which
// refresh a single line with \r) as one updating line instead of a flood.
function renderStreamText(text) {
    return text.split('\n').map(line => {
        const idx = line.lastIndexOf('\r');
        return idx >= 0 ? line.slice(idx + 1) : line;
    }).join('\n');
}

/**
 * Incremental renderer for one cell execution's streaming output.
 *
 * Public handlers mirror SSEKernelClient callbacks:
 *   handleStream(name, text)
 *   handleDisplayData(data, metadata)
 *   handleResult(data, executionCount)
 *   handleError(ename, evalue, traceback)
 *   handleStatus(state)
 */
export class StreamOutputRenderer {
    /**
     * @param {HTMLElement} container - the .cell-output-area element to render into.
     *   The renderer clears it on construction and appends children in canonical order.
     */
    constructor(container) {
        this._container = container;
        this._container.textContent = '';
        this._sections = {};                 // name -> element (lazily created)
        this._streamBuf = { stdout: '', stderr: '' };
        this._accumulated = {
            stdout: '',
            stderr: '',
            html: '',
            plots: [],
        };
        this._executionCount = null;
        this._hasError = false;
    }

    // ---- public API (mirrors SSEKernelClient callbacks) ----

    handleStream(name, text) {
        if (name !== 'stdout' && name !== 'stderr') name = 'stdout';
        this._streamBuf[name] += text;
        this._accumulated[name] += text;
        const pre = this._getOrCreateSection(
            name,
            name === 'stderr' ? 'output-stderr' : 'output-stdout',
            'pre'
        );
        pre.textContent = renderStreamText(this._streamBuf[name]);
    }

    handleDisplayData(data, metadata = {}) {
        const mime = this._pickMime(data);
        if (!mime) return;
        const node = this._renderMime(mime, data[mime], metadata);
        this._accumulateMime(data, mime);
        if (!node) return;
        const sectionName = this._sectionForMime(mime);
        const className = sectionName === 'plots'
            ? 'output-plots-container'
            : sectionName === 'html'
                ? 'output-html'
                : 'output-display';
        const section = this._getOrCreateSection(sectionName, className, 'div');
        section.appendChild(node);
    }

    handleResult(data, executionCount) {
        if (executionCount != null) {
            this._executionCount = executionCount;
        }
        const mime = this._pickMime(data);
        if (!mime) return;
        const node = this._renderMime(mime, data[mime], {});
        this._accumulateMime(data, mime);
        if (!node) return;
        const section = this._getOrCreateSection('result', 'output-result', 'div');
        if (!section.childElementCount) {
            const label = document.createElement('span');
            label.className = 'output-result-label';
            label.textContent = `Out[${executionCount != null ? executionCount : ''}]:`;
            section.appendChild(label);
        }
        section.appendChild(node);
    }

    handleError(ename, evalue, traceback) {
        this._hasError = true;
        const section = this._getOrCreateSection('error', 'output-error-block', 'div');
        const header = document.createElement('div');
        header.className = 'output-error-header';
        header.textContent = `${ename}: ${evalue}`;
        section.appendChild(header);
        if (Array.isArray(traceback) && traceback.length) {
            const pre = document.createElement('pre');
            pre.className = 'output-error-traceback';
            pre.textContent = stripAnsi(traceback.join('\n'));
            section.appendChild(pre);
        }
    }

    handleStatus(state) {
        if (state === 'idle') {
            // Reset in-flight line buffers so a subsequent execution on the
            // same renderer starts fresh. (Callers typically create a new
            // renderer per execution, so this is defensive.)
            this._streamBuf = { stdout: '', stderr: '' };
        }
    }

    /** Returns accumulated output in the legacy cell.output shape. */
    getAccumulatedOutput() {
        return {
            stdout: this._accumulated.stdout,
            stderr: this._accumulated.stderr,
            html: this._accumulated.html,
            plots: this._accumulated.plots.slice(),
        };
    }

    getExecutionCount() {
        return this._executionCount;
    }

    hasError() {
        return this._hasError;
    }

    // ---- MIME rendering ----

    _pickMime(data) {
        if (!data) return null;
        for (const mime of MIME_PRIORITY) {
            if (data[mime]) return mime;
        }
        return null;
    }

    _sectionForMime(mime) {
        if (mime === 'image/png' || mime === 'image/jpeg' || mime === 'image/svg+xml') {
            return 'plots';
        }
        if (mime === 'text/html') {
            return 'html';
        }
        return 'display';
    }

    _renderMime(mime, content, metadata) {
        switch (mime) {
            case 'image/png':
            case 'image/jpeg':
                return this._makeImage(mime, content);
            case 'image/svg+xml':
                return this._makeHtml(content, 'output-svg');
            case 'text/html':
                return this._makeHtml(content, 'output-html');
            case 'text/markdown':
            case 'text/latex':
            case 'text/plain':
                return this._makePlainText(content);
            case 'application/javascript':
                return this._makeJavaScript(content);
            default:
                return null;
        }
    }

    _makeImage(mime, content) {
        const img = document.createElement('img');
        img.className = 'output-plot-img';
        img.src = `data:${mime};base64,${String(content).replace(/\n/g, '')}`;
        img.alt = '代码执行输出图表';
        img.loading = 'lazy';
        return img;
    }

    _makeHtml(content, className) {
        const wrap = document.createElement('div');
        wrap.className = className;
        wrap.innerHTML = content;
        return wrap;
    }

    _makePlainText(content) {
        const pre = document.createElement('pre');
        pre.className = 'output-stdout';
        pre.textContent = content;
        return pre;
    }

    _makeJavaScript(content) {
        // Execute kernel-provided JS in a try/catch. Output is side-effect
        // based (e.g. IPython display JS). No DOM node is returned.
        try {
            // eslint-disable-next-line no-new-func
            (new Function(String(content)))();
        } catch (e) {
            console.warn('display_data JavaScript execution failed:', e);
        }
        return null;
    }

    _accumulateMime(data, mime) {
        if (mime === 'image/png' && data['image/png']) {
            this._accumulated.plots.push(String(data['image/png']).replace(/\n/g, ''));
        } else if (mime === 'image/jpeg' && data['image/jpeg']) {
            this._accumulated.plots.push(String(data['image/jpeg']).replace(/\n/g, ''));
        }
        if (data['text/html']) {
            this._accumulated.html += data['text/html'];
        }
    }

    // ---- section management ----

    _getOrCreateSection(name, className, tagName) {
        if (this._sections[name]) return this._sections[name];
        const el = document.createElement(tagName);
        el.className = className;
        el.setAttribute('data-section', name);
        this._insertInOrder(el, name);
        this._sections[name] = el;
        return el;
    }

    _insertInOrder(node, name) {
        let myIdx = SECTION_ORDER.indexOf(name);
        if (myIdx === -1) myIdx = SECTION_ORDER.length;
        let refNode = null;
        for (const child of Array.from(this._container.children)) {
            const childName = child.getAttribute('data-section') || '';
            let childIdx = SECTION_ORDER.indexOf(childName);
            if (childIdx === -1) childIdx = SECTION_ORDER.length;
            if (childIdx > myIdx) {
                refNode = child;
                break;
            }
        }
        if (refNode) {
            this._container.insertBefore(node, refNode);
        } else {
            this._container.appendChild(node);
        }
    }
}

// Exported for unit tests and for callers that want to verify stream-text
// rendering of \r-style progress output without a DOM.
export { renderStreamText, escapeHtml, stripAnsi };
