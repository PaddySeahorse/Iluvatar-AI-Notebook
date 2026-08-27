"""Tool registry for the ReAct agent.

Each tool pairs an OpenAI function-calling JSON schema with a Python callable.
Tool implementations read live state from a context object (kernel manager,
workspace directory, path-safety checker) so they stay decoupled from Flask.

All tools degrade to a structured error result instead of raising — the agent
loop translates failures into an observation it can reason about.
"""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout


_MAX_RESULT_CHARS = 2000
_MAX_READ_CHARS = 6000

# Module-level executor so the context manager exit doesn't block waiting for
# threads that are still running after a timeout.
_tool_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='tool-exec')


def _shutdown_executor():
    _tool_executor.shutdown(wait=False)


import atexit
atexit.register(_shutdown_executor)


def _clip(text: str, limit: int = _MAX_RESULT_CHARS) -> str:
    """Truncate long tool output while preserving the head and the tail."""
    text = text or ''
    if len(text) <= limit:
        return text
    head = text[: int(limit * 0.8)]
    tail = text[-int(limit * 0.2):]
    return f"{head}\n... [truncated {len(text) - len(head) - len(tail)} chars] ...\n{tail}"


def _summarize(text: str, limit: int = 400) -> str:
    """Return a short summary line(s) for a tool result."""
    text = (text or '').strip()
    if not text:
        return 'empty'
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    head = lines[: int(limit / 60)]
    tail = lines[-2:]
    preview = ' | '.join(head)
    if head != tail and len(lines) > len(head) + 2:
        preview += f" ... ({len(lines) - len(head)} more lines) ... " + ' | '.join(tail)
    if len(preview) > limit:
        preview = preview[:limit] + '...'
    return preview


def _run_cell(args, ctx):
    code = str(args.get('code', '') or '')
    if not code.strip():
        return {'ok': False, 'summary': 'no code provided', 'stdout': '', 'stderr': ''}
    km = ctx['kernel_manager']
    try:
        result = km.execute(code)
    except Exception as e:
        return {'ok': False, 'summary': f"kernel execution failed: {e}", 'stdout': '', 'stderr': str(e)}
    stdout = result.get('stdout') or ''
    stderr = result.get('stderr') or ''
    ok = bool(result.get('success', False)) and not stderr
    summary = _summarize(stdout or stderr or ('ok' if ok else 'error'))
    return {
        'ok': ok,
        'summary': summary,
        'stdout': _clip(stdout),
        'stderr': _clip(stderr),
        'plots': int(len(result.get('plots') or [])),
    }


def _get_variables(args, ctx):
    km = ctx['kernel_manager']
    try:
        variables = km.get_variables()
    except Exception as e:
        return {'ok': False, 'summary': f"cannot read variables: {e}", 'data': []}
    names = [f"{v.get('name')}({v.get('type')})" for v in variables]
    summary = f"{len(names)} variables: " + ', '.join(names[:20])
    if len(names) > 20:
        summary += f" (+{len(names) - 20} more)"
    return {'ok': True, 'summary': summary, 'data': variables[:50]}


def _list_files(args, ctx):
    workspace = ctx['workspace_dir']
    try:
        files = sorted(
            f for f in os.listdir(workspace)
            if f.endswith('.ipynb') and os.path.isfile(os.path.join(workspace, f))
        )
    except OSError as e:
        return {'ok': False, 'summary': f"cannot list workspace: {e}", 'data': []}
    summary = f"{len(files)} notebook(s): " + ', '.join(files[:15])
    if len(files) > 15:
        summary += f" (+{len(files) - 15} more)"
    return {'ok': True, 'summary': summary, 'data': files}


def _read_nb(args, ctx):
    filename = str(args.get('filename', '') or '')
    workspace = ctx['workspace_dir']
    is_safe_path = ctx['is_safe_path']
    if not filename.endswith('.ipynb') or not is_safe_path(filename):
        return {'ok': False, 'summary': 'invalid or unsafe filename', 'data': {}}
    filepath = os.path.join(workspace, filename)
    if not os.path.exists(filepath):
        return {'ok': False, 'summary': f"notebook '{filename}' not found", 'data': {}}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return {'ok': False, 'summary': f"cannot read notebook: {e}", 'data': {}}

    cells = content.get('cells', []) if isinstance(content, dict) else []
    pieces = []
    for i, cell in enumerate(cells, 1):
        src = ''.join(cell.get('source', [])) if isinstance(cell.get('source'), list) else str(cell.get('source', ''))
        kind = cell.get('cell_type', 'code')
        code_trim = src[:300] + ('...' if len(src) > 300 else '')
        pieces.append(f"[cell {i}] ({kind}) {code_trim}")
    text = '\n'.join(pieces)
    return {
        'ok': True,
        'summary': f"notebook '{filename}' with {len(cells)} cell(s)",
        'data': {'cells': _clip(text, _MAX_READ_CHARS)},
    }


def _gpu_status(args, ctx):
    try:
        from core.gpu import get_real_gpu_state
        gpu = get_real_gpu_state()
    except Exception as e:
        return {'ok': False, 'summary': f"gpu telemetry unavailable: {e}", 'data': {}}
    summary = (
        f"{gpu.get('name')} util={gpu.get('utilization')}% "
        f"vram={gpu.get('vram_used')}/{gpu.get('vram_total')}MB "
        f"temp={gpu.get('temperature')}C power={gpu.get('power_draw')}W "
        f"status={gpu.get('status')}"
    )
    return {'ok': True, 'summary': summary, 'data': gpu}


def _kernel_status(args, ctx):
    km = ctx['kernel_manager']
    try:
        alive = km.is_kernel_alive()
        watchdog = km.is_watchdog_alive()
    except Exception as e:
        return {'ok': False, 'summary': f"cannot read kernel status: {e}", 'data': {}}
    summary = f"kernel_alive={alive} watchdog_alive={watchdog}"
    return {
        'ok': True,
        'summary': summary,
        'data': {'kernel_alive': alive, 'watchdog_alive': watchdog},
    }


TOOL_DEFS = {
    'run_cell': {
        'description': 'Execute a Python code cell in the Jupyter kernel. '
                       'Use this to run experiments, verify hypotheses, compute values or '
                       'inspect runtime objects. Returns stdout, stderr and result summary.',
        'parameters': {
            'type': 'object',
            'properties': {
                'code': {'type': 'string', 'description': 'The Python code to execute'},
            },
            'required': ['code'],
        },
        'func': _run_cell,
    },
    'get_variables': {
        'description': 'List the active variables currently defined in the kernel '
                       'namespace with their type and value preview.',
        'parameters': {'type': 'object', 'properties': {}},
        'func': _get_variables,
    },
    'list_files': {
        'description': 'List the notebook (.ipynb) files stored in the workspace.',
        'parameters': {'type': 'object', 'properties': {}},
        'func': _list_files,
    },
    'read_nb': {
        'description': 'Read a notebook file from the workspace and return a summary '
                       'of its cells (type + code preview).',
        'parameters': {
            'type': 'object',
            'properties': {
                'filename': {'type': 'string', 'description': 'The .ipynb filename in the workspace'},
            },
            'required': ['filename'],
        },
        'func': _read_nb,
    },
    'gpu_status': {
        'description': 'Query the current Iluvatar GPU telemetry: utilization, VRAM usage, '
                       'temperature, power draw and runtime status.',
        'parameters': {'type': 'object', 'properties': {}},
        'func': _gpu_status,
    },
    'kernel_status': {
        'description': 'Check whether the Python kernel and its watchdog are alive.',
        'parameters': {'type': 'object', 'properties': {}},
        'func': _kernel_status,
    },
}


def get_tool_schemas() -> list:
    """Return the OpenAI function-calling schema for every registered tool."""
    return [
        {
            'type': 'function',
            'function': {
                'name': name,
                'description': t['description'],
                'parameters': t['parameters'],
            },
        }
        for name, t in TOOL_DEFS.items()
    ]


def execute_tool(name: str, arguments, ctx, *, timeout: float = 30) -> dict:
    """Execute a tool by name with parsed JSON arguments.

    Returns a normalized result dict with at least ``ok`` and ``summary``
    keys plus an optional ``data`` payload.

    ``timeout`` is the maximum wall-clock seconds the tool is allowed to run.
    On timeout the result is an error the agent can reason about and decide
    whether to retry or move on.
    """
    tool = TOOL_DEFS.get(name)
    if tool is None:
        return {'ok': False, 'summary': f"unknown tool: {name}", 'data': {}}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {'_raw': arguments}
    if not isinstance(arguments, dict):
        arguments = {'_raw': str(arguments)}
    future = _tool_executor.submit(tool['func'], arguments, ctx)
    try:
        result = future.result(timeout=timeout)
    except FuturesTimeout:
        future.cancel()
        return {
            'ok': False,
            'summary': f"tool {name} timed out after {int(timeout)}s",
            'data': {},
        }
    except Exception as e:
        result = {'ok': False, 'summary': f"tool {name} raised: {e}", 'data': {}}
    result.setdefault('ok', False)
    result.setdefault('summary', '')
    result.setdefault('data', {})
    return result