// Unit tests for GpuModal exported from static/js/gpu-modal.js.
//
// Run with: node --test tests/js/gpu-modal.test.mjs
//
// GpuModal queries its field elements from an injected document and mutates
// .innerText / .style.width. We provide a minimal fake DOM (no jsdom) and
// assert on the recorded mutations. The class requires the following ids:
// gpuModalName, gpuModalArch, gpuModalTemp, gpuModalPower, gpuModalStatus,
// gpuModalVramUsed, gpuModalVramTotal, gpuModalVramBar, gpuModalCoreClock,
// gpuModalMemClock.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { GpuModal } from '../../static/js/gpu-modal.js';

const FIELD_IDS = [
    'gpuModalName',
    'gpuModalArch',
    'gpuModalTemp',
    'gpuModalPower',
    'gpuModalStatus',
    'gpuModalVramUsed',
    'gpuModalVramTotal',
    'gpuModalVramBar',
    'gpuModalCoreClock',
    'gpuModalMemClock'
];

class FakeElement {
    constructor() {
        this.innerText = '';
        this.style = { width: '' };
    }
}

function makeDocument(ids = FIELD_IDS) {
    const elements = new Map(ids.map(id => [id, new FakeElement()]));
    const missing = new Set();
    return {
        elements,
        missing,
        getElementById(id) {
            if (elements.has(id)) return elements.get(id);
            missing.add(id);
            return null;
        }
    };
}

function fullPayload(overrides = {}) {
    return {
        name: 'MR-V100',
        vram_total: 32768,
        vram_used: 4096,
        utilization: 86.0,
        temperature: 62.0,
        power_draw: 158.4,
        core_clock: 1350,
        memory_clock: 1200,
        status: 'Training / Computing',
        ...overrides
    };
}

test('constructor tolerates missing field elements (null-safe)', () => {
    const doc = makeDocument(['gpuModalName', 'gpuModalTemp']);
    assert.doesNotThrow(() => new GpuModal(doc));
});

test('update renders device name from telemetry into title and arch', () => {
    const doc = makeDocument();
    const modal = new GpuModal(doc);
    modal.update(fullPayload());

    assert.equal(doc.elements.get('gpuModalName').innerText, 'MR-V100');
    assert.equal(doc.elements.get('gpuModalArch').innerText, 'MR-V100');
});

test('update falls back to generic name when telemetry name is blank', () => {
    const doc = makeDocument();
    const modal = new GpuModal(doc);
    modal.update(fullPayload({ name: '  ' }));

    assert.equal(doc.elements.get('gpuModalName').innerText, 'Iluvatar GPU');
    assert.equal(doc.elements.get('gpuModalArch').innerText, 'Iluvatar GPU');
});

test('update renders temperature, power, status and vram fields', () => {
    const doc = makeDocument();
    const modal = new GpuModal(doc);
    modal.update(fullPayload());

    assert.equal(doc.elements.get('gpuModalTemp').innerText, '62°C');
    assert.equal(doc.elements.get('gpuModalPower').innerText, '158.4 W');
    assert.equal(doc.elements.get('gpuModalStatus').innerText, 'Training / Computing');
    assert.equal(doc.elements.get('gpuModalVramUsed').innerText, '4096 MB');
    assert.equal(doc.elements.get('gpuModalVramTotal').innerText, '32768 MB (32GB)');
});

test('update sets vram bar width to used/total percent', () => {
    const doc = makeDocument();
    const modal = new GpuModal(doc);
    modal.update(fullPayload({ vram_total: 32768, vram_used: 8192 }));

    assert.equal(doc.elements.get('gpuModalVramBar').style.width, '25%');
});

test('update guards vram bar against zero total', () => {
    const doc = makeDocument();
    const modal = new GpuModal(doc);
    modal.update(fullPayload({ vram_total: 0, vram_used: 100 }));

    assert.equal(doc.elements.get('gpuModalVramBar').style.width, '0%');
});

test('update renders clock fields and shows placeholder when zero', () => {
    const doc = makeDocument();
    const modal = new GpuModal(doc);
    modal.update(fullPayload());

    assert.equal(doc.elements.get('gpuModalCoreClock').innerText, '1350 MHz');
    assert.equal(doc.elements.get('gpuModalMemClock').innerText, '1200 MHz');

    modal.update(fullPayload({ core_clock: 0, memory_clock: 0 }));
    assert.equal(doc.elements.get('gpuModalCoreClock').innerText, '--');
    assert.equal(doc.elements.get('gpuModalMemClock').innerText, '--');
});

test('update with null payload is a no-op', () => {
    const doc = makeDocument();
    const modal = new GpuModal(doc);
    assert.doesNotThrow(() => modal.update(null));
    assert.equal(doc.elements.get('gpuModalName').innerText, '');
});
