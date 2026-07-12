// Unit tests for the pure helpers exported from static/js/completion.js (P3).
//
// Run with: node --test tests/js/completion.test.mjs
//
// Covers:
//   - shouldTriggerCompletion: Tab completion trigger heuristics
//   - clampIndex: cursor index clamping
//   - wordPrefixAt: word prefix extraction at a cursor position

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    shouldTriggerCompletion,
    clampIndex,
    wordPrefixAt,
} from '../../static/js/completion.js';

// ── shouldTriggerCompletion ──────────────────────────────────────────

test('shouldTriggerCompletion: returns false for empty / falsy input', () => {
    assert.equal(shouldTriggerCompletion(''), false);
    assert.equal(shouldTriggerCompletion(null), false);
    assert.equal(shouldTriggerCompletion(undefined), false);
});

test('shouldTriggerCompletion: dot triggers completion', () => {
    assert.equal(shouldTriggerCompletion('np.'), true);
    assert.equal(shouldTriggerCompletion('obj.attr.'), true);
});

test('shouldTriggerCompletion: open paren and bracket trigger completion', () => {
    assert.equal(shouldTriggerCompletion('print('), true);
    assert.equal(shouldTriggerCompletion('lst['), true);
});

test('shouldTriggerCompletion: a trailing word of length >= 2 triggers', () => {
    assert.equal(shouldTriggerCompletion('import p'), false);  // length 1
    assert.equal(shouldTriggerCompletion('import ma'), true);  // length 2
    assert.equal(shouldTriggerCompletion('import matplotlib'), true);
});

test('shouldTriggerCompletion: single trailing word char does NOT trigger', () => {
    assert.equal(shouldTriggerCompletion('x'), false);
    assert.equal(shouldTriggerCompletion('a'), false);
});

test('shouldTriggerCompletion: whitespace and punctuation do not trigger', () => {
    assert.equal(shouldTriggerCompletion(' '), false);
    assert.equal(shouldTriggerCompletion('hello '), false);
    assert.equal(shouldTriggerCompletion('x + '), false);
    assert.equal(shouldTriggerCompletion('def '), false);
});

// ── clampIndex ────────────────────────────────────────────────────────

test('clampIndex: clamps to [0, length]', () => {
    assert.equal(clampIndex(5, 10), 5);
    assert.equal(clampIndex(0, 10), 0);
    assert.equal(clampIndex(10, 10), 10);
    assert.equal(clampIndex(15, 10), 10);
    assert.equal(clampIndex(-3, 10), 0);
});

test('clampIndex: non-numeric / NaN / Infinity values become 0', () => {
    assert.equal(clampIndex(NaN, 10), 0);
    assert.equal(clampIndex('abc', 10), 0);
    assert.equal(clampIndex(null, 10), 0);
    assert.equal(clampIndex(undefined, 10), 0);
    // Infinity is non-finite: treated as invalid, returns 0 (safe default)
    assert.equal(clampIndex(Infinity, 10), 0);
    assert.equal(clampIndex(-Infinity, 10), 0);
});

test('clampIndex: floors fractional values', () => {
    assert.equal(clampIndex(5.7, 10), 5);
    assert.equal(clampIndex(3.99, 10), 3);
    assert.equal(clampIndex(0.9, 10), 0);
});

// ── wordPrefixAt ──────────────────────────────────────────────────────

test('wordPrefixAt: returns empty string for empty code', () => {
    assert.equal(wordPrefixAt('', 0), '');
    assert.equal(wordPrefixAt(null, 0), '');
});

test('wordPrefixAt: extracts the word ending at the cursor', () => {
    assert.equal(wordPrefixAt('print(he', 8), 'he');
    assert.equal(wordPrefixAt('import mat', 10), 'mat');
    assert.equal(wordPrefixAt('matplotlib', 5), 'matpl');
});

test('wordPrefixAt: returns empty when cursor is after non-word char', () => {
    assert.equal(wordPrefixAt('print(', 6), '');
    assert.equal(wordPrefixAt('a + b', 3), '');
    assert.equal(wordPrefixAt('hello world', 6), '');
});

test('wordPrefixAt: clamps out-of-range cursor positions', () => {
    assert.equal(wordPrefixAt('hello', 100), 'hello');
    assert.equal(wordPrefixAt('hello', -5), '');
});
