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
    km = ctx['kernel_manager']
    workspace = ctx.get('workspace_dir', '')
    is_safe_path = ctx.get('is_safe_path', lambda p: True)
    code = None
    filename = None
    cell_index = None
    if args.get('cell_index') is not None or args.get('cellId') is not None or args.get('cell_id') is not None:
        raw_idx = args.get('cell_index', args.get('cellId', args.get('cell_id')))
        try:
            cell_index = int(raw_idx)
        except (TypeError, ValueError):
            return {'ok': False, 'summary': f"invalid cell_index: {raw_idx!r}", 'stdout': '', 'stderr': ''}
        if cell_index < 1:
            return {'ok': False, 'summary': f"cell_index must be >=1, got {cell_index}", 'stdout': '', 'stderr': ''}
        filename = str(args.get('filename', '') or '').strip()
        if not filename:
            try:
                files = sorted(f for f in os.listdir(workspace) if f.endswith('.ipynb') and os.path.isfile(os.path.join(workspace, f)))
            except OSError as e:
                return {'ok': False, 'summary': f"cannot list workspace: {e}", 'stdout': '', 'stderr': ''}
            if len(files) == 1:
                filename = files[0]
            elif len(files) == 0:
                return {'ok': False, 'summary': 'no notebook found in workspace; create one first', 'stdout': '', 'stderr': ''}
            else:
                return {'ok': False, 'summary': f"multiple notebooks exist ({', '.join(files[:5])}); please specify filename", 'stdout': '', 'stderr': ''}
        if not filename.endswith('.ipynb') or not is_safe_path(filename):
            return {'ok': False, 'summary': 'invalid or unsafe filename', 'stdout': '', 'stderr': ''}
        filepath = os.path.join(workspace, filename)
        if not os.path.exists(filepath):
            return {'ok': False, 'summary': f"notebook '{filename}' not found", 'stdout': '', 'stderr': ''}
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                nb = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return {'ok': False, 'summary': f"cannot read notebook: {e}", 'stdout': '', 'stderr': ''}
        cells = nb.get('cells', []) if isinstance(nb, dict) else []
        if cell_index > len(cells):
            return {'ok': False, 'summary': f"cell_index {cell_index} out of range (notebook has {len(cells)} cells)", 'stdout': '', 'stderr': ''}
        cell = cells[cell_index - 1]
        if cell.get('cell_type') != 'code':
            return {'ok': False, 'summary': f"cell {cell_index} is not a code cell (type={cell.get('cell_type')})", 'stdout': '', 'stderr': ''}
        src = cell.get('source', '')
        code = ''.join(src) if isinstance(src, list) else str(src)
        if not code.strip():
            return {'ok': False, 'summary': f"cell {cell_index} is empty", 'stdout': '', 'stderr': '', 'data': {'filename': filename, 'cell_index': cell_index}}
    else:
        code = str(args.get('code', '') or '')
        filename = str(args.get('filename', '') or '').strip() or None
        cell_index = None
        if not code.strip():
            return {'ok': False, 'summary': 'no code or cell_index provided', 'stdout': '', 'stderr': ''}
    try:
        result = km.execute(code)
    except Exception as e:
        return {'ok': False, 'summary': f"kernel execution failed: {e}", 'stdout': '', 'stderr': str(e), 'data': {'filename': filename, 'cell_index': cell_index, 'code': code[:500]}}
    stdout = result.get('stdout') or ''
    stderr = result.get('stderr') or ''
    ok = bool(result.get('success', False)) and not stderr
    if cell_index is not None:
        summary = f"executed cell {cell_index}" + (f" from '{filename}'" if filename else "") + f": {_summarize(stdout or stderr or ('ok' if ok else 'error'))}"
    else:
        summary = _summarize(stdout or stderr or ('ok' if ok else 'error'))
    return {
        'ok': ok,
        'summary': summary,
        'stdout': _clip(stdout),
        'stderr': _clip(stderr),
        'plots': int(len(result.get('plots') or [])),
        'data': {'filename': filename, 'cell_index': cell_index, 'code': code[:6000]},
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


def _webfetch(args, ctx):
    url = str(args.get('url', '') or '').strip()
    if not url:
        return {'ok': False, 'summary': 'no url provided', 'data': {}}

    import urllib.request
    import urllib.error
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0 (Iluvatar AI Notebook)'}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            import re
            text = re.sub(r'<[^>]+>', ' ', html)
            text = re.sub(r'\s+', ' ', text).strip()
            return {
                'ok': True,
                'summary': f"fetched {len(html)} bytes from {url}",
                'data': {'content': _clip(text, _MAX_READ_CHARS)}
            }
    except Exception as e:
        return {'ok': False, 'summary': f"failed to fetch {url}: {e}", 'data': {}}

def _create_cell(args, ctx):
    code = str(args.get('code', '') or '')
    cell_type = str(args.get('cell_type', 'code') or 'code').strip().lower()
    if cell_type not in ('code', 'markdown'):
        cell_type = 'code'
    if not code.strip():
        return {'ok': False, 'summary': 'no content provided', 'data': {}}
    index = args.get('index', args.get('position'))
    if index is not None:
        try:
            index = int(index)
        except (TypeError, ValueError):
            return {'ok': False, 'summary': f"invalid index: {index!r}", 'data': {}}
    preview = _summarize(code, 200)
    if index is not None:
        summary = f"created {cell_type} cell at {index}: {preview}"
    else:
        summary = f"created {cell_type} cell: {preview}"
    return {
        'ok': True,
        'summary': summary,
        'data': {'cell_type': cell_type, 'code': code[:6000], 'index': index},
    }


TOOL_DEFS = {
    'run_cell': {
        'description': 'Execute an existing notebook cell by its index. The cell index follows '
                       'the [cell N] numbering shown by read_nb. Loads the cell source from the '
                       'notebook file and executes it in the kernel. Prefer this over raw code. '
                       'Fallback `code` is kept for ad-hoc probing.',
        'parameters': {
            'type': 'object',
            'properties': {
                'cell_index': {'type': 'integer', 'description': '1-based index of an existing code cell (as shown by read_nb)'},
                'filename': {'type': 'string', 'description': 'Notebook filename (.ipynb) in workspace; omit only when a single notebook exists'},
                'code': {'type': 'string', 'description': 'Raw Python code (deprecated fallback; use cell_index instead)'},
            },
            'required': [],
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
    'create_cell': {
        'description': 'Create a new cell in the user\'s current Notebook. Only creates the cell, '
                       'does NOT execute it. Use this to deliver reusable code or markdown. '
                       'Index is 0-based insertion position (0 = top, omit = append, K = after K cells / after [cell K]).',
        'parameters': {
            'type': 'object',
            'properties': {
                'code': {'type': 'string', 'description': 'Cell content (Python code or markdown text)'},
                'cell_type': {
                    'type': 'string',
                    'enum': ['code', 'markdown'],
                    'description': 'Cell type, defaults to "code"',
                },
                'index': {
                    'type': 'integer',
                    'description': '0-based insertion position. 0 = before first cell, 1 = after [cell 1], omit = append to end',
                },
            },
            'required': ['code'],
        },
        'func': _create_cell,
    },
    'webfetch': {
        'description': 'Fetch and extract text content from a web page URL. Useful for retrieving documentation or external resources.',
        'parameters': {
            'type': 'object',
            'properties': {
                'url': {'type': 'string', 'description': 'The URL of the web page to fetch'},
            },
            'required': ['url'],
        },
        'func': _webfetch,
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