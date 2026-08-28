"""APIRouter-based route registration for the notebook backend (方案三).

FastAPI 迁移后的路由注册。原 Flask 版通过 ``current_app.config['_STATE_MODULE']``
读取入口模块的运行时状态；这里改为在请求时经 ``request.app.state`` 读取同一个
:data:`core.state.app_state` 实例（由 :mod:`app_fastapi` 挂载）。两者的语义
一致 —— 都是请求时读取、可被测试 monkeypatch，且避免 ``import app`` 循环。
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from core.errors import AppError

logger = logging.getLogger(__name__)


def state(request: Request):
    """Return the shared :class:`core.state.AppState` instance for this request."""
    return request.app.state.app_state


async def json_body(request: Request) -> dict:
    """Read the request JSON body, tolerating an empty / non-dict payload.

    FastAPI 不会像 Flask 那样对空 body 返回 ``None``，这里补齐该行为，
    让既有前端（可能不携带 body 的 POST）保持兼容。
    """
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001 - 空 body / 非 JSON 一律按 {} 处理
        return {}
    return data if isinstance(data, dict) else {}


def register_error_handlers(app):
    """Register structured JSON error handlers (ISSUE-009, FastAPI 版)."""
    from fastapi.exceptions import StarletteHTTPException

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        """Convert any AppError subclass into a structured JSON response."""
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return JSONResponse(
                status_code=404,
                content={
                    'error': True,
                    'error_code': 'NOT_FOUND',
                    'message': 'Resource not found',
                },
            )
        if exc.status_code == 405:
            return JSONResponse(
                status_code=405,
                content={
                    'error': True,
                    'error_code': 'METHOD_NOT_ALLOWED',
                    'message': 'Method not allowed',
                },
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                'error': exc.status_code >= 400,
                'error_code': 'HTTP_ERROR',
                'message': str(exc.detail),
            },
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(request: Request, exc: Exception):
        logger.exception(
            'unhandled_exception',
            extra={'path': request.url.path, 'method': request.method},
        )
        return JSONResponse(
            status_code=500,
            content={
                'error': True,
                'error_code': 'INTERNAL_ERROR',
                'message': 'An unexpected server error occurred',
            },
        )


def register_routers(app):
    """Import and register every route APIRouter on *app*.

    ``litellm_routes`` 独占 catch-all（``/{subpath:path}``），必须最后注册，
    避免拦截其它路由；静态文件（/static）与 Chainlit（/agent）已在
    :func:`register_static_routes` / ``app_fastapi`` 中先行挂载为 Mount，
    优先级高于下方的通配路由。
    """
    from .static_routes import register_static_routes
    from .gpu_routes import router as gpu_router
    from .kernel_routes import router as kernel_router
    from .ai_routes import router as ai_router
    from .lint_routes import router as lint_router
    from .file_routes import router as file_router
    from .agent_routes import router as agent_router
    from .metrics_routes import router as metrics_router
    from .terminal_routes import router as terminal_router
    from .litellm_routes import router as litellm_router

    register_static_routes(app)
    app.include_router(gpu_router)
    app.include_router(kernel_router)
    app.include_router(ai_router)
    app.include_router(lint_router)
    app.include_router(file_router)
    app.include_router(agent_router)
    app.include_router(metrics_router)
    app.include_router(terminal_router)
    app.include_router(litellm_router)  # catch-all，必须最后