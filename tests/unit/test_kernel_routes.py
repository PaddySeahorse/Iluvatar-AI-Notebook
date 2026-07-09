"""Unit tests for core/routes/kernel_routes.py error mapping and edge cases.

These complement the real-kernel integration tests by exercising the
backward-compatible error contract (RuntimeError / OSError → 503 KernelError)
and the interrupt failure branches with a fake kernel manager, so no ipykernel
subprocess is required.
"""

import pytest

import app as notebook_app


class _FakeKM:
    """Minimal fake kernel_manager for route-level tests."""

    def __init__(self, *, execute_raises=None, interrupt_result=None,
                 alive=True, variables=None):
        self._execute_raises = execute_raises
        self._interrupt_result = interrupt_result
        self._alive = alive
        self._variables = variables or []
        self.last_code = None

    def execute(self, code):
        self.last_code = code
        if self._execute_raises is not None:
            raise self._execute_raises
        return {
            'success': True,
            'stdout': '',
            'stderr': '',
            'html': '',
            'plots': [],
            'variables': self._variables,
        }

    def interrupt(self):
        if self._interrupt_result is not None:
            return self._interrupt_result
        return True

    def is_kernel_alive(self):
        return self._alive

    def is_watchdog_alive(self):
        return True

    def get_variables(self):
        return list(self._variables)


@pytest.fixture()
def client(monkeypatch):
    """Flask test client wired to a fresh fake kernel manager per test."""
    fake = _FakeKM()
    monkeypatch.setattr(notebook_app, 'kernel_manager', fake)
    # PROPAGATE_EXCEPTIONS must be False so the registered AppError handler
    # produces the structured JSON response instead of re-raising.
    notebook_app.app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
    with notebook_app.app.test_client() as c:
        yield c, fake


class TestRunCellErrorMapping:
    """run_cell maps kernel errors to 503 KernelError responses."""

    def test_runtime_error_maps_to_503(self, client):
        c, fake = client
        fake._execute_raises = RuntimeError('queues not initialised')

        resp = c.post('/api/run_cell', json={'code': 'x = 1'})

        assert resp.status_code == 503
        data = resp.get_json()
        assert data['error'] is True
        assert data['error_code'] == 'KERNEL_NOT_READY'

    def test_oserror_maps_to_503(self, client):
        c, fake = client
        fake._execute_raises = OSError('broken pipe')

        resp = c.post('/api/run_cell', json={'code': 'x = 1'})

        assert resp.status_code == 503
        data = resp.get_json()
        assert data['error_code'] == 'KERNEL_IO_ERROR'

    def test_happy_path_returns_backward_compatible_shape(self, client):
        c, fake = client
        fake._variables = [{'name': 'x', 'type': 'int', 'repr': '1', 'shape': None}]

        resp = c.post('/api/run_cell', json={'code': "print('hi')"})

        assert resp.status_code == 200
        data = resp.get_json()
        # Route contract: success/stdout/stderr/html/elapsed_time/plots
        assert set(data.keys()) >= {
            'success', 'stdout', 'stderr', 'html', 'elapsed_time', 'plots'
        }
        assert fake.last_code == "print('hi')"


class TestInterruptRoute:
    """interrupt_kernel route branches."""

    def test_interrupt_success(self, client):
        c, _ = client
        resp = c.post('/api/interrupt_kernel')

        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_interrupt_failure_when_kernel_alive(self, client):
        c, fake = client
        fake._interrupt_result = False
        fake._alive = True

        resp = c.post('/api/interrupt_kernel')

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is False

    def test_interrupt_failure_when_kernel_not_alive(self, client):
        c, fake = client
        fake._interrupt_result = False
        fake._alive = False

        resp = c.post('/api/interrupt_kernel')

        assert resp.status_code == 200
        assert resp.get_json()['success'] is False


class TestKernelStatusRoute:
    def test_status_shape(self, client):
        c, _ = client
        from core.kernel import KernelManager

        resp = c.get('/api/kernel_status')

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['kernel_alive'] is True
        assert data['watchdog_alive'] is True
        assert data['watchdog_interval_seconds'] == KernelManager.WATCHDOG_INTERVAL


class TestRunCellStreamRoute:
    def test_empty_code_returns_400(self, client):
        c, _ = client
        resp = c.post('/api/run_cell_stream', json={'code': '   '})

        assert resp.status_code == 400


class TestGetVariablesRoute:
    def test_returns_cached_variables(self, client):
        c, fake = client
        fake._variables = [{'name': 'x', 'type': 'int', 'repr': '1', 'shape': None}]

        resp = c.get('/api/get_variables')

        assert resp.status_code == 200
        assert resp.get_json() == [
            {'name': 'x', 'type': 'int', 'repr': '1', 'shape': None}
        ]
