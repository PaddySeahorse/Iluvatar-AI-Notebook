// Unit tests for saveApiConfig from static/js/api.js (API config persistence).
//
// Verifies that saving the config updates localStorage and, when the backend
// is reachable, persists it to the project .env via POST /api/save_config.
//
// Run with: node --test tests/js/api-config.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';

const saved = {};
globalThis.localStorage = {
    getItem: (k) => (k in saved ? saved[k] : null),
    setItem: (k, v) => { saved[k] = v; },
};

let fetchCalls = [];
let nextFetchResult = { ok: true };
globalThis.fetch = async (url, opts) => {
    fetchCalls.push({ url, opts });
    return nextFetchResult;
};

const { saveApiConfig, apiConfig } = await import('../../static/js/api.js');

test('saveApiConfig updates config + localStorage and calls /api/save_config', async () => {
    fetchCalls = [];
    const ok = await saveApiConfig('https://x/v1/chat/completions', 'tok', 'm1');

    assert.equal(ok, true);
    assert.equal(apiConfig.url, 'https://x/v1/chat/completions');
    assert.equal(apiConfig.token, 'tok');
    assert.equal(apiConfig.model, 'm1');
    assert.equal(localStorage.getItem('openi_api_url'), 'https://x/v1/chat/completions');
    assert.equal(localStorage.getItem('openi_api_model'), 'm1');

    assert.equal(fetchCalls.length, 1);
    assert.equal(fetchCalls[0].url, '/api/save_config');
    assert.equal(fetchCalls[0].opts.method, 'POST');
    const body = JSON.parse(fetchCalls[0].opts.body);
    assert.deepEqual(body, { url: 'https://x/v1/chat/completions', token: 'tok', model: 'm1' });
});

test('saveApiConfig returns false when backend write fails', async () => {
    nextFetchResult = { ok: false };
    const ok = await saveApiConfig('https://x/v1/chat/completions', '', 'm1');
    assert.equal(ok, false);
    // localStorage still updated as a fallback.
    assert.equal(localStorage.getItem('openi_api_url'), 'https://x/v1/chat/completions');
});

test('saveApiConfig returns false when fetch throws', async () => {
    nextFetchResult = { ok: true };
    globalThis.fetch = async () => { throw new Error('network down'); };
    const ok = await saveApiConfig('https://x/v1/chat/completions', '', 'm1');
    assert.equal(ok, false);
});