"""Metrics endpoints: JSON snapshot + Prometheus text exposition (方案三).

Both endpoints read the process-wide registry from
:func:`core.observability.get_metrics`, so they reflect kernel restarts,
execution durations and HTTP request counters accumulated at runtime.
"""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from core.observability import get_metrics

router = APIRouter()


@router.get('/api/metrics')
async def metrics_json():
    """Return the full metrics snapshot as JSON."""
    return get_metrics().snapshot()


@router.get('/metrics')
async def metrics_prometheus():
    """Render metrics in Prometheus text exposition format (0.0.4)."""
    return PlainTextResponse(
        get_metrics().prometheus_text(),
        media_type='text/plain; version=0.0.4; charset=utf-8',
    )