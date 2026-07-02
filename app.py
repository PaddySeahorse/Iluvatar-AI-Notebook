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
import atexit

from flask import Flask
from flask_cors import CORS

from core.kernel import KernelManager
from core.routes import register_routes, register_error_handlers
from core.utils import is_safe_path as _is_safe_path_impl

# ---------------------------------------------------------------------------
# Configuration (.env loaded manually to avoid hardcoding API secrets)
# ---------------------------------------------------------------------------
if os.path.exists('.env'):
    with open('.env') as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip().strip("'").strip('"')

DEFAULT_API_URL = os.environ.get('OPENI_API_URL', 'https://token.openi.org.cn/v1/chat/completions')
DEFAULT_API_TOKEN = os.environ.get('OPENI_API_TOKEN', '')
DEFAULT_API_MODEL = os.environ.get('OPENI_API_MODEL', 'dsv4')

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
kernel_manager = KernelManager()
WORKSPACE_DIR = os.path.realpath('.')


def is_safe_path(path):
    """Workspace-confined path check, resolved against the current WORKSPACE_DIR."""
    return _is_safe_path_impl(WORKSPACE_DIR, path)


# Expose this entry-point module to Blueprints so request-time views can read
# the module-level state above (kernel_manager / WORKSPACE_DIR / is_safe_path)
# without importing ``app`` (which would double-init under `python app.py`).
app.config['_STATE_MODULE'] = sys.modules[__name__]

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
