"""Unit tests for core/user_config.py (config directory path helper).

The legacy user-config snapshot (``config.yaml``) has been retired; the
module now only provides the config directory used by the LiteLLM manager.
"""

import os

from core import user_config


class TestGetConfigDir:
    def test_joins_home_with_config_dir_name(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        assert user_config.get_config_dir() == os.path.join(
            str(tmp_path), user_config.CONFIG_DIR_NAME
        )

    def test_config_dir_name_is_stable(self):
        assert user_config.CONFIG_DIR_NAME == '.Iluvatar-AI-Notebook'
