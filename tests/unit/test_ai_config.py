"""Unit tests for the API config routes (core/routes/ai_routes.py).

Covers ``POST /api/save_config`` (runtime defaults + ``os.environ`` sync +
LiteLLM proxy rewrite, manual-management refusal) and ``GET /api/get_config``
(first-route read-back with environment fallback).

方案三适配：Flask test_client → starlette TestClient；monkeypatch 目标由
入口模块（``app``）改为共享状态单例（``core.state.app_state``）。
"""

import os

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

from app_fastapi import app
from core.state import app_state


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
        # The save route also syncs the local LiteLLM Proxy; stub the manager
        # and the name-bound helpers so the tests can assert each branch.
        sync_calls = []
        monkeypatch.setattr(
            'core.routes.ai_routes.litellm_manager',
            SimpleNamespace(
                sync_config=lambda url, token, model: sync_calls.append((url, token, model)) or True
            ),
        )
        monkeypatch.setattr('core.routes.ai_routes.is_manually_managed', lambda: False)
        monkeypatch.setattr(
            'core.routes.ai_routes.read_first_route',
            lambda: ('', ''),
        )
        with TestClient(app) as c:
            c._sync_calls = sync_calls
            yield c

    def _reset_defaults(self, monkeypatch):
        monkeypatch.setattr(app_state, 'DEFAULT_API_URL', '')
        monkeypatch.setattr(app_state, 'DEFAULT_API_MODEL', '')
        monkeypatch.setattr(app_state, 'DEFAULT_API_TOKEN', '')

    def test_saves_config_and_syncs_runtime_defaults(self, client, monkeypatch):
        self._reset_defaults(monkeypatch)
        monkeypatch.setattr(
            'core.routes.ai_routes.read_first_route',
            lambda: ('https://new.example/v1/chat/completions', 'dsv7'),
        )

        resp = client.post('/api/save_config', json={
            'url': 'https://new.example/v1/chat/completions',
            'token': 'secret-token',
            'model': 'dsv7',
        })

        assert resp.status_code == 200
        assert resp.json()['ok'] is True

        assert app_state.DEFAULT_API_URL == 'https://new.example/v1/chat/completions'
        assert app_state.DEFAULT_API_TOKEN == 'secret-token'
        assert app_state.DEFAULT_API_MODEL == 'dsv7'
        assert os.environ.get('OPENI_API_URL') == 'https://new.example/v1/chat/completions'
        assert os.environ.get('OPENI_API_MODEL') == 'dsv7'

        # The local LiteLLM Proxy route is updated with the same upstream triple.
        assert client._sync_calls == [
            ('https://new.example/v1/chat/completions', 'secret-token', 'dsv7')
        ]

    def test_rejects_when_manually_managed(self, client, monkeypatch):
        self._reset_defaults(monkeypatch)
        monkeypatch.delenv('OPENI_API_URL', raising=False)
        monkeypatch.delenv('OPENI_API_MODEL', raising=False)
        monkeypatch.setattr('core.routes.ai_routes.is_manually_managed', lambda: True)

        resp = client.post('/api/save_config', json={
            'url': 'https://new.example/v1/chat/completions',
            'token': 'secret-token',
            'model': 'dsv7',
        })

        assert resp.status_code == 409
        data = resp.json()
        assert data['error_code'] == 'CONFIG_MANAGED_MANUALLY'
        assert '高级模式' in data['message']

        # Manual management means zero side effects on runtime state.
        assert client._sync_calls == []
        assert app_state.DEFAULT_API_URL == ''
        assert os.environ.get('OPENI_API_URL') != 'https://new.example/v1/chat/completions'

    def test_rejects_empty_url_or_model(self, client):
        resp = client.post('/api/save_config', json={'url': '', 'token': '', 'model': 'dsv4'})
        assert resp.status_code == 400
        assert resp.json()['error_code'] == 'INVALID_CONFIG'
        assert client._sync_calls == []

    def test_get_config_reads_first_route(self, client, monkeypatch):
        monkeypatch.setattr(
            'core.routes.ai_routes.read_first_route',
            lambda: ('https://first.example/v1', 'first-model'),
        )
        resp = client.get('/api/get_config')
        assert resp.status_code == 200
        assert resp.json() == {
            'default_url': 'https://first.example/v1',
            'default_model': 'first-model',
        }

    def test_get_config_falls_back_to_runtime_defaults(self, client, monkeypatch):
        monkeypatch.setattr(app_state, 'DEFAULT_API_URL', 'https://seed.example/v1')
        monkeypatch.setattr(app_state, 'DEFAULT_API_MODEL', 'seed-model')
        monkeypatch.setattr('core.routes.ai_routes.read_first_route', lambda: ('', ''))

        resp = client.get('/api/get_config')
        assert resp.status_code == 200
        assert resp.json() == {
            'default_url': 'https://seed.example/v1',
            'default_model': 'seed-model',
        }

    def test_get_config_still_hides_token(self, client):
        resp = client.get('/api/get_config')
        assert resp.status_code == 200
        assert 'default_token' not in resp.json()
