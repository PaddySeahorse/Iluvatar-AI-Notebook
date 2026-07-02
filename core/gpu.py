"""GPU telemetry helpers backed by ``pynvml``.

``get_real_gpu_state`` queries the first NVIDIA/Iluvatar device and returns a
dict of hardware metrics.  When ``pynvml`` is unavailable or the driver cannot
be reached, a safe zeroed-out fallback state is returned so the dashboard still
renders.
"""


def get_real_gpu_state():
    try:
        import pynvml
        if not hasattr(pynvml, '_nvml_inited'):
            pynvml.nvmlInit()
            pynvml._nvml_inited = True
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)

        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        vram_total = mem_info.total // (1024 * 1024)
        vram_used = mem_info.used // (1024 * 1024)

        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        utilization = float(util.gpu)

        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)

        try:
            power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
        except Exception:
            power = 0.0

        try:
            core_clock = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_SM)
            mem_clock = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM)
        except Exception:
            core_clock = 0
            mem_clock = 0

        if utilization > 50:
            status = 'Training / Computing'
        elif utilization > 15:
            status = 'Inference Active'
        else:
            status = 'Idle'

        return {
            'name': 'Iluvatar MR-V100',
            'vram_total': vram_total,
            'vram_used': vram_used,
            'utilization': utilization,
            'temperature': float(temp),
            'power_draw': round(power, 1),
            'core_clock': core_clock,
            'memory_clock': mem_clock,
            'status': status
        }
    except Exception as e:
        return {
            'name': 'Iluvatar MR-V100',
            'vram_total': 32768,
            'vram_used': 0,
            'utilization': 0.0,
            'temperature': 0.0,
            'power_draw': 0.0,
            'core_clock': 0,
            'memory_clock': 0,
            'status': f'Error: {str(e)}'
        }
