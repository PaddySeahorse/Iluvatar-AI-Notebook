"""Unit tests for core/startup_flags.py (hardware probe + env pinning).

Covers the Iluvatar GPU detection (ixuca-smi / ixsmi CLI priority, mirroring
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

    def test_prefers_ixuca_smi(self, monkeypatch):
        monkeypatch.setattr(sf.shutil, 'which', lambda name: '/usr/bin/' + name)
        monkeypatch.setattr(
            sf.subprocess, 'run', lambda *a, **k: _gpu_cli_result()
        )
        assert sf.detect_iluvatar_device() == 'ixuca-smi'

    def test_falls_back_to_ixsmi(self, monkeypatch):
        monkeypatch.setattr(
            sf.shutil, 'which', lambda name: '/usr/bin/' + name if name == 'ixsmi' else None
        )
        monkeypatch.setattr(
            sf.subprocess, 'run', lambda *a, **k: _gpu_cli_result()
        )
        assert sf.detect_iluvatar_device() == 'ixsmi'

    def test_skips_cli_with_nonzero_exit(self, monkeypatch):
        monkeypatch.setattr(sf.shutil, 'which', lambda name: '/usr/bin/' + name)
        results = [_gpu_cli_result(returncode=1), _gpu_cli_result()]
        monkeypatch.setattr(sf.subprocess, 'run', lambda *a, **k: results.pop(0))
        assert sf.detect_iluvatar_device() == 'ixsmi'

    def test_skips_cli_with_empty_output(self, monkeypatch):
        monkeypatch.setattr(sf.shutil, 'which', lambda name: '/usr/bin/' + name)
        results = [_gpu_cli_result(stdout=''), _gpu_cli_result()]
        monkeypatch.setattr(sf.subprocess, 'run', lambda *a, **k: results.pop(0))
        assert sf.detect_iluvatar_device() == 'ixsmi'

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
        monkeypatch.setattr(sf, 'detect_iluvatar_device', lambda: 'ixuca-smi')

        payload = sf.apply_startup_flags()

        assert payload['detector'] == 'ixuca-smi'
        assert payload['use_iluvatar_provisioner'] is True
        assert os.environ['USE_ILUVATAR_PROVISIONER'] == 'true'
        assert os.environ['USE_OPENAI_SDK'] == '1'

        setting_path = os.path.join(
            str(tmp_path), '.Iluvatar-AI-Notebook', sf.SETTING_FILE_NAME
        )
        saved = json.load(open(setting_path, encoding='utf-8'))
        assert saved['detector'] == 'ixuca-smi'
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
