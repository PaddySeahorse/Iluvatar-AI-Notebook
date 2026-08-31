/**
 * GPU Details Modal view.
 *
 * Renders the "国产算力详情" modal from live telemetry returned by
 * /api/gpu_status. All displayed values — including the device name — come
 * from the backend (`pynvml` first, `ixsmi` fallback), so the modal never
 * hardcodes a specific model string and stays truthful across different
 * Iluvatar cards (BI-150, MR-V100, ...).
 *
 * The constructor touches `document` immediately, mirroring KernelIndicator;
 * tests inject a fake document. `update(data)` is idempotent and safe to call
 * on every telemetry tick (1.5s) while the modal is open.
 */
export class GpuModal {
    /**
     * @param {Document} doc document to query modal field elements from
     */
    constructor(doc) {
        this._els = {};
        for (const id of [
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
        ]) {
            this._els[id] = doc.getElementById(id);
        }
    }

    /**
     * Refresh every modal field from a /api/gpu_status payload.
     * @param {object} data telemetry payload (name, temperature, power_draw,
     *        status, vram_used, vram_total, core_clock, memory_clock, ...)
     */
    update(data) {
        if (!data) return;
        const name = (data.name && String(data.name).trim()) || 'Iluvatar GPU';

        this._setText('gpuModalName', name);
        this._setText('gpuModalArch', name);
        this._setText('gpuModalTemp', `${data.temperature}°C`);
        this._setText('gpuModalPower', `${data.power_draw} W`);
        this._setText('gpuModalStatus', data.status || 'Idle');
        this._setText('gpuModalVramUsed', `${data.vram_used} MB`);

        const total = Number(data.vram_total) || 0;
        const totalGb = Math.round(total / 1024);
        this._setText('gpuModalVramTotal', `${total} MB (${totalGb}GB)`);

        const bar = this._els.gpuModalVramBar;
        if (bar) {
            const percent = total > 0 ? (data.vram_used / total) * 100 : 0;
            bar.style.width = `${percent}%`;
        }

        this._setText('gpuModalCoreClock', data.core_clock > 0 ? `${data.core_clock} MHz` : '--');
        this._setText('gpuModalMemClock', data.memory_clock > 0 ? `${data.memory_clock} MHz` : '--');
    }

    _setText(id, text) {
        const el = this._els[id];
        if (el) el.innerText = text;
    }
}
