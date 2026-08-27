"""Unit tests for the API config persistence route (core/routes/ai_routes.py).

Covers the ``POST /api/save_config`` endpoint: writing the OPENI_API_* triple
to ``~/.Iluvatar-AI-Notebook/config.yaml``, syncing runtime defaults +
``os.environ``, and the validation / write-failure branches.
"""

import os

import pytest
import yaml

import app as notebook_app
from core.user_config import get_config_path


class TestSaveConfigEndpoint:
    @pytest.fixture()
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.setattr(notebook_app, 'WORKSPACE_DIR', os.path.realpath(tmp_path))
        notebook_app.app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
        with notebook_app.app.test_client() as c:
            yield c

    def test_saves_config_file_and_syncs_runtime_defaults(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(notebook_app, 'DEFAULT_API_URL', '')
        monkeypatch.setattr(notebook_app, 'DEFAULT_API_MODEL', '')
        monkeypatch.setattr(notebook_app, 'DEFAULT_API_TOKEN', '')

        resp = client.post('/api/save_config', json={
            'url': 'https://new.example/v1/chat/completions',
            'token': 'secret-token',
            'model': 'dsv7',
        })

        assert resp.status_code == 200
        assert resp.get_json()['ok'] is True

        config = yaml.safe_load(open(get_config_path(), encoding='utf-8').read())['config']
        assert config['OPENI_API_URL'] == 'https://new.example/v1/chat/completions'
        assert config['OPENI_API_TOKEN'] == 'secret-token'
        assert config['OPENI_API_MODEL'] == 'dsv7'

        assert notebook_app.DEFAULT_API_URL == 'https://new.example/v1/chat/completions'
        assert notebook_app.DEFAULT_API_TOKEN == 'secret-token'
        assert notebook_app.DEFAULT_API_MODEL == 'dsv7'
        assert os.environ.get('OPENI_API_URL') == 'https://new.example/v1/chat/completions'
        assert os.environ.get('OPENI_API_MODEL') == 'dsv7'

    def test_rejects_empty_url_or_model(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.setattr(notebook_app, 'WORKSPACE_DIR', os.path.realpath(tmp_path))
        resp = client.post('/api/save_config', json={'url': '', 'token': '', 'model': 'dsv4'})
        assert resp.status_code == 400
        assert resp.get_json()['error_code'] == 'INVALID_CONFIG'
        assert not os.path.exists(get_config_path())

    def test_write_error_returns_500(self, client, monkeypatch):
        def boom(url, token, model):
            raise OSError('read-only fs')

        monkeypatch.setattr('core.routes.ai_routes.save_model_config', boom)
        resp = client.post('/api/save_config', json={
            'url': 'https://x/v1/chat/completions', 'token': '', 'model': 'm',
        })
        assert resp.status_code == 500
        data = resp.get_json()
        assert data['error_code'] == 'CONFIG_WRITE_ERROR'

    def test_get_config_still_hides_token(self, client):
        resp = client.get('/api/get_config')
        assert resp.status_code == 200
        assert 'default_token' not in resp.get_json()
