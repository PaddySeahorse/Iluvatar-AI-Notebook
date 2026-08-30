// Unit tests for saveApiConfig from static/js/api.js (API config persistence).
//
// Verifies that saving the config updates localStorage, calls POST
// /api/save_config, and returns {ok, message?, errorCode?} so callers can
// react to e.g. the CONFIG_MANAGED_MANUALLY refusal.
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
    nextFetchResult = { ok: true };
    const result = await saveApiConfig('https://x/v1/chat/completions', 'tok', 'm1');

    assert.deepEqual(result, { ok: true });
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

test('saveApiConfig returns error object with backend message and code', async () => {
    fetchCalls = [];
    nextFetchResult = {
        ok: false,
        status: 409,
        json: async () => ({
            error: true,
            error_code: 'CONFIG_MANAGED_MANUALLY',
            message: 'LiteLLM 路由处于手动接管状态，请在高级模式中手动配置',
        }),
    };
    const result = await saveApiConfig('https://x/v1/chat/completions', '', 'm1');
    assert.equal(result.ok, false);
    assert.equal(result.errorCode, 'CONFIG_MANAGED_MANUALLY');
    assert.match(result.message, /高级模式/);
    // localStorage still updated as a fallback.
    assert.equal(localStorage.getItem('openi_api_url'), 'https://x/v1/chat/completions');
});

test('saveApiConfig falls back to a generic message on non-JSON errors', async () => {
    nextFetchResult = {
        ok: false,
        status: 500,
        json: async () => { throw new Error('not json'); },
    };
    const result = await saveApiConfig('https://x/v1/chat/completions', '', 'm1');
    assert.equal(result.ok, false);
    assert.match(result.message, /500/);
    assert.equal(result.errorCode, '');
});

test('saveApiConfig returns error object when fetch throws', async () => {
    globalThis.fetch = async () => { throw new Error('network down'); };
    const result = await saveApiConfig('https://x/v1/chat/completions', '', 'm1');
    assert.equal(result.ok, false);
    assert.match(result.message, /network down/);
    assert.equal(result.errorCode, '');
});
