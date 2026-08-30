"""Host-side config directory (``~/.Iluvatar-AI-Notebook``).

The legacy user-config snapshot (``config.yaml``) has been retired: the
LiteLLM proxy config (``litellm_config.yaml``) is the single source of truth
for LLM settings. This module now only provides the config directory path
shared by :mod:`core.litellm_manager`.
"""

import os

CONFIG_DIR_NAME = '.Iluvatar-AI-Notebook'


def get_config_dir():
    """Return the host-side config directory ``~/.Iluvatar-AI-Notebook``."""
    return os.path.join(os.path.expanduser('~'), CONFIG_DIR_NAME)
