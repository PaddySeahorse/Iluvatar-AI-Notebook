"""Kernel execution, interrupt, status and variable routes."""

import json
import time

from flask import Blueprint, request, jsonify, Response, stream_with_context

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


@bp.route('/api/run_cell_stream', methods=['POST'])
def run_cell_stream():
    """Stream code execution via Server-Sent Events.

    Request:  {"code": "..."}
    Response: text/event-stream

    Each SSE ``data:`` line contains a JSON message:
        {"type": "stream", "name": "stdout", "text": "..."}
        {"type": "display_data", "data": {"image/png": "base64..."}}
        {"type": "execute_result", "data": {...}, "execution_count": N}
        {"type": "error", "ename": "...", "evalue": "...", "traceback": [...]}
        {"type": "status", "execution_state": "busy"|"idle"}

    The stream terminates with ``data: [DONE]``.
    """
    data = request.json or {}
    code = data.get('code', '')

    if not code.strip():
        return jsonify({'error': 'Empty code'}), 400

    def generate():
        kernel_manager = state().kernel_manager
        for msg in kernel_manager.execute_stream(code):
            yield f'data: {json.dumps(msg)}\n\n'
        yield 'data: [DONE]\n\n'

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )


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


@bp.route('/api/complete', methods=['POST'])
def complete():
    """Code completion (P3).

    Request:
        {"code": "...", "cursor_pos": <int>}

    Response (always 200, matches may be empty on any failure):
        {
            "matches": ["DataFrame", "DataFrameGroupBy", ...],
            "cursor_start": <int>,
            "cursor_end": <int>,
            "metadata": {...}
        }

    Delegates to ``KernelManager.complete`` which wraps
    ``jupyter_client``'s shell-channel ``complete_request`` (IPython jedi
    completer). The kernel must already be started; if it isn't, an empty
    match list is returned so the frontend can fail soft.
    """
    data = request.json or {}
    code = data.get('code', '')
    cursor_pos = data.get('cursor_pos', len(code))

    if not isinstance(cursor_pos, int) or cursor_pos < 0:
        cursor_pos = len(code)

    result = state().kernel_manager.complete(code, cursor_pos)
    return jsonify(result)


@bp.route('/api/inspect', methods=['POST'])
def inspect():
    """Object introspection (? / ??) (P3).

    Request:
        {"code": "...", "cursor_pos": <int>, "detail_level": 0|1}

    Response (always 200, found=False on any failure):
        {
            "found": <bool>,
            "data": {"text/plain": "...", "text/html": "..."},
            "metadata": {...}
        }

    ``detail_level`` 0 corresponds to ``?`` (docstring + signature);
    1 corresponds to ``??`` (full source).
    """
    data = request.json or {}
    code = data.get('code', '')
    cursor_pos = data.get('cursor_pos', len(code))
    detail_level = data.get('detail_level', 0)

    if not isinstance(cursor_pos, int) or cursor_pos < 0:
        cursor_pos = len(code)
    if detail_level not in (0, 1):
        detail_level = 0

    result = state().kernel_manager.inspect(code, cursor_pos, detail_level)
    return jsonify(result)
