"""Lightweight ReAct agent loop for the notebook AI assistant.

The agent can call a small set of tools (run a kernel cell, inspect variables,
list/read notebooks, query GPU telemetry, check kernel health) to answer the
user's question, then writes a final answer.

Two LLM protocols are supported:

1. **Function calling** — the ``tools`` parameter is sent and every
   assistant message is inspected for ``tool_calls``.
2. **Text protocol (fallback)** — for APIs that reject the ``tools``
   parameter. The system prompt describes the tools in JSON form and
   instructs the model to emit ``{"action": ..., "arguments": ...}``. This
   works on plain chat-completions endpoints such as the default OpenI/DeepSeek
   endpoint.

The loop is a generator that yields event dicts suitable for SSE::

    {"type": "status", "stage": "thinking"}
    {"type": "tool_call", "name": "run_cell", "label": "执行代码单元", "arguments": {...}}
    {"type": "tool_result", "name": "run_cell", "ok": true, "summary": "..."}
    {"type": "content", "text": "..."}        # final answer (possibly many chunks)
    {"type": "done", "final": "..."}

Tool decision rounds use blocking calls for reliable JSON parsing; the final
answer round uses a streaming request for a typewriter-style response.
"""

import json
import re

from core.context import build_context, context_to_text
from core.llm import (
    LLMError,
    chat_nostream as llm_chat_nostream,
    chat_stream as llm_chat_stream,
    probe_tool_support as llm_probe_tool_support,
)
from core.tools import TOOL_DEFS, execute_tool, get_tool_schemas

MAX_STEPS = 0
REQUESTS_TIMEOUT = 60
STREAM_TIMEOUT = 180
TOOL_TIMEOUT = 30

TOOL_LABELS = {
    'run_cell': '执行已知单元格',
    'create_cell': '创建新单元格',
    'get_variables': '查看变量表',
    'list_files': '列出文件',
    'read_nb': '读取笔记本',
    'gpu_status': '查询 GPU 状态',
    'kernel_status': '检查内核状态',
}

_TEXT_PROTOCOL_SYSTEM = """你是一个集成在 Iluvatar AI Notebook 中的 AI 代理(ReAct)。
你的目标是为用户解答关于国产 AI 芯片(天数智芯 Iluvatar Corex)、PyTorch/TensorFlow 开发调试、以及通用 Python 编程的问题。
你具备专业的 IXUCA（天数智芯软件栈）知识，熟悉其工具链、算子适配与常见问题的排查方法。
你可以使用以下工具来获取信息或执行操作：

- run_cell(cell_index, filename): 执行一个已知的单元格。cell_index 为 read_nb 展示的 1-based 编号，filename 为 .ipynb 文件名（单文件时可省略）。只执行已存在单元格，不创建新格。参数: {"cell_index": 3, "filename": "demo.ipynb"}；兼容 {"code": "..."} 仅作临时探测。
- create_cell(code, cell_type, index): 在用户当前的 Notebook 创建一个新单元格，仅创建不执行。index 为 0-based 插入位置（0=顶部, 1=在 [cell 1] 之后, 省略=末尾）。cell_type 为 "code"(默认) 或 "markdown"。参数: {"code": "单元格内容", "cell_type": "code", "index": 2}
- get_variables(): 列出内核命名空间中当前活动的变量（名称、类型、值预览）。
- list_files(): 列出工作区中的 notebook (.ipynb) 文件。
- read_nb(filename): 读取指定 notebook 文件，返回其单元格的类型与代码预览。
- gpu_status(): 查询天数智芯 GPU 的实时状态（使用率、显存、温度、功耗）。
- kernel_status(): 检查 Python 内核及 watchdog 是否存活。

职责分离：run_cell 只执行已知单元格、create_cell 只创建；需要“执行并留档”时先 read_nb 再 run_cell，交付时用 create_cell。
需要调用工具时，只输出一个 JSON 对象，不要输出任何其他文字或 markdown：
{"action": "工具名", "arguments": {参数对象}}

如果不需要调用工具，直接针对用户的问题给出回答。
回答尽量简洁、准确，必要时给出可直接运行的 PyTorch/NumPy 代码。"""

_FUNCTION_SYSTEM = """你是一个集成在 Iluvatar AI Notebook 中的 AI 代理(ReAct)。
你的目标是为用户解答关于国产 AI 芯片(天数智芯 Iluvatar Corex)、PyTorch/TensorFlow 开发调试、以及通用 Python 编程的问题。
你具备专业的 IXUCA（天数智芯软件栈）知识，熟悉其工具链、算子适配与常见问题的排查方法。
你可以调用工具来获取内核上下文、执行代码、查询文件或 GPU 状态。需要调用工具时使用 tool_call；直接能回答时直接回答。

工具职责：run_cell 执行一个已知的单元格（按 read_nb 的 cell_index），不创建新格；create_cell 在指定 index 创建新单元格（省略则末尾）且不执行。
回答尽量简洁、准确，必要时给出可直接运行的 PyTorch/NumPy 代码。"""


class AgentError(Exception):
    """Raised when the agent cannot proceed (network/HTTP/protocol failures)."""


def build_tool_context(state_module) -> dict:
    """Build the execution context shared by every tool implementation."""
    return {
        'kernel_manager': state_module.kernel_manager,
        'workspace_dir': state_module.WORKSPACE_DIR,
        'is_safe_path': state_module.is_safe_path,
    }


def probe_tool_support(url, token, model, backend=None) -> bool:
    """Return True when the endpoint accepts the OpenAI ``tools`` parameter.

    A lightweight single-shot probe with a tiny payload; any non-200 or
    parser rejection counts as unsupported so the loop falls back to text mode.
    """
    return llm_probe_tool_support(url, token, model, backend=backend)


def _chat_nostream(url, token, model, messages, tools, timeout=REQUESTS_TIMEOUT, backend=None) -> dict:
    """Blocking chat-completions call. Returns the assistant message dict."""
    try:
        return llm_chat_nostream(url, token, model, messages, tools=tools, timeout=timeout, backend=backend)
    except LLMError as e:
        raise AgentError(str(e)) from e


def _chat_stream(url, token, model, messages, timeout=STREAM_TIMEOUT, backend=None):
    """Streaming chat-completions call; yields text deltas."""
    try:
        yield from llm_chat_stream(url, token, model, messages, timeout=timeout, backend=backend)
    except LLMError as e:
        raise AgentError(str(e)) from e


def _normalize_tool_calls(message: dict):
    """Return a normalized [{name, arguments}] list from a message dict."""
    tool_calls = message.get('tool_calls')
    if not tool_calls:
        return None
    normalized = []
    for tc in tool_calls:
        fn = tc.get('function', {})
        normalized.append({
            'id': tc.get('id', ''),
            'name': fn.get('name', ''),
            'arguments': fn.get('arguments', '{}'),
        })
    return normalized or None


def _parse_text_action(content: str):
    """Parse a text-protocol tool action from the model's raw output."""
    content = (content or '').strip()
    if not content:
        return None
    candidates = []
    code = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
    if code:
        candidates.append(code.group(1))
    brace = re.search(r'\{.*\}', content, re.DOTALL)
    if brace:
        candidates.append(brace.group(0))
    candidates.append(content)
    for cand in candidates:
        cand = cand.strip()
        if not cand.startswith('{'):
            continue
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        action = obj.get('action') or obj.get('name')
        if isinstance(action, str) and action in TOOL_DEFS:
            arguments = obj.get('arguments') or obj.get('params') or {}
            if not isinstance(arguments, dict):
                arguments = {'_raw': str(arguments)}
            return {'name': action, 'arguments': arguments}
    return None


def _load_arguments(arguments: str):
    try:
        return json.loads(arguments or '{}')
    except json.JSONDecodeError:
        return {'_raw': arguments}


def agent_loop(
    *,
    url,
    token,
    model,
    history,
    query,
    include_context,
    state_module,
    max_steps=MAX_STEPS,
    use_tools_probe=True,
    backend=None,
):
    """Run the ReAct loop; yields SSE-ready event dicts.

    ``use_tools_probe`` exists for tests to force function-calling or text
    protocol shortcuts without network access.  ``backend`` forces the LLM
    transport ("openai" or "requests"); ``None`` auto-selects.
    """
    try:
        tool_schemas = get_tool_schemas()
        tool_context = build_tool_context(state_module)
    except Exception as e:
        yield {'type': 'error', 'message': f'Agent 上下文初始化失败: {e.__class__.__name__}: {e}'}
        yield {'type': 'done', 'final': ''}
        return

    try:
        use_tools = bool(use_tools_probe) and probe_tool_support(url, token, model, backend=backend)
    except Exception as e:
        yield {'type': 'error', 'message': f'LLM 连接探测失败: {e.__class__.__name__}: {e}'}
        yield {'type': 'done', 'final': ''}
        return
    system_prompt = _FUNCTION_SYSTEM if use_tools else _TEXT_PROTOCOL_SYSTEM

    if include_context:
        try:
            ctx = build_context(state_module.kernel_manager, state_module.WORKSPACE_DIR)
            sys_ctx = context_to_text(ctx)
            system_prompt += (
                "\n\n以下是从当前内核实时采集的结构化上下文，供你参考（变量、最近的输出与错误）：\n"
                + sys_ctx
            )
        except Exception:
            pass

    messages = [{'role': 'system', 'content': system_prompt}]
    messages.extend([dict(m) for m in history or []])
    messages.append({'role': 'user', 'content': query})

    yield {'type': 'status', 'stage': 'thinking'}

    tool_call_count = 0
    step = 0
    while True:
        if max_steps and step >= max_steps:
            yield {'type': 'error', 'message': f"已达到最大工具调用步数({max_steps})，请尝试更具体的问题。"}
            yield {'type': 'done', 'final': ''}
            return
        step += 1
        # Text-protocol mode (no native function-calling) streams tokens so the
        # user sees the reply as it's generated.  Function-calling mode keeps
        # the non-streaming call because accumulating tool_calls across stream
        # chunks adds complexity for marginal UX gain in tool-heavy flows.
        if use_tools:
            try:
                reply = _chat_nostream(
                    url, token, model, messages, tools=tool_schemas,
                    backend=backend,
                )
            except AgentError as e:
                yield {'type': 'error', 'message': str(e)}
                yield {'type': 'done', 'final': ''}
                return

            content = reply.get('content') or ''
            streamed = False
        else:
            content_parts = []
            try:
                for delta in _chat_stream(url, token, model, messages, backend=backend):
                    content_parts.append(delta)
                    yield {'type': 'content', 'text': delta}
            except AgentError as e:
                yield {'type': 'error', 'message': str(e)}
                yield {'type': 'done', 'final': ''}
                return
            content = ''.join(content_parts)
            reply = {'content': content, 'tool_calls': None}
            streamed = True
        tool_calls = _normalize_tool_calls(reply) if use_tools else None

        if tool_calls:
            messages.append({'role': 'assistant', 'content': content, 'tool_calls': reply.get('tool_calls')})
            for tc in tool_calls:
                name = tc['name']
                arguments = _load_arguments(tc['arguments'])
                tool_call_count += 1
                yield {
                    'type': 'tool_call',
                    'name': name,
                    'label': TOOL_LABELS.get(name, name),
                    'arguments': arguments,
                }
                result = execute_tool(name, arguments, tool_context, timeout=TOOL_TIMEOUT)
                yield {
                    'type': 'tool_result',
                    'name': name,
                    'ok': bool(result.get('ok')),
                    'summary': str(result.get('summary', '')),
                    'stdout': str(result.get('stdout', ''))[:4000],
                    'stderr': str(result.get('stderr', ''))[:4000],
                    'plots': int(result.get('plots', 0) or 0),
                    'arguments': arguments,
                    'data': result.get('data', {}),
                }
                messages.append({
                    'role': 'tool',
                    'tool_call_id': tc.get('id', ''),
                    'name': name,
                    'content': json.dumps(result, ensure_ascii=False)[:4000],
                })
            continue

        action = _parse_text_action(content) if not use_tools else None
        if action:
            name = action['name']
            arguments = action['arguments']
            tool_call_count += 1
            messages.append({'role': 'assistant', 'content': content})
            yield {
                'type': 'tool_call',
                'name': name,
                'label': TOOL_LABELS.get(name, name),
                'arguments': arguments,
            }
            result = execute_tool(name, arguments, tool_context, timeout=TOOL_TIMEOUT)
            yield {
                'type': 'tool_result',
                'name': name,
                'ok': bool(result.get('ok')),
                'summary': str(result.get('summary', '')),
                'stdout': str(result.get('stdout', ''))[:4000],
                'stderr': str(result.get('stderr', ''))[:4000],
                'plots': int(result.get('plots', 0) or 0),
                'arguments': arguments,
                'data': result.get('data', {}),
            }
            messages.append({
                'role': 'user',
                'content': f"工具 {name} 返回结果: {json.dumps(result, ensure_ascii=False)[:4000]}",
            })
            continue

        # No tool call: this is the final answer.
        messages.append({'role': 'assistant', 'content': content})
        if streamed:
            # Already yielded token-by-token above; just close the stream.
            yield {'type': 'done', 'final': content}
            return
        # Function-calling mode: content was collected non-streamingly. Yield
        # it as a single content chunk so the UI shows the same progressive
        # accumulation pattern as text mode, then close.
        yield {'type': 'content', 'text': content}
        yield {'type': 'done', 'final': content}
        return