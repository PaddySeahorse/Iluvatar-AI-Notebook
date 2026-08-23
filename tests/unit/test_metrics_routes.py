"""Unit tests for the metrics endpoints and request tracing hooks.

Covers:
- GET /api/metrics returns the JSON snapshot from the shared registry.
- GET /metrics returns Prometheus text exposition.
- Every response carries an X-Request-ID header; a caller-supplied header is
  propagated, otherwise a fresh trace id is generated.
- Requests accumulate http_requests counters in the shared registry.
"""

import pytest

import app as notebook_app

from core.observability import get_metrics


@pytest.fixture()
def client():
    get_metrics().reset()
    notebook_app.app.config.update(TESTING=True)
    with notebook_app.app.test_client() as c:
        yield c
    get_metrics().reset()


class TestMetricsEndpoints:
    def test_metrics_json_shape(self, client):
        get_metrics().record_kernel_restart()
        get_metrics().record_execution(0.12, success=True)

        resp = client.get('/api/metrics')

        assert resp.status_code == 200
        data = resp.get_json()
        assert 'uptime_seconds' in data
        assert data['kernel']['restarts_total'] == 1
        assert data['executions']['total'] == 1
        assert data['executions']['succeeded'] == 1
        assert 'http_requests' in data

    def test_metrics_prometheus_text(self, client):
        resp = client.get('/metrics')

        assert resp.status_code == 200
        assert resp.mimetype.startswith('text/plain')
        body = resp.get_data(as_text=True)
        assert '# TYPE notebook_kernel_restarts_total counter' in body
        assert 'notebook_kernel_starts_total' in body


class TestRequestTracing:
    def test_response_has_trace_header(self, client):
        resp = client.get('/api/kernel_status')
        assert resp.headers.get('X-Request-ID')

    def test_trace_header_is_propagated_from_request(self, client):
        resp = client.get('/api/kernel_status', headers={'X-Request-ID': 'trace-caller'})
        assert resp.headers['X-Request-ID'] == 'trace-caller'

    def test_trace_ids_are_unique_across_requests(self, client):
        first = client.get('/api/kernel_status').headers['X-Request-ID']
        second = client.get('/api/kernel_status').headers['X-Request-ID']
        assert first != second

    def test_http_requests_counter_increments(self, client):
        before = get_metrics().snapshot()['http_requests']['total']

        client.get('/api/kernel_status')
        client.post('/api/interrupt_kernel')

        after = get_metrics().snapshot()['http_requests']
        assert after['total'] == before + 2
        assert after['by_route']['/api/kernel_status'] >= 1