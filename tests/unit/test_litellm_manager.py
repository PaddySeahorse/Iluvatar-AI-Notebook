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


class TestManualManagement:
    def test_marker_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        assert lm.is_manually_managed() is False
        lm.mark_manually_managed()
        assert lm.is_manually_managed() is True
        assert os.path.exists(lm.get_manual_marker_path())


class TestApplyConfigWithRollback:
    def test_success_writes_content_and_marks_manual(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        lm.write_config('https://old.example/v1', 'sk-old', 'old-model')
        m = lm.LitellmManager()
        starts = []
        monkeypatch.setattr(m, 'ensure_running', lambda: starts.append(1) or True)

        new_content = (
            'model_list:\n'
            '- model_name: new-model\n'
            '  litellm_params:\n'
            '    model: openai/new-model\n'
            '    api_key: sk-new\n'
            '    api_base: https://new.example/v1\n'
        )
        ok, summary = m.apply_config_with_rollback(new_content)

        assert (ok, summary) == (True, '')
        assert open(lm.get_litellm_config_path(), encoding='utf-8').read() == new_content
        assert (os.stat(lm.get_litellm_config_path()).st_mode & 0o777) == 0o600
        assert lm.is_manually_managed() is True
        assert starts == [1]

    def test_failure_restores_previous_content(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        old_path = lm.get_litellm_config_path()
        lm.write_config('https://old.example/v1', 'sk-old', 'old-model')
        original = open(old_path, encoding='utf-8').read()
        m = lm.LitellmManager()
        monkeypatch.setattr(m, 'ensure_running', lambda: False)

        ok, summary = m.apply_config_with_rollback('model_list: []\n')

        assert ok is False
        assert open(old_path, encoding='utf-8').read() == original

    def test_failure_removes_file_when_no_previous_content(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        path = lm.get_litellm_config_path()
        m = lm.LitellmManager()
        monkeypatch.setattr(m, 'ensure_running', lambda: False)

        ok, _summary = m.apply_config_with_rollback('model_list: []\n')

        assert ok is False
        assert not os.path.exists(path)

    def test_failure_summary_captures_new_log_output(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        log_path = lm.get_litellm_log_path()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write('previous boot output\n')
        m = lm.LitellmManager()

        def fail_and_log():
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write('\x1b[31mERROR: bad model config\x1b[0m\n')
            return False

        monkeypatch.setattr(m, 'ensure_running', fail_and_log)
        ok, summary = m.apply_config_with_rollback('model_list: []\n')

        assert ok is False
        assert 'ERROR: bad model config' in summary
        assert 'previous boot output' not in summary


class TestReadFirstRoute:
    def test_reads_generated_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        lm.write_config('https://api.upstream.example/v1', 'sk', 'dsv4')
        assert lm.read_first_route() == ('https://api.upstream.example/v1', 'dsv4')

    def test_reads_first_of_multiple_entries(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        path = lm.get_litellm_config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(
                'model_list:\n'
                "- model_name: first\n"
                '  litellm_params:\n'
                '    model: openai/first\n'
                '    api_base: https://first.example/v1\n'
                "- model_name: second\n"
                '  litellm_params:\n'
                '    model: openai/second\n'
                '    api_base: https://second.example/v1\n'
            )
        assert lm.read_first_route() == ('https://first.example/v1', 'first')

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        assert lm.read_first_route() == ('', '')

    def test_corrupt_yaml_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        path = lm.get_litellm_config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('model_list: [unclosed\n')
        assert lm.read_first_route() == ('', '')

    def test_missing_model_list_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        path = lm.get_litellm_config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('general_settings: {}\n')
        assert lm.read_first_route() == ('', '')