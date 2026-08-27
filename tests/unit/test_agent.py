"""Unit tests for the ReAct agent loop (core/agent.py).

The agent is exercised with injected fake LLM transports so no network or
real kernel is needed. Both protocols (function calling and the text-JSON
fallback) and the step-cap guard are covered.
"""

import pytest

from core import agent as agent_module
from core.agent import agent_loop


class _FakeKM:
    """Minimal kernel manager double for agent tool wiring."""

    def __init__(self):
        self._vars = [{'name': 'x', 'type': 'int', 'repr': '1', 'shape': None}]
        self._errors = [{'title': 'NameError: foo', 'summary': 'Traceback ... foo is not defined'}]

    def get_variables(self):
        return list(self._vars)

    def set_variables(self, variables):
        self._vars = list(variables)

    def fetch_recent_outputs(self, n=6):
        return {'1': 'x = 1'}

    def get_recent_errors(self):
        return list(self._errors)

    def execute(self, code):
        return {'success': True, 'stdout': '42', 'stderr': '', 'html': '', 'plots': [], 'variables': []}

    def is_kernel_alive(self):
        return True

    def is_watchdog_alive(self):
        return True


class _State:
    """Mirrors the app entry-point module's attribute access."""

    def __init__(self, **overrides):
        self.kernel_manager = _FakeKM()
        self.WORKSPACE_DIR = '/tmp'
        self.is_safe_path = lambda path: not path.startswith('/')
        for k, v in overrides.items():
            setattr(self, k, v)


def _state(**overrides):
    return _State(**overrides)


@pytest.fixture()
def no_tool_probe(monkeypatch):
    monkeypatch.setattr(agent_module, 'probe_tool_support', lambda *a, **k: True)
    return agent_module


def _run(monkeypatch, *, nostream_replies, stream_chunks=('Hello', ' world'), probe=True,
         max_steps=6, include_context=False, query='帮我检查变量'):
    """Run the agent loop with fully mocked LLM transports; return events list."""
    calls = []

    def fake_nostream(url, token, model, messages, tools, timeout=60, backend=None):
        calls.append(('nostream', url, token, model, bool(tools), len(messages)))
        return nostream_replies[len(calls) - 1]

    def fake_stream(url, token, model, messages, timeout=180, backend=None):
        yield from stream_chunks

    monkeypatch.setattr(agent_module, 'probe_tool_support', lambda *a, **k: probe)
    monkeypatch.setattr(agent_module, '_chat_nostream', fake_nostream)
    monkeypatch.setattr(agent_module, '_chat_stream', fake_stream)

    events = list(agent_loop(
        url='http://x/v1/chat/completions',
        token='t',
        model='m',
        history=[],
        query=query,
        include_context=include_context,
        state_module=_state(),
        max_steps=max_steps,
        use_tools_probe=probe,
    ))
    return events, calls


def test_function_calling_round_trip(monkeypatch):
    reply_tool = {
        'content': '',
        'tool_calls': [
            {'id': 'call_1', 'type': 'function', 'function': {'name': 'run_cell', 'arguments': '{"code": "print(1)"}'}}
        ],
    }
    reply_final = {'content': '执行结果已返回', 'tool_calls': None}

    events, calls = _run(
        monkeypatch,
        nostream_replies=[reply_tool, reply_final],
        stream_chunks=['执行', '结果', '已返回'],
    )

    types = [e['type'] for e in events]
    # tool_call round (nostream) + final-answer round (nostream content).
    assert types == ['status', 'tool_call', 'tool_result', 'content', 'done']
    assert events[1]['name'] == 'run_cell'
    assert events[1]['arguments'] == {'code': 'print(1)'}
    assert events[2]['ok'] is True
    assert events[2]['summary'].startswith('42')
    assert events[3]['text'] == '执行结果已返回'
    assert events[-1]['final'] == '执行结果已返回'
    assert len(calls) == 2

    # Every nostream decision round carries the function schemas in
    # function-calling mode.
    assert calls[0][4] is True
    assert calls[1][4] is True


def test_text_protocol_fallback(monkeypatch):
    # Text-protocol mode streams the reply directly; no separate re-stream.
    events, calls = _run(
        monkeypatch,
        nostream_replies=[],
        stream_chunks=['GPU', ' 正常'],
        probe=False,
    )

    types = [e['type'] for e in events]
    # status -> stream deltas -> done. No tool_call because the streamed text
    # is plain (no embedded ACTION JSON).
    assert types == ['status', 'content', 'content', 'done']
    assert events[1]['text'] == 'GPU'
    assert events[2]['text'] == ' 正常'
    assert events[-1]['final'] == 'GPU 正常'
    # _chat_nostream should not be called in text mode.
    assert calls == []


def test_max_steps_guard(monkeypatch):
    reply_tool = {
        'content': '',
        'tool_calls': [
            {'id': 'c', 'type': 'function', 'function': {'name': 'get_variables', 'arguments': '{}'}}
        ],
    }

    events, _ = _run(monkeypatch, nostream_replies=[reply_tool] * 10, probe=True, max_steps=2)

    types = [e['type'] for e in events]
    assert types.count('tool_call') == 2
    assert 'error' in types
    assert types[-1] == 'done'


def test_llm_failure_yields_error_event(monkeypatch):
    def failing(url, token, model, messages, tools, timeout=60, backend=None):
        raise agent_module.AgentError('API 返回 HTTP 500: boom')

    monkeypatch.setattr(agent_module, 'probe_tool_support', lambda *a, **k: True)
    monkeypatch.setattr(agent_module, '_chat_nostream', failing)

    events = list(agent_loop(
        url='http://x', token='t', model='m', history=[], query='hi',
        include_context=False, state_module=_state(), use_tools_probe=True,
    ))

    assert [e['type'] for e in events] == ['status', 'error', 'done']
    assert 'HTTP 500' in events[1]['message']


def test_system_prompt_includes_structured_context(monkeypatch):
    captured = {}

    def fake_stream(url, token, model, messages, timeout=180, backend=None):
        captured['messages'] = messages
        return
        yield  # pragma: no cover - makes this a generator

    monkeypatch.setattr(agent_module, 'probe_tool_support', lambda *a, **k: False)
    monkeypatch.setattr(agent_module, '_chat_stream', fake_stream)

    list(agent_loop(
        url='http://x', token='t', model='m', history=[],
        query='hi', include_context=True, state_module=_state(), use_tools_probe=False,
    ))

    sys_prompt = captured['messages'][0]['content']
    assert 'x (int)' in sys_prompt
    assert 'Out 1] x = 1' in sys_prompt
    assert 'NameError: foo' in sys_prompt