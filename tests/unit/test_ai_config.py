"""Unit tests for the API config persistence route (core/routes/ai_routes.py).

Covers the ``POST /api/save_config`` endpoint: writing the OPENI_API_* triple
to ``~/.Iluvatar-AI-Notebook/config.yaml``, syncing runtime defaults +
``os.environ``, and the validation / write-failure branches.

方案三适配：Flask test_client → starlette TestClient；monkeypatch 目标由
入口模块（``app``）改为共享状态单例（``core.state.app_state``）。
"""

import os

import pytest
import yaml
from fastapi.testclient import TestClient
from types import SimpleNamespace

from app_fastapi import app
from core.state import app_state
from core.user_config import get_config_path


class TestSaveConfigEndpoint:
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
        with TestClient(app) as c:
            yield c

    def test_saves_config_file_and_syncs_runtime_defaults(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(app_state, 'DEFAULT_API_URL', '')
        monkeypatch.setattr(app_state, 'DEFAULT_API_MODEL', '')
        monkeypatch.setattr(app_state, 'DEFAULT_API_TOKEN', '')

        resp = client.post('/api/save_config', json={
            'url': 'https://new.example/v1/chat/completions',
            'token': 'secret-token',
            'model': 'dsv7',
        })

        assert resp.status_code == 200
        assert resp.json()['ok'] is True

        config = yaml.safe_load(open(get_config_path(), encoding='utf-8').read())['config']
        assert config['OPENI_API_URL'] == 'https://new.example/v1/chat/completions'
        assert config['OPENI_API_TOKEN'] == 'secret-token'
        assert config['OPENI_API_MODEL'] == 'dsv7'

        assert app_state.DEFAULT_API_URL == 'https://new.example/v1/chat/completions'
        assert app_state.DEFAULT_API_TOKEN == 'secret-token'
        assert app_state.DEFAULT_API_MODEL == 'dsv7'
        assert os.environ.get('OPENI_API_URL') == 'https://new.example/v1/chat/completions'
        assert os.environ.get('OPENI_API_MODEL') == 'dsv7'

    def test_rejects_empty_url_or_model(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.setattr(app_state, 'WORKSPACE_DIR', os.path.realpath(tmp_path))
        resp = client.post('/api/save_config', json={'url': '', 'token': '', 'model': 'dsv4'})
        assert resp.status_code == 400
        assert resp.json()['error_code'] == 'INVALID_CONFIG'
        assert not os.path.exists(get_config_path())

    def test_write_error_returns_500(self, client, monkeypatch):
        def boom(url, token, model):
            raise OSError('read-only fs')

        monkeypatch.setattr('core.routes.ai_routes.save_model_config', boom)
        resp = client.post('/api/save_config', json={
            'url': 'https://x/v1/chat/completions', 'token': '', 'model': 'm',
        })
        assert resp.status_code == 500
        data = resp.json()
        assert data['error_code'] == 'CONFIG_WRITE_ERROR'

    def test_get_config_still_hides_token(self, client):
        resp = client.get('/api/get_config')
        assert resp.status_code == 200
        assert 'default_token' not in resp.json()