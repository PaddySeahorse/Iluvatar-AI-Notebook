"""Iluvatar AI Notebook — FastAPI (ASGI) 统一入口（方案三）。

单一 uvicorn 进程同时提供两条面（原 Flask 版方案二分别由 Chainlit / Flask
两个进程拼装，方案三收敛为一个 ASGI 应用）：

* Notebook 主界面与全部原有 API —— ``/``、``/api/*``、``/static/*``。
  路由以 APIRouter 直接实现（``core/routes/*``），URL 与请求/响应格式
  保持兼容，前端 JS 无需把 `/api` 改成 `/nb/api`。
* Chainlit Agent 聊天界面 —— 经官方 ``chainlit.utils.mount_chainlit``
  挂载在 ``/agent``，与 Notebook 共享同一个 ``kernel_manager``
  （``core.state.app_state``），聊天与 Notebook 的变量互通。

启动::

    python app_fastapi.py              # 等价于下面的 uvicorn 命令
    uvicorn app_fastapi:app --host 0.0.0.0 --port 5000

向后兼容：``app.py`` 仍是薄壳，``python app.py`` / ``uvicorn app:app``
照常可用，并继续按原名暴露 ``kernel_manager`` / ``WORKSPACE_DIR`` /
``is_safe_path`` / ``DEFAULT_API_*`` 符号。
"""

import atexit
import logging
import os
import sys
import time

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from core.observability import (
    configure_logging,
    get_metrics,
    get_trace_id,
    new_trace_id,
    set_trace_id,
)
from core.litellm_manager import get_litellm_config_path, litellm_manager, write_config
from core.routes import register_error_handlers, register_routers
from core.state import app_state
from core.user_config import apply_saved_config

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 结构化日志（JSON lines）+ LOG_LEVEL
_log_level = getattr(
    logging, os.environ.get('LOG_LEVEL', 'INFO').upper(), logging.INFO
)
configure_logging(level=_log_level)

# 从 ~/.Iluvatar-AI-Notebook/config.yaml 恢复（首次运行自环境种子化）
apply_saved_config()
# state.py 的 DEFAULT_API_* 模块常量在 env 恢复前已初始化；配置恢复进
# os.environ 后把运行时默认值同步为已保存值，get_config / agent 默认请求
# 才会使用用户保存的上游模型（而非模块默认）。
for _key in ('OPENI_API_URL', 'OPENI_API_TOKEN', 'OPENI_API_MODEL'):
    _saved = os.environ.get(_key)
    if _saved:
        setattr(
            app_state,
            'DEFAULT_API_' + _key.replace('OPENI_API_', ''),
            _saved,
        )


def _cleanup_gpu():
    """Release the pynvml library handle (nvmlShutdown) on process exit."""
    try:
        import pynvml
        if hasattr(pynvml, '_nvml_inited'):
            pynvml.nvmlShutdown()
    except Exception:  # noqa: BLE001
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-start the kernel + watchdog; stop them cleanly on shutdown.

    内核实例在 ``core.state`` 中被两条链路（FastAPI 路由 / Chainlit）
    共享，这里只负责启动与停止：warm_start 用线程池执行以避免阻塞
    ASGI 生命周期的事件循环。
    """
    await run_in_threadpool(app_state.kernel_manager.warm_start)

    def _bootstrap_litellm():
        if not os.path.exists(get_litellm_config_path()):
            url = (os.environ.get('OPENI_API_URL') or app_state.DEFAULT_API_URL or '').strip()
            token = (os.environ.get('OPENI_API_TOKEN') or app_state.DEFAULT_API_TOKEN or '').strip()
            model = (os.environ.get('OPENI_API_MODEL') or app_state.DEFAULT_API_MODEL or '').strip()
            if url and model:
                try:
                    write_config(url, token, model)
                except OSError as e:
                    logger.warning('litellm_bootstrap_failed', extra={'error': str(e)})

    try:
        await run_in_threadpool(_bootstrap_litellm)
        await run_in_threadpool(litellm_manager.ensure_running)
    except Exception:  # noqa: BLE001
        logger.warning('litellm_autostart_failed', exc_info=True)

    # pynvml / watchdog 清理（脚本级启动时保证退出干净）
    atexit.register(_cleanup_gpu)
    atexit.register(app_state.kernel_manager.stop_watchdog)

    try:
        yield
    finally:
        atexit.unregister(_cleanup_gpu)
        atexit.unregister(app_state.kernel_manager.stop_watchdog)
        await run_in_threadpool(app_state.kernel_manager.stop_watchdog)
        await run_in_threadpool(app_state.kernel_manager.shutdown)
        try:
            await app_state.terminal_manager.shutdown_all()
        except Exception:
            pass
        litellm_manager.shutdown()


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------
app = FastAPI(
    title='Iluvatar AI Notebook',
    version='0.4.0',
    lifespan=lifespan,
)

# 把共享状态挂到 app.state：core/routes 的 request-time state() 从这里读。
# 与 Chainlit 通过 core.state 单例引用的是同一个实例。
app.state.app_state = app_state

# 挂载 Chainlit 必须在注册 API 路由之前：/agent Mount 需要排在
# litellm_routes 的 catch-all（/{subpath:path}）前面，否则会被拦截。
from chainlit.utils import mount_chainlit  # noqa: E402

mount_chainlit(
    app=app,
    target=os.path.join(_PROJECT_ROOT, 'chainlit_app.py'),
    path='/agent',
)


@app.get('/agent', include_in_schema=False)
async def _redirect_agent_root():
    """Redirect ``/agent`` → ``/agent/``.

    starlette 1.6 的 ``Mount`` 对无尾斜杠的根路径（``/agent``）不会匹配
    （其 path regex 带尾斜杠），否则请求会落到 ``litellm_routes`` 的
    catch-all 返回 404。补一个 307 重定向即可。
    """
    return RedirectResponse('/agent/', status_code=307)

# API 路由（static mount 与 / 页面在 register_routers 内完成）。
register_routers(app)
register_error_handlers(app)

# CORS（与 Flask-CORS 相同的默认策略：ALLOWED_ORIGINS，默认 *）。
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get('ALLOWED_ORIGINS', '*').split(','),
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.middleware('http')
async def _http_trace_middleware(request: Request, call_next):
    """Request tracing: correlate logs via the X-Request-ID header + metrics.

    迁移自 Flask 的 before_request / after_request 钩子：传播请求级的
    trace id、记录结构化 http_request 日志、累加 Metrics 的 HTTP 计数器。
    """
    trace_id = request.headers.get('X-Request-ID') or new_trace_id()
    set_trace_id(trace_id)
    started = time.monotonic()

    response = await call_next(request)

    response.headers['X-Request-ID'] = trace_id or ''
    duration_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        'http_request',
        extra={
            'trace_id': trace_id,
            'method': request.method,
            'path': request.url.path,
            'status': response.status_code,
            'duration_ms': duration_ms,
        },
    )
    get_metrics().record_http_request(
        request.method, request.url.path, response.status_code,
    )
    return response


# ---------------------------------------------------------------------------
# 向后兼容符号（等价于原 Flask app.py 的模块级状态，供 app.py 薄壳转发）
# ---------------------------------------------------------------------------
kernel_manager = app_state.kernel_manager
WORKSPACE_DIR = app_state.WORKSPACE_DIR
DEFAULT_API_URL = app_state.DEFAULT_API_URL
DEFAULT_API_TOKEN = app_state.DEFAULT_API_TOKEN
DEFAULT_API_MODEL = app_state.DEFAULT_API_MODEL


def is_safe_path(path):
    """Workspace-confined path check, resolved against the current WORKSPACE_DIR."""
    return app_state.is_safe_path(path)


if __name__ == '__main__':
    import uvicorn

    port = int(os.environ.get('OPENI_SELF_PORT', 5000))
    host = os.environ.get('OPENI_SELF_HOST', '0.0.0.0')
    uvicorn.run(app, host=host, port=port, log_level='info')