"""GPU telemetry route."""

from flask import Blueprint, jsonify

from core.gpu import get_real_gpu_state

bp = Blueprint('gpu', __name__)


@bp.route('/api/gpu_status', methods=['GET'])
def get_gpu_status():
    gpu_state = get_real_gpu_state()

    return jsonify({
        **gpu_state,
        'utilization': round(gpu_state['utilization'], 1),
        'temperature': round(gpu_state['temperature'], 1),
        'power_draw': gpu_state['power_draw']
    })
