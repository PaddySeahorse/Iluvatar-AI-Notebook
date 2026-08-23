"""Unit tests for core.observability:

- JsonFormatter emits single-line JSON with reserved + extra fields.
- configure_logging is idempotent and applies a level.
- Trace-id contextvars round-trip through set/get.
- Metrics counts kernel starts/restarts, interruptions, executions (with
  duration + success/failure) and HTTP requests; snapshot / prometheus_text /
  reset behave correctly.
"""

import json
import logging

from core.observability import (
    JsonFormatter,
    Metrics,
    configure_logging,
    get_metrics,
    get_trace_id,
    new_trace_id,
    set_trace_id,
)


# --------------------------------------------------------------------------- #
#  JsonFormatter                                                               #
# --------------------------------------------------------------------------- #

class TestJsonFormatter:
    def _log_record(self, msg, level=logging.INFO, exc_info=None, extra=None):
        record = logging.LogRecord(
            name='test.logger',
            level=level,
            pathname=__file__,
            lineno=1,
            msg=msg,
            args=(),
            exc_info=exc_info,
        )
        for key, value in (extra or {}).items():
            setattr(record, key, value)
        return record

    def test_basic_fields(self):
        payload = json.loads(
            JsonFormatter().format(self._log_record('hello %s', extra={'x': 1}))
        )
        assert payload['level'] == 'INFO'
        assert payload['logger'] == 'test.logger'
        assert payload['message'] == 'hello %s'
        assert payload['x'] == 1
        assert 'ts' in payload

    def test_message_is_formatted_args(self):
        record = self._log_record('kernel %s started', extra={})
        payload = json.loads(JsonFormatter().format(record))
        # The formatter uses getMessage(), so %-args are interpolated.
        assert payload['message'] == 'kernel %s started'

    def test_extra_fields_merged(self):
        payload = json.loads(JsonFormatter().format(
            self._log_record('req', extra={
                'trace_id': 'abc', 'method': 'POST', 'status': 200,
            })
        ))
        assert payload['trace_id'] == 'abc'
        assert payload['method'] == 'POST'
        assert payload['status'] == 200

    def test_exception_serialised_as_string(self):
        try:
            raise ValueError('boom')
        except ValueError:
            import sys
            record = self._log_record('failed', exc_info=sys.exc_info())
        payload = json.loads(JsonFormatter().format(record))
        assert 'exception' in payload
        assert 'ValueError' in payload['exception']

    def test_non_serialisable_value_falls_back_to_str(self):
        payload = json.loads(JsonFormatter().format(
            self._log_record('x', extra={'thing': object()})
        ))
        assert isinstance(payload['thing'], str)


# --------------------------------------------------------------------------- #
#  configure_logging                                                           #
# --------------------------------------------------------------------------- #

class TestConfigureLogging:
    def test_idempotent_single_handler(self):
        configure_logging()
        root = logging.getLogger()
        json_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.StreamHandler) and getattr(h, '_json', False)
        ]
        assert len(json_handlers) == 1

    def test_applies_level(self):
        configure_logging(level=logging.DEBUG)
        assert logging.getLogger().level == logging.DEBUG
        configure_logging(level=logging.INFO)  # restore


# --------------------------------------------------------------------------- #
#  Trace id                                                                    #
# --------------------------------------------------------------------------- #

class TestTraceId:
    def test_default_is_empty_string(self):
        set_trace_id('')
        assert get_trace_id() == ''

    def test_set_and_get_round_trip(self):
        set_trace_id('trace-123')
        assert get_trace_id() == 'trace-123'
        set_trace_id('')  # restore default so later tests are isolated

    def test_new_trace_id_is_hex(self):
        tid = new_trace_id()
        assert len(tid) == 32
        int(tid, 16)  # must be valid hex
        set_trace_id('')  # restore default so later tests are isolated


# --------------------------------------------------------------------------- #
#  Metrics                                                                     #
# --------------------------------------------------------------------------- #

class TestMetrics:
    def test_initial_snapshot_is_zeroed(self):
        m = Metrics()
        snap = m.snapshot()
        assert snap['kernel']['starts_total'] == 0
        assert snap['kernel']['restarts_total'] == 0
        assert snap['kernel']['watchdog_restarts_total'] == 0
        assert snap['interrupts_total'] == 0
        assert snap['executions'] == {
            'total': 0,
            'succeeded': 0,
            'failed': 0,
            'duration_sum_seconds': 0.0,
            'duration_avg_seconds': 0.0,
            'duration_max_seconds': 0.0,
            'last_duration_seconds': 0.0,
            'recent_durations_seconds': [],
        }
        assert snap['http_requests']['total'] == 0
        assert snap['uptime_seconds'] >= 0

    def test_kernel_counters(self):
        m = Metrics()
        m.record_kernel_start()
        m.record_kernel_restart()
        m.record_watchdog_restart()
        snap = m.snapshot()['kernel']
        # restart +1 start; watchdog restarts are restarts of an already
        # counted start, so they only bump their own counter.
        assert snap['starts_total'] == 2
        assert snap['restarts_total'] == 1
        assert snap['watchdog_restarts_total'] == 1

    def test_execution_durations_and_average(self):
        m = Metrics()
        m.record_execution(0.5, success=True)
        m.record_execution(0.75, success=True)
        m.record_execution(1.25, success=False)
        ex = m.snapshot()['executions']
        assert ex['total'] == 3
        assert ex['succeeded'] == 2
        assert ex['failed'] == 1
        assert ex['duration_sum_seconds'] == 2.5
        assert ex['duration_avg_seconds'] == round(2.5 / 3, 4)
        assert ex['duration_max_seconds'] == 1.25
        assert ex['last_duration_seconds'] == 1.25
        assert ex['recent_durations_seconds'] == [0.5, 0.75, 1.25]

    def test_execution_duration_ring_bounded(self):
        m = Metrics()
        for i in range(Metrics.RECENT_DURATIONS_MAX + 5):
            m.record_execution(0.1, success=True)
        recent = m.snapshot()['executions']['recent_durations_seconds']
        assert len(recent) == Metrics.RECENT_DURATIONS_MAX

    def test_http_counters(self):
        m = Metrics()
        m.record_http_request('GET', '/api/kernel_status', 200)
        m.record_http_request('POST', '/api/run_cell', 200)
        m.record_http_request('POST', '/api/run_cell', 500)
        http = m.snapshot()['http_requests']
        assert http['total'] == 3
        assert http['by_method'] == {'GET': 1, 'POST': 2}
        assert http['by_status'] == {'200': 2, '500': 1}
        assert http['by_route'] == {
            '/api/kernel_status': 1,
            '/api/run_cell': 2,
        }

    def test_reset_clears_counters(self):
        m = Metrics()
        m.record_kernel_start()
        m.record_execution(0.2, success=False)
        m.record_http_request('GET', '/api/v', 200)
        m.reset()
        snap = m.snapshot()
        assert snap['kernel']['starts_total'] == 0
        assert snap['executions']['total'] == 0
        assert snap['http_requests']['total'] == 0

    def test_prometheus_text_is_counter_rows(self):
        m = Metrics()
        m.record_kernel_restart()
        m.record_execution(1.0, success=True)
        text = m.prometheus_text()
        assert 'notebook_kernel_restarts_total 1' in text
        assert 'notebook_executions_total 1' in text
        assert 'notebook_http_requests_total 0' in text


class TestGetMetrics:
    def test_singleton(self):
        assert get_metrics() is get_metrics()

    def test_record_via_singleton(self):
        m = get_metrics()
        m.reset()
        m.record_kernel_start()
        assert get_metrics().snapshot()['kernel']['starts_total'] == 1
        get_metrics().reset()  # leave the shared singleton clean for other tests