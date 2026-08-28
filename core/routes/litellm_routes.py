"""Reverse proxy for the local LiteLLM Proxy (WebUI + admin API, 方案三).

Only the served port (``OPENI_SELF_PORT``) is reachable from outside networks,
so the LiteLLM Proxy's native WebUI cannot be embedded directly: the browser
would try to reach ``localhost:4000`` and fail.  This router forwards a
whitelisted set of LiteLLM-owned path prefixes — the WebUI assets
(``/ui``, ``/litellm-asset-prefix``), its login/favicon endpoints and the
admin API namespaces the WebUI calls (``/key``, ``/user``, ``/team`` ...).

The prefixes are all LiteLLM-specific namespaces and never collide with the
notebook's own routes (``/``, ``/api/*``). Requests are streamed through so
SSE and large JS chunks work, with hop-by-hop headers filtered.

迁移说明：Flask（同步 requests）→ FastAPI（异步 httpx）。此 router 独占
``/{subpath:path}`` catch-all，因此必须在其它 router 之后注册（见
:func:`core.routes.register_routers`），否则会挡住所有未匹配的路径。
"""

import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from core.errors import AppError

logger = logging.getLogger(__name__)

router = APIRouter()

LITELLM_UPSTREAM = 'http://localhost:4000'

# LiteLLM Proxy owned path prefixes (WebUI assets + admin API namespaces).
LITELLM_PREFIXES = (
    '/ui',
    '/ui/',
    '/litellm-asset-prefix',
    '/key',
    '/user',
    '/team',
    '/model',
    '/models',
    '/v1',
    '/health',
    '/global',
    '/spend',
    '/config',
    '/get_favicon',
    '/sso',
    '/login',
    '/logout',
    '/auth',
)

# Hop-by-hop headers never forwarded in either direction (RFC 7230 §6.1).
_HOP_BY_HOP = frozenset((
    'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
    'te', 'trailer', 'transfer-encoding', 'upgrade', 'host',
    'content-encoding', 'content-length',
))


def is_litellm_path(path: str) -> bool:
    """Return True when *path* belongs to the LiteLLM Proxy namespace."""
    for prefix in LITELLM_PREFIXES:
        if path == prefix or path.startswith(prefix + '/') or (prefix + '?') in (path + '?'):
            return True
    return False


async def _forward(path: str, request: Request) -> StreamingResponse:
    """Stream a request through to the local LiteLLM Proxy."""
    query = request.url.query
    upstream_url = LITELLM_UPSTREAM + '/' + path + (f'?{query}' if query else '')

    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    body = await request.body()

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0), follow_redirects=False,
        ) as client:
            upstream = await client.request(
                request.method,
                upstream_url,
                headers=headers,
                content=body,
            )
    except httpx.RequestError as e:
        logger.warning('litellm_proxy_upstream_error', extra={'path': '/' + path, 'error': str(e)})
        return JSONResponse(
            {'error': True, 'message': f'LiteLLM Proxy 不可达: {e.__class__.__name__}'},
            status_code=502,
        )

    out_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP}

    async def body_stream():
        try:
            async for chunk in upstream.aiter_bytes(chunk_size=64 * 1024):
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(
        body_stream(),
        status_code=upstream.status_code,
        headers=out_headers,
    )


@router.api_route(
    '/{subpath:path}',
    methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'],
    include_in_schema=False,
)
async def proxy_any(subpath: str, request: Request):
    """Forward any whitelisted LiteLLM path; 404 for everything else."""
    if not is_litellm_path('/' + subpath):
        raise AppError('未知路径: /%s' % subpath, status_code=404)
    return await _forward(subpath, request)