// Unit tests for the pure helpers exported from static/js/output-renderer.js.
//
// Run with: node --test tests/js/output-renderer.test.mjs
//
// These cover the P2 streaming-renderer contract:
//   - renderStreamText: \r-style progress-bar (tqdm) collapsing
//   - escapeHtml / stripAnsi: defensive string sanitisation
//   - pickMime: Jupyter MIME-type priority ordering

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    renderStreamText,
    escapeHtml,
    stripAnsi,
    pickMime,
} from '../../static/js/output-renderer.js';

// ── renderStreamText ──────────────────────────────────────────────────

test('renderStreamText: returns plain text unchanged when no \\r', () => {
    assert.equal(renderStreamText('hello\nworld'), 'hello\nworld');
    assert.equal(renderStreamText(''), '');
    assert.equal(renderStreamText('no newline'), 'no newline');
});

test('renderStreamText: \\r collapses current line, keeping only the tail', () => {
    // tqdm-style: each \r refresh overwrites the current line content.
    const out = renderStreamText('progress=0\rprogress=1\rprogress=2\n');
    assert.equal(out, 'progress=2\n');
});

test('renderStreamText: \\r only affects the line it is on, other lines stay intact', () => {
    const input = 'line1\nfoo\rbar\nline3';
    const out = renderStreamText(input);
    assert.equal(out, 'line1\nbar\nline3');
});

test('renderStreamText: multiple \\r on the same line keep the last segment', () => {
    assert.equal(renderStreamText('a\rb\rc\rd'), 'd');
    assert.equal(renderStreamText('a\rb\rc\rd\n'), 'd\n');
});

test('renderStreamText: trailing \\r with no content after it yields empty line', () => {
    assert.equal(renderStreamText('abc\r'), '');
    assert.equal(renderStreamText('abc\r\n'), '\n');
});

// ── escapeHtml ────────────────────────────────────────────────────────

test('escapeHtml: escapes the five HTML-significant characters', () => {
    assert.equal(escapeHtml('<script>alert("x")</script>'),
        '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;');
    assert.equal(escapeHtml(`a & b 'c'`), 'a &amp; b &#39;c&#39;');
});

test('escapeHtml: leaves safe text untouched', () => {
    assert.equal(escapeHtml('hello world 123'), 'hello world 123');
    assert.equal(escapeHtml(''), '');
});

test('escapeHtml: coerces non-string input to string first', () => {
    assert.equal(escapeHtml(42), '42');
    assert.equal(escapeHtml(null), 'null');
    assert.equal(escapeHtml(undefined), 'undefined');
});

// ── stripAnsi ─────────────────────────────────────────────────────────

test('stripAnsi: removes SGR colour/style escape sequences', () => {
    assert.equal(stripAnsi('\x1b[31mred\x1b[0m text'), 'red text');
    assert.equal(stripAnsi('\x1b[1;32mbold green\x1b[0m'), 'bold green');
});

test('stripAnsi: leaves plain text untouched', () => {
    assert.equal(stripAnsi('no escapes here'), 'no escapes here');
    assert.equal(stripAnsi(''), '');
});

test('stripAnsi: handles traceback-style multi-segment ANSI', () => {
    const tb = '\x1b[0;36mFile\x1b[0m "\x1b[0;32mfoo.py\x1b[0m", line 1\n';
    assert.equal(stripAnsi(tb), 'File "foo.py", line 1\n');
});

// ── pickMime ──────────────────────────────────────────────────────────

test('pickMime: returns null for empty / falsy data', () => {
    assert.equal(pickMime(null), null);
    assert.equal(pickMime(undefined), null);
    assert.equal(pickMime({}), null);
});

test('pickMime: image/png wins over text/html and text/plain', () => {
    const data = { 'text/plain': 'x', 'text/html': '<p/>', 'image/png': 'base64...' };
    assert.equal(pickMime(data), 'image/png');
});

test('pickMime: text/html wins over text/plain when no image present', () => {
    const data = { 'text/plain': 'x', 'text/html': '<p/>' };
    assert.equal(pickMime(data), 'text/html');
});

test('pickMime: image/jpeg beats text/html but loses to image/png', () => {
    assert.equal(pickMime({ 'image/jpeg': 'j', 'text/html': 'h' }), 'image/jpeg');
    assert.equal(pickMime({ 'image/png': 'p', 'image/jpeg': 'j' }), 'image/png');
});

test('pickMime: text/plain is the lowest-priority fallback', () => {
    assert.equal(pickMime({ 'text/plain': 'only' }), 'text/plain');
});

test('pickMime: treats empty-string MIME values as absent', () => {
    // Jupyter payloads sometimes include empty strings for unavailable
    // representations; pickMime must skip them, not return them.
    assert.equal(pickMime({ 'image/png': '', 'text/plain': 'fallback' }), 'text/plain');
    assert.equal(pickMime({ 'text/html': '' }), null);
});

test('pickMime: ignores unknown MIME types', () => {
    assert.equal(pickMime({ 'application/vnd.custom+json': '{}' }), null);
});

test('pickMime: image/svg+xml ranks between image/jpeg and text/html', () => {
    const data = { 'text/html': '<p/>', 'image/svg+xml': '<svg/>' };
    assert.equal(pickMime(data), 'image/svg+xml');
    const data2 = { 'image/jpeg': 'j', 'image/svg+xml': 's' };
    assert.equal(pickMime(data2), 'image/jpeg');
});
