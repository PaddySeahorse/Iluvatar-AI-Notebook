"""Flask route integration tests against a real ipykernel.

Validates the P1 backward-compatibility contract for the kernel routes
(/api/run_cell, /api/run_cell_stream, /api/kernel_status, /api/get_variables,
/api/interrupt_kernel) by driving the real Flask app with a real kernel
subprocess — no mocking.

Marked ``integration`` so they can be deselected in fast CI lanes:
    pytest -m "not integration"
"""

import json
import threading
import time

import pytest

import app as notebook_app


@pytest.fixture(scope="module")
def client():
    """Real Flask test client with a warm-started kernel, shut down at teardown."""
    notebook_app.app.config.update(TESTING=True)
    notebook_app.kernel_manager.warm_start()
    with notebook_app.app.test_client() as c:
        yield c
    notebook_app.kernel_manager.shutdown()


def _parse_sse_events(body: str):
    """Parse an SSE response body into a list of decoded event payloads.

    Returns the list of JSON dicts for ``data: {...}`` lines, plus the string
    ``[DONE]`` sentinel if present.
    """
    events = []
    for chunk in body.split('\n\n'):
        for line in chunk.splitlines():
            if line.startswith('data: '):
                payload = line[len('data: '):]
                if payload == '[DONE]':
                    events.append('[DONE]')
                else:
                    events.append(json.loads(payload))
    return events


@pytest.mark.integration
class TestKernelRoutesIntegration:
    """End-to-end route behaviour with a real kernel."""

    def test_run_cell_returns_backward_compatible_shape(self, client):
        resp = client.post('/api/run_cell', json={'code': "print('hello')"})

        assert resp.status_code == 200
        data = resp.get_json()
        # Contract from core/routes/kernel_routes.py
        assert set(data.keys()) >= {
            'success', 'stdout', 'stderr', 'html', 'elapsed_time', 'plots'
        }
        assert data['success'] is True
        assert data['stdout'].strip() == 'hello'
        assert data['stderr'] == ''
        assert data['html'] == ''
        assert data['plots'] == []
        assert isinstance(data['elapsed_time'], (int, float))

    def test_run_cell_reports_error(self, client):
        resp = client.post('/api/run_cell', json={'code': '1 / 0'})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is False
        assert 'ZeroDivisionError' in data['stderr']

    def test_run_cell_stream_emits_sse_events(self, client):
        resp = client.post(
            '/api/run_cell_stream',
            json={'code': "for i in range(3):\n    print(i)"},
        )

        assert resp.status_code == 200
        assert resp.content_type.startswith('text/event-stream')

        events = _parse_sse_events(resp.get_data(as_text=True))
        assert events[-1] == '[DONE]'

        statuses = [e for e in events if isinstance(e, dict) and e.get('type') == 'status']
        assert any(e['execution_state'] == 'busy' for e in statuses)
        assert any(e['execution_state'] == 'idle' for e in statuses)

        stream_text = ''.join(
            e['text'] for e in events
            if isinstance(e, dict) and e.get('type') == 'stream'
        )
        for i in range(3):
            assert str(i) in stream_text

    def test_run_cell_stream_empty_code_returns_400(self, client):
        resp = client.post('/api/run_cell_stream', json={'code': '   '})

        assert resp.status_code == 400

    def test_kernel_status_reports_alive(self, client):
        resp = client.get('/api/kernel_status')

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['kernel_alive'] is True
        assert data['watchdog_alive'] is True

    def test_get_variables_after_assignment(self, client):
        client.post('/api/run_cell', json={'code': 'route_var = 99'})

        resp = client.get('/api/get_variables')
        assert resp.status_code == 200
        names = [v['name'] for v in resp.get_json()]
        assert 'route_var' in names

    def test_interrupt_route_stops_long_running_cell(self, client):
        """P1 admission criterion: /api/interrupt_kernel stops a busy kernel."""
        done = threading.Event()
        execute_result = {}

        def run_long():
            # Drive the shared kernel_manager directly so the test client
            # stays free to issue the interrupt request.
            execute_result['r'] = notebook_app.kernel_manager.execute(
                "while True:\n    pass"
            )
            done.set()

        t = threading.Thread(target=run_long, daemon=True)
        t.start()
        time.sleep(1.0)

        resp = client.post('/api/interrupt_kernel')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

        assert done.wait(timeout=10), "long-running cell should return after interrupt"
        assert execute_result['r']['success'] is False
        assert 'KeyboardInterrupt' in execute_result['r']['stderr']

    def test_state_persists_across_requests(self, client):
        client.post('/api/run_cell', json={'code': '_acc = 100'})
        resp = client.post('/api/run_cell', json={'code': '_acc += 1\nprint(_acc)'})

        data = resp.get_json()
        assert data['success'] is True
        assert '101' in data['stdout']
