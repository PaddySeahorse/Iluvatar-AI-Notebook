"""AI proxy routes: default config exposure and upstream LLM calls (方案三).

与 Flask 版保持相同的 URL 路径与请求/响应格式；流式分支改用
``StreamingResponse``（SSE），非流式分支通过 ``run_in_threadpool`` 调用阻塞的
上游 HTTP 请求，避免阻塞事件循环。
"""

import json
import os

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from core import llm as llm_transport
from core.errors import UpstreamAPIError
from core.routes import json_body, state
from core.user_config import save_model_config

router = APIRouter()


@router.get('/api/get_config')
async def get_config(request: Request):
    # Expose defaults loaded from env for initialization
    s = state(request)
    return {
        'default_url': s.DEFAULT_API_URL,
        'default_model': s.DEFAULT_API_MODEL,
    }


@router.post('/api/save_config')
async def save_config(request: Request):
    """Persist the user-provided LLM API config on the host machine.

    Request: ``{"url": "...", "token": "...", "model": "..."}``

    The values are written to the ``OPENI_API_URL`` / ``OPENI_API_TOKEN`` /
    ``OPENI_API_MODEL`` keys of ``~/.Iluvatar-AI-Notebook/config.yaml``
    (other tracked keys are preserved), and the in-memory runtime defaults +
    ``os.environ`` are updated at the same time so the new config takes
    effect without a restart.
    """
    s = state(request)
    data = await json_body(request)
    url = str(data.get('url') or '').strip()
    token = str(data.get('token') or '').strip()
    model = str(data.get('model') or '').strip()

    if not url or not model:
        return JSONResponse(
            status_code=400,
            content={
                'error': True,
                'error_code': 'INVALID_CONFIG',
                'message': 'API URL 与模型名称不能为空',
            },
        )

    try:
        await run_in_threadpool(save_model_config, url, token, model)
    except OSError as e:
        return JSONResponse(
            status_code=500,
            content={
                'error': True,
                'error_code': 'CONFIG_WRITE_ERROR',
                'message': f'写入配置文件失败: {e}',
            },
        )

    # Make the config effective immediately (no restart needed).
    s.DEFAULT_API_URL = url
    s.DEFAULT_API_TOKEN = token
    s.DEFAULT_API_MODEL = model
    os.environ['OPENI_API_URL'] = url
    os.environ['OPENI_API_TOKEN'] = token
    os.environ['OPENI_API_MODEL'] = model

    return {'ok': True, 'message': 'API 配置已保存'}


@router.post('/api/ai_call')
async def ai_call(request: Request):
    s = state(request)
    data = await json_body(request)
    url = data.get('url') or s.DEFAULT_API_URL
    token = data.get('token') or s.DEFAULT_API_TOKEN
    model = data.get('model') or s.DEFAULT_API_MODEL
    messages = data.get('messages', [])
    stream = data.get('stream', False)
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

            return StreamingResponse(
                generate(),
                media_type='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no',
                },
            )

        result = await run_in_threadpool(
            llm_transport.chat_nostream,
            url, token, model, messages, backend=backend,
        )
        return result
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