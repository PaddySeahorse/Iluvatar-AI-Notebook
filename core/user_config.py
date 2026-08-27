"""Host-side persistent model config (``~/.Iluvatar-AI-Notebook/config.yaml``).

The notebook stores its LLM API configuration in the user's home directory on
the host machine instead of a project-local file, so settings survive
workspace rebuilds and can be inspected outside the project.

Two entry points:

- :func:`save_model_config` — persist values coming from ``POST
  /api/save_config``; raises ``OSError`` so the route can report the failure.
- :func:`apply_saved_config` — startup hook: seeds ``config.yaml`` from the
  environment on first run and restores previously saved values afterwards.

The config file is written with mode ``0600`` because it holds an API token.
"""

import logging
import os
import time

import yaml

logger = logging.getLogger(__name__)

CONFIG_DIR_NAME = '.Iluvatar-AI-Notebook'
CONFIG_FILE_NAME = 'config.yaml'

# Model-related settings tracked in the snapshot (save_config updates the
# OPENI_API_* triple; the toggles are preserved across saves).
PERSISTED_KEYS = (
    'OPENI_API_URL',
    'OPENI_API_TOKEN',
    'OPENI_API_MODEL',
    'USE_ILUVATAR_PROVISIONER',
    'USE_OPENAI_SDK',
)


def get_config_dir():
    """Return the host-side config directory ``~/.Iluvatar-AI-Notebook``."""
    return os.path.join(os.path.expanduser('~'), CONFIG_DIR_NAME)


def get_config_path():
    """Return the path of the persisted config file."""
    return os.path.join(get_config_dir(), CONFIG_FILE_NAME)


def _read_payload():
    """Return the raw parsed payload dict, or ``{}`` when absent/corrupt."""
    try:
        with open(get_config_path(), 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            return data
    except (OSError, yaml.YAMLError):
        pass
    return {}


def load_saved_config():
    """Return the previously saved config mapping, or ``{}``.

    Corrupt or unreadable files are treated as absent.
    """
    config = _read_payload().get('config')
    return config if isinstance(config, dict) else {}


def save_model_config(url, token, model):
    """Persist the LLM API configuration as native YAML; return the path.

    Keys other than the saved triple (e.g. runtime toggles) are preserved.
    Raises ``OSError`` on filesystem failure.
    """
    saved = load_saved_config()
    saved.update({
        'OPENI_API_URL': url,
        'OPENI_API_TOKEN': token,
        'OPENI_API_MODEL': model,
    })

    os.makedirs(get_config_dir(), exist_ok=True)
    path = get_config_path()
    payload = {
        'saved_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'config': {key: saved.get(key, '') for key in PERSISTED_KEYS},
    }
    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(payload, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    os.chmod(path, 0o600)
    logger.info('user_config_saved', extra={'path': path})
    return path


def apply_saved_config():
    """Startup hook: seed or restore ``config.yaml``, filling ``os.environ``.

    On first run the effective environment values are written to a fresh
    ``config.yaml``. Afterwards the saved values are restored into
    ``os.environ`` with setdefault semantics, so real environment variables
    still take precedence. Returns the config path, or ``None`` when seeding
    failed (best-effort; failures are logged and swallowed).
    """
    try:
        os.makedirs(get_config_dir(), exist_ok=True)
        if not os.path.exists(get_config_path()):
            save_model_config(
                os.environ.get('OPENI_API_URL', ''),
                os.environ.get('OPENI_API_TOKEN', ''),
                os.environ.get('OPENI_API_MODEL', ''),
            )
        for key, value in load_saved_config().items():
            if value:
                os.environ.setdefault(key, str(value))
        logger.info('user_config_applied', extra={'path': get_config_path()})
        return get_config_path()
    except OSError as e:
        logger.warning('user_config_apply_failed', extra={'error': str(e)})
        return None
