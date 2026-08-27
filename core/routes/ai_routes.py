"""AI proxy routes: default config exposure and upstream LLM calls."""

import json
import os

import requests
from flask import Blueprint, request, jsonify, Response

from core.errors import UpstreamAPIError
from core.routes import state
from core.user_config import save_model_config
from core import llm as llm_transport

bp = Blueprint('ai', __name__)


@bp.route('/api/get_config', methods=['GET'])
def get_config():
    # Expose defaults loaded from env for initialization
    s = state()
    return jsonify({
        'default_url': s.DEFAULT_API_URL,
        'default_model': s.DEFAULT_API_MODEL
    })


@bp.route('/api/save_config', methods=['POST'])
def save_config():
    """Persist the user-provided LLM API config on the host machine.

    Request: ``{"url": "...", "token": "...", "model": "..."}``

    The values are written to the ``OPENI_API_URL`` / ``OPENI_API_TOKEN`` /
    ``OPENI_API_MODEL`` keys of ``~/.Iluvatar-AI-Notebook/config.yaml``
    (other tracked keys are preserved), and the in-memory runtime defaults +
    ``os.environ`` are updated at the same time so the new config takes
    effect without a restart.
    """
    s = state()
    data = request.json or {}
    url = str(data.get('url') or '').strip()
    token = str(data.get('token') or '').strip()
    model = str(data.get('model') or '').strip()

    if not url or not model:
        return jsonify({
            'error': True,
            'error_code': 'INVALID_CONFIG',
            'message': 'API URL 与模型名称不能为空',
        }), 400

    try:
        save_model_config(url, token, model)
    except OSError as e:
        return jsonify({
            'error': True,
            'error_code': 'CONFIG_WRITE_ERROR',
            'message': f'写入配置文件失败: {e}',
        }), 500

    # Make the config effective immediately (no restart needed).
    s.DEFAULT_API_URL = url
    s.DEFAULT_API_TOKEN = token
    s.DEFAULT_API_MODEL = model
    os.environ['OPENI_API_URL'] = url
    os.environ['OPENI_API_TOKEN'] = token
    os.environ['OPENI_API_MODEL'] = model

    return jsonify({'ok': True, 'message': 'API 配置已保存'})


@bp.route('/api/ai_call', methods=['POST'])
def ai_call():
    s = state()
    data = request.json or {}
    url = data.get('url') or s.DEFAULT_API_URL
    token = data.get('token') or s.DEFAULT_API_TOKEN
    model = data.get('model') or s.DEFAULT_API_MODEL
    messages = data.get('messages', [])
    stream = data.get('stream', False)
    temperature = data.get('temperature', 0.7)
    max_tokens = data.get('max_tokens')
    backend = data.get('backend')

    try:
        if stream:
            # Stream tokens as OpenAI-style `data:` SSE events.
            def generate():
                try:
                    for chunk in llm_transport.chat_stream(
                        url, token, model, messages, backend=backend,
                    ):
                        yield 'data: {"choices":[{"delta":{"content":' + json.dumps(chunk, ensure_ascii=False) + '}}]}\n\n'
                    yield 'data: [DONE]\n\n'
                except llm_transport.LLMError as e:
                    yield 'data: ' + json.dumps({"error": True, "message": str(e)}, ensure_ascii=False) + '\n\n'
            return Response(generate(), mimetype='text/event-stream', headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
            })
        payload = {
            'model': model,
            'messages': messages,
            'temperature': temperature,
        }
        if max_tokens is not None:
            payload['max_tokens'] = max_tokens
        result = llm_transport.chat_nostream(
            url, token, model, messages, backend=backend,
        )
        return jsonify(result)
    except llm_transport.LLMError as e:
        raise UpstreamAPIError(
            f"Upstream API error: {e}", error_code='UPSTREAM_API_ERROR',
            status_code=e.http_status or 502,
        ) from e
    except requests.exceptions.ConnectionError as e:
        raise UpstreamAPIError(
            f'Cannot reach API server at "{url}": connection refused or DNS failure.',
            error_code='UPSTREAM_CONNECTION_ERROR', status_code=502,
        ) from e
    except requests.exceptions.Timeout as e:
        raise UpstreamAPIError(
            f'Request to "{url}" timed out.', error_code='UPSTREAM_TIMEOUT',
            status_code=504,
        ) from e
    except requests.exceptions.RequestException as e:
        raise UpstreamAPIError(
            f'Unexpected error communicating with API server: {e}',
            error_code='UPSTREAM_REQUEST_ERROR', status_code=502,
        ) from e
    except requests.exceptions.Timeout as e:
        raise UpstreamAPIError(
            f"Request to '{url}' timed out after 45 seconds.",
            error_code='UPSTREAM_TIMEOUT',
            status_code=504,
        ) from e
    except requests.exceptions.RequestException as e:
        raise UpstreamAPIError(
            f"Unexpected error communicating with API server: {e}",
            error_code='UPSTREAM_REQUEST_ERROR',
            status_code=502,
        ) from e
