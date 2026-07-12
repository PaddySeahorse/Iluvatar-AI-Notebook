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
                 alive=True, variables=None,
                 complete_result=None, inspect_result=None):
        self._execute_raises = execute_raises
        self._interrupt_result = interrupt_result
        self._alive = alive
        self._variables = variables or []
        self._complete_result = complete_result
        self._inspect_result = inspect_result
        self.last_code = None
        # Captured call args so tests can assert the route forwarded them.
        self.last_complete_args = None
        self.last_inspect_args = None

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

    def complete(self, code, cursor_pos):
        self.last_complete_args = (code, cursor_pos)
        if self._complete_result is not None:
            return self._complete_result
        return {
            'matches': [],
            'cursor_start': cursor_pos,
            'cursor_end': cursor_pos,
            'metadata': {},
        }

    def inspect(self, code, cursor_pos, detail_level=0):
        self.last_inspect_args = (code, cursor_pos, detail_level)
        if self._inspect_result is not None:
            return self._inspect_result
        return {'found': False, 'data': {}, 'metadata': {}}


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


# --------------------------------------------------------------------------- #
#  /api/complete (P3)                                                          #
# --------------------------------------------------------------------------- #

class TestCompleteRoute:
    """/api/complete forwards args to KernelManager.complete and returns JSON."""

    def test_returns_matches_from_kernel(self, client):
        c, fake = client
        fake._complete_result = {
            'matches': ['DataFrame', 'DataFrameGroupBy'],
            'cursor_start': 3,
            'cursor_end': 5,
            'metadata': {'_jupyter_types_experimental': []},
        }

        resp = c.post('/api/complete', json={'code': 'pd.Da', 'cursor_pos': 5})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['matches'] == ['DataFrame', 'DataFrameGroupBy']
        assert data['cursor_start'] == 3
        assert data['cursor_end'] == 5
        # Route forwards code + cursor_pos verbatim.
        assert fake.last_complete_args == ('pd.Da', 5)

    def test_defaults_cursor_pos_to_code_length(self, client):
        c, fake = client

        c.post('/api/complete', json={'code': 'pd.'})

        assert fake.last_complete_args == ('pd.', 3)

    def test_empty_matches_returned_as_empty_list(self, client):
        c, fake = client
        fake._complete_result = {
            'matches': [], 'cursor_start': 0, 'cursor_end': 3, 'metadata': {},
        }

        resp = c.post('/api/complete', json={'code': 'xyz', 'cursor_pos': 3})

        assert resp.status_code == 200
        assert resp.get_json()['matches'] == []

    def test_rejects_negative_cursor_pos_by_clamping_to_length(self, client):
        c, fake = client

        c.post('/api/complete', json={'code': 'pd.', 'cursor_pos': -1})

        # Route clamps negative cursor_pos to len(code) (here 3).
        assert fake.last_complete_args == ('pd.', 3)

    def test_rejects_non_int_cursor_pos_by_clamping_to_length(self, client):
        c, fake = client

        c.post('/api/complete', json={'code': 'pd.', 'cursor_pos': 'not an int'})

        assert fake.last_complete_args == ('pd.', 3)

    def test_missing_body_defaults_to_empty_code(self, client):
        c, fake = client

        resp = c.post('/api/complete', json={})

        assert resp.status_code == 200
        assert resp.get_json()['matches'] == []
        assert fake.last_complete_args == ('', 0)


# --------------------------------------------------------------------------- #
#  /api/inspect (P3)                                                           #
# --------------------------------------------------------------------------- #

class TestInspectRoute:
    """/api/inspect forwards args and returns found/data/metadata."""

    def test_returns_found_payload_from_kernel(self, client):
        c, fake = client
        fake._inspect_result = {
            'found': True,
            'data': {
                'text/plain': 'DataFrame([data, index, columns, dtype, copy])',
                'text/html': '<table/>',
            },
            'metadata': {},
        }

        resp = c.post('/api/inspect', json={
            'code': 'pd.DataFrame',
            'cursor_pos': 12,
            'detail_level': 0,
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['found'] is True
        assert 'text/plain' in data['data']
        assert fake.last_inspect_args == ('pd.DataFrame', 12, 0)

    def test_not_found_returns_200_with_found_false(self, client):
        c, fake = client
        fake._inspect_result = {'found': False, 'data': {}, 'metadata': {}}

        resp = c.post('/api/inspect', json={'code': 'x', 'cursor_pos': 1})

        assert resp.status_code == 200
        assert resp.get_json()['found'] is False

    def test_defaults_detail_level_to_zero(self, client):
        c, fake = client

        c.post('/api/inspect', json={'code': 'x', 'cursor_pos': 1})

        assert fake.last_inspect_args == ('x', 1, 0)

    def test_forwards_detail_level_1_for_double_question_mark(self, client):
        c, fake = client

        c.post('/api/inspect', json={
            'code': 'foo', 'cursor_pos': 3, 'detail_level': 1,
        })

        assert fake.last_inspect_args == ('foo', 3, 1)

    def test_invalid_detail_level_clamps_to_zero(self, client):
        c, fake = client

        c.post('/api/inspect', json={
            'code': 'foo', 'cursor_pos': 3, 'detail_level': 5,
        })

        assert fake.last_inspect_args == ('foo', 3, 0)

    def test_defaults_cursor_pos_to_code_length(self, client):
        c, fake = client

        c.post('/api/inspect', json={'code': 'pd.DataFrame'})

        assert fake.last_inspect_args == ('pd.DataFrame', 12, 0)

    def test_rejects_negative_cursor_pos_by_clamping_to_length(self, client):
        c, fake = client

        c.post('/api/inspect', json={'code': 'x', 'cursor_pos': -5})

        assert fake.last_inspect_args == ('x', 1, 0)

    def test_missing_body_defaults_to_empty_code(self, client):
        c, fake = client

        resp = c.post('/api/inspect', json={})

        assert resp.status_code == 200
        assert resp.get_json()['found'] is False
        assert fake.last_inspect_args == ('', 0, 0)
