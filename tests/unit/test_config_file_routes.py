"""Unit tests for the raw config-file routes (core/routes/config_file_routes.py).

Covers ``GET /api/config_file`` (read raw ``config.yaml`` text) and ``POST
/api/config_file`` (validate YAML / write-back / apply the OPENI_API_* triple
to runtime defaults + ``os.environ`` / sync the LiteLLM Proxy route).
"""

import os

import pytest
import yaml
from fastapi.testclient import TestClient
from types import SimpleNamespace

from app_fastapi import app
from core.state import app_state
from core.user_config import get_config_path


class TestConfigFileEndpoint:
    @pytest.fixture()
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.setattr(app_state, 'WORKSPACE_DIR', os.path.realpath(tmp_path))
        fake_kernel = SimpleNamespace(
            warm_start=lambda: None,
            stop_watchdog=lambda: None,
            shutdown=lambda: None,
        )
        monkeypatch.setattr(app_state, 'kernel_manager', fake_kernel)
        monkeypatch.setattr(
            app_state, 'DEFAULT_API_URL', 'https://old.example/v1/chat/completions',
        )
        monkeypatch.setattr(app_state, 'DEFAULT_API_TOKEN', 'old-token')
        monkeypatch.setattr(app_state, 'DEFAULT_API_MODEL', 'old-model')
        sync_calls = []
        monkeypatch.setattr(
            'core.routes.config_file_routes.litellm_manager',
            SimpleNamespace(
                sync_config=lambda url, token, model: sync_calls.append((url, token, model)) or True
            ),
        )
        with TestClient(app) as c:
            c._sync_calls = sync_calls
            yield c

    def test_get_missing_file_returns_empty(self, client):
        resp = client.get('/api/config_file')
        assert resp.status_code == 200
        data = resp.json()
        assert data['exists'] is False
        assert data['content'] == ''
        assert data['path'] == get_config_path()

    def test_get_returns_raw_content(self, client):
        os.makedirs(os.path.dirname(get_config_path()), exist_ok=True)
        with open(get_config_path(), 'w', encoding='utf-8') as f:
            f.write('config:\n  OPENI_API_MODEL: dsv4\n')
        data = client.get('/api/config_file').json()
        assert data['exists'] is True
        assert 'OPENI_API_MODEL: dsv4' in data['content']

    def test_post_writes_raw_and_applies_runtime(self, client):
        content = (
            'config:\n'
            '  OPENI_API_URL: https://new.example/v1/chat/completions\n'
            '  OPENI_API_TOKEN: secret\n'
            '  OPENI_API_MODEL: dsv7\n'
            '  USE_OPENAI_SDK: \'true\'\n'
        )
        resp = client.post('/api/config_file', json={'content': content})
        assert resp.status_code == 200
        assert resp.json()['ok'] is True

        # File was written verbatim (mode 0600) and keeps the USE_* key.
        raw = open(get_config_path(), encoding='utf-8').read()
        assert raw == content
        assert (os.stat(get_config_path()).st_mode & 0o777) == 0o600
        saved = yaml.safe_load(raw)['config']
        assert saved['OPENI_API_MODEL'] == 'dsv7'
        assert saved['USE_OPENAI_SDK'] == 'true'

        assert app_state.DEFAULT_API_URL == 'https://new.example/v1/chat/completions'
        assert app_state.DEFAULT_API_TOKEN == 'secret'
        assert app_state.DEFAULT_API_MODEL == 'dsv7'
        assert os.environ.get('OPENI_API_URL') == 'https://new.example/v1/chat/completions'
        assert os.environ.get('OPENI_API_MODEL') == 'dsv7'

        assert client._sync_calls == [
            ('https://new.example/v1/chat/completions', 'secret', 'dsv7')
        ]

    def test_post_skips_litellm_when_url_empty(self, client):
        content = (
            'config:\n'
            '  OPENI_API_URL: \'\'\n'
            '  OPENI_API_TOKEN: \'\'\n'
            '  OPENI_API_MODEL: dsv4\n'
        )
        resp = client.post('/api/config_file', json={'content': content})
        assert resp.status_code == 200
        assert client._sync_calls == []

    def test_post_rejects_bad_yaml(self, client):
        resp = client.post('/api/config_file', json={'content': 'config: [unclosed'})
        assert resp.status_code == 400
        assert resp.json()['error_code'] == 'INVALID_CONFIG'

    def test_post_rejects_missing_config_mapping(self, client):
        resp = client.post('/api/config_file', json={'content': 'foo: bar\n'})
        assert resp.status_code == 400
        assert resp.json()['error_code'] == 'INVALID_CONFIG'

    def test_post_rejects_empty_content(self, client):
        resp = client.post('/api/config_file', json={'content': '  '})
        assert resp.status_code == 400
        assert resp.json()['error_code'] == 'INVALID_CONFIG'

    def test_post_write_error_returns_500(self, client, monkeypatch):
        def boom(content):
            raise OSError('read-only fs')

        monkeypatch.setattr(
            'core.routes.config_file_routes.write_raw_config_content', boom
        )
        resp = client.post('/api/config_file', json={'content': 'config: {}\n'})
        assert resp.status_code == 500
        assert resp.json()['error_code'] == 'CONFIG_WRITE_ERROR'