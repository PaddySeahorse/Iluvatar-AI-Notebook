"""Unit tests for the LLM transport layer (core/llm.py).

Both backends (OpenAI SDK against the LiteLLM proxy and the plain requests
fallback) are exercised with injected fakes so no network is needed.  Also
covers the URL normalization helper and the transport-neutral public API.
"""

import pytest

from core import llm as llm_module
from core.llm import LLMError, chat_nostream, chat_stream, probe_tool_support


# ---------------------------------------------------------------------------
# normalization helpers
# ---------------------------------------------------------------------------

def test_to_api_base_pins_local_litellm():
    base = llm_module.LITELLM_PROXY_URL.rstrip('/')
    expected = base if base.endswith('/v1') else f'{base}/v1'
    # Every backend is pinned to the self-hosted proxy regardless of the
    # upstream config passed in.
    assert llm_module._to_api_base('https://x.com/v1/chat/completions') == expected
    assert llm_module._to_api_base('https://x.com/v1/') == expected
    assert llm_module._to_api_base('https://x.com') == expected


def test_normalize_tool_calls():
    class _Fn:
        name = 'run_cell'
        arguments = '{"code": "1+1"}'

    class _TC:
        id = 'call_1'
        type = 'function'
        function = _Fn()

    class _Msg:
        tool_calls = [_TC()]

    assert llm_module._normalize_tool_calls(_Msg()) == [
        {'id': 'call_1', 'type': 'function', 'function': {'name': 'run_cell', 'arguments': '{"code": "1+1"}'}}
    ]
    assert llm_module._normalize_tool_calls(object()) is None


# ---------------------------------------------------------------------------
# requests (fallback) backend
# ---------------------------------------------------------------------------

def test_requests_nostream_success(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update(url=url, headers=headers, payload=json, timeout=timeout)
        return _FakeResp({'choices': [{'message': {'content': 'hi', 'tool_calls': None}}]})

    monkeypatch.setattr(llm_module.requests, 'post', fake_post)
    out = chat_nostream('http://x/v1/chat/completions', 'tok', 'dsv4', [{'role': 'user', 'content': 'hi'}],
                        tools=None, backend='requests')
    assert out == {'content': 'hi', 'tool_calls': None}
    assert captured['url'] == llm_module._LITELLM_CHAT_ENDPOINT
    assert captured['payload']['model'] == 'dsv4'
    assert captured['headers']['Authorization'] == 'Bearer tok'


def test_requests_nostream_tools_attached(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured['payload'] = json
        return _FakeResp({'choices': [{'message': {'content': '', 'tool_calls': None}}]})

    monkeypatch.setattr(llm_module.requests, 'post', fake_post)
    tools = [{'type': 'function', 'function': {'name': 'ping'}}]
    chat_nostream('http://x', 't', 'm', [], tools=tools, backend='requests')
    assert captured['payload']['tools'] == tools
    assert captured['payload']['tool_choice'] == 'auto'


def test_requests_nostream_http_error(monkeypatch):
    monkeypatch.setattr(llm_module.requests, 'post', lambda *a, **k: _FakeResp('boom', status=500))
    with pytest.raises(LLMError) as ei:
        chat_nostream('http://x', '', 'm', [], backend='requests')
    assert 'HTTP 500' in str(ei.value)
    assert ei.value.http_status == 500


def test_requests_stream_yields_deltas(monkeypatch):
    lines = [
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        b'data: {"choices":[{"delta":{"content":"lo"}}]}',
        b'data: [DONE]',
    ]
    monkeypatch.setattr(llm_module.requests, 'post', lambda *a, **k: _FakeResp(lines, status=200, stream=True))
    assert list(chat_stream('http://x', '', 'm', [], backend='requests')) == ['Hel', 'lo']


def test_requests_probe_accepts_tools(monkeypatch):
    monkeypatch.setattr(llm_module.requests, 'post', lambda *a, **k: _FakeResp({'choices': [1]}))
    assert probe_tool_support('http://x', '', 'm', backend='requests') is True


class _FakeResp:
    """Stand-in for a ``requests.Response``."""

    def __init__(self, body, status=200, stream=False):
        self._body = body
        self.status_code = status
        self.text = body if isinstance(body, str) else 'boom'
        self._stream = stream

    def json(self):
        return self._body

    def iter_lines(self):
        return iter(self._body)


# ---------------------------------------------------------------------------
# OpenAI SDK backend (LiteLLM proxy)
# ---------------------------------------------------------------------------

class _OpenAIFake:
    """Minimal stand-in for the ``openai`` module (instance-based mutable)."""

    class APITimeoutError(Exception):
        pass

    class RateLimitError(Exception):
        pass

    class AuthenticationError(Exception):
        pass

    class BadRequestError(Exception):
        pass

    class APIConnectionError(Exception):
        pass

    last_client = None

    def __init__(self):
        self.completion_response = None
        self.completion_raised = None
        self.call_kwargs = None
        self.clients = []

    class _Completions:
        def create(self, **kwargs):
            client = _OpenAIFake.last_client
            fake = client._fake
            fake.call_kwargs = kwargs
            if fake.completion_raised:
                raise fake.completion_raised
            return fake.completion_response

    class _Chat:
        def __init__(self, completions):
            self.completions = completions

    def OpenAI(self, base_url=None, api_key=None, max_retries=0):
        client = _FakeClient(base_url, api_key, max_retries, self)
        self.clients.append(client)
        _OpenAIFake.last_client = client
        return client


class _FakeClient:
    def __init__(self, base_url, api_key, max_retries, fake):
        self.base_url = base_url
        self.api_key = api_key
        self.max_retries = max_retries
        self._fake = fake
        self.chat = _OpenAIFake._Chat(_OpenAIFake._Completions())


class _Msg:
    def __init__(self, content='', tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, message):
        self.message = message


class _Resp:
    def __init__(self, message):
        self.choices = [_Choice(message)]


def _mk_nostream_response(content='hi', tool_calls=None):
    return _Resp(_Msg(content=content, tool_calls=tool_calls))


def test_openai_nostream_success(monkeypatch):
    fake = _OpenAIFake()
    fake.completion_response = _mk_nostream_response(content='hi from proxy')
    monkeypatch.setattr(llm_module, 'openai', fake)

    out = chat_nostream('https://upstream.example/v1', 'tok', 'dsv4',
                        [{'role': 'user', 'content': 'hi'}], backend='openai')
    assert out == {'content': 'hi from proxy', 'tool_calls': None}
    client = fake.clients[0]
    # The SDK always talks to the self-hosted LiteLLM Proxy, never to the
    # upstream config passed in.
    assert client.base_url == llm_module.LITELLM_PROXY_URL + '/v1'
    assert client.api_key == 'tok'
    assert fake.call_kwargs['model'] == 'dsv4'


def test_openai_nostream_ignores_upstream_url(monkeypatch):
    fake = _OpenAIFake()
    fake.completion_response = _mk_nostream_response(content='ok')
    monkeypatch.setattr(llm_module, 'openai', fake)

    chat_nostream('https://farfaraway.example/v2', '', 'm', [], backend='openai')
    assert fake.clients[0].base_url == llm_module.LITELLM_PROXY_URL + '/v1'


def test_openai_nostream_tool_calls(monkeypatch):
    class _Fn:
        name = 'run_cell'
        arguments = '{"code": "1+1"}'

    class _TC:
        id = 'call_9'
        type = 'function'
        function = _Fn()

    fake = _OpenAIFake()
    fake.completion_response = _mk_nostream_response(content='', tool_calls=[_TC()])
    monkeypatch.setattr(llm_module, 'openai', fake)

    out = chat_nostream('http://x', 't', 'm', [], tools=[{'x': 1}], backend='openai')
    assert out['content'] == ''
    assert out['tool_calls'][0]['id'] == 'call_9'
    assert out['tool_calls'][0]['function']['name'] == 'run_cell'
    assert fake.call_kwargs['tool_choice'] == 'auto'


def test_openai_nostream_maps_errors(monkeypatch):
    fake = _OpenAIFake()
    cases = [
        (fake.APITimeoutError('slow'), '超时'),
        (fake.RateLimitError('429'), '限流'),
        (fake.AuthenticationError('401'), '鉴权失败'),
        (fake.BadRequestError('400'), '被拒绝'),
        (fake.APIConnectionError('down'), '无法连接'),
    ]
    for exc, expected in cases:
        fake.completion_raised = exc
        monkeypatch.setattr(llm_module, 'openai', fake)
        with pytest.raises(LLMError) as ei:
            chat_nostream('http://x', '', 'm', [], backend='openai')
        assert expected in str(ei.value)


def test_openai_stream(monkeypatch):
    class _Delta:
        content = 'Hel'

    class _StreamChoice:
        delta = _Delta()

    class _Chunk:
        choices = [_StreamChoice()]

    fake = _OpenAIFake()
    fake.completion_response = iter([_Chunk()])
    monkeypatch.setattr(llm_module, 'openai', fake)

    assert list(chat_stream('http://x', '', 'm', [], backend='openai')) == ['Hel']
    assert fake.call_kwargs['stream'] is True


def test_openai_probe(monkeypatch):
    fake = _OpenAIFake()
    fake.completion_response = _mk_nostream_response()
    monkeypatch.setattr(llm_module, 'openai', fake)

    assert probe_tool_support('http://x', '', 'm', backend='openai') is True


# ---------------------------------------------------------------------------
# transport-neutral dispatch
# ---------------------------------------------------------------------------

def test_auto_dispatch_prefers_openai_sdk_when_available(monkeypatch):
    import core.llm as m

    called = []

    def fake_openai(url, token, model, messages, tools=None, timeout=60):
        called.append('openai')
        return {'content': 'ok', 'tool_calls': None}

    def fake_req(url, token, model, messages, tools=None, timeout=60):
        called.append('requests')
        return {'content': 'ok', 'tool_calls': None}

    monkeypatch.setattr(m, 'is_openai_sdk_enabled', lambda: True)
    monkeypatch.setattr(m, '_openai_nostream', fake_openai)
    monkeypatch.setattr(m, '_requests_nostream', fake_req)

    chat_nostream('http://x', '', 'm', [])
    assert called == ['openai']

    chat_nostream('http://x', '', 'm', [], backend='requests')
    assert called == ['openai', 'requests']


def test_use_openai_sdk_env_overrides(monkeypatch):
    monkeypatch.setattr(llm_module, 'OPENAI_AVAILABLE', False)
    monkeypatch.setenv('USE_OPENAI_SDK', '0')
    assert llm_module.is_openai_sdk_enabled() is False
    monkeypatch.setenv('USE_OPENAI_SDK', 'true')
    assert llm_module.is_openai_sdk_enabled() is False
    monkeypatch.setattr(llm_module, 'OPENAI_AVAILABLE', True)
    assert llm_module.is_openai_sdk_enabled() is True
