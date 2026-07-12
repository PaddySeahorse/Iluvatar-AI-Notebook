// Unit tests for KernelIndicator exported from static/js/kernel-indicator.js.
//
// Run with: node --test tests/js/kernel-indicator.test.mjs
//
// KernelIndicator talks to the DOM via document.querySelector + element
// .className / .innerText. We provide a minimal fake DOM (no jsdom) so the
// tests run under plain Node and assert on the recorded DOM mutations.
//
// The module is safe to import at top level because KernelIndicator only
// touches `document` inside its constructor — not at module-load time.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { KernelIndicator } from '../../static/js/kernel-indicator.js';

// ── minimal DOM mock ──────────────────────────────────────────────────

class FakeElement {
    constructor() {
        this.className = '';
        this.innerText = '';
        this._children = {}; // selector -> FakeElement
    }
    querySelector(selector) {
        return this._children[selector] || null;
    }
    /** test helper: register a child reachable by selector */
    _attach(selector, child) {
        this._children[selector] = child;
        return child;
    }
}

function makeKernelStatusDom() {
    const root = new FakeElement();
    const dot = root._attach('.status-dot', new FakeElement());
    const text = root._attach('.status-text', new FakeElement());
    dot.className = 'status-dot online';
    text.innerText = 'Python 3 (天数智芯 BI-150)';
    return { root, dot, text };
}

function withDocument(root) {
    const prev = globalThis.document;
    globalThis.document = {
        querySelector: (sel) => (sel === '.kernel-status' ? root : null),
    };
    return () => { globalThis.document = prev; };
}

// ── tests ─────────────────────────────────────────────────────────────

test('KernelIndicator: defaults to idle state and binds to .kernel-status', () => {
    const { root } = makeKernelStatusDom();
    const restore = withDocument(root);
    try {
        const ki = new KernelIndicator();
        assert.equal(ki.getState(), 'idle');
        assert.equal(ki.isBound(), true);
    } finally {
        restore();
    }
});

test('KernelIndicator: setState busy updates dot class but keeps text when omitted', () => {
    const { root, dot, text } = makeKernelStatusDom();
    const restore = withDocument(root);
    try {
        const ki = new KernelIndicator();
        const beforeText = text.innerText;
        ki.setState('busy'); // no text arg
        assert.equal(dot.className, 'status-dot busy');
        assert.equal(ki.getState(), 'busy');
        // text should be unchanged when no text arg is passed
        assert.equal(text.innerText, beforeText);
    } finally {
        restore();
    }
});

test('KernelIndicator: setState idle maps to the online CSS class', () => {
    const { root, dot, text } = makeKernelStatusDom();
    const restore = withDocument(root);
    try {
        const ki = new KernelIndicator();
        ki.setState('busy', '执行中');
        ki.setState('idle', 'Python 3 (天数智芯 BI-150)');
        assert.equal(dot.className, 'status-dot online');
        assert.equal(text.innerText, 'Python 3 (天数智芯 BI-150)');
        assert.equal(ki.getState(), 'idle');
    } finally {
        restore();
    }
});

test('KernelIndicator: online is treated as an alias of idle', () => {
    const { root, dot } = makeKernelStatusDom();
    const restore = withDocument(root);
    try {
        const ki = new KernelIndicator();
        ki.setState('online', 'ready');
        assert.equal(dot.className, 'status-dot online');
    } finally {
        restore();
    }
});

test('KernelIndicator: error and disconnected states map to their CSS classes', () => {
    const { root, dot } = makeKernelStatusDom();
    const restore = withDocument(root);
    try {
        const ki = new KernelIndicator();
        ki.setState('error', '执行出错');
        assert.equal(dot.className, 'status-dot error');
        ki.setState('disconnected', '内核未运行');
        assert.equal(dot.className, 'status-dot disconnected');
    } finally {
        restore();
    }
});

test('KernelIndicator: unknown state falls back to disconnected CSS', () => {
    const { root, dot } = makeKernelStatusDom();
    const restore = withDocument(root);
    try {
        const ki = new KernelIndicator();
        ki.setState('bogus-state', '???');
        assert.equal(dot.className, 'status-dot disconnected');
    } finally {
        restore();
    }
});

test('KernelIndicator: isBound() is false when DOM is missing', () => {
    const restore = withDocument(null);
    try {
        const ki = new KernelIndicator();
        assert.equal(ki.isBound(), false);
        // setState must not throw even when unbound
        ki.setState('busy', '执行中');
        assert.equal(ki.getState(), 'busy');
    } finally {
        restore();
    }
});

test('KernelIndicator: accepts a root element directly (no document lookup)', () => {
    const { root, dot, text } = makeKernelStatusDom();
    // No global document set; passing the element directly must still work.
    const ki = new KernelIndicator(root);
    assert.equal(ki.isBound(), true);
    ki.setState('busy', '执行中');
    assert.equal(dot.className, 'status-dot busy');
    assert.equal(text.innerText, '执行中');
});
