"""Iluvatar AI Notebook — application entry point (ISSUE-007 refactor).

This file is intentionally lightweight: it loads configuration, instantiates the
shared mutable runtime state (``kernel_manager`` / ``WORKSPACE_DIR`` /
``is_safe_path``), wires up the Flask app with error handlers and Blueprints
defined in the :mod:`core` package, and runs the server.

All route logic now lives under ``core/routes/`` and the kernel / GPU / error /
utility code under ``core/``.  The entry-point module is exposed to Blueprints
via ``app.config['_STATE_MODULE']`` so views read monkeypatchable module-level
state at request time without ``import app`` cycles.
"""

import os
import sys
import time
import logging
import atexit

from flask import Flask, request
from flask_cors import CORS

from core.kernel import KernelManager
from core.routes import register_routes, register_error_handlers
from core.utils import is_safe_path as _is_safe_path_impl
from core.observability import (
    configure_logging,
    get_metrics,
    get_trace_id,
    new_trace_id,
    set_trace_id,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured logging (JSON lines) + log level from LOG_LEVEL env var
# ---------------------------------------------------------------------------
_log_level = getattr(
    logging, os.environ.get('LOG_LEVEL', 'INFO').upper(), logging.INFO
)
configure_logging(level=_log_level)

# ---------------------------------------------------------------------------
# Configuration: model settings live in ~/.Iluvatar-AI-Notebook/config.yaml
# (seeded from the environment on first run, restored on every start)
# ---------------------------------------------------------------------------
from core.user_config import apply_saved_config

apply_saved_config()

DEFAULT_API_URL = os.environ.get('OPENI_API_URL', 'https://token.openi.org.cn/v1/chat/completions')
DEFAULT_API_TOKEN = os.environ.get('OPENI_API_TOKEN', '')
DEFAULT_API_MODEL = os.environ.get('OPENI_API_MODEL', 'dsv4')

# P4: When enabled, the notebook backend uses the Iluvatar GPU kernel
# provisioner (core/iluvatar_provisioner.py) which injects IXUCA SDK
# environment variables and provides GPU-aware interrupt.  Requires the
# ``iluvatar_python`` kernelspec to be installed:
#     jupyter kernelspec install kernels/iluvatar_python --user
USE_ILUVATAR_PROVISIONER = os.environ.get(
    'USE_ILUVATAR_PROVISIONER', 'false'
).lower() == 'true'
KERNEL_NAME = 'iluvatar_python' if USE_ILUVATAR_PROVISIONER else 'python3'

# Force matplotlib to use Agg backend so it doesn't open GUI windows
try:
    import matplotlib
    matplotlib.use('Agg')
except Exception:
    pass

# ---------------------------------------------------------------------------
# Flask application + CORS
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder='static')
CORS(app, resources={r"/api/*": {"origins": os.environ.get('ALLOWED_ORIGINS', '*').split(',')}})

# ---------------------------------------------------------------------------
# Mutable runtime state (monkeypatched by the test-suite)
# ---------------------------------------------------------------------------
kernel_manager = KernelManager(
    kernel_name=KERNEL_NAME,
    use_iluvatar_provisioner=USE_ILUVATAR_PROVISIONER,
)
WORKSPACE_DIR = os.path.realpath('.')


def is_safe_path(path):
    """Workspace-confined path check, resolved against the current WORKSPACE_DIR."""
    return _is_safe_path_impl(WORKSPACE_DIR, path)


# Expose this entry-point module to Blueprints so request-time views can read
# the module-level state above (kernel_manager / WORKSPACE_DIR / is_safe_path)
# without importing ``app`` (which would double-init under `python app.py`).
app.config['_STATE_MODULE'] = sys.modules[__name__]

# ---------------------------------------------------------------------------
# Request tracing: generate/ propagate a trace id, log it and expose it via
# the X-Request-ID response header so failures can be correlated across logs.
# ---------------------------------------------------------------------------
@app.before_request
def _begin_request_trace():
    trace_id = request.headers.get('X-Request-ID') or new_trace_id()
    set_trace_id(trace_id)
    request.environ['_request_started'] = time.monotonic()


@app.after_request
def _finish_request_trace(response):
    trace_id = get_trace_id()
    response.headers['X-Request-ID'] = trace_id or ''
    duration_ms = int(
        (time.monotonic() - request.environ.get('_request_started', time.monotonic()))
        * 1000
    )
    logger.info(
        'http_request',
        extra={
            'trace_id': trace_id,
            'method': request.method,
            'path': request.path,
            'status': response.status_code,
            'duration_ms': duration_ms,
            'remote_addr': request.remote_addr or '',
        },
    )
    get_metrics().record_http_request(request.method, request.path, response.status_code)
    return response


# ---------------------------------------------------------------------------
# Wire up error handlers and routes
# ---------------------------------------------------------------------------
register_error_handlers(app)
register_routes(app)


if __name__ == '__main__':
    # Ensure static folder exists
    os.makedirs(app.static_folder, exist_ok=True)

    # Pre-start kernel and watchdog so the first request is warm (ISSUE-010)
    kernel_manager.warm_start()

    # Register pynvml cleanup on exit
    def cleanup_gpu():
        try:
            import pynvml
            if hasattr(pynvml, '_nvml_inited'):
                pynvml.nvmlShutdown()
        except Exception:
            pass
    atexit.register(cleanup_gpu)

    # Stop watchdog cleanly on exit
    atexit.register(kernel_manager.stop_watchdog)

    port = int(os.environ.get('OPENI_SELF_PORT', 5000))
    app.run(host='0.0.0.0', port=port)
