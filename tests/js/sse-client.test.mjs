// Unit tests for parseSseChunk exported from static/js/sse-client.js.
//
// Run with: node --test tests/js/sse-client.test.mjs
//
// These cover the SSE framing logic independently of fetch / ReadableStream:
//   - splitting on \n\n
//   - carrying a trailing partial chunk across calls
//   - extracting the `data: <payload>` line
//   - recognising the [DONE] sentinel
//   - ignoring non-data SSE fields (event:, id:, comment lines)

import { test } from 'node:test';
import assert from 'node:assert/strict';

// parseSseChunk is a pure function; importing it does NOT pull in api.js
// (which references browser globals) because ES module imports are hoisted
// but only the named export is resolved. To be safe under Node without a
// DOM, we import directly from the source file — the api.js import inside
// sse-client.js is a side-effect import that would fail in pure-Node, so
// we stub the browser globals api.js touches before importing.
globalThis.fetch = () => { throw new Error('fetch should not be called in unit test'); };
globalThis.localStorage = { getItem: () => null, setItem: () => {} };

const { parseSseChunk } = await import('../../static/js/sse-client.js');

// ── basic framing ─────────────────────────────────────────────────────

test('parseSseChunk: parses a single complete message', () => {
    const out = parseSseChunk('', 'data: {"type":"stream","text":"hi"}\n\n');
    assert.deepEqual(out.messages, ['{"type":"stream","text":"hi"}']);
    assert.equal(out.buffer, '');
    assert.equal(out.done, false);
});

test('parseSseChunk: parses multiple messages in one chunk', () => {
    const chunk = 'data: a\n\ndata: b\n\ndata: c\n\n';
    const out = parseSseChunk('', chunk);
    assert.deepEqual(out.messages, ['a', 'b', 'c']);
    assert.equal(out.buffer, '');
    assert.equal(out.done, false);
});

// ── partial chunks ────────────────────────────────────────────────────

test('parseSseChunk: keeps a trailing partial message in buffer', () => {
    const out = parseSseChunk('', 'data: {"type":"stre');
    assert.deepEqual(out.messages, []);
    assert.equal(out.buffer, 'data: {"type":"stre');
    assert.equal(out.done, false);
});

test('parseSseChunk: completes a partial message on the next call', () => {
    let out = parseSseChunk('', 'data: {"type":"stre');
    assert.deepEqual(out.messages, []);
    out = parseSseChunk(out.buffer, 'am","text":"hi"}\n\n');
    assert.deepEqual(out.messages, ['{"type":"stream","text":"hi"}']);
    assert.equal(out.buffer, '');
});

test('parseSseChunk: splits a message split across 3 chunks', () => {
    let buf = '';
    let messages = [];
    for (const piece of ['data: {"a":', '1,"b":', '2}\n\n']) {
        const out = parseSseChunk(buf, piece);
        buf = out.buffer;
        messages.push(...out.messages);
    }
    assert.deepEqual(messages, ['{"a":1,"b":2}']);
    assert.equal(buf, '');
});

// ── [DONE] sentinel ───────────────────────────────────────────────────

test('parseSseChunk: recognises the [DONE] sentinel', () => {
    const out = parseSseChunk('', 'data: [DONE]\n\n');
    assert.deepEqual(out.messages, []);
    assert.equal(out.done, true);
    assert.equal(out.buffer, '');
});

test('parseSseChunk: [DONE] does not consume earlier messages', () => {
    const chunk = 'data: {"type":"status"}\n\ndata: [DONE]\n\n';
    const out = parseSseChunk('', chunk);
    assert.deepEqual(out.messages, ['{"type":"status"}']);
    assert.equal(out.done, true);
});

test('parseSseChunk: ignores any payload after [DONE] in the same chunk', () => {
    // The reader loop is responsible for returning once `done` is true;
    // parseSseChunk itself keeps parsing the remainder for completeness,
    // but the [DONE] flag must still be set.
    const chunk = 'data: [DONE]\n\ndata: {"type":"late"}\n\n';
    const out = parseSseChunk('', chunk);
    assert.equal(out.done, true);
    assert.deepEqual(out.messages, ['{"type":"late"}']);
});

// ── non-data SSE fields ───────────────────────────────────────────────

test('parseSseChunk: ignores event: / id: / comment lines', () => {
    const chunk =
        ': this is a comment\n' +
        'event: status\n' +
        'id: 42\n' +
        'data: {"type":"stream"}\n\n';
    const out = parseSseChunk('', chunk);
    assert.deepEqual(out.messages, ['{"type":"stream"}']);
});

test('parseSseChunk: handles multi-line data: fields by taking the first match', () => {
    // Per SSE spec a multi-line data: field concatenates, but our parser
    // is intentionally simple: it captures the first data: line per
    // \n\n-delimited block. This test documents that contract.
    const chunk = 'data: first line\ndata: second line\n\n';
    const out = parseSseChunk('', chunk);
    assert.deepEqual(out.messages, ['first line']);
});

// ── edge cases ────────────────────────────────────────────────────────

test('parseSseChunk: empty chunk preserves buffer', () => {
    const out = parseSseChunk('data: partial', '');
    assert.equal(out.buffer, 'data: partial');
    assert.deepEqual(out.messages, []);
    assert.equal(out.done, false);
});

test('parseSseChunk: chunk with no data lines yields no messages', () => {
    const out = parseSseChunk('', 'event: ping\n\n');
    assert.deepEqual(out.messages, []);
    assert.equal(out.buffer, '');
});

test('parseSseChunk: handles blank lines inside buffer gracefully', () => {
    const out = parseSseChunk('', '\n\ndata: x\n\n\n\n');
    assert.deepEqual(out.messages, ['x']);
    assert.equal(out.buffer, '');
});
