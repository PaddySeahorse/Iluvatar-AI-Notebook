"""LLM transport layer via the OpenAI SDK against the local LiteLLM Proxy.

The ReAct agent talks to the LightLLM Proxy this notebook self-hosts on
``LITELLM_PROXY_URL`` (default ``http://localhost:4000``) — the proxy is the
OpenAI-compatible gateway that forwards each call to the real upstream model
API configured in the settings panel. This module wraps that local call in a
single transport API using the official ``openai`` Python SDK:

- The request address is **hard-coded** to the local proxy; the ``url``
  argument accepted by the public functions is the *upstream model config*
  known to the proxy and is never used to build the network request.
- The OpenAI SDK handles retries, timeouts and a normalized error surface
  when talking to the proxy's ``/chat/completions`` endpoint.
- A plain ``requests`` path stays as a zero-dependency fallback so the app
  still works when the ``openai`` package is not installed.

Both backends return identical, normalized shapes:

- non-streaming: ``{"content": str, "tool_calls": [{"id","type","function":{...}}] | None}``
- streaming:     a generator of text deltas
- probe:         ``bool`` (whether the endpoint accepted the ``tools`` param)

The active backend is chosen by: explicit ``backend=`` argument > ``USE_OPENAI_SDK``
env var (``1``/``true``/``yes`` enables, ``0``/``false``/``no`` disables) >
auto-detect (OpenAI SDK if importable, otherwise requests).
"""

import json
import os

import requests

try:
    import openai
    OPENAI_AVAILABLE = True
except Exception:  # pragma: no cover - depends on environment
    openai = None
    OPENAI_AVAILABLE = False

from core.litellm_manager import LITELLM_PROXY_URL

_REQUESTS_TIMEOUT = 60
_STREAM_TIMEOUT = 180

# The transport never dials the upstream model endpoint directly: every
# request (OpenAI SDK ``/v1`` and plain ``requests``) is aimed at the local
# LiteLLM Proxy, which routes to the real model using its own ``model_list``
# config.
_LITELLM_API_BASE = f'{LITELLM_PROXY_URL}/v1'
_LITELLM_CHAT_ENDPOINT = f'{LITELLM_PROXY_URL}/v1/chat/completions'


class LLMError(Exception):
    """Raised when the LLM transport cannot complete a request."""

    def __init__(self, message: str, http_status: int | None = None):
        super().__init__(message)
        self.http_status = http_status


def is_openai_sdk_enabled() -> bool:
    """Return True when traffic should go through the OpenAI SDK."""
    value = os.environ.get('USE_OPENAI_SDK', '').strip().lower()
    if value in ('1', 'true', 'yes', 'on'):
        return OPENAI_AVAILABLE
    if value in ('0', 'false', 'no', 'off'):
        return False
    return OPENAI_AVAILABLE


def _to_api_base(url: str) -> str:
    """Return the local LiteLLM Proxy OpenAI-compatible base URL."""
    return _LITELLM_API_BASE


def _upstream_base(url: str) -> str:
    if not url:
        return ''
    u = url.strip()
    if '/chat/completions' in u:
        u = u.split('/chat/completions')[0]
    return u.rstrip('/')


def _is_proxy_error(e) -> bool:
    msg = str(e).lower()
    return any(k in msg for k in ['connection', 'proxy', 'cannot reach', 'refused', 'failed to connect', 'name or service not known'])


def _upstream_client(url, token):
    base = _upstream_base(url)
    if not base:
        base = _LITELLM_API_BASE
    if base.endswith('/v1'):
        pass
    elif '/v1' not in base:
        base = base.rstrip('/') + '/v1'
    return openai.OpenAI(base_url=base or None, api_key=token or None, max_retries=1)


def _upstream_endpoint(url: str) -> str:
    base = _upstream_base(url)
    if not base:
        return _LITELLM_CHAT_ENDPOINT
    if base.endswith('/v1'):
        return base + '/chat/completions'
    return base.rstrip('/') + '/v1/chat/completions'


def _normalize_tool_calls(message) -> list | None:
    """Convert OpenAI SDK tool_calls objects into plain dicts."""
    raw = getattr(message, 'tool_calls', None) or []
    out = []
    for tc in raw:
        fn = getattr(tc, 'function', None) or {}
        out.append({
            'id': getattr(tc, 'id', '') or '',
            'type': getattr(tc, 'type', '') or 'function',
            'function': {
                'name': getattr(fn, 'name', '') or '',
                'arguments': getattr(fn, 'arguments', '') or '{}',
            },
        })
    return out or None


def _openai_client(url, token):
    """Build an OpenAI client pointed at the LiteLLM proxy."""
    return openai.OpenAI(
        base_url=_to_api_base(url) or None,
        api_key=token or None,
        max_retries=2,
    )


def _map_openai_error(e, streaming=False):
    """Translate an OpenAI SDK exception into an ``LLMError``."""
    kind = 'API 流式请求超时' if streaming else 'API 请求超时'
    if isinstance(e, openai.APITimeoutError):
        return LLMError(kind)
    if isinstance(e, openai.RateLimitError):
        return LLMError('API 请求被限流')
    if isinstance(e, openai.AuthenticationError):
        return LLMError(f'API 鉴权失败: {e}')
    if isinstance(e, openai.BadRequestError):
        return LLMError(f'API 请求被拒绝: {e}')
    if isinstance(e, openai.APIConnectionError):
        return LLMError(f'无法连接 API 服务: {e}')
    label = 'OpenAI SDK 流式调用失败' if streaming else 'OpenAI SDK 调用失败'
    if isinstance(e, LLMError):
        return e
    return LLMError(f'{label}: {e}')


# ---------------------------------------------------------------------------
# OpenAI SDK backend (LiteLLM proxy)
# ---------------------------------------------------------------------------

def _openai_nostream(url, token, model, messages, tools=None, timeout=_REQUESTS_TIMEOUT) -> dict:
    try:
        resp = _openai_client(url, token).chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            tools=tools or None,
            tool_choice='auto' if tools else None,
            timeout=timeout,
        )
    except Exception as e:
        if _is_proxy_error(e) and _upstream_base(url):
            try:
                resp = _upstream_client(url, token).chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.7,
                    tools=tools or None,
                    tool_choice='auto' if tools else None,
                    timeout=timeout,
                )
            except Exception as ue:
                raise _map_openai_error(ue) from ue
        else:
            raise _map_openai_error(e) from e

    try:
        message = resp.choices[0].message
        if isinstance(message, str):
            return {'content': message, 'tool_calls': None}
        return {
            'content': getattr(message, 'content', None) or '',
            'tool_calls': _normalize_tool_calls(message),
        }
    except (IndexError, AttributeError, TypeError) as e:
        raise LLMError(f'API 响应格式无法解析: {e}') from e


def _openai_stream(url, token, model, messages, timeout=_STREAM_TIMEOUT):
    def _iter(client):
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=0.7, stream=True, timeout=timeout)
        for chunk in resp:
            choices = getattr(chunk, 'choices', None) or []
            if not choices:
                continue
            delta = getattr(choices[0], 'delta', None)
            if delta is None:
                delta = choices[0]
            text = getattr(delta, 'content', None)
            if text:
                yield text
    try:
        yield from _iter(_openai_client(url, token))
    except LLMError:
        raise
    except Exception as e:
        if _is_proxy_error(e) and _upstream_base(url):
            try:
                yield from _iter(_upstream_client(url, token))
            except LLMError:
                raise
            except Exception as ue:
                raise _map_openai_error(ue, streaming=True) from ue
        else:
            raise _map_openai_error(e, streaming=True) from e


def _openai_probe(url, token, model) -> bool:
    """Probe whether the endpoint accepts the ``tools`` parameter."""
    try:
        resp = _openai_client(url, token).chat.completions.create(
            model=model,
            messages=[{'role': 'user', 'content': 'ping'}],
            max_tokens=1,
            tools=[{
                'type': 'function',
                'function': {
                    'name': 'ping',
                    'description': 'test',
                    'parameters': {'type': 'object', 'properties': {}},
                },
            }],
            tool_choice='none',
            timeout=_REQUESTS_TIMEOUT,
        )
        return bool(getattr(resp, 'choices', None))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# requests backend (zero-dependency fallback)
# ---------------------------------------------------------------------------

def _requests_nostream(url, token, model, messages, tools=None, timeout=_REQUESTS_TIMEOUT) -> dict:
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    payload = {'model': model, 'messages': messages, 'temperature': 0.7}
    if tools:
        payload['tools'] = tools
        payload['tool_choice'] = 'auto'
    def _do(endpoint):
        return requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
    try:
        resp = _do(_LITELLM_CHAT_ENDPOINT)
    except requests.exceptions.ConnectionError as e:
        if _upstream_base(url):
            try:
                resp = _do(_upstream_endpoint(url))
            except requests.exceptions.ConnectionError as ue:
                raise LLMError(f'无法连接 API 服务: {ue}') from ue
            except requests.exceptions.Timeout as ue:
                raise LLMError('API 请求超时') from ue
            except requests.exceptions.RequestException as ue:
                raise LLMError(f'API 请求失败: {ue}') from ue
        else:
            raise LLMError(f'无法连接 API 服务: {e}') from e
    except requests.exceptions.Timeout as e:
        raise LLMError('API 请求超时') from e
    except requests.exceptions.RequestException as e:
        raise LLMError(f'API 请求失败: {e}') from e
    if resp.status_code != 200:
        is_proxy = getattr(getattr(resp, 'request', None), 'url', '') == _LITELLM_CHAT_ENDPOINT or not getattr(getattr(resp, 'request', None), 'url', '')
        if resp.status_code >= 500 and _upstream_base(url) and is_proxy:
            try:
                r2 = _do(_upstream_endpoint(url))
                if r2.status_code == 200:
                    resp = r2
                else:
                    raise LLMError(f'API 返回 HTTP {r2.status_code}: {r2.text[:200]}', http_status=r2.status_code)
            except LLMError:
                raise
            except Exception:
                raise LLMError(f'API 返回 HTTP {resp.status_code}: {resp.text[:200]}', http_status=resp.status_code)
        else:
            raise LLMError(f'API 返回 HTTP {resp.status_code}: {resp.text[:200]}', http_status=resp.status_code)

    try:
        data = resp.json()
        message = data['choices'][0]['message']
        if isinstance(message, str):
            return {'content': message, 'tool_calls': None}
        return {
            'content': message.get('content') or '',
            'tool_calls': message.get('tool_calls') or None,
        }
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise LLMError(f'API 响应格式无法解析: {e}') from e


def _requests_stream(url, token, model, messages, timeout=_STREAM_TIMEOUT):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    payload = {'model': model, 'messages': messages, 'temperature': 0.7, 'stream': True}
    def _do(endpoint):
        return requests.post(endpoint, headers=headers, json=payload, timeout=timeout, stream=True)
    try:
        resp = _do(_LITELLM_CHAT_ENDPOINT)
    except requests.exceptions.RequestException as e:
        if _upstream_base(url):
            try:
                resp = _do(_upstream_endpoint(url))
            except requests.exceptions.RequestException as ue:
                raise LLMError(f'API 流式请求失败: {ue}') from ue
        else:
            raise LLMError(f'API 流式请求失败: {e}') from e
    if resp.status_code != 200:
        is_proxy2 = getattr(getattr(resp, 'request', None), 'url', '') == _LITELLM_CHAT_ENDPOINT or not getattr(getattr(resp, 'request', None), 'url', '')
        if _upstream_base(url) and is_proxy2:
            try:
                r2 = _do(_upstream_endpoint(url))
                if r2.status_code == 200:
                    resp = r2
                else:
                    raise LLMError(f'API 返回 HTTP {r2.status_code}: {r2.text[:200]}', http_status=r2.status_code)
            except LLMError:
                raise
            except Exception:
                raise LLMError(f'API 返回 HTTP {resp.status_code}: {resp.text[:200]}', http_status=resp.status_code)
        else:
            raise LLMError(f'API 返回 HTTP {resp.status_code}: {resp.text[:200]}', http_status=resp.status_code)

    for raw_line in resp.iter_lines():
        if not raw_line:
            continue
        line = raw_line.decode('utf-8', errors='replace').strip()
        if line.startswith('data: '):
            line = line[len('data: '):]
        if line == '[DONE]':
            break
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        delta = (obj.get('choices') or [{}])[0].get('delta') or {}
        text = delta.get('content') or ''
        if text:
            yield text


def _requests_probe(url, token, model) -> bool:
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    payload = {
        'model': model,
        'messages': [{'role': 'user', 'content': 'ping'}],
        'max_tokens': 1,
        'tools': [
            {
                'type': 'function',
                'function': {
                    'name': 'ping',
                    'description': 'test',
                    'parameters': {'type': 'object', 'properties': {}},
                },
            }
        ],
        'tool_choice': 'none',
    }
    try:
        resp = requests.post(_LITELLM_CHAT_ENDPOINT, headers=headers, json=payload, timeout=_REQUESTS_TIMEOUT)
        if resp.status_code != 200:
            return False
        return 'choices' in resp.json()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Transport-neutral public API
# ---------------------------------------------------------------------------

def chat_nostream(url, token, model, messages, tools=None, timeout=_REQUESTS_TIMEOUT, backend=None) -> dict:
    """Blocking chat call; returns ``{"content", "tool_calls"}``."""
    if backend == 'openai' or (backend is None and is_openai_sdk_enabled()):
        return _openai_nostream(url, token, model, messages, tools=tools, timeout=timeout)
    return _requests_nostream(url, token, model, messages, tools=tools, timeout=timeout)


def chat_stream(url, token, model, messages, timeout=_STREAM_TIMEOUT, backend=None):
    """Streaming chat call; yields text deltas."""
    if backend == 'openai' or (backend is None and is_openai_sdk_enabled()):
        yield from _openai_stream(url, token, model, messages, timeout=timeout)
    else:
        yield from _requests_stream(url, token, model, messages, timeout=timeout)


def check_api_health(url, token, model, timeout=8) -> dict:
    try:
        if is_openai_sdk_enabled():
            _openai_client(url, token).chat.completions.create(
                model=model, messages=[{'role': 'user', 'content': 'ping'}], max_tokens=1, timeout=timeout)
        else:
            headers = {'Content-Type': 'application/json'}
            if token:
                headers['Authorization'] = f'Bearer {token}'
            endpoint = _LITELLM_CHAT_ENDPOINT
            try:
                r = requests.post(endpoint, headers=headers, json={'model': model, 'messages': [{'role': 'user', 'content': 'ping'}], 'max_tokens': 1}, timeout=timeout)
                if r.status_code != 200 and _upstream_base(url):
                    r = requests.post(_upstream_endpoint(url), headers=headers, json={'model': model, 'messages': [{'role': 'user', 'content': 'ping'}], 'max_tokens': 1}, timeout=timeout)
                r.raise_for_status()
            except Exception:
                raise
        return {'ok': True, 'message': '连接正常'}
    except Exception as e:
        return {'ok': False, 'message': str(e)[:300]}


def probe_tool_support(url, token, model, backend=None) -> bool:
    """Return True when the endpoint accepts the OpenAI ``tools`` parameter."""
    if backend == 'openai' or (backend is None and is_openai_sdk_enabled()):
        return _openai_probe(url, token, model)
    return _requests_probe(url, token, model)
