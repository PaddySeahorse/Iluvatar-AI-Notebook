"""Kernel management based on jupyter_client + ipykernel (P0 migration).

This module provides the :class:`KernelManager` — a thread-safe supervisor that
wraps ``jupyter_client``'s KernelManager/KernelClient to manage an ipykernel
subprocess. It replaces the legacy ``multiprocessing.Queue`` + ``exec()``
approach with ZMQ five-channel protocol (shell/iopub/control/stdin/hb).

Backward-compatible interface:
    - execute(code) -> dict  (same response format as legacy)
    - interrupt() -> bool
    - is_kernel_alive() / is_watchdog_alive() -> bool
    - get_variables() -> list
    - warm_start() / stop_watchdog()

New interface:
    - execute_stream(code) -> generator  (yields message dicts for SSE)
"""

import os
import json
import queue as _queue
import threading
import logging
from typing import Optional, Generator, Dict, Any, List

from jupyter_client import KernelManager as JupyterKernelManager

logger = logging.getLogger(__name__)


class KernelManager:
    """Kernel manager wrapping jupyter_client.KernelManager.

    Provides backward-compatible interface with the legacy exec()-based
    KernelManager, plus new ``execute_stream()`` for SSE streaming.
    """

    # How often (seconds) the watchdog checks kernel health
    WATCHDOG_INTERVAL = 5

    # Execution timeout (seconds); 0 = unlimited
    EXECUTION_TIMEOUT = 300

    def __init__(self, kernel_name: str = "python3"):
        self._kernel_name = kernel_name
        self._km: Optional[JupyterKernelManager] = None
        self._kc = None  # KernelClient
        self._lock = threading.RLock()
        self._execution_lock = threading.Lock()
        self._warm_started = False
        self._cached_variables: List[Dict] = []
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_stop = threading.Event()
        self._restarting = False

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def _start_kernel(self):
        """Start the ipykernel subprocess. Caller must hold _lock."""
        self._km = JupyterKernelManager(kernel_name=self._kernel_name)
        self._km.start_kernel()
        self._kc = self._km.client()
        self._kc.start_channels()
        self._kc.wait_for_ready(timeout=60)
        logger.info("Kernel started: %s", getattr(self._km, 'kernel_id', 'unknown'))

    def ensure_kernel(self):
        """Ensure the kernel is running; start it if not."""
        with self._lock:
            if self._km is None or not self._km.is_alive():
                self._start_kernel()

    def warm_start(self):
        """Pre-start kernel and watchdog so the first request is warm."""
        self.ensure_kernel()
        self.start_watchdog()

    def shutdown(self):
        """Shutdown the kernel cleanly."""
        with self._lock:
            if self._kc is not None:
                try:
                    self._kc.stop_channels()
                except Exception:
                    pass
            if self._km is not None:
                try:
                    self._km.shutdown_kernel(now=True)
                except Exception:
                    pass
            self._km = None
            self._kc = None

    def restart(self):
        """Restart the kernel."""
        with self._lock:
            self._restarting = True
            try:
                if self._km is not None:
                    self._km.restart_kernel()
                    self._kc = self._km.client()
                    self._kc.start_channels()
                    self._kc.wait_for_ready(timeout=60)
            finally:
                self._restarting = False

    # ------------------------------------------------------------------ #
    #  Watchdog                                                           #
    # ------------------------------------------------------------------ #

    def _watchdog_loop(self):
        """Background thread: restart the kernel if it dies unexpectedly."""
        while not self._watchdog_stop.is_set():
            self._watchdog_stop.wait(timeout=self.WATCHDOG_INTERVAL)
            if self._watchdog_stop.is_set():
                break
            with self._lock:
                if self._restarting:
                    continue
                if self._km is None or not self._km.is_alive():
                    try:
                        self._start_kernel()
                    except Exception:
                        pass  # Will retry next cycle

    def start_watchdog(self):
        """Start the watchdog thread (idempotent)."""
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            return
        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, name="KernelWatchdog", daemon=True
        )
        self._watchdog_thread.start()

    def stop_watchdog(self):
        """Stop the watchdog thread."""
        self._watchdog_stop.set()

    # ------------------------------------------------------------------ #
    #  Status                                                             #
    # ------------------------------------------------------------------ #

    def is_kernel_alive(self):
        """Check if the kernel process is alive."""
        with self._lock:
            return self._km is not None and self._km.is_alive()

    def is_watchdog_alive(self):
        """Check if the watchdog thread is alive."""
        return self._watchdog_thread is not None and self._watchdog_thread.is_alive()

    # ------------------------------------------------------------------ #
    #  Execution — synchronous (backward compatible)                      #
    # ------------------------------------------------------------------ #

    def execute(self, code: str) -> Dict[str, Any]:
        """Synchronously execute code (backward compatible with legacy API).

        Returns:
            {
                'success': bool,
                'stdout': str,
                'stderr': str,
                'html': str,      # joined HTML strings
                'plots': list,    # list of base64 PNG strings
                'variables': list, # cached variable info
            }
        """
        with self._execution_lock:
            self.ensure_kernel()

            result: Dict[str, Any] = {
                'success': True,
                'stdout': '',
                'stderr': '',
                'html': '',
                'plots': [],
                'variables': [],
            }

            if not code.strip():
                result['variables'] = self._cached_variables
                return result

            if self._kc is None:
                result['success'] = False
                result['stderr'] = 'Kernel not started'
                return result

            msg_id = self._kc.execute(code, store_history=True)

            html_parts: List[str] = []
            while True:
                try:
                    msg = self._kc.iopub_channel.get_msg(timeout=self.EXECUTION_TIMEOUT)
                except _queue.Empty:
                    result['success'] = False
                    result['stderr'] += '\n[Timeout: kernel did not respond]'
                    break
                except Exception as e:
                    result['success'] = False
                    result['stderr'] += f'\n[Kernel communication error: {e}]'
                    break

                parent_id = msg.get('parent_header', {}).get('msg_id', '')
                if parent_id != msg_id:
                    continue

                msg_type = msg.get('msg_type', '')
                content = msg.get('content', {})

                if msg_type == 'stream':
                    name = content.get('name', 'stdout')
                    text = content.get('text', '')
                    if name == 'stderr':
                        result['stderr'] += text
                    else:
                        result['stdout'] += text
                elif msg_type == 'display_data':
                    data = content.get('data', {})
                    if 'image/png' in data:
                        result['plots'].append(data['image/png'])
                    if 'text/html' in data:
                        html_parts.append(data['text/html'])
                elif msg_type == 'execute_result':
                    data = content.get('data', {})
                    if 'image/png' in data:
                        png = data['image/png']
                        if png not in result['plots']:
                            result['plots'].append(png)
                    if 'text/html' in data:
                        html_parts.append(data['text/html'])
                    if 'text/plain' in data:
                        text = data['text/plain']
                        if result['stdout'] and not result['stdout'].endswith('\n'):
                            result['stdout'] += '\n'
                        result['stdout'] += text + '\n'
                elif msg_type == 'error':
                    result['success'] = False
                    traceback_list = content.get('traceback', [])
                    result['stderr'] += '\n'.join(traceback_list)
                elif msg_type == 'status':
                    if content.get('execution_state') == 'idle':
                        break

            result['html'] = '\n'.join(html_parts) if html_parts else ''

            # Update cached variables (best effort)
            try:
                self._cached_variables = self._fetch_variables()
                result['variables'] = self._cached_variables
            except Exception:
                result['variables'] = self._cached_variables

            return result

    # ------------------------------------------------------------------ #
    #  Execution — streaming (new, for SSE)                               #
    # ------------------------------------------------------------------ #

    def execute_stream(self, code: str) -> Generator[Dict[str, Any], None, None]:
        """Stream execution — yields message dicts suitable for SSE.

        Yields messages of type:
            {"type": "stream", "name": "stdout"|"stderr", "text": "..."}
            {"type": "display_data", "data": {...}, "metadata": {...}}
            {"type": "execute_result", "data": {...}, "execution_count": N}
            {"type": "error", "ename": "...", "evalue": "...", "traceback": [...]}
            {"type": "status", "execution_state": "busy"|"idle"}
        """
        with self._execution_lock:
            self.ensure_kernel()

            if self._kc is None:
                yield {
                    "type": "error",
                    "ename": "KernelError",
                    "evalue": "Kernel not started",
                    "traceback": [],
                }
                return

            if not code.strip():
                yield {"type": "status", "execution_state": "idle"}
                return

            msg_id = self._kc.execute(code, store_history=True)

            while True:
                try:
                    msg = self._kc.iopub_channel.get_msg(timeout=self.EXECUTION_TIMEOUT)
                except _queue.Empty:
                    yield {
                        "type": "error",
                        "ename": "TimeoutError",
                        "evalue": "Kernel did not respond within timeout",
                        "traceback": [],
                    }
                    return
                except Exception as e:
                    yield {
                        "type": "error",
                        "ename": "KernelError",
                        "evalue": str(e),
                        "traceback": [],
                    }
                    return

                parent_id = msg.get('parent_header', {}).get('msg_id', '')
                if parent_id != msg_id:
                    continue

                msg_type = msg.get('msg_type', '')
                content = msg.get('content', {})

                if msg_type == 'stream':
                    yield {
                        "type": "stream",
                        "name": content.get("name", "stdout"),
                        "text": content.get("text", ""),
                    }
                elif msg_type == 'display_data':
                    yield {
                        "type": "display_data",
                        "data": content.get("data", {}),
                        "metadata": content.get("metadata", {}),
                    }
                elif msg_type == 'execute_result':
                    yield {
                        "type": "execute_result",
                        "data": content.get("data", {}),
                        "execution_count": content.get("execution_count"),
                    }
                elif msg_type == 'error':
                    yield {
                        "type": "error",
                        "ename": content.get("ename", ""),
                        "evalue": content.get("evalue", ""),
                        "traceback": content.get("traceback", []),
                    }
                elif msg_type == 'status':
                    yield {
                        "type": "status",
                        "execution_state": content.get("execution_state", ""),
                    }
                    if content.get("execution_state") == "idle":
                        break

    # ------------------------------------------------------------------ #
    #  Interrupt                                                          #
    # ------------------------------------------------------------------ #

    def interrupt(self) -> bool:
        """Interrupt kernel execution via control channel (SIGINT)."""
        with self._lock:
            if self._km is None:
                return False
            try:
                self._km.interrupt_kernel()
                return True
            except Exception as e:
                logger.error("Failed to interrupt kernel: %s", e)
                return False

    # ------------------------------------------------------------------ #
    #  Variables                                                          #
    # ------------------------------------------------------------------ #

    def get_variables(self) -> List[Dict]:
        """Return cached variables."""
        return list(self._cached_variables)

    def set_variables(self, variables):
        """Set cached variables."""
        self._cached_variables = list(variables) if variables else []

    def _fetch_variables(self) -> List[Dict]:
        """Fetch current namespace variables from kernel via a snippet.

        Executes a Python snippet that collects variable info as JSON,
        keeping all temporaries underscore-prefixed so they don't pollute
        subsequent listings.
        """
        if self._kc is None:
            return []

        snippet = (
            "import json as _json\n"
            "_vars = []\n"
            "for _k, _v in list(globals().items()):\n"
            "    if _k.startswith('_') or _k in ('In', 'Out', 'exit', 'quit',\n"
            "        'open', 'dir', 'print', 'input', 'help', 'get_ipython'):\n"
            "        continue\n"
            "    _t = type(_v).__name__\n"
            "    try:\n"
            "        _r = repr(_v)\n"
            "        if len(_r) > 100: _r = _r[:100] + '...'\n"
            "    except Exception:\n"
            "        _r = '<Unable to display>'\n"
            "    _s = None\n"
            "    try:\n"
            "        if hasattr(_v, 'shape'):\n"
            "            _s = str(list(_v.shape)) if hasattr(_v.shape, '__iter__') else str(_v.shape)\n"
            "    except Exception:\n"
            "        pass\n"
            "    _vars.append({'name': _k, 'type': _t, 'repr': _r, 'shape': _s})\n"
            "_vars.sort(key=lambda x: x['name'])\n"
            "print(_json.dumps(_vars))"
        )

        msg_id = self._kc.execute(snippet, store_history=False)
        output = ''
        while True:
            try:
                msg = self._kc.iopub_channel.get_msg(timeout=10)
            except _queue.Empty:
                break
            except Exception:
                break

            parent_id = msg.get('parent_header', {}).get('msg_id', '')
            if parent_id != msg_id:
                continue

            msg_type = msg.get('msg_type', '')
            content = msg.get('content', {})

            if msg_type == 'stream' and content.get('name') == 'stdout':
                output += content.get('text', '')
            elif msg_type == 'status' and content.get('execution_state') == 'idle':
                break

        if output.strip():
            try:
                return json.loads(output.strip())
            except json.JSONDecodeError:
                return []
        return []
