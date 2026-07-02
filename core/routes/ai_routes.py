"""AI proxy routes: default config exposure and upstream LLM calls."""

import requests
from flask import Blueprint, request, jsonify, Response

from core.errors import UpstreamAPIError
from core.routes import state

bp = Blueprint('ai', __name__)


@bp.route('/api/get_config', methods=['GET'])
def get_config():
    # Expose defaults loaded from env for initialization
    s = state()
    return jsonify({
        'default_url': s.DEFAULT_API_URL,
        'default_model': s.DEFAULT_API_MODEL
    })


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
