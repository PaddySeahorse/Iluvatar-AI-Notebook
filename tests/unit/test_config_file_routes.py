"""Unit tests for the raw config-file routes (core/routes/config_file_routes.py).

Covers ``GET /api/config_file`` (read raw ``litellm_config.yaml`` text or the
generated preview when the file is absent) and ``POST /api/config_file``
(lightweight YAML validation, rollback-aware save via ``apply_config_with_rollback``,
runtime-default sync from the first route).
"""

import os

import pytest
import yaml
from fastapi.testclient import TestClient
from types import SimpleNamespace

from app_fastapi import app
from core.litellm_manager import get_litellm_config_path
from core.state import app_state

VALID_CONTENT = (
    'model_list:\n'
    '- model_name: dsv7\n'
    '  litellm_params:\n'
    '    model: openai/dsv7\n'
    '    api_key: secret\n'
    '    api_base: https://new.example/v1\n'
)


class TestConfigFileEndpoint:
    @pytest.fixture()
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setenv('HOME', str(tmp_path))
        # Isolate from OPENI_API_* leakage across test files; the lifespan
        # bootstrap would otherwise seed a real config file from them.
        for key in ('OPENI_API_URL', 'OPENI_API_TOKEN', 'OPENI_API_MODEL'):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setattr(app_state, 'WORKSPACE_DIR', os.path.realpath(tmp_path))
        fake_kernel = SimpleNamespace(
            warm_start=lambda: None,
            stop_watchdog=lambda: None,
            shutdown=lambda: None,
        )
        monkeypatch.setattr(app_state, 'kernel_manager', fake_kernel)
        # Empty URL/TOKEN keeps the lifespan bootstrap from writing the config
        # file, so the GET preview branch can be exercised deterministically.
        monkeypatch.setattr(app_state, 'DEFAULT_API_URL', '')
        monkeypatch.setattr(app_state, 'DEFAULT_API_TOKEN', '')
        monkeypatch.setattr(app_state, 'DEFAULT_API_MODEL', 'old-model')
        apply_calls = []
        monkeypatch.setattr(
            'core.routes.config_file_routes.litellm_manager',
            SimpleNamespace(
                apply_config_with_rollback=lambda content: apply_calls.append(content) or (True, '')
            ),
        )
        monkeypatch.setattr('core.routes.config_file_routes.is_manually_managed', lambda: False)
        monkeypatch.setattr(
            'core.routes.config_file_routes.read_first_route',
            lambda: ('https://new.example/v1', 'dsv7'),
        )
        with TestClient(app) as c:
            c._apply_calls = apply_calls
            yield c

    def test_get_missing_file_returns_generated_preview(self, client):
        resp = client.get('/api/config_file')
        assert resp.status_code == 200
        data = resp.json()
        assert data['exists'] is False
        assert data['preview'] is True
        assert data['managed_manually'] is False
        assert data['path'] == get_litellm_config_path()
        parsed = yaml.safe_load(data['content'])
        assert parsed['model_list'][0]['model_name'] == 'old-model'

    def test_get_returns_raw_content(self, client):
        path = get_litellm_config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(VALID_CONTENT)
        data = client.get('/api/config_file').json()
        assert data['exists'] is True
        assert data['preview'] is False
        assert data['content'] == VALID_CONTENT

    def test_get_reports_manual_management(self, client, monkeypatch):
        monkeypatch.setattr('core.routes.config_file_routes.is_manually_managed', lambda: True)
        data = client.get('/api/config_file').json()
        assert data['managed_manually'] is True

    def test_post_success_writes_and_syncs_runtime(self, client, monkeypatch):
        monkeypatch.setattr(app_state, 'DEFAULT_API_URL', '')
        monkeypatch.setattr(app_state, 'DEFAULT_API_MODEL', '')

        resp = client.post('/api/config_file', json={'content': VALID_CONTENT})

        assert resp.status_code == 200
        assert resp.json()['ok'] is True
        assert client._apply_calls == [VALID_CONTENT]

        assert app_state.DEFAULT_API_URL == 'https://new.example/v1'
        assert app_state.DEFAULT_API_MODEL == 'dsv7'
        assert os.environ.get('OPENI_API_URL') == 'https://new.example/v1'
        assert os.environ.get('OPENI_API_MODEL') == 'dsv7'

    def test_post_restart_failure_returns_502_with_summary(self, client, monkeypatch):
        monkeypatch.setattr(
            'core.routes.config_file_routes.litellm_manager',
            SimpleNamespace(apply_config_with_rollback=lambda content: (False, 'ERROR: bad model')),
        )
        resp = client.post('/api/config_file', json={'content': VALID_CONTENT})
        assert resp.status_code == 502
        data = resp.json()
        assert data['error_code'] == 'LITELLM_RESTART_FAILED'
        assert 'ERROR: bad model' in data['message']

    def test_post_rejects_bad_yaml(self, client):
        resp = client.post('/api/config_file', json={'content': 'model_list: [unclosed'})
        assert resp.status_code == 400
        assert resp.json()['error_code'] == 'INVALID_LITELLM_CONFIG'

    def test_post_rejects_non_mapping_top_level(self, client):
        resp = client.post('/api/config_file', json={'content': '- just\n- a list\n'})
        assert resp.status_code == 400
        assert resp.json()['error_code'] == 'INVALID_LITELLM_CONFIG'

    def test_post_rejects_empty_content(self, client):
        resp = client.post('/api/config_file', json={'content': '  '})
        assert resp.status_code == 400
        assert resp.json()['error_code'] == 'INVALID_CONFIG'
