"""Unit tests for core/startup_flags.py (hardware probe + env pinning).

Covers the Iluvatar GPU detection (ixsmi single-path CLI probe, mirroring
core/iluvatar_provisioner), the USE_ILUVATAR_PROVISIONER pinning, the
USE_OPENAI_SDK=1 default with explicit-0 escape hatch, and the setting.json
persistence artifact.
"""

import json
import os
import subprocess
from types import SimpleNamespace

import core.startup_flags as sf


def _gpu_cli_result(returncode=0, stdout='0\n'):
    return SimpleNamespace(returncode=returncode, stdout=stdout)


class TestDetectIluvatarDevice:
    def test_none_when_no_cli_on_path(self, monkeypatch):
        monkeypatch.setattr(sf.shutil, 'which', lambda name: None)
        assert sf.detect_iluvatar_device() is None

    def test_detects_ixsmi_with_single_cli_path(self, monkeypatch):
        monkeypatch.setattr(
            sf.shutil, 'which', lambda name: '/usr/bin/' + name if name == 'ixsmi' else None
        )
        calls = []

        def fake_run(args, *a, **k):
            calls.append(args)
            return _gpu_cli_result()

        monkeypatch.setattr(sf.subprocess, 'run', fake_run)
        assert sf.detect_iluvatar_device() == 'ixsmi'
        assert calls == [['ixsmi', *sf._GPU_QUERY_ARGS]]

    def test_skips_cli_with_nonzero_exit(self, monkeypatch):
        monkeypatch.setattr(sf.shutil, 'which', lambda name: '/usr/bin/' + name)
        monkeypatch.setattr(
            sf.subprocess, 'run', lambda *a, **k: _gpu_cli_result(returncode=1)
        )
        assert sf.detect_iluvatar_device() is None

    def test_skips_cli_with_empty_output(self, monkeypatch):
        monkeypatch.setattr(sf.shutil, 'which', lambda name: '/usr/bin/' + name)
        monkeypatch.setattr(
            sf.subprocess, 'run', lambda *a, **k: _gpu_cli_result(stdout='')
        )
        assert sf.detect_iluvatar_device() is None

    def test_none_when_probe_times_out(self, monkeypatch):
        monkeypatch.setattr(sf.shutil, 'which', lambda name: '/usr/bin/' + name)

        def boom(*a, **k):
            raise subprocess.TimeoutExpired(cmd=['ixuca-smi'], timeout=5)

        monkeypatch.setattr(sf.subprocess, 'run', boom)
        assert sf.detect_iluvatar_device() is None


class TestApplyStartupFlags:
    def test_pins_provisioner_true_and_persists(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.delenv('USE_OPENAI_SDK', raising=False)
        monkeypatch.setattr(sf, 'detect_iluvatar_device', lambda: 'ixsmi')

        payload = sf.apply_startup_flags()

        assert payload['detector'] == 'ixsmi'
        assert payload['use_iluvatar_provisioner'] is True
        assert os.environ['USE_ILUVATAR_PROVISIONER'] == 'true'
        assert os.environ['USE_OPENAI_SDK'] == '1'

        setting_path = os.path.join(
            str(tmp_path), '.Iluvatar-AI-Notebook', sf.SETTING_FILE_NAME
        )
        saved = json.load(open(setting_path, encoding='utf-8'))
        assert saved['detector'] == 'ixsmi'
        assert saved['use_iluvatar_provisioner'] is True
        assert saved['use_openai_sdk'] == '1'
        assert os.stat(setting_path).st_mode & 0o777 == 0o600

    def test_pins_provisioner_false_without_device(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.setattr(sf, 'detect_iluvatar_device', lambda: None)

        payload = sf.apply_startup_flags()

        assert payload['detector'] is None
        assert payload['use_iluvatar_provisioner'] is False
        assert os.environ['USE_ILUVATAR_PROVISIONER'] == 'false'

    def test_explicit_use_openai_sdk_zero_is_preserved(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.setenv('USE_OPENAI_SDK', '0')
        monkeypatch.setattr(sf, 'detect_iluvatar_device', lambda: None)

        payload = sf.apply_startup_flags()

        assert os.environ['USE_OPENAI_SDK'] == '0'
        assert payload['use_openai_sdk'] == '0'
