"""Unit tests for the LLM transport layer (core/llm.py).

Both backends (LiteLLM and the plain requests fallback) are exercised with
injected fakes so no network is needed.  Also covers the URL/model
normalization helpers and the transport-neutral public API.
"""

import pytest

from core import llm as llm_module
from core.llm import LLMError, chat_nostream, chat_stream, probe_tool_support


# ---------------------------------------------------------------------------
# normalization helpers
# ---------------------------------------------------------------------------

def test_to_api_base_strips_chat_suffix():
    assert llm_module._to_api_base('https://x.com/v1/chat/completions') == 'https://x.com/v1'
    assert llm_module._to_api_base('https://x.com/v1/') == 'https://x.com/v1'
    assert llm_module._to_api_base('https://x.com') == 'https://x.com'


def test_to_litellm_model_prefixes_openai():
    assert llm_module._to_litellm_model('dsv4') == 'openai/dsv4'
    assert llm_module._to_litellm_model('openai/gpt-4o') == 'openai/gpt-4o'
    with pytest.raises(LLMError):
        llm_module._to_litellm_model('')


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
    assert captured['url'] == 'http://x/v1/chat/completions'
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
# LiteLLM backend
# ---------------------------------------------------------------------------

class _LiteLLMFake:
    """Minimal stand-in for the ``litellm`` module (instance-based mutable)."""

    class exceptions:
        class Timeout(Exception):
            pass

        class RateLimitError(Exception):
            pass

        class AuthenticationError(Exception):
            pass

        class BadRequestError(Exception):
            pass

    def __init__(self):
        self.completion_response = None
        self.completion_raised = None
        self.call_kwargs = None

    def completion(self, **kwargs):
        self.call_kwargs = kwargs
        if self.completion_raised:
            raise self.completion_raised
        return self.completion_response


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


def test_litellm_nostream_success(monkeypatch):
    fake = _LiteLLMFake()
    fake.completion_response = _mk_nostream_response(content='hi from lite')
    monkeypatch.setattr(llm_module, 'litellm', fake)

    out = chat_nostream('https://x.com/v1/chat/completions', 'tok', 'dsv4',
                        [{'role': 'user', 'content': 'hi'}], backend='litellm')
    assert out == {'content': 'hi from lite', 'tool_calls': None}
    assert fake.call_kwargs['model'] == 'openai/dsv4'
    assert fake.call_kwargs['api_base'] == 'https://x.com/v1'
    assert fake.call_kwargs['api_key'] == 'tok'


def test_litellm_nostream_tool_calls(monkeypatch):
    class _Fn:
        name = 'run_cell'
        arguments = '{"code": "1+1"}'

    class _TC:
        id = 'call_9'
        type = 'function'
        function = _Fn()

    fake = _LiteLLMFake()
    fake.completion_response = _mk_nostream_response(content='', tool_calls=[_TC()])
    monkeypatch.setattr(llm_module, 'litellm', fake)

    out = chat_nostream('http://x', 't', 'openai/m', [], tools=[{'x': 1}], backend='litellm')
    assert out['content'] == ''
    assert out['tool_calls'][0]['id'] == 'call_9'
    assert out['tool_calls'][0]['function']['name'] == 'run_cell'


def test_litellm_nostream_maps_errors(monkeypatch):
    fake = _LiteLLMFake()
    fake.completion_raised = fake.exceptions.Timeout('slow')
    monkeypatch.setattr(llm_module, 'litellm', fake)

    with pytest.raises(LLMError) as ei:
        chat_nostream('http://x', '', 'm', [], backend='litellm')
    assert '超时' in str(ei.value)


def test_litellm_stream(monkeypatch):
    class _Delta:
        content = 'Hel'

    class _StreamChoice:
        delta = _Delta()

    class _Chunk:
        choices = [_StreamChoice()]

    fake = _LiteLLMFake()
    fake.completion_response = iter([_Chunk()])
    monkeypatch.setattr(llm_module, 'litellm', fake)

    assert list(chat_stream('http://x', '', 'm', [], backend='litellm')) == ['Hel']
    assert fake.call_kwargs['stream'] is True


def test_litellm_probe(monkeypatch):
    fake = _LiteLLMFake()
    fake.completion_response = _mk_nostream_response()
    monkeypatch.setattr(llm_module, 'litellm', fake)

    assert probe_tool_support('http://x', '', 'm', backend='litellm') is True


# ---------------------------------------------------------------------------
# transport-neutral dispatch
# ---------------------------------------------------------------------------

def test_auto_dispatch_prefers_litellm_when_available(monkeypatch):
    import core.llm as m

    called = []

    def fake_lite(url, token, model, messages, tools=None, timeout=60):
        called.append('litellm')
        return {'content': 'ok', 'tool_calls': None}

    def fake_req(url, token, model, messages, tools=None, timeout=60):
        called.append('requests')
        return {'content': 'ok', 'tool_calls': None}

    monkeypatch.setattr(m, 'is_litellm_enabled', lambda: True)
    monkeypatch.setattr(m, '_litellm_nostream', fake_lite)
    monkeypatch.setattr(m, '_requests_nostream', fake_req)

    chat_nostream('http://x', '', 'm', [])
    assert called == ['litellm']

    chat_nostream('http://x', '', 'm', [], backend='requests')
    assert called == ['litellm', 'requests']