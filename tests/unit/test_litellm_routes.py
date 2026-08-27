"""Unit tests for the LiteLLM reverse-proxy routes (core/routes/litellm_routes.py).

Covers path whitelisting, header/body forwarding, upstream status passthrough
and the 502 branch when the proxy is unreachable.  Upstream traffic is faked
by monkeypatching ``requests.request`` so no real proxy is needed.
"""

import pytest

import app as notebook_app
from core.routes import litellm_routes


@pytest.fixture()
def client(monkeypatch):
    notebook_app.app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
    with notebook_app.app.test_client() as c:
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


class TestProxyForwarding:
    def test_forwards_ui_get(self, client, monkeypatch):
        captured = {}

        class _FakeUpstream:
            status_code = 200
            headers = {'Content-Type': 'text/html', 'Transfer-Encoding': 'chunked'}

            def iter_content(self, chunk_size):
                return iter([b'<html>ui</html>'])

        def fake_request(method, url, headers, data, stream, timeout, allow_redirects):
            captured.update(method=method, url=url, headers=headers, data=data)
            return _FakeUpstream()

        monkeypatch.setattr(litellm_routes.requests, 'request', fake_request)
        resp = client.get('/ui/')

        assert resp.status_code == 200
        assert resp.data == b'<html>ui</html>'
        assert captured['url'].startswith(litellm_routes.LITELLM_UPSTREAM + '/ui/')
        assert 'Content-Type' in resp.headers
        assert 'Transfer-Encoding' not in resp.headers

    def test_forwards_post_with_body_and_auth(self, client, monkeypatch):
        captured = {}

        class _FakeUpstream:
            status_code = 201
            headers = {'Content-Type': 'application/json'}

            def iter_content(self, chunk_size):
                return iter([b'{"token": "sk-x"}'])

        def fake_request(method, url, headers, data, stream, timeout, allow_redirects):
            captured.update(method=method, url=url, headers=headers, data=data)
            return _FakeUpstream()

        monkeypatch.setattr(litellm_routes.requests, 'request', fake_request)
        resp = client.post('/key/generate', json={'models': ['m']},
                           headers={'Authorization': 'Bearer sk-test'})

        assert resp.status_code == 201
        assert captured['method'] == 'POST'
        assert captured['url'].endswith('/key/generate')
        assert captured['data'] is not None
        assert captured['headers']['Authorization'] == 'Bearer sk-test'

    def test_upstream_error_returns_502(self, client, monkeypatch):
        import requests as real_requests

        def fake_request(**kwargs):
            raise real_requests.exceptions.ConnectionError('refused')

        monkeypatch.setattr(litellm_routes.requests, 'request', fake_request)
        resp = client.get('/health/liveliness')
        assert resp.status_code == 502
        assert 'LiteLLM Proxy' in resp.get_data(as_text=True)

    def test_non_whitelisted_path_404(self, client):
        resp = client.get('/definitely/not/litellm')
        assert resp.status_code == 404

    def test_app_routes_unaffected(self, client):
        resp = client.get('/api/get_config')
        assert resp.status_code == 200
