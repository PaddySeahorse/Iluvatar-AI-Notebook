"""Local LiteLLM Proxy lifecycle management.

The notebook self-hosts a LiteLLM Proxy (an OpenAI-compatible gateway) on
``localhost:4000``. The OpenAI SDK / requests transport in :mod:`core.llm`
always talks to this local endpoint; the proxy is what forwards each request
to the real upstream model API.

The model routes the proxy exposes come from the same config the user saves
in the Notebook settings panel (``core.routes.ai_routes.save_config``). On
save we rewrite the proxy's ``model_list`` config file and bounce the proxy so
the new upstream configuration takes effect immediately. On application
startup we make sure the proxy is running; on shutdown we stop the process if
we started it.

The proxy is launched as a child process (``litellm --config ... --port 4000``)
only when the ``litellm`` CLI is available; otherwise ``ensure_running`` logs
the missing binary and leaves the transport to fail with a clear connection
error, so the notebook still boots without the optional dependency.
"""

import logging
import os
import shutil
import subprocess
import time

import requests
import yaml

from core.user_config import get_config_dir

logger = logging.getLogger(__name__)

LITELLM_PORT = int(os.environ.get('LITELLM_PORT', 4000))
LITELLM_HOST = os.environ.get('LITELLM_HOST', '127.0.0.1')
LITELLM_PROXY_URL = os.environ.get(
    'LITELLM_PROXY_URL', f'http://localhost:{LITELLM_PORT}'
)
LITELLM_CONFIG_NAME = 'litellm_config.yaml'
_READY_TIMEOUT = 45
_READY_POLL = 0.5
_STARTUP_LOG_NAME = 'litellm_proxy.log'


def get_litellm_config_path():
    """Return the host-side LiteLLM proxy config path."""
    return os.path.join(get_config_dir(), LITELLM_CONFIG_NAME)


def get_litellm_log_path():
    """Return the host-side LiteLLM proxy stdout/stderr log path."""
    return os.path.join(get_config_dir(), _STARTUP_LOG_NAME)


def build_litellm_config(url, token, model):
    """Return the proxy ``model_list`` YAML mapping for an upstream model.

    ``url`` / ``token`` / ``model`` describe the real upstream OpenAI-compatible
    endpoint; the proxy exposes it under the same ``model`` name so the
    transport can request it from the local proxy.
    """
    return {
        'model_list': [
            {
                'model_name': model,
                'litellm_params': {
                    'model': f'openai/{model}',
                    'api_key': token,
                    'api_base': url,
                },
            }
        ],
        'general_settings': {},
    }


def write_config(url, token, model):
    """Write the proxy config file; return its path.

    Raises ``OSError`` on filesystem failure so callers can report it.
    """
    path = get_litellm_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = build_litellm_config(url, token, model)
    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(payload, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    os.chmod(path, 0o600)
    logger.info('litellm_config_written', extra={'path': path, 'model': model})
    return path


class LitellmManager:
    """Owns the local LiteLLM Proxy child process when launched by this app."""

    def __init__(self):
        self._proc = None

    # ------------------------------------------------------------------
    # health
    # ------------------------------------------------------------------

    def is_alive(self, timeout=2.0) -> bool:
        """Return True when the proxy health endpoint responds."""
        try:
            resp = requests.get(
                f'{LITELLM_PROXY_URL}/health/liveliness', timeout=timeout
            )
            return resp.status_code < 500
        except requests.exceptions.RequestException:
            return False

    def _wait_alive(self, timeout) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_alive():
                return True
            if self._proc is not None and self._proc.poll() is not None:
                return False
            time.sleep(_READY_POLL)
        return self.is_alive()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def _litellm_cli():
        return shutil.which('litellm')

    def _spawn(self, config_path):
        cli = self._litellm_cli()
        if not cli:
            logger.warning(
                'litellm_cli_missing',
                extra={'hint': 'pip install "litellm[proxy]"'},
            )
            return False
        log_path = get_litellm_log_path()
        try:
            with open(log_path, 'a', encoding='utf-8') as logf:
                self._proc = subprocess.Popen(
                    [
                        cli,
                        '--config', config_path,
                        '--port', str(LITELLM_PORT),
                        '--host', LITELLM_HOST,
                    ],
                    stdout=logf,
                    stderr=logf,
                    start_new_session=True,
                )
        except OSError as e:
            logger.warning('litellm_proxy_spawn_failed', extra={'error': str(e)})
            return False
        logger.info(
            'litellm_proxy_spawned',
            extra={'pid': self._proc.pid, 'port': LITELLM_PORT},
        )
        return True

    def ensure_running(self):
        """Start the proxy if it is not already responding.

        Returns True when the proxy answers on the health endpoint afterwards
        (either because it was already up or we just started it).
        """
        if self.is_alive():
            return True
        config_path = get_litellm_config_path()
        if not os.path.exists(config_path):
            logger.info('litellm_config_missing_skip_start')
            return False
        if not self._spawn(config_path):
            return False
        if self._wait_alive(_READY_TIMEOUT):
            logger.info('litellm_proxy_ready')
            return True
        logger.warning('litellm_proxy_not_ready')
        return False

    def sync_config(self, url, token, model):
        """Apply a new upstream model config to the live proxy.

        Rewrites the ``model_list`` config file and restarts the proxy so the
        route takes effect immediately. When no upstream ``url`` is supplied
        the config is left untouched (nothing to route yet). Best-effort:
        failures are logged and swallowed so config saving still succeeds.
        """
        if not (url and model):
            logger.info('litellm_config_skipped_empty_upstream')
            return False
        try:
            write_config(url, token, model)
        except OSError as e:
            logger.warning('litellm_config_write_failed', extra={'error': str(e)})
            return False
        if self._proc is not None and self._proc.poll() is None:
            self._stop()
        return self.ensure_running()

    def _stop(self):
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def shutdown(self):
        """Stop the proxy if this manager started it."""
        self._stop()


litellm_manager = LitellmManager()