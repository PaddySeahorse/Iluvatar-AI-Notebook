"""Kernel execution, interrupt, status and variable routes (方案三：FastAPI 版).

与 Flask 版的差异集中在两点：

* 状态改为 request-time 读取 ``request.app.state.app_state``（见
  :func:`core.routes.state`），语义不变。
* 阻塞的内核调用（``execute`` / ``complete`` / ``inspect`` /
  ``get_variables`` …) 通过 ``run_in_threadpool`` 放入线程池，避免卡住
  事件循环；SSE 端点仍用同步 generator + ``StreamingResponse``（iterable
  由 Starlette 在线程池中迭代）。
"""

import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from core.errors import KernelError
from core.kernel import KernelManager
from core.routes import json_body, state

router = APIRouter()


@router.post('/api/run_cell')
async def run_cell(request: Request):
    s = state(request)
    data = await json_body(request)
    code = data.get('code', '') or ''

    start_time = time.time()

    try:
        result = await run_in_threadpool(s.kernel_manager.execute, code)
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

    return {
        'success': result.get('success', False),
        'stdout': result.get('stdout', ''),
        'stderr': result.get('stderr', ''),
        'html': result.get('html', ''),
        'elapsed_time': elapsed_time,
        'plots': result.get('plots', []),
    }


@router.post('/api/run_cell_stream')
async def run_cell_stream(request: Request):
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
    s = state(request)
    data = await json_body(request)
    code = data.get('code', '') or ''

    if not code.strip():
        return JSONResponse({'error': 'Empty code'}, status_code=400)

    # 先在 handler 内取回 kernel_manager 再闭包引用：StreamingResponse 的
    # generator 在流式期间运行，届时不再有请求上下文可读。
    kernel_manager = s.kernel_manager

    def generate():
        for msg in kernel_manager.execute_stream(code):
            yield f'data: {json.dumps(msg)}\n\n'
        yield 'data: [DONE]\n\n'

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )


@router.post('/api/interrupt_kernel')
async def interrupt_kernel(request: Request):
    kernel_manager = state(request).kernel_manager
    if await run_in_threadpool(kernel_manager.interrupt):
        return {'success': True, 'message': '中断信号已发送 (Interrupt signal sent)'}
    if await run_in_threadpool(kernel_manager.is_kernel_alive):
        return {'success': False, 'message': 'Failed to send interrupt signal'}
    return {'success': False, 'message': 'Kernel is not running'}


@router.get('/api/kernel_status')
async def kernel_status(request: Request):
    """Return current kernel and watchdog health status."""
    kernel_manager = state(request).kernel_manager
    return {
        'kernel_alive': await run_in_threadpool(kernel_manager.is_kernel_alive),
        'watchdog_alive': await run_in_threadpool(kernel_manager.is_watchdog_alive),
        'watchdog_interval_seconds': KernelManager.WATCHDOG_INTERVAL,
    }


@router.get('/api/get_variables')
async def get_variables(request: Request):
    return await run_in_threadpool(state(request).kernel_manager.get_variables)


@router.post('/api/complete')
async def complete(request: Request):
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

    Delegates to ``KernelManager.complete`` which wraps ``jupyter_client``'s
    shell-channel ``complete_request`` (IPython jedi completer). The kernel
    must already be started; if it isn't, an empty match list is returned so
    the frontend can fail soft.
    """
    s = state(request)
    data = await json_body(request)
    code = data.get('code', '') or ''
    cursor_pos = data.get('cursor_pos', len(code))

    if not isinstance(cursor_pos, int) or cursor_pos < 0:
        cursor_pos = len(code)

    return await run_in_threadpool(s.kernel_manager.complete, code, cursor_pos)


@router.post('/api/inspect')
async def inspect(request: Request):
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
    s = state(request)
    data = await json_body(request)
    code = data.get('code', '') or ''
    cursor_pos = data.get('cursor_pos', len(code))
    detail_level = data.get('detail_level', 0)

    if not isinstance(cursor_pos, int) or cursor_pos < 0:
        cursor_pos = len(code)
    if detail_level not in (0, 1):
        detail_level = 0

    return await run_in_threadpool(s.kernel_manager.inspect, code, cursor_pos, detail_level)