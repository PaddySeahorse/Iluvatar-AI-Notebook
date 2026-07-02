"""Kernel execution, interrupt, status and variable routes."""

import time

from flask import Blueprint, request, jsonify

from core.errors import KernelError
from core.kernel import KernelManager
from core.routes import state

bp = Blueprint('kernel', __name__)


@bp.route('/api/run_cell', methods=['POST'])
def run_cell():
    data = request.json or {}
    code = data.get('code', '')

    start_time = time.time()

    try:
        result = state().kernel_manager.execute(code)
    except RuntimeError as e:
        # KernelManager raises RuntimeError when queues are not initialised
        raise KernelError(
            f"Kernel is not ready: {e}",
            error_code='KERNEL_NOT_READY',
            status_code=503,
        ) from e
    except OSError as e:
        raise KernelError(
            f"Kernel process I/O error: {e}",
            error_code='KERNEL_IO_ERROR',
            status_code=503,
        ) from e

    elapsed_time = round(time.time() - start_time, 3)

    return jsonify({
        'success': result.get('success', False),
        'stdout': result.get('stdout', ''),
        'stderr': result.get('stderr', ''),
        'html': result.get('html', ''),
        'elapsed_time': elapsed_time,
        'plots': result.get('plots', [])
    })


@bp.route('/api/interrupt_kernel', methods=['POST'])
def interrupt_kernel():
    kernel_manager = state().kernel_manager
    if kernel_manager.interrupt():
        return jsonify({'success': True, 'message': '中断信号已发送 (Interrupt signal sent)'})
    else:
        if kernel_manager.is_kernel_alive():
            return jsonify({'success': False, 'message': 'Failed to send interrupt signal'})
        return jsonify({'success': False, 'message': 'Kernel is not running'})


@bp.route('/api/kernel_status', methods=['GET'])
def kernel_status():
    """Return current kernel and watchdog health status."""
    kernel_manager = state().kernel_manager
    return jsonify({
        'kernel_alive': kernel_manager.is_kernel_alive(),
        'watchdog_alive': kernel_manager.is_watchdog_alive(),
        'watchdog_interval_seconds': KernelManager.WATCHDOG_INTERVAL,
    })


@bp.route('/api/get_variables', methods=['GET'])
def get_variables():
    return jsonify(state().kernel_manager.get_variables())
