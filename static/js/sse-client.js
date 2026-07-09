// SSE streaming kernel client for Iluvatar AI Notebook (P2 frontend adaptation).
//
// Wraps fetch + ReadableStream to the /api/run_cell_stream SSE endpoint,
// parses Jupyter-style messages, and dispatches them to callbacks for
// incremental rendering. Supports abort (interrupt). Falls back to the
// legacy blocking /api/run_cell endpoint when the SSE connection fails
// before any output is received, so the renderer code stays uniform.

import { runCellOnBackend, interruptKernelOnBackend } from './api.js';

const STREAM_ENDPOINT = '/api/run_cell_stream';

/**
 * SSE kernel execution client.
 *
 * Callbacks (all optional):
 *   onStream(name, text)                 - stdout/stderr chunk
 *   onDisplayData(data, metadata)        - rich MIME display
 *   onResult(data, executionCount)       - Out[N] execute_result
 *   onError(ename, evalue, traceback[])  - error
 *   onStatus(state)                      - 'busy' | 'idle'
 *   onDone()                             - stream finished (called once)
 *
 * Usage:
 *   const client = new SSEKernelClient();
 *   await client.executeStream(code, callbacks);
 *   // later, to interrupt:
 *   client.abort();
 */
export class SSEKernelClient {
    constructor() {
        this._abortController = null;
        this._aborted = false;
        this._receivedAny = false;
        this._done = false;
    }

    /**
     * Stream-execute code, dispatching messages to callbacks. Resolves when
     * the stream ends ([DONE], idle, abort, or fallback completion).
     */
    async executeStream(code, callbacks = {}) {
        this._aborted = false;
        this._receivedAny = false;
        this._done = false;
        this._abortController = new AbortController();

        try {
            const resp = await fetch(STREAM_ENDPOINT, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code }),
                signal: this._abortController.signal,
            });

            if (!resp.ok || !resp.body) {
                // Server error / non-SSE response before any output:
                // fall back to the legacy blocking endpoint.
                if (!this._aborted) await this._executeLegacy(code, callbacks);
                return;
            }

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                // SSE messages are separated by a blank line (\n\n).
                const parts = buffer.split('\n\n');
                buffer = parts.pop(); // keep trailing partial chunk

                for (const part of parts) {
                    const match = part.match(/^data: (.+)$/m);
                    if (!match) continue;

                    const data = match[1];
                    if (data === '[DONE]') {
                        this._finish(callbacks);
                        return;
                    }
                    try {
                        this._dispatch(JSON.parse(data), callbacks);
                    } catch (e) {
                        console.warn('Failed to parse SSE message:', data, e);
                    }
                }
            }
            // Stream closed without the [DONE] sentinel; treat as finished.
            this._finish(callbacks);
        } catch (err) {
            if (err && err.name === 'AbortError') {
                // User-initiated interrupt: emit idle + done.
                if (callbacks.onStatus) callbacks.onStatus('idle');
                this._finish(callbacks);
                return;
            }
            // Network error before any output was received: fall back to
            // the legacy API so a transient SSE hiccup doesn't break execution.
            if (!this._receivedAny && !this._aborted) {
                await this._executeLegacy(code, callbacks);
                return;
            }
            // Mid-stream error after output already started: report and finish.
            if (callbacks.onError) {
                callbacks.onError('ConnectionError', (err && err.message) || 'Stream error', []);
            }
            this._finish(callbacks);
        } finally {
            this._abortController = null;
        }
    }

    _dispatch(msg, callbacks) {
        this._receivedAny = true;
        switch (msg.type) {
            case 'stream':
                if (callbacks.onStream) callbacks.onStream(msg.name, msg.text);
                break;
            case 'display_data':
                if (callbacks.onDisplayData) callbacks.onDisplayData(msg.data || {}, msg.metadata || {});
                break;
            case 'execute_result':
                if (callbacks.onResult) callbacks.onResult(msg.data || {}, msg.execution_count);
                break;
            case 'error':
                if (callbacks.onError) callbacks.onError(msg.ename, msg.evalue, msg.traceback || []);
                break;
            case 'status':
                if (callbacks.onStatus) callbacks.onStatus(msg.execution_state);
                break;
        }
    }

    _finish(callbacks) {
        if (this._done) return;
        this._done = true;
        if (callbacks.onDone) callbacks.onDone();
    }

    /**
     * Abort the current stream and send an interrupt to the kernel.
     *
     * Aborting the fetch stops reading the SSE stream client-side; the
     * backend interrupt is still required because the kernel keeps running
     * (the control channel works even when the shell channel is blocked by
     * GPU compute).
     */
    abort() {
        this._aborted = true;
        if (this._abortController) {
            this._abortController.abort();
        }
        interruptKernelOnBackend().catch(() => {});
    }

    /**
     * Legacy fallback: call /api/run_cell and map its single blocking
     * response into the streaming callback sequence so the renderer code
     * stays uniform. Reports errors via onError and never throws.
     */
    async _executeLegacy(code, callbacks = {}) {
        const { onStream, onDisplayData, onError, onStatus } = callbacks;
        if (onStatus) onStatus('busy');

        let data = null;
        try {
            data = await runCellOnBackend(code);
        } catch (err) {
            if (onError) onError('ConnectionError', (err && err.message) || 'Request failed', []);
            if (onStatus) onStatus('error');
            this._finish(callbacks);
            return;
        }

        if (this._aborted) {
            // Interrupted while waiting for the legacy response.
            if (onStatus) onStatus('idle');
            this._finish(callbacks);
            return;
        }

        if (data.stdout) { onStream && onStream('stdout', data.stdout); }
        if (data.stderr) { onStream && onStream('stderr', data.stderr); }
        if (data.html && data.html.trim()) {
            onDisplayData && onDisplayData({ 'text/html': data.html });
        }
        if (Array.isArray(data.plots)) {
            data.plots.forEach(p => onDisplayData && onDisplayData({ 'image/png': p }));
        }
        if (!data.success) {
            onError && onError('Error', data.stderr || 'Execution failed', []);
        }
        if (onStatus) onStatus('idle');
        this._finish(callbacks);
    }
}
