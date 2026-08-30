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
from core.litellm_manager import is_manually_managed, litellm_manager, read_first_route
from core.routes import json_body, state

router = APIRouter()


@router.get('/api/get_config')
async def get_config(request: Request):
    # Expose the effective route (first model_list entry) for initialization,
    # falling back to the environment-seeded defaults.
    s = state(request)
    api_base, model_name = await run_in_threadpool(read_first_route)
    return {
        'default_url': api_base or s.DEFAULT_API_URL,
        'default_model': model_name or s.DEFAULT_API_MODEL,
    }


@router.post('/api/save_config')
async def save_config(request: Request):
    """Persist the upstream model config via the local LiteLLM Proxy config.

    Request: ``{"url": "...", "token": "...", "model": "..."}``

    The values describe the **upstream model endpoint** that the self-hosted
    LiteLLM Proxy must route to (the OpenAI SDK always talks to the local
    proxy, never to this address directly). While the proxy config is under
    manual management (advanced mode has hand-saved ``litellm_config.yaml``)
    the write is refused with ``CONFIG_MANAGED_MANUALLY`` and the user is
    directed to advanced mode. Otherwise the in-memory runtime defaults +
    ``os.environ`` are updated and the local LiteLLM Proxy's ``model_list``
    is rewritten + the proxy bounced so the new route is live immediately.
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

    if is_manually_managed():
        return JSONResponse(
            status_code=409,
            content={
                'error': True,
                'error_code': 'CONFIG_MANAGED_MANUALLY',
                'message': 'LiteLLM 路由处于手动接管状态，请在高级模式中手动配置',
            },
        )

    # Make the config effective immediately (no restart needed).
    s.DEFAULT_API_URL = url
    s.DEFAULT_API_TOKEN = token
    s.DEFAULT_API_MODEL = model
    os.environ['OPENI_API_URL'] = url
    os.environ['OPENI_API_TOKEN'] = token
    os.environ['OPENI_API_MODEL'] = model

    # Rewrite the local LiteLLM Proxy's model route; blocking I/O off-loop.
    await run_in_threadpool(litellm_manager.sync_config, url, token, model)

    api_base, model_name = await run_in_threadpool(read_first_route)
    if api_base:
        s.DEFAULT_API_URL = api_base
    if model_name:
        s.DEFAULT_API_MODEL = model_name

    return {'ok': True, 'message': 'API 配置已保存'}


@router.get('/api/health_check')
async def health_check(request: Request):
    s = state(request)
    url = s.DEFAULT_API_URL
    token = s.DEFAULT_API_TOKEN
    model = s.DEFAULT_API_MODEL
    q = request.query_params
    if q.get('url'):
        url = q.get('url')
    if q.get('token') is not None:
        token = q.get('token')
    if q.get('model'):
        model = q.get('model')
    result = await run_in_threadpool(llm_transport.check_api_health, url, token, model)
    return result


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