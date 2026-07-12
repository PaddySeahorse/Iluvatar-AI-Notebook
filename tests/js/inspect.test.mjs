// Unit tests for the pure helpers exported from static/js/inspect.js (P3).
//
// Run with: node --test tests/js/inspect.test.mjs
//
// Covers:
//   - wordAtCursor: word extraction at a flat cursor position
//   - pickInspectMime: MIME priority for inspect data dicts
//   - renderInspectContent: MIME -> HTML rendering

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    wordAtCursor,
    pickInspectMime,
    renderInspectContent,
} from '../../static/js/inspect.js';

// ── wordAtCursor ─────────────────────────────────────────────────────

test('wordAtCursor: returns empty string for empty code', () => {
    assert.equal(wordAtCursor('', 0), '');
    assert.equal(wordAtCursor(null, 0), '');
});

test('wordAtCursor: extracts a bare word at the cursor', () => {
    assert.equal(wordAtCursor('print', 3), 'print');
    assert.equal(wordAtCursor('matplotlib', 5), 'matplotlib');
    assert.equal(wordAtCursor('hello world', 5), 'hello');
    assert.equal(wordAtCursor('hello world', 8), 'world');
});

test('wordAtCursor: includes dotted attribute access', () => {
    // cursor at end of "np.array"
    assert.equal(wordAtCursor('np.array', 8), 'np.array');
    // cursor in the middle of "np.array" — returns the full word (left + right)
    assert.equal(wordAtCursor('np.array', 5), 'np.array');
    // chained attribute access
    assert.equal(wordAtCursor('os.path.join', 12), 'os.path.join');
});

test('wordAtCursor: returns empty when cursor is between non-word chars', () => {
    assert.equal(wordAtCursor('a + b', 2), '');
    assert.equal(wordAtCursor('a + b', 3), '');
    assert.equal(wordAtCursor('()', 1), '');
});

test('wordAtCursor: clamps out-of-range cursor positions', () => {
    assert.equal(wordAtCursor('hello', 100), 'hello');
    // Negative cursor clamps to 0; word at position 0 is 'hello'
    assert.equal(wordAtCursor('hello', -5), 'hello');
});

// ── pickInspectMime ──────────────────────────────────────────────────

test('pickInspectMime: returns null for empty / falsy data', () => {
    assert.equal(pickInspectMime(null), null);
    assert.equal(pickInspectMime(undefined), null);
    assert.equal(pickInspectMime({}), null);
});

test('pickInspectMime: text/markdown wins over text/html and text/plain', () => {
    // Inspect MIME priority differs from output: markdown > html > latex > plain
    const data = { 'text/plain': 'x', 'text/html': '<p/>', 'text/markdown': '# h' };
    assert.equal(pickInspectMime(data), 'text/markdown');
});

test('pickInspectMime: text/html wins over text/plain when no markdown', () => {
    assert.equal(pickInspectMime({ 'text/plain': 'x', 'text/html': '<p/>' }), 'text/html');
});

test('pickInspectMime: text/latex wins over text/plain', () => {
    assert.equal(pickInspectMime({ 'text/plain': 'x', 'text/latex': '\\frac{1}{2}' }), 'text/latex');
});

test('pickInspectMime: text/plain is the lowest-priority fallback', () => {
    assert.equal(pickInspectMime({ 'text/plain': 'only' }), 'text/plain');
});

test('pickInspectMime: treats empty-string MIME values as absent', () => {
    assert.equal(pickInspectMime({ 'text/markdown': '', 'text/plain': 'fallback' }), 'text/plain');
    assert.equal(pickInspectMime({ 'text/html': '' }), null);
});

// ── renderInspectContent ─────────────────────────────────────────────

test('renderInspectContent: text/plain escapes HTML and wraps in pre.inspect-plain', () => {
    const out = renderInspectContent('text/plain', '<script>alert("x")</script>');
    assert.ok(out.startsWith('<pre class="inspect-plain">'));
    assert.ok(out.includes('&lt;script&gt;'));
    assert.ok(!out.includes('<script>'));
});

test('renderInspectContent: text/html is returned as-is (trusted)', () => {
    const out = renderInspectContent('text/html', '<b>bold</b>');
    assert.equal(out, '<b>bold</b>');
});

test('renderInspectContent: text/latex wraps in pre.inspect-latex', () => {
    const out = renderInspectContent('text/latex', '\\frac{1}{2}');
    assert.ok(out.startsWith('<pre class="inspect-latex">'));
    assert.ok(out.includes('\\frac{1}{2}'));
});

test('renderInspectContent: text/markdown renders headers and bold', () => {
    const out = renderInspectContent('text/markdown', '# Title\n\n**bold** text');
    assert.ok(out.includes('<h2>'), 'should render # as h2');
    assert.ok(out.includes('<strong>bold</strong>'), 'should render ** as strong');
    assert.ok(out.includes('<p>'), 'should wrap paragraphs');
});

test('renderInspectContent: text/markdown escapes raw HTML in the source', () => {
    const out = renderInspectContent('text/markdown', '<script>alert(1)</script>');
    assert.ok(!out.includes('<script>'));
    assert.ok(out.includes('&lt;script&gt;'));
});

test('renderInspectContent: text/markdown renders fenced code blocks', () => {
    const md = '```python\nprint("hi")\n```';
    const out = renderInspectContent('text/markdown', md);
    assert.ok(out.includes('<pre class="inspect-code">'), 'should render fenced code as pre.inspect-code');
    assert.ok(out.includes('print('));
});

test('renderInspectContent: null/undefined content is rendered as empty', () => {
    const out = renderInspectContent('text/plain', null);
    assert.equal(out, '<pre class="inspect-plain"></pre>');
});

test('renderInspectContent: unknown MIME falls back to text/plain rendering', () => {
    const out = renderInspectContent('application/x-unknown', 'hello');
    assert.ok(out.startsWith('<pre class="inspect-plain">'));
    assert.ok(out.includes('hello'));
});
