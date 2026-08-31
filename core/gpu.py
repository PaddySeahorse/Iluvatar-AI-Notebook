"""GPU telemetry helpers backed by ``pynvml``.

``get_real_gpu_state`` queries the first NVIDIA/Iluvatar device and returns a
dict of hardware metrics.  When ``pynvml`` is unavailable or the driver cannot
be reached, a safe zeroed-out fallback state is returned so the dashboard still
renders.
"""

import shutil
import subprocess


def _get_ixsmi_device_name():
    if not shutil.which("ixsmi"):
        return None
    for args in (
        ["ixsmi", "--query-gpu=name", "--format=csv,noheader"],
        ["ixsmi", "--query-gpu=gpu_name", "--format=csv,noheader"],
    ):
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().splitlines()[0].strip()
        except Exception:
            continue
    return None


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
            raw_power = pynvml.nvmlDeviceGetPowerUsage(handle)
            # NVML spec returns milliwatts (e.g. 35000 = 35W), but the Iluvatar
            # driver reports watts directly (e.g. 35).  Tolerate both units.
            power = raw_power / 1000.0 if raw_power > 100 else float(raw_power)
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

        try:
            raw_name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(raw_name, bytes):
                raw_name = raw_name.decode('utf-8', errors='ignore')
            name = raw_name.strip() if raw_name else None
        except Exception:
            name = None
        if not name:
            name = _get_ixsmi_device_name() or 'Iluvatar GPU'

        return {
            'gpu_available': True,
            'name': name,
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
        fallback_name = _get_ixsmi_device_name()
        if fallback_name:
            return {
                'gpu_available': True,
                'name': fallback_name,
                'vram_total': 0,
                'vram_used': 0,
                'utilization': 0.0,
                'temperature': 0.0,
                'power_draw': 0.0,
                'core_clock': 0,
                'memory_clock': 0,
                'status': 'Idle'
            }
        return {
            'gpu_available': False,
            'name': None,
            'vram_total': 0,
            'vram_used': 0,
            'utilization': 0.0,
            'temperature': 0.0,
            'power_draw': 0.0,
            'core_clock': 0,
            'memory_clock': 0,
            'status': 'No GPU detected'
        }
