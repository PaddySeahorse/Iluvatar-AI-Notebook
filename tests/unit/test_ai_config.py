"""Unit tests for the API config persistence route (core/routes/ai_routes.py).

Covers the ``.env`` upsert helper and the ``POST /api/save_config`` endpoint:
in-place update of existing keys, appending new keys, preserving comments and
unrelated lines, syncing runtime defaults + ``os.environ``, and the
validation / write-failure branches.
"""

import os

import pytest

import app as notebook_app
from core.routes.ai_routes import _upsert_env


class TestUpsertEnv:
    """_upsert_env preserves structure while updating the three OPENI_API_* keys."""

    def test_creates_file_when_missing(self, tmp_path):
        env = tmp_path / '.env'
        _upsert_env(str(env), {'OPENI_API_URL': 'https://x/v1/chat/completions', 'OPENI_API_TOKEN': 'tok', 'OPENI_API_MODEL': 'm1'})
        content = env.read_text(encoding='utf-8')
        assert 'OPENI_API_URL=https://x/v1/chat/completions' in content
        assert 'OPENI_API_TOKEN=tok' in content
        assert 'OPENI_API_MODEL=m1' in content

    def test_updates_in_place_and_preserves_other_lines(self, tmp_path):
        env = tmp_path / '.env'
        env.write_text(
            '# comment\n'
            'OPENI_API_URL=https://old.example/v1/chat/completions\n'
            'USE_ILUVATAR_PROVISIONER=true\n'
            'OPENI_API_MODEL=dsv4\n',
            encoding='utf-8',
        )
        _upsert_env(str(env), {'OPENI_API_URL': 'https://new.example/v1/chat/completions', 'OPENI_API_TOKEN': 'tok', 'OPENI_API_MODEL': 'dsv5'})
        lines = env.read_text(encoding='utf-8').splitlines()
        assert lines[0] == '# comment'
        assert lines[1] == 'OPENI_API_URL=https://new.example/v1/chat/completions'
        assert lines[2] == 'USE_ILUVATAR_PROVISIONER=true'
        assert lines[3] == 'OPENI_API_MODEL=dsv5'
        assert 'OPENI_API_TOKEN=tok' in lines
        assert sum(1 for l in lines if l.startswith('OPENI_API_URL=')) == 1

    def test_appends_missing_key_only(self, tmp_path):
        env = tmp_path / '.env'
        env.write_text('OPENI_API_MODEL=dsv4\n', encoding='utf-8')
        _upsert_env(str(env), {'OPENI_API_TOKEN': 'tok', 'OPENI_API_MODEL': 'new'})
        lines = env.read_text(encoding='utf-8').splitlines()
        assert lines[0] == 'OPENI_API_MODEL=new'
        assert 'OPENI_API_TOKEN=tok' in lines


class TestSaveConfigEndpoint:
    @pytest.fixture()
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setattr(notebook_app, 'WORKSPACE_DIR', os.path.realpath(tmp_path))
        notebook_app.app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
        with notebook_app.app.test_client() as c:
            yield c

    def test_saves_env_and_syncs_runtime_defaults(self, client, monkeypatch, tmp_path):
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
        env = tmp_path / '.env'
        assert env.exists()
        assert 'OPENI_API_URL=https://new.example/v1/chat/completions' in env.read_text(encoding='utf-8')

        assert notebook_app.DEFAULT_API_URL == 'https://new.example/v1/chat/completions'
        assert notebook_app.DEFAULT_API_TOKEN == 'secret-token'
        assert notebook_app.DEFAULT_API_MODEL == 'dsv7'
        assert os.environ.get('OPENI_API_URL') == 'https://new.example/v1/chat/completions'
        assert os.environ.get('OPENI_API_MODEL') == 'dsv7'

    def test_rejects_empty_url_or_model(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(notebook_app, 'WORKSPACE_DIR', os.path.realpath(tmp_path))
        resp = client.post('/api/save_config', json={'url': '', 'token': '', 'model': 'dsv4'})
        assert resp.status_code == 400
        assert resp.get_json()['error_code'] == 'INVALID_CONFIG'
        assert not (tmp_path / '.env').exists()

    def test_write_error_returns_500(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(notebook_app, 'WORKSPACE_DIR', os.path.realpath(tmp_path))

        def boom(path, updates):
            raise OSError('read-only fs')

        monkeypatch.setattr('core.routes.ai_routes._upsert_env', boom)
        resp = client.post('/api/save_config', json={
            'url': 'https://x/v1/chat/completions', 'token': '', 'model': 'm',
        })
        assert resp.status_code == 500
        data = resp.get_json()
        assert data['error_code'] == 'ENV_WRITE_ERROR'

    def test_get_config_still_hides_token(self, client):
        resp = client.get('/api/get_config')
        assert resp.status_code == 200
        assert 'default_token' not in resp.get_json()