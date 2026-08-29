"""Unit tests for the self-hosted LiteLLM Proxy lifecycle (core/litellm_manager.py).

Covers config model-list generation, writing the proxy config file, liveness
probing and the start/restart/stop flow — all with network/subprocess fakes so
no LiteLLM binary nor listening port is required.
"""

import os

import yaml
from types import SimpleNamespace

import core.litellm_manager as lm


def _auth_headers():
    return {'token': 'sk-upstream', 'url': 'https://api.upstream.example/v1', 'model': 'dsv4'}


class TestBuildConfig:
    def test_model_list_maps_upstream_endpoint(self):
        cfg = lm.build_litellm_config('https://api.upstream.example/v1', 'sk-123', 'dsv4')
        model = cfg['model_list'][0]
        assert model['model_name'] == 'dsv4'
        assert model['litellm_params'] == {
            'model': 'openai/dsv4',
            'api_key': 'sk-123',
            'api_base': 'https://api.upstream.example/v1',
        }


class TestWriteConfig:
    def test_writes_yaml_with_0600(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        path = lm.write_config('https://api.upstream.example/v1', 'sk-123', 'dsv4')
        assert path == lm.get_litellm_config_path()
        data = yaml.safe_load(open(path, encoding='utf-8').read())
        assert data['model_list'][0]['model_name'] == 'dsv4'
        assert os.stat(path).st_mode & 0o777 == 0o600


class TestLiveness:
    def test_is_alive_true(self, monkeypatch):
        monkeypatch.setattr(
            lm.requests,
            'get',
            lambda *a, **k: SimpleNamespace(status_code=200),
        )
        assert lm.litellm_manager.is_alive() is True

    def test_is_alive_false_on_network_error(self, monkeypatch):
        def boom(*a, **k):
            raise lm.requests.exceptions.ConnectionError('down')

        monkeypatch.setattr(lm.requests, 'get', boom)
        assert lm.litellm_manager.is_alive() is False


class TestEnsureRunning:
    def test_returns_true_when_already_alive(self, monkeypatch):
        m = lm.LitellmManager()
        monkeypatch.setattr(m, 'is_alive', lambda timeout=2.0: True)
        assert m.ensure_running() is True

    def test_skips_start_when_no_config_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        m = lm.LitellmManager()
        monkeypatch.setattr(m, 'is_alive', lambda timeout=2.0: False)
        monkeypatch.setattr(m, '_spawn', lambda config_path: (_ for _ in ()).throw(AssertionError('must not spawn')))
        assert m.ensure_running() is False

    def test_spawns_and_waits_until_ready(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        lm.write_config('https://api.upstream.example/v1', 'sk', 'dsv4')
        m = lm.LitellmManager()
        monkeypatch.setattr(m, 'is_alive', lambda timeout=2.0: False)
        spawned = []
        monkeypatch.setattr(m, '_spawn', lambda config_path: spawned.append(config_path) or True)
        monkeypatch.setattr(m, '_wait_alive', lambda timeout: True)
        assert m.ensure_running() is True
        assert spawned == [lm.get_litellm_config_path()]

    def test_spawn_without_cli_reports_failure(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        lm.write_config('https://api.upstream.example/v1', 'sk', 'dsv4')
        m = lm.LitellmManager()
        monkeypatch.setattr(m, 'is_alive', lambda timeout=2.0: False)
        monkeypatch.setattr(m, '_litellm_cli', lambda: None)
        assert m.ensure_running() is False


class TestSyncConfig:
    def test_skips_when_upstream_url_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        m = lm.LitellmManager()
        monkeypatch.setattr(m, 'ensure_running', lambda: (_ for _ in ()).throw(AssertionError('must not run')))
        assert m.sync_config('', 'sk', 'dsv4') is False

    def test_writes_config_and_restarts(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        m = lm.LitellmManager()
        started = []
        monkeypatch.setattr(m, 'ensure_running', lambda: started.append(1) or True)
        assert m.sync_config('https://api.upstream.example/v1', 'sk', 'dsv4') is True
        assert os.path.exists(lm.get_litellm_config_path())
        assert started == [1]

    def test_stops_managed_process_before_restart(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        m = lm.LitellmManager()
        stopped = []
        monkeypatch.setattr(m, '_stop', lambda: stopped.append(1))
        monkeypatch.setattr(m, 'ensure_running', lambda: True)
        m._proc = SimpleNamespace(poll=lambda: None)
        assert m.sync_config('https://api.upstream.example/v1', 'sk', 'dsv4') is True
        assert stopped == [1]


class TestShutdown:
    def test_terminates_child_oproc(self, monkeypatch):
        proc = SimpleNamespace(poll=lambda: None, terminate=lambda: None, wait=lambda t=0: None)
        m = lm.LitellmManager()
        m._proc = proc
        monkeypatch.setattr(proc, 'wait', lambda timeout=10: 0)
        m.shutdown()
        assert m._proc is None