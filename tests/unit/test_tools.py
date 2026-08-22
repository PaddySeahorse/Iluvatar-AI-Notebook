"""Unit tests for the agent tool registry (core/tools.py)."""

import json

import core.tools as tools
from core.utils import is_safe_path


class _FakeKM:
    def __init__(self):
        self._vars = [{'name': 'x', 'type': 'int', 'repr': '1', 'shape': None}]
        self._errors = [{'title': 'NameError: foo', 'summary': 'x'}]

    def get_variables(self):
        return list(self._vars)

    def get_recent_errors(self):
        return list(self._errors)

    def execute(self, code):
        return {
            'success': True,
            'stdout': '42\n',
            'stderr': '',
            'html': '',
            'plots': [],
            'variables': [],
        }

    def is_kernel_alive(self):
        return True

    def is_watchdog_alive(self):
        return True


def _ctx(workspace):
    return {
        'kernel_manager': _FakeKM(),
        'workspace_dir': ws
        if (ws := getattr(workspace, 'workspace_dir', None)) else '/tmp',
        'is_safe_path': lambda p: is_safe_path('/tmp', p) if not getattr(workspace, 'workspace_dir', None) else is_safe_path(workspace.workspace_dir, p),
    }


def test_tool_schemas_cover_all_defs():
    schemas = tools.get_tool_schemas()
    names = {s['function']['name'] for s in schemas}
    assert names == set(tools.TOOL_DEFS.keys())
    assert 'run_cell' in names
    for s in schemas:
        assert s['type'] == 'function'
        assert 'description' in s['function']


def test_execute_run_cell(tmp_path):
    ctx = {
        'kernel_manager': _FakeKM(),
        'workspace_dir': str(tmp_path),
        'is_safe_path': lambda p: is_safe_path(str(tmp_path), p),
    }
    result = tools.execute_tool('run_cell', {'code': 'print(1)'}, ctx)
    assert result['ok'] is True
    assert '42' in result['stdout']
    assert '42' in result['summary']


def test_execute_run_cell_with_string_arguments(tmp_path):
    ctx = {
        'kernel_manager': _FakeKM(),
        'workspace_dir': str(tmp_path),
        'is_safe_path': lambda p: is_safe_path(str(tmp_path), p),
    }
    # Simulate an API that returns arguments as a JSON string.
    result = tools.execute_tool('run_cell', json.dumps({'code': 'print(2)'}), ctx)
    assert result['ok'] is True
    assert '42' in result['stdout']


def test_execute_list_files(tmp_path):
    (tmp_path / 'a.ipynb').write_text('{}', encoding='utf-8')
    (tmp_path / 'b.ipynb').write_text('{}', encoding='utf-8')
    ctx = {
        'kernel_manager': _FakeKM(),
        'workspace_dir': str(tmp_path),
        'is_safe_path': lambda p: is_safe_path(str(tmp_path), p),
    }
    result = tools.execute_tool('list_files', {}, ctx)
    assert result['ok'] is True
    assert result['data'] == ['a.ipynb', 'b.ipynb']


def test_execute_read_nb(tmp_path):
    nb = {"cells": [{"cell_type": "code", "source": ["print('hi')"]}]}
    (tmp_path / 'n.ipynb').write_text(json.dumps(nb), encoding='utf-8')
    ctx = {
        'kernel_manager': _FakeKM(),
        'workspace_dir': str(tmp_path),
        'is_safe_path': lambda p: is_safe_path(str(tmp_path), p),
    }
    result = tools.execute_tool('read_nb', {'filename': 'n.ipynb'}, ctx)
    assert result['ok'] is True
    assert '1 cell' in result['summary']
    assert "print('hi')" in result['data']['cells']


def test_execute_read_nb_rejects_traversal(tmp_path):
    ctx = {
        'kernel_manager': _FakeKM(),
        'workspace_dir': str(tmp_path),
        'is_safe_path': lambda p: is_safe_path(str(tmp_path), p),
    }
    result = tools.execute_tool('read_nb', {'filename': '../etc/passwd.ipynb'}, ctx)
    assert result['ok'] is False


def test_execute_gpu_status(tmp_path, monkeypatch):
    def fake_gpu_state():
        return {
            'name': 'Iluvatar MR-V100', 'vram_total': 32768, 'vram_used': 100,
            'utilization': 42.0, 'temperature': 55.0, 'power_draw': 30.0,
            'core_clock': 1200, 'memory_clock': 800, 'status': 'Idle',
        }
    monkeypatch.setattr('core.gpu.get_real_gpu_state', fake_gpu_state)
    ctx = {
        'kernel_manager': _FakeKM(),
        'workspace_dir': str(tmp_path),
        'is_safe_path': lambda p: is_safe_path(str(tmp_path), p),
    }
    result = tools.execute_tool('gpu_status', {}, ctx)
    assert result['ok'] is True
    assert '42.0%' in result['summary']


def test_execute_unknown_tool(tmp_path):
    ctx = {
        'kernel_manager': _FakeKM(),
        'workspace_dir': str(tmp_path),
        'is_safe_path': lambda p: is_safe_path(str(tmp_path), p),
    }
    result = tools.execute_tool('does_not_exist', {}, ctx)
    assert result['ok'] is False
    assert 'unknown tool' in result['summary']