"""ReAct agent + structured context routes.

- ``GET /api/context``  -> structured kernel context (variables + recent Out
  results + recent error summaries) used to build smart prompts.
- ``POST /api/agent_call`` -> SSE stream of agent events (tool calls/results
  and the final answer).
"""

import json

from flask import Blueprint, request, jsonify, Response, stream_with_context

from core.agent import agent_loop
from core.context import build_context
from core.routes import state

bp = Blueprint('agent', __name__)


@bp.route('/api/context', methods=['GET'])
def get_context():
    """Return the structured context snapshot of the live kernel."""
    s = state()
    ctx = build_context(s.kernel_manager, s.WORKSPACE_DIR)
    return jsonify(ctx)


@bp.route('/api/agent_call', methods=['POST'])
def agent_call():
    """Run the ReAct agent and stream its events via Server-Sent Events.

    Request body mirrors ``/api/ai_call`` plus agent-specific fields::

        {
          "url": "...", "token": "...", "model": "...",
          "messages": [...],          # conversation history (excludes the query)
          "query": "user question",   # the current user message
          "include_context": true,    # attach structured kernel context (default true)
          "max_steps": 6              # max tool-call rounds (default 6)
        }

    Event stream:
        data: {"type":"status","stage":"thinking"}
        data: {"type":"tool_call","name":"run_cell","arguments":{...}}
        data: {"type":"tool_result","name":"run_cell","ok":true,"summary":"..."}
        data: {"type":"content","text":"..."}
        data: {"type":"done","final":"..."}
        data: [DONE]
    """
    data = request.json or {}
    s = state()
    url = data.get('url', s.DEFAULT_API_URL)
    token = data.get('token', s.DEFAULT_API_TOKEN)
    model = data.get('model', s.DEFAULT_API_MODEL)
    query = str(data.get('query', '') or '')
    messages = data.get('messages') or []
    include_context = bool(data.get('include_context', True))
    max_steps = int(data.get('max_steps', 6) or 6)

    if not query.strip():
        return jsonify({'error': True, 'error_code': 'EMPTY_QUERY', 'message': 'Empty query'}), 400

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
        ):
            yield f'data: {json.dumps(event, ensure_ascii=False)}\n\n'
        yield 'data: [DONE]\n\n'

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )