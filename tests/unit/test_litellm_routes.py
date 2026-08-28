"""Unit tests for the LiteLLM reverse-proxy routes (core/routes/litellm_routes.py).

Covers path whitelisting, header/body forwarding, upstream status passthrough
and the 502 branch when the proxy is unreachable.  Upstream traffic is faked
by monkeypatching ``httpx.AsyncClient`` so no real proxy is needed.

方案三适配：实现由 Flask（requests）迁移为 FastAPI（httpx.AsyncClient），
因此 fake 改为异步客户端；路由经 starlette TestClient 驱动。
"""

import httpx
import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

from app_fastapi import app
from core.routes import litellm_routes
from core.state import app_state


@pytest.fixture()
def client(monkeypatch):
    # FastAPI lifespan 需要 kernel 生命周期方法；此套测试不触碰内核。
    fake_kernel = SimpleNamespace(
        warm_start=lambda: None,
        stop_watchdog=lambda: None,
        shutdown=lambda: None,
    )
    monkeypatch.setattr(app_state, 'kernel_manager', fake_kernel)
    with TestClient(app) as c:
        yield c


class TestIsLitellmPath:
    def test_accepts_litellm_namespaces(self):
        assert litellm_routes.is_litellm_path('/ui/')
        assert litellm_routes.is_litellm_path('/ui/models')
        assert litellm_routes.is_litellm_path('/litellm-asset-prefix/_next/static/chunks/x.js')
        assert litellm_routes.is_litellm_path('/key/generate')
        assert litellm_routes.is_litellm_path('/v1/chat/completions')
        assert litellm_routes.is_litellm_path('/health/liveliness')
        assert litellm_routes.is_litellm_path('/get_favicon')

    def test_rejects_app_namespaces(self):
        assert not litellm_routes.is_litellm_path('/api/run_cell')
        assert not litellm_routes.is_litellm_path('/static/js/main.js')
        assert not litellm_routes.is_litellm_path('/modelsx')
        assert not litellm_routes.is_litellm_path('/useragent')
        assert not litellm_routes.is_litellm_path('/')
        assert not litellm_routes.is_litellm_path('/favicon.ico')


class _FakeUpstream:
    def __init__(self, status_code=200, headers=None, body=b''):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body

    async def aiter_bytes(self, chunk_size):
        yield self._body

    async def aclose(self):
        pass


class _FakeAsyncClient:
    def __init__(self, *, status_code=200, headers=None, body=b'', raised=None,
                 captured=None):
        self._status_code = status_code
        self._headers = headers or {}
        self._body = body
        self._raised = raised
        self._captured = captured if captured is not None else {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def request(self, method, url, headers=None, content=None):
        self._captured.update(method=method, url=url, headers=headers, content=content)
        if self._raised is not None:
            raise self._raised
        return _FakeUpstream(self._status_code, self._headers, self._body)


@pytest.fixture()
def captured():
    return {}


class TestProxyForwarding:
    def test_forwards_ui_get(self, client, monkeypatch, captured):
        fake = _FakeAsyncClient(
            headers={'Content-Type': 'text/html', 'Transfer-Encoding': 'chunked'},
            body=b'<html>ui</html>',
            captured=captured,
        )
        monkeypatch.setattr(litellm_routes.httpx, 'AsyncClient', lambda *a, **kw: fake)
        resp = client.get('/ui/')

        assert resp.status_code == 200
        assert resp.content == b'<html>ui</html>'
        assert captured['url'].startswith(litellm_routes.LITELLM_UPSTREAM + '/ui/')
        assert 'Content-Type' in resp.headers
        assert 'Transfer-Encoding' not in resp.headers

    def test_forwards_post_with_body_and_auth(self, client, monkeypatch, captured):
        fake = _FakeAsyncClient(
            status_code=201,
            headers={'Content-Type': 'application/json'},
            body=b'{"token": "sk-x"}',
            captured=captured,
        )
        monkeypatch.setattr(litellm_routes.httpx, 'AsyncClient', lambda *a, **kw: fake)
        resp = client.post(
            '/key/generate', json={'models': ['m']},
            headers={'Authorization': 'Bearer sk-test'},
        )

        assert resp.status_code == 201
        assert captured['method'] == 'POST'
        assert captured['url'].endswith('/key/generate')
        assert captured['content'] is not None
        # httpx 会把请求头名归一化为小写
        assert captured['headers']['authorization'] == 'Bearer sk-test'

    def test_upstream_error_returns_502(self, client, monkeypatch):
        fake = _FakeAsyncClient(raised=httpx.ConnectError('refused'))
        monkeypatch.setattr(litellm_routes.httpx, 'AsyncClient', lambda *a, **kw: fake)
        resp = client.get('/health/liveliness')
        assert resp.status_code == 502
        assert 'LiteLLM Proxy' in resp.text

    def test_non_whitelisted_path_404(self, client):
        resp = client.get('/definitely/not/litellm')
        assert resp.status_code == 404

    def test_favicon_not_proxied_404(self, client):
        resp = client.get('/favicon.ico')
        assert resp.status_code == 404

    def test_app_routes_unaffected(self, client):
        resp = client.get('/api/get_config')
        assert resp.status_code == 200