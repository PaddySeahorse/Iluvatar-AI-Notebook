"""AI proxy routes: default config exposure and upstream LLM calls."""

import os

import requests
from flask import Blueprint, request, jsonify, Response

from core.errors import UpstreamAPIError
from core.routes import state

bp = Blueprint('ai', __name__)


def _upsert_env(env_path: str, updates: dict):
    """Update ``KEY=VALUE`` lines in an .env file, preserving other lines.

    Existing keys are replaced in place; missing keys are appended at the end.
    """
    lines = []
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()

    out = []
    written = set()
    for line in lines:
        stripped = line.strip()
        if stripped and '=' in stripped and not stripped.startswith('#'):
            key = stripped.split('=', 1)[0].strip()
            if key in updates:
                out.append(f'{key}={updates[key]}')
                written.add(key)
                continue
        out.append(line)
    for key, value in updates.items():
        if key not in written:
            out.append(f'{key}={value}')

    with open(env_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')


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
    """Persist the user-provided LLM API config into the project ``.env``.

    Request: ``{"url": "...", "token": "...", "model": "..."}``

    The values are written to ``OPENI_API_URL`` / ``OPENI_API_TOKEN`` /
    ``OPENI_API_MODEL`` in the project-root .env (existing unrelated lines are
    preserved), and the in-memory runtime defaults + ``os.environ`` are updated
    at the same time so the new config takes effect without a restart.
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

    env_path = os.path.join(s.WORKSPACE_DIR, '.env')
    try:
        _upsert_env(env_path, {
            'OPENI_API_URL': url,
            'OPENI_API_TOKEN': token,
            'OPENI_API_MODEL': model,
        })
    except OSError as e:
        return jsonify({
            'error': True,
            'error_code': 'ENV_WRITE_ERROR',
            'message': f'写入 .env 失败: {e}',
        }), 500

    # Make the config effective immediately (no restart needed).
    s.DEFAULT_API_URL = url
    s.DEFAULT_API_TOKEN = token
    s.DEFAULT_API_MODEL = model
    os.environ['OPENI_API_URL'] = url
    os.environ['OPENI_API_TOKEN'] = token
    os.environ['OPENI_API_MODEL'] = model

    return jsonify({'ok': True, 'message': 'API 配置已保存到 .env'})


@bp.route('/api/ai_call', methods=['POST'])
def ai_call():
    s = state()
    data = request.json or {}
    url = data.get('url', s.DEFAULT_API_URL)
    token = data.get('token', s.DEFAULT_API_TOKEN)
    model = data.get('model', s.DEFAULT_API_MODEL)
    messages = data.get('messages', [])
    stream = data.get('stream', False)

    headers = {
        'Content-Type': 'application/json'
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'

    payload = {
        'model': model,
        'messages': messages,
        'temperature': 0.7
    }
    if stream:
        payload['stream'] = True

    try:
        if stream:
            # Proxy streaming request to user-configured API URL
            response = requests.post(url, headers=headers, json=payload, timeout=45, stream=True)
            if response.status_code == 200:
                def generate():
                    for chunk in response.iter_lines():
                        if chunk:
                            yield chunk + b'\n'
                return Response(generate(), mimetype='text/event-stream')
            else:
                raise UpstreamAPIError(
                    f"Upstream API returned {response.status_code}: {response.text[:200]}",
                    error_code='UPSTREAM_HTTP_ERROR',
                    status_code=response.status_code,
                )
        else:
            # Proxy request to user-configured API URL
            response = requests.post(url, headers=headers, json=payload, timeout=45)
            if response.status_code == 200:
                return jsonify(response.json())
            else:
                raise UpstreamAPIError(
                    f"Upstream API returned {response.status_code}: {response.text[:200]}",
                    error_code='UPSTREAM_HTTP_ERROR',
                    status_code=response.status_code,
                )
    except requests.exceptions.ConnectionError as e:
        raise UpstreamAPIError(
            f"Cannot reach API server at '{url}': connection refused or DNS failure.",
            error_code='UPSTREAM_CONNECTION_ERROR',
            status_code=502,
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
