import os

import pytest
from fastapi.testclient import TestClient

from app_fastapi import app
from core.state import app_state


class FakeKernelManager:
    """Minimal fake that satisfies the FastAPI lifespan + used routes."""

    def warm_start(self):
        pass

    def stop_watchdog(self):
        pass

    def shutdown(self):
        pass

    def __init__(self):
        self.code = None

    def execute(self, code):
        self.code = code
        return {
            'success': True,
            'stdout': 'ok\n',
            'stderr': '',
            'html': '',
            'plots': [],
            'variables': [{'name': 'x', 'type': 'int', 'repr': '1', 'shape': None}],
        }

    def get_variables(self):
        return []


@pytest.fixture()
def client(monkeypatch):
    fake = FakeKernelManager()
    monkeypatch.setattr(app_state, 'kernel_manager', fake)
    with TestClient(app) as c:
        yield c, fake


def test_get_config_does_not_expose_default_token(client):
    c, _ = client
    response = c.get('/api/get_config')

    assert response.status_code == 200
    data = response.json()
    assert 'default_url' in data
    assert 'default_model' in data
    assert 'default_token' not in data


def test_lint_cell_reports_syntax_errors(client):
    c, _ = client
    response = c.post('/api/lint_cell', json={'code': 'x ='})

    assert response.status_code == 200
    data = response.json()
    assert data['warnings'] == []
    assert data['errors']
    assert data['errors'][0]['line'] == 1


def test_run_cell_delegates_to_kernel_manager(client):
    c, fake = client
    response = c.post('/api/run_cell', json={'code': "print('ok')"})

    assert response.status_code == 200
    data = response.json()
    assert fake.code == "print('ok')"
    assert data['success'] is True
    assert data['stdout'] == 'ok\n'
    assert data['stderr'] == ''
    assert 'elapsed_time' in data


def test_file_save_and_read_round_trip(client, monkeypatch, tmp_path):
    c, _ = client
    monkeypatch.setattr(app_state, 'WORKSPACE_DIR', os.path.realpath(tmp_path))
    content = {'cells': [], 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 2}

    save_response = c.post(
        '/api/files/save',
        json={'filename': 'example.ipynb', 'content': content},
    )
    read_response = c.get('/api/files/read?filename=example.ipynb')

    assert save_response.status_code == 200
    assert save_response.json()['success'] is True
    assert read_response.status_code == 200
    assert read_response.json()['content'] == content


def test_is_safe_path_blocks_symlink_escape(monkeypatch, tmp_path):
    workspace = tmp_path / 'workspace'
    external = tmp_path / 'external'
    workspace.mkdir()
    external.mkdir()
    (external / 'secret.ipynb').write_text('{}', encoding='utf-8')
    (workspace / 'linked.ipynb').symlink_to(external / 'secret.ipynb')

    monkeypatch.setattr(app_state, 'WORKSPACE_DIR', os.path.realpath(workspace))

    assert app_state.is_safe_path('linked.ipynb') is False