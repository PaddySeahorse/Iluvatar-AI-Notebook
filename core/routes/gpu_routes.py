"""GPU telemetry route (方案三：FastAPI 版)."""

from fastapi import APIRouter

from core.gpu import get_real_gpu_state

router = APIRouter()


@router.get('/api/gpu_status')
async def get_gpu_status():
    gpu_state = get_real_gpu_state()

    return {
        **gpu_state,
        'utilization': round(gpu_state['utilization'], 1),
        'temperature': round(gpu_state['temperature'], 1),
        'power_draw': gpu_state['power_draw'],
    }