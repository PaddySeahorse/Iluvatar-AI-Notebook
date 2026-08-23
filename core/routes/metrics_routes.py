"""Metrics endpoints: JSON snapshot + Prometheus text exposition.

Both endpoints read the process-wide registry from
:func:`core.observability.get_metrics`, so they reflect kernel restarts,
execution durations and HTTP request counters accumulated at runtime.
"""

from flask import Blueprint, jsonify, Response

from core.observability import get_metrics

bp = Blueprint('metrics', __name__)


@bp.route('/api/metrics', methods=['GET'])
def metrics_json():
    """Return the full metrics snapshot as JSON."""
    return jsonify(get_metrics().snapshot())


@bp.route('/metrics', methods=['GET'])
def metrics_prometheus():
    """Render metrics in Prometheus text exposition format (0.0.4)."""
    return Response(
        get_metrics().prometheus_text(),
        mimetype='text/plain; version=0.0.4; charset=utf-8',
    )