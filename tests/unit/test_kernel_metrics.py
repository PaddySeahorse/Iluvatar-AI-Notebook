"""Tests that KernelManager records execution / restart / interrupt metrics.

These assert the observability wiring (core.kernel -> get_metrics) without
spawning a real kernel, using the same mock-client technique as
test_kernel_manager.py.
"""

from core.kernel import KernelManager
from core.observability import get_metrics


def _msg(msg_id, msg_type, **content):
    """Build an IOPub-style message dict with a matching parent_header."""
    return {
        'parent_header': {'msg_id': msg_id},
        'msg_type': msg_type,
        'content': content,
    }


def _make_km_with_mock_client(mocker):
    """Return a KernelManager wired to a mock kernel + client (as above)."""
    km = KernelManager()
    km._km = mocker.MagicMock()
    km._km.is_alive.return_value = True
    km._kc = mocker.MagicMock()
    km._kc.execute.return_value = 'test-msg-id'
    mocker.patch.object(km, '_fetch_variables', return_value=[])
    return km


class TestKernelMetrics:
    def test_execute_records_successful_execution(self, mocker):
        get_metrics().reset()
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('test-msg-id', 'stream', name='stdout', text='hi\n'),
            _msg('test-msg-id', 'status', execution_state='idle'),
        ]

        km.execute("print('hi')")

        snap = get_metrics().snapshot()['executions']
        assert snap['total'] == 1
        assert snap['succeeded'] == 1
        assert snap['failed'] == 0
        assert snap['last_duration_seconds'] >= 0

    def test_execute_records_failed_execution(self, mocker):
        get_metrics().reset()
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('test-msg-id', 'error', ename='NameError',
                 evalue='x', traceback=['NameError: x']),
            _msg('test-msg-id', 'status', execution_state='idle'),
        ]

        km.execute('print(x)')

        snap = get_metrics().snapshot()['executions']
        assert snap['total'] == 1
        assert snap['failed'] == 1
        assert snap['succeeded'] == 0

    def test_execute_stream_records_execution(self, mocker):
        get_metrics().reset()
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('test-msg-id', 'status', execution_state='busy'),
            _msg('test-msg-id', 'status', execution_state='idle'),
        ]

        list(km.execute_stream('2+2'))

        snap = get_metrics().snapshot()['executions']
        assert snap['total'] == 1
        assert snap['succeeded'] == 1

    def test_execute_stream_records_failure_on_kernel_error(self, mocker):
        get_metrics().reset()
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('test-msg-id', 'error', ename='ZeroDivisionError',
                 evalue='division by zero', traceback=['tb']),
            _msg('test-msg-id', 'status', execution_state='idle'),
        ]

        list(km.execute_stream('1/0'))

        snap = get_metrics().snapshot()['executions']
        assert snap['total'] == 1
        assert snap['failed'] == 1

    def test_interrupt_records_interrupt(self, mocker):
        get_metrics().reset()
        km = _make_km_with_mock_client(mocker)

        assert km.interrupt() is True

        assert get_metrics().snapshot()['interrupts_total'] == 1

    def test_restart_records_restart(self, mocker):
        get_metrics().reset()
        mock_jkm = mocker.patch('core.kernel.JupyterKernelManager')
        mock_jkm.return_value.client.side_effect = [
            mocker.MagicMock(), mocker.MagicMock(),
        ]
        km = KernelManager()
        km.ensure_kernel()

        km.restart()

        kernel = get_metrics().snapshot()['kernel']
        assert kernel['starts_total'] == 2  # initial start + restart
        assert kernel['restarts_total'] == 1

    def test_watchdog_records_restart_after_death(self, mocker):
        get_metrics().reset()
        first = mocker.MagicMock()
        first.is_alive.return_value = True
        second = mocker.MagicMock()
        second.is_alive.return_value = True
        mock_jkm = mocker.patch('core.kernel.JupyterKernelManager')
        mock_jkm.side_effect = [first, second]

        km = KernelManager()
        km.ensure_kernel()
        assert km._km is first

        first.is_alive.return_value = False  # simulate kernel death

        # Make the watchdog Event.wait return immediately on the first call
        # (so the body runs once), then stop the loop on the second call.
        calls = {'count': 0}

        def fake_wait(timeout=None):
            calls['count'] += 1
            if calls['count'] >= 2:
                km._watchdog_stop.set()
            return False

        km._watchdog_stop.wait = fake_wait  # type: ignore[assignment]

        km._watchdog_loop()

        kernel = get_metrics().snapshot()['kernel']
        # 1 initial start + 1 (re)start via _start_kernel inside the loop.
        assert kernel['watchdog_restarts_total'] == 1
        assert kernel['starts_total'] == 2

    def test_initial_kernel_start_counts(self, mocker):
        get_metrics().reset()
        mock_jkm = mocker.patch('core.kernel.JupyterKernelManager')
        mock_jkm.return_value.is_alive.return_value = True

        km = KernelManager()
        km.ensure_kernel()

        assert get_metrics().snapshot()['kernel']['starts_total'] == 1