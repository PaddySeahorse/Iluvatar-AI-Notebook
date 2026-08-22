// Unit tests for the ReAct agent SSE event parsing exported from
// static/js/api.js (parseAgentEventLine) plus a driver-level test of
// callAgentStream that feeds it a mocked fetch stream.
//
// Run with: node --test tests/js/agent-stream.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';

// api.js reads localStorage (initConfig) and calls fetch (never invoked for
// parseAgentEventLine). Stub the browser globals api.js touches before import.
globalThis.localStorage = {
    getItem: () => null,
    setItem: () => {},
};
globalThis.fetch = () => { throw new Error('fetch should not be called'); };

const { parseAgentEventLine, callAgentStream } = await import('../../static/js/api.js');

// ── parseAgentEventLine ───────────────────────────────────────────────

test('parseAgentEventLine: parses a data JSON line', () => {
    const evt = parseAgentEventLine('data: {"type":"tool_call","name":"run_cell"}');
    assert.deepEqual(evt, { type: 'tool_call', name: 'run_cell' });
});

test('parseAgentEventLine: ignores [DONE] sentinel', () => {
    assert.equal(parseAgentEventLine('data: [DONE]'), null);
});

test('parseAgentEventLine: ignores non-data lines', () => {
    assert.equal(parseAgentEventLine('event: foo'), null);
    assert.equal(parseAgentEventLine(': comment'), null);
});

test('parseAgentEventLine: ignores malformed JSON', () => {
    assert.equal(parseAgentEventLine('data: {not json'), null);
});

test('parseAgentEventLine: handles empty/blank input', () => {
    assert.equal(parseAgentEventLine(''), null);
    assert.equal(parseAgentEventLine('   '), null);
    assert.equal(parseAgentEventLine(null), null);
});

// ── callAgentStream ───────────────────────────────────────────────────

function streamFromEvents(events) {
    const payload = events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('') + 'data: [DONE]\n\n';
    const encoder = new TextEncoder();
    const bytes = encoder.encode(payload);
    return {
        body: {
            getReader() {
                let i = 0;
                return {
                    read() {
                        if (i < bytes.length) {
                            const chunk = bytes.subarray(i, i + 20);
                            i += 20;
                            return Promise.resolve({ value: chunk, done: false });
                        }
                        return Promise.resolve({ value: undefined, done: true });
                    },
                    cancel() {},
                };
            }
        }
    };
}

test('callAgentStream: replays agent events in order via handlers', async () => {
    const events = [
        { type: 'status', stage: 'thinking' },
        { type: 'tool_call', name: 'run_cell', label: '执行代码单元', arguments: { code: 'print(1)' } },
        { type: 'tool_result', name: 'run_cell', ok: true, summary: '42' },
        { type: 'content', text: '结果' },
        { type: 'content', text: '是42' },
        { type: 'done', final: '结果是42' },
    ];
    globalThis.fetch = async (url, opts) => {
        assert.equal(url, '/api/agent_call');
        assert.deepEqual(JSON.parse(opts.body).query, '帮我看看');
        return { ok: true, body: streamFromEvents(events).body };
    };

    const seen = [];
    const final = await callAgentStream(
        { query: '帮我看看', messages: [], includeContext: true, maxSteps: 6 },
        {
            onToolCall: (e) => seen.push(['call', e.name]),
            onToolResult: (e) => seen.push(['result', e.name, e.ok]),
        }
    );

    assert.deepEqual(seen, [['call', 'run_cell'], ['result', 'run_cell', true]]);
    assert.equal(final, '结果是42');
    globalThis.fetch = () => { throw new Error('fetch should not be called'); };
});

test('callAgentStream: throws on non-ok HTTP response with backend error message', async () => {
    globalThis.fetch = async () => ({
        ok: false,
        status: 500,
        json: async () => ({ message: '代理执行失败' }),
    });
    await assert.rejects(
        callAgentStream({ query: 'hi' }, {}),
        /代理执行失败/
    );
    globalThis.fetch = () => { throw new Error('fetch should not be called'); };
});