"""Observability: structured JSON logging, request tracing and metrics.

Three pieces, all stdlib-only (the project intentionally avoids extra deps):

- :func:`configure_logging` installs a :class:`JsonFormatter` on the root
  logger so every ``logging`` record is emitted as a single-line JSON object.
- Trace-ids flow through a :class:`contextvars.ContextVar`; Flask hooks set
  one per request and echo it back via the ``X-Request-ID`` response header.
- :func:`get_metrics` returns the process-wide :class:`Metrics` registry that
  counts kernel restarts, executions (with durations) and HTTP requests.
"""

import json
import logging
import threading
import time
import uuid
from collections import deque
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Deque, Dict, List, Tuple

# LogRecord attributes that belong to the record itself and must never be
# treated as structured ``extra`` fields.
_RESERVED_ATTRS = frozenset((
    'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename',
    'funcName', 'levelname', 'levelno', 'lineno', 'module', 'msecs',
    'message', 'msg', 'name', 'pathname', 'process', 'processName',
    'relativeCreated', 'stack_info', 'thread', 'threadName', 'taskName',
))

_trace_var: ContextVar[str] = ContextVar('request_trace_id', default='')


def get_trace_id() -> str:
    """Return the current request's trace id ('' outside a request)."""
    return _trace_var.get()


def set_trace_id(trace_id: str) -> None:
    """Bind *trace_id* to the current execution context."""
    _trace_var.set(trace_id)


def new_trace_id() -> str:
    """Return a random hex trace id suitable for a new request."""
    return uuid.uuid4().hex


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object.

    Standard fields become ``ts`` / ``level`` / ``logger`` / ``message`` and
    any ``extra={...}`` kwargs passed to the logging call are merged into the
    payload as their own keys.  Values that are not JSON-serialisable fall
    back to :func:`str`.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            'ts': datetime.now().isoformat(timespec='milliseconds'),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and key not in payload:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Install a JSON StreamHandler on the root logger (idempotent).

    Only attaches a handler once; subsequent calls just adjust the level so a
    test-suite (which installs its own handlers) is not disturbed.
    """
    root = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) and getattr(h, '_json', False)
               for h in root.handlers):
        handler = logging.StreamHandler()
        handler._json = True  # type: ignore[attr-defined]
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    root.setLevel(level)


class Metrics:
    """Thread-safe counters and duration summaries for the notebook backend.

    Keeps process-wide totals plus a small ring of the most recent execution
    durations so operators can see both running sums and the recent history.
    """

    RECENT_DURATIONS_MAX = 20

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = time.monotonic()
        self._kernel_starts = 0
        self._kernel_restarts = 0
        self._watchdog_restarts = 0
        self._interrupts = 0
        self._executions = 0
        self._executions_succeeded = 0
        self._executions_failed = 0
        self._execution_duration_sum = 0.0
        self._execution_duration_max = 0.0
        self._last_execution_duration = 0.0
        self._recent_durations: Deque[float] = deque(maxlen=self.RECENT_DURATIONS_MAX)
        self._http_total = 0
        self._http_by_method: Dict[str, int] = {}
        self._http_by_status: Dict[str, int] = {}
        self._http_by_route: Dict[str, int] = {}

    # ------------------------------------------------------------------ #
    #  Recording callbacks                                                #
    # ------------------------------------------------------------------ #

    def record_kernel_start(self) -> None:
        """Count a freshly started kernel subprocess."""
        with self._lock:
            self._kernel_starts += 1

    def record_kernel_restart(self) -> None:
        """Count an explicit (manual) kernel restart."""
        with self._lock:
            self._kernel_restarts += 1
            self._kernel_starts += 1

    def record_watchdog_restart(self) -> None:
        """Count a watchdog-triggered restart after an unexpected death.

        Note: a kernel (re)start from the watchdog path flows through
        ``_start_kernel`` which already increments ``starts_total``, so this
        only bumps the dedicated watchdog counter.
        """
        with self._lock:
            self._watchdog_restarts += 1

    def record_interrupt(self) -> None:
        """Count a successful kernel interrupt."""
        with self._lock:
            self._interrupts += 1

    def record_execution(self, duration_seconds: float, success: bool) -> None:
        """Record one kernel execution and its wall-clock duration."""
        with self._lock:
            self._executions += 1
            if success:
                self._executions_succeeded += 1
            else:
                self._executions_failed += 1
            self._execution_duration_sum += duration_seconds
            self._last_execution_duration = duration_seconds
            if duration_seconds > self._execution_duration_max:
                self._execution_duration_max = duration_seconds
            self._recent_durations.append(duration_seconds)

    def record_http_request(self, method: str, path: str, status: int) -> None:
        """Count an HTTP request for request tracing."""
        with self._lock:
            self._http_total += 1
            self._http_by_method[method] = self._http_by_method.get(method, 0) + 1
            status_key = str(status)
            self._http_by_status[status_key] = self._http_by_status.get(status_key, 0) + 1
            self._http_by_route[path] = self._http_by_route.get(path, 0) + 1

    # ------------------------------------------------------------------ #
    #  Readout                                                            #
    # ------------------------------------------------------------------ #

    def _snapshot_locked(self) -> Dict[str, Any]:
        executions = self._executions
        avg = (self._execution_duration_sum / executions) if executions else 0.0
        return {
            'uptime_seconds': round(time.monotonic() - self._started_at, 3),
            'kernel': {
                'starts_total': self._kernel_starts,
                'restarts_total': self._kernel_restarts,
                'watchdog_restarts_total': self._watchdog_restarts,
            },
            'interrupts_total': self._interrupts,
            'executions': {
                'total': self._executions,
                'succeeded': self._executions_succeeded,
                'failed': self._executions_failed,
                'duration_sum_seconds': round(self._execution_duration_sum, 3),
                'duration_avg_seconds': round(avg, 4),
                'duration_max_seconds': round(self._execution_duration_max, 3),
                'last_duration_seconds': round(self._last_execution_duration, 3),
                'recent_durations_seconds': [
                    round(d, 3) for d in self._recent_durations
                ],
            },
            'http_requests': {
                'total': self._http_total,
                'by_method': dict(self._http_by_method),
                'by_status': dict(self._http_by_status),
                'by_route': dict(self._http_by_route),
            },
        }

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-ready point-in-time snapshot of all metrics."""
        with self._lock:
            return self._snapshot_locked()

    def prometheus_text(self) -> str:
        """Render the metrics as Prometheus text exposition (version 0.0.4)."""
        with self._lock:
            snap = self._snapshot_locked()
        lines: List[str] = [
            '# HELP notebook_uptime_seconds Process uptime since boot.',
            '# TYPE notebook_uptime_seconds gauge',
            f'notebook_uptime_seconds {snap["uptime_seconds"]}',
            '# HELP notebook_kernel_starts_total Total kernel subprocess starts.',
            '# TYPE notebook_kernel_starts_total counter',
            f'notebook_kernel_starts_total {snap["kernel"]["starts_total"]}',
            '# HELP notebook_kernel_restarts_total Explicit kernel restarts.',
            '# TYPE notebook_kernel_restarts_total counter',
            f'notebook_kernel_restarts_total {snap["kernel"]["restarts_total"]}',
            '# HELP notebook_kernel_watchdog_restarts_total Watchdog-triggered restarts.',
            '# TYPE notebook_kernel_watchdog_restarts_total counter',
            f'notebook_kernel_watchdog_restarts_total {snap["kernel"]["watchdog_restarts_total"]}',
            '# HELP notebook_interrupts_total Kernel interrupts sent.',
            '# TYPE notebook_interrupts_total counter',
            f'notebook_interrupts_total {snap["interrupts_total"]}',
            '# HELP notebook_executions_total Kernel executions started.',
            '# TYPE notebook_executions_total counter',
            f'notebook_executions_total {snap["executions"]["total"]}',
            '# HELP notebook_executions_succeeded_total Successful executions.',
            '# TYPE notebook_executions_succeeded_total counter',
            f'notebook_executions_succeeded_total {snap["executions"]["succeeded"]}',
            '# HELP notebook_executions_failed_total Failed executions.',
            '# TYPE notebook_executions_failed_total counter',
            f'notebook_executions_failed_total {snap["executions"]["failed"]}',
            '# HELP notebook_execution_duration_seconds Execution duration summary.',
            '# TYPE notebook_execution_duration_seconds summary',
            f'notebook_execution_duration_seconds_sum {snap["executions"]["duration_sum_seconds"]}',
            f'notebook_execution_duration_seconds_count {snap["executions"]["total"]}',
            '# HELP notebook_execution_duration_max_seconds Longest single execution.',
            '# TYPE notebook_execution_duration_max_seconds gauge',
            f'notebook_execution_duration_max_seconds {snap["executions"]["duration_max_seconds"]}',
            '# HELP notebook_http_requests_total HTTP requests served.',
            '# TYPE notebook_http_requests_total counter',
            f'notebook_http_requests_total {snap["http_requests"]["total"]}',
        ]
        return '\n'.join(lines) + '\n'

    def reset(self) -> None:
        """Reset all counters (used by the test-suite for isolation)."""
        with self._lock:
            self._started_at = time.monotonic()
            self._kernel_starts = 0
            self._kernel_restarts = 0
            self._watchdog_restarts = 0
            self._interrupts = 0
            self._executions = 0
            self._executions_succeeded = 0
            self._executions_failed = 0
            self._execution_duration_sum = 0.0
            self._execution_duration_max = 0.0
            self._last_execution_duration = 0.0
            self._recent_durations = deque(maxlen=self.RECENT_DURATIONS_MAX)
            self._http_total = 0
            self._http_by_method = {}
            self._http_by_status = {}
            self._http_by_route = {}


_metrics_instance: Metrics | None = None
_metrics_lock = threading.Lock()


def get_metrics() -> Metrics:
    """Return the process-wide metrics singleton."""
    global _metrics_instance
    if _metrics_instance is None:
        with _metrics_lock:
            if _metrics_instance is None:
                _metrics_instance = Metrics()
    return _metrics_instance