"""ReAct agent + structured context routes (方案三：FastAPI 版).

- ``GET /api/context``  -> structured kernel context (variables + recent Out
  results + recent error summaries) used to build smart prompts.
- ``POST /api/agent_call`` -> SSE stream of agent events (tool calls/results
  and the final answer).

``agent_loop`` 是同步 generator（内部含阻塞的 LLM / 内核调用），交给
``StreamingResponse`` 后由 Starlette 在线程池中迭代，保持事件循环不被卡住。
共享状态经 :func:`core.routes.state` 在请求时读取，与 Flask 版行为一致。
"""

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from core.agent import agent_loop
from core.context import build_context
from core.routes import json_body, state

router = APIRouter()


@router.get('/api/context')
async def get_context(request: Request):
    """Return the structured context snapshot of the live kernel."""
    s = state(request)
    ctx = await run_in_threadpool(build_context, s.kernel_manager, s.WORKSPACE_DIR)
    return ctx


@router.post('/api/agent_call')
async def agent_call(request: Request):
    """Run the ReAct agent and stream its events via Server-Sent Events.

    Request body mirrors ``/api/ai_call`` plus agent-specific fields::

        {
          "url": "...", "token": "...", "model": "...",
          "messages": [...],          # conversation history (excludes the query)
          "query": "user question",   # the current user message
          "include_context": true,    # attach structured kernel context (default true)
          "max_steps": 0              # max tool-call rounds, 0 = unlimited (default 0)
        }

    Event stream:
        data: {"type":"status","stage":"thinking"}
        data: {"type":"tool_call","name":"run_cell","arguments":{...}}
        data: {"type":"tool_result","name":"run_cell","ok":true,"summary":"..."}
        data: {"type":"content","text":"..."}
        data: {"type":"done","final":"..."}
        data: [DONE]
    """
    s = state(request)
    data = await json_body(request)
    url = data.get('url') or s.DEFAULT_API_URL
    token = data.get('token') or s.DEFAULT_API_TOKEN
    model = data.get('model') or s.DEFAULT_API_MODEL
    query = str(data.get('query', '') or '')
    messages = data.get('messages') or []
    include_context = bool(data.get('include_context', True))
    raw_steps = data.get('max_steps')
    try:
        max_steps = int(raw_steps) if raw_steps is not None and str(raw_steps).strip() != '' else 0
    except (TypeError, ValueError):
        max_steps = 0
    if max_steps < 0:
        max_steps = 0
    use_tools_probe = bool(data.get('use_tools_probe', True))
    backend = data.get('backend') or None

    if not query.strip():
        return JSONResponse(
            status_code=400,
            content={'error': True, 'error_code': 'EMPTY_QUERY', 'message': 'Empty query'},
        )

    def generate():
        for event in agent_loop(
            url=url,
            token=token,
            model=model,
            history=messages,
            query=query,
            include_context=include_context,
            state_module=s,
            max_steps=max_steps,
            use_tools_probe=use_tools_probe,
            backend=backend,
        ):
            yield f'data: {json.dumps(event, ensure_ascii=False)}\n\n'
        yield 'data: [DONE]\n\n'

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )