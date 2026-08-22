"""Structured AI context builder.

Builds a compact, kernel-derived context snapshot for the LLM instead of
pasting the whole notebook source: the active variable table, the most recent
``Out`` results and a summary of the latest execution errors.  The output is a
plain-text block designed to fit inside a ``system``/``user`` message.

The data is pulled from the live kernel via :class:`core.kernel.KernelManager`
(the same source the variable inspector and execution streams use), so it
always reflects the actual runtime state of the kernel.
"""

from typing import Dict, List

_MAX_VARS = 40
_MAX_OUTPUTS = 6
_MAX_VAR_REPR = 120
_MAX_OUTPUT_REPR = 300


def build_context(
    kernel_manager,
    workspace_dir: str,
    *,
    max_vars: int = _MAX_VARS,
    max_outputs: int = _MAX_OUTPUTS,
) -> Dict:
    """Return a structured context dictionary from the live kernel state.

    Returns::

        {
            'variables': [{'name', 'type', 'repr', 'shape'}, ...],
            'recent_outputs': {'6': 'repr', ...},
            'recent_errors': [{'title', 'summary'}, ...],
        }

    Every component degrades gracefully on kernel/API failures rather than
    raising — the AI chat must keep working without a live kernel.
    """
    variables: List[Dict] = []
    recent_outputs: Dict[str, str] = {}
    recent_errors: List[Dict] = []

    try:
        variables = _summarize_variables(kernel_manager.get_variables(), max_vars)
    except Exception:
        variables = []

    try:
        recent_outputs = kernel_manager.fetch_recent_outputs(max_outputs)
    except Exception:
        recent_outputs = {}

    try:
        recent_errors = list(kernel_manager.get_recent_errors())[:5]
    except Exception:
        recent_errors = []

    return {
        'variables': variables,
        'recent_outputs': recent_outputs,
        'recent_errors': recent_errors,
    }


def _summarize_variables(variables: List[Dict], max_vars: int) -> List[Dict]:
    """Trim the variable table to a bounded, LLM-friendly size."""
    out: List[Dict] = []
    for v in (variables or [])[:max_vars]:
        name = str(v.get('name', ''))
        if not name:
            continue
        repr_val = v.get('repr') or ''
        if len(repr_val) > _MAX_VAR_REPR:
            repr_val = repr_val[:_MAX_VAR_REPR] + '...'
        out.append({
            'name': name,
            'type': str(v.get('type', '') or ''),
            'repr': repr_val,
            'shape': v.get('shape'),
        })
    return out


def context_to_text(ctx: Dict) -> str:
    """Render a context dict into a plain-text block for a prompt."""
    parts: List[str] = []

    variables = ctx.get('variables') or []
    if variables:
        lines = []
        for v in variables:
            shape = f" shape={v['shape']}" if v.get('shape') else ''
            lines.append(f"- {v['name']} ({v['type']}{shape}): {v['repr']}")
        parts.append("变量表 (active variables):\n" + "\n".join(lines))

    recent_outputs = ctx.get('recent_outputs') or {}
    if recent_outputs:
        lines = [
            f"[Out {k}] {v}" for k, v in sorted(recent_outputs.items())
        ]
        parts.append("最近的 Out 结果 (recent outputs):\n" + "\n".join(lines))

    recent_errors = ctx.get('recent_errors') or []
    if recent_errors:
        for err in recent_errors:
            title = err.get('title') or ''
            summary = err.get('summary') or ''
            if summary and summary != title:
                parts.append(f"最近错误 (recent error): {title}\n{summary}")
            else:
                parts.append(f"最近错误 (recent error): {title}")

    if not parts:
        return "内核当前没有可用的变量、输出或错误记录。"
    return "\n\n".join(parts)