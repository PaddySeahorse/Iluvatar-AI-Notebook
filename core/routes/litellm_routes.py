"""Reverse proxy for the local LiteLLM Proxy (WebUI + admin API).

Only the Flask port (``OPENI_SELF_PORT``) is reachable from outside networks,
so the LiteLLM Proxy's native WebUI cannot be embedded directly: the browser
would try to reach ``localhost:4000`` and fail.  This blueprint forwards a
whitelisted set of LiteLLM-owned path prefixes — the WebUI assets
(``/ui``, ``/litellm-asset-prefix``), its login/favicon endpoints and the
admin API namespaces the WebUI calls (``/key``, ``/user``, ``/team`` ...).

The prefixes are all LiteLLM-specific namespaces and never collide with the
notebook's own routes (``/``, ``/api/*``).  Requests are streamed through so
SSE and large JS chunks work, with hop-by-hop headers filtered.
"""

import logging

import requests
from flask import Blueprint, Response, request

logger = logging.getLogger(__name__)

bp = Blueprint('litellm_proxy', __name__)

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
    '/favicon.ico',
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


def _forward(path: str) -> Response:
    """Stream a request through to the local LiteLLM Proxy."""
    url = LITELLM_UPSTREAM + request.full_path.rstrip('?') if request.full_path else LITELLM_UPSTREAM + path

    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    body = request.get_data()

    try:
        upstream = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            data=body,
            stream=True,
            timeout=120,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as e:
        logger.warning('litellm_proxy_upstream_error', extra={'path': path, 'error': str(e)})
        return Response(
            '{"error": true, "message": "LiteLLM Proxy 不可达: %s"}' % e.__class__.__name__,
            status=502, mimetype='application/json',
        )

    out_headers = [(k, v) for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP]
    return Response(
        upstream.iter_content(chunk_size=64 * 1024),
        status=upstream.status_code,
        headers=out_headers,
    )


@bp.route('/<path:subpath>', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'])
def proxy_any(subpath):
    """Forward any whitelisted LiteLLM path; 404 for everything else."""
    if not is_litellm_path('/' + subpath):
        from core.errors import AppError

        raise AppError('未知路径: /%s' % subpath, status_code=404)
    return _forward('/' + subpath)
