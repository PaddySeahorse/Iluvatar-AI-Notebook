"""Unit tests for the host-side user config (core/user_config.py).

Covers ``save_model_config`` (the persistence behind POST /api/save_config)
and ``apply_saved_config`` (the startup seed / restore hook), both against
the native YAML config file.
"""

import os

import pytest
import yaml

from core import user_config


@pytest.fixture()
def home(monkeypatch, tmp_path):
    monkeypatch.setenv('HOME', str(tmp_path))
    return tmp_path


@pytest.fixture()
def clean_env(monkeypatch):
    for key in user_config.PERSISTED_KEYS:
        monkeypatch.delenv(key, raising=False)


def _read_config(home):
    path = home / '.Iluvatar-AI-Notebook' / 'config.yaml'
    return yaml.safe_load(path.read_text(encoding='utf-8'))


class TestSaveModelConfig:
    def test_writes_triple_and_timestamp(self, home):
        path = user_config.save_model_config(
            'https://x.example/v1/chat/completions', 'tok-123', 'dsv4')

        assert path == str(home / '.Iluvatar-AI-Notebook' / 'config.yaml')
        data = _read_config(home)
        assert data['config']['OPENI_API_URL'] == 'https://x.example/v1/chat/completions'
        assert data['config']['OPENI_API_TOKEN'] == 'tok-123'
        assert data['config']['OPENI_API_MODEL'] == 'dsv4'
        assert 'saved_at' in data

    def test_file_permissions_restrictive(self, home):
        path = user_config.save_model_config('https://x/v1/chat/completions', '', 'm')
        assert (os.stat(path).st_mode & 0o777) == 0o600

    def test_preserves_unrelated_keys(self, home):
        cfg = home / '.Iluvatar-AI-Notebook' / 'config.yaml'
        cfg.parent.mkdir(parents=True)
        cfg.write_text(yaml.safe_dump({
            'saved_at': '2026-01-01T00:00:00',
            'config': {'USE_OPENAI_SDK': '1'},
        }), encoding='utf-8')

        user_config.save_model_config('https://new/v1/chat/completions', 't', 'm')

        config = _read_config(home)['config']
        assert config['USE_OPENAI_SDK'] == '1'
        assert config['OPENI_API_MODEL'] == 'm'

    def test_overwrites_previous_values(self, home):
        user_config.save_model_config('https://old/v1/chat/completions', 'old-tok', 'old')
        user_config.save_model_config('https://new/v1/chat/completions', 'new-tok', 'new')

        config = _read_config(home)['config']
        assert config['OPENI_API_URL'] == 'https://new/v1/chat/completions'
        assert config['OPENI_API_TOKEN'] == 'new-tok'

    def test_raises_oserror_on_write_failure(self, home, monkeypatch):
        blocked = home / 'blocked'
        blocked.mkdir()
        monkeypatch.setattr(user_config, 'get_config_path', lambda: str(blocked))

        with pytest.raises(OSError):
            user_config.save_model_config('https://x/v1/chat/completions', '', 'm')


class TestApplySavedConfig:
    def test_seeds_config_from_environment_on_first_run(self, home, clean_env, monkeypatch):
        monkeypatch.setenv('OPENI_API_URL', 'https://seed.example/v1/chat/completions')
        monkeypatch.setenv('OPENI_API_TOKEN', 'seed-tok')

        path = user_config.apply_saved_config()

        assert path == user_config.get_config_path()
        config = _read_config(home)['config']
        assert config['OPENI_API_URL'] == 'https://seed.example/v1/chat/completions'
        assert config['OPENI_API_TOKEN'] == 'seed-tok'

    def test_restores_saved_values_into_environ(self, home, clean_env):
        cfg = home / '.Iluvatar-AI-Notebook' / 'config.yaml'
        cfg.parent.mkdir(parents=True)
        cfg.write_text(yaml.safe_dump({
            'config': {'OPENI_API_URL': 'https://restored/v1/chat/completions', 'OPENI_API_TOKEN': 'restored-tok'},
        }), encoding='utf-8')

        user_config.apply_saved_config()

        assert os.environ.get('OPENI_API_URL') == 'https://restored/v1/chat/completions'
        assert os.environ.get('OPENI_API_TOKEN') == 'restored-tok'

    def test_environment_takes_precedence(self, home, clean_env, monkeypatch):
        cfg = home / '.Iluvatar-AI-Notebook' / 'config.yaml'
        cfg.parent.mkdir(parents=True)
        cfg.write_text(yaml.safe_dump({
            'config': {'OPENI_API_MODEL': 'saved-model'},
        }), encoding='utf-8')
        monkeypatch.setenv('OPENI_API_MODEL', 'env-model')

        user_config.apply_saved_config()

        assert os.environ.get('OPENI_API_MODEL') == 'env-model'

    def test_empty_saved_values_are_skipped(self, home, clean_env):
        cfg = home / '.Iluvatar-AI-Notebook' / 'config.yaml'
        cfg.parent.mkdir(parents=True)
        cfg.write_text(yaml.safe_dump({'config': {'OPENI_API_TOKEN': ''}}), encoding='utf-8')

        user_config.apply_saved_config()

        assert 'OPENI_API_TOKEN' not in os.environ

    def test_returns_none_when_seeding_fails(self, home, clean_env, monkeypatch):
        def boom(*args, **kwargs):
            raise OSError('read-only fs')

        monkeypatch.setattr(user_config, 'save_model_config', boom)

        assert user_config.apply_saved_config() is None


class TestLoadSavedConfig:
    def test_missing_file_returns_empty(self, home):
        assert user_config.load_saved_config() == {}

    def test_corrupt_file_returns_empty(self, home):
        cfg = home / '.Iluvatar-AI-Notebook' / 'config.yaml'
        cfg.parent.mkdir(parents=True)
        cfg.write_text('{not: [valid: yaml', encoding='utf-8')
        assert user_config.load_saved_config() == {}

    def test_non_dict_config_returns_empty(self, home):
        cfg = home / '.Iluvatar-AI-Notebook' / 'config.yaml'
        cfg.parent.mkdir(parents=True)
        cfg.write_text(yaml.safe_dump({'config': ['not', 'a', 'dict']}), encoding='utf-8')
        assert user_config.load_saved_config() == {}
