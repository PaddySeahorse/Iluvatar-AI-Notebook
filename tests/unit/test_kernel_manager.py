"""Unit tests for core.kernel.KernelManager (P1 + P3).

Covers lifecycle, synchronous execution, streaming execution, interrupt,
variables, watchdog (P1) and the complete/inspect shell-channel helpers (P3)
defined in docs/plan/testing-and-rollout.md.

Tests mock ``jupyter_client`` so no real ipykernel subprocess is spawned.
"""

import queue as _queue

from core.kernel import KernelManager


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _msg(msg_id, msg_type, **content):
    """Build an IOPub-style message dict with a matching parent_header."""
    return {
        'parent_header': {'msg_id': msg_id},
        'msg_type': msg_type,
        'content': content,
    }


def _make_km_with_mock_client(mocker):
    """Return a KernelManager wired to a mock kernel + client.

    The kernel reports alive so ``ensure_kernel`` is a no-op (no real kernel
    is spawned). ``_fetch_variables`` is patched to return [] so the execute
    loop can be tested in isolation.
    """
    km = KernelManager()
    km._km = mocker.MagicMock()
    km._km.is_alive.return_value = True
    km._kc = mocker.MagicMock()
    km._kc.execute.return_value = 'test-msg-id'
    mocker.patch.object(km, '_fetch_variables', return_value=[])
    return km


# --------------------------------------------------------------------------- #
#  Lifecycle                                                                   #
# --------------------------------------------------------------------------- #

class TestKernelManagerLifecycle:
    """Kernel lifecycle: ensure_kernel / warm_start / shutdown / restart."""

    def test_ensure_kernel_starts_when_none(self, mocker):
        mock_jkm = mocker.patch('core.kernel.JupyterKernelManager')
        km = KernelManager()
        assert km._km is None

        km.ensure_kernel()

        mock_jkm.assert_called_once_with(kernel_name='python3')
        mock_jkm.return_value.start_kernel.assert_called_once()
        mock_jkm.return_value.client.assert_called_once()
        assert km._kc is mock_jkm.return_value.client.return_value

    def test_ensure_kernel_noop_when_alive(self, mocker):
        mock_jkm = mocker.patch('core.kernel.JupyterKernelManager')
        km = KernelManager()
        km.ensure_kernel()
        km.ensure_kernel()  # second call must not start another kernel

        assert mock_jkm.call_count == 1
        assert mock_jkm.return_value.start_kernel.call_count == 1

    def test_ensure_kernel_restarts_when_dead(self, mocker):
        mock_jkm = mocker.patch('core.kernel.JupyterKernelManager')
        first = mock_jkm.return_value
        first.is_alive.return_value = True
        second = mocker.MagicMock()
        second.is_alive.return_value = True
        mock_jkm.side_effect = [first, second]

        km = KernelManager()
        km.ensure_kernel()
        assert km._km is first

        first.is_alive.return_value = False  # simulate kernel death
        km.ensure_kernel()

        assert km._km is second
        second.start_kernel.assert_called_once()

    def test_warm_start_starts_kernel_and_watchdog(self, mocker):
        mock_jkm = mocker.patch('core.kernel.JupyterKernelManager')
        mock_jkm.return_value.is_alive.return_value = True
        km = KernelManager()
        km.warm_start()

        assert km.is_kernel_alive() is True
        assert km.is_watchdog_alive() is True
        km.stop_watchdog()

    def test_shutdown_stops_channels_and_kernel(self, mocker):
        mock_jkm = mocker.patch('core.kernel.JupyterKernelManager')
        km = KernelManager()
        km.ensure_kernel()
        kc = km._kc
        km.shutdown()

        kc.stop_channels.assert_called_once()
        mock_jkm.return_value.shutdown_kernel.assert_called_once_with(now=True)
        assert km._km is None
        assert km._kc is None
        assert km.is_kernel_alive() is False

    def test_shutdown_is_safe_when_never_started(self):
        km = KernelManager()
        # Must not raise even though _km / _kc are None
        km.shutdown()
        assert km.is_kernel_alive() is False

    def test_restart_recreates_client(self, mocker):
        mock_jkm = mocker.patch('core.kernel.JupyterKernelManager')
        first_kc = mocker.MagicMock()
        second_kc = mocker.MagicMock()
        mock_jkm.return_value.client.side_effect = [first_kc, second_kc]

        km = KernelManager()
        km.ensure_kernel()
        assert km._kc is first_kc

        km.restart()

        mock_jkm.return_value.restart_kernel.assert_called_once()
        assert km._kc is second_kc
        second_kc.start_channels.assert_called_once()


# --------------------------------------------------------------------------- #
#  Synchronous execution (backward-compatible API)                             #
# --------------------------------------------------------------------------- #

class TestKernelManagerExecution:
    """execute(): stdout / stderr / error / plot / html / empty / not-started."""

    def test_execute_stdout(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('test-msg-id', 'stream', name='stdout', text='hello\n'),
            _msg('test-msg-id', 'status', execution_state='idle'),
        ]

        result = km.execute("print('hello')")

        assert result['success'] is True
        assert result['stdout'] == 'hello\n'
        assert result['stderr'] == ''
        assert result['plots'] == []
        assert result['html'] == ''

    def test_execute_stderr(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('test-msg-id', 'stream', name='stderr', text='boom\n'),
            _msg('test-msg-id', 'status', execution_state='idle'),
        ]

        result = km.execute("import sys; sys.stderr.write('boom')")

        assert result['success'] is True
        assert result['stderr'] == 'boom\n'
        assert result['stdout'] == ''

    def test_execute_error_marks_unsuccessful(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('test-msg-id', 'error', ename='NameError',
                 evalue="name 'x' is not defined",
                 traceback=['Traceback', 'NameError: x']),
            _msg('test-msg-id', 'status', execution_state='idle'),
        ]

        result = km.execute('print(x)')

        assert result['success'] is False
        assert 'NameError' in result['stderr']

    def test_execute_captures_png_plot(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('test-msg-id', 'display_data',
                 data={'image/png': 'BASE64PNG'}, metadata={}),
            _msg('test-msg-id', 'status', execution_state='idle'),
        ]

        result = km.execute("plt.plot([1,2,3])")

        assert result['plots'] == ['BASE64PNG']

    def test_execute_captures_html(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('test-msg-id', 'display_data',
                 data={'text/html': '<table/>'}, metadata={}),
            _msg('test-msg-id', 'status', execution_state='idle'),
        ]

        result = km.execute("df")

        assert result['html'] == '<table/>'

    def test_execute_mixed_stdout_result_and_plot(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('test-msg-id', 'stream', name='stdout', text='running\n'),
            _msg('test-msg-id', 'execute_result',
                 data={'text/plain': '42', 'image/png': 'PNG'},
                 execution_count=1),
            _msg('test-msg-id', 'status', execution_state='idle'),
        ]

        result = km.execute("print('running'); 42")

        assert result['success'] is True
        assert 'running' in result['stdout']
        assert '42' in result['stdout']
        assert 'PNG' in result['plots']

    def test_execute_empty_code_returns_cached_variables(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km.set_variables([{'name': 'x', 'type': 'int', 'repr': '1', 'shape': None}])

        result = km.execute('   ')

        assert result['success'] is True
        assert result['variables'] == [
            {'name': 'x', 'type': 'int', 'repr': '1', 'shape': None}
        ]
        km._kc.execute.assert_not_called()

    def test_execute_when_kernel_not_started(self, mocker):
        km = KernelManager()
        km._km = mocker.MagicMock()
        km._km.is_alive.return_value = True
        # _kc stays None
        mocker.patch.object(km, '_fetch_variables', return_value=[])

        result = km.execute('print(1)')

        assert result['success'] is False
        assert result['stderr'] == 'Kernel not started'

    def test_execute_ignores_unrelated_messages(self, mocker):
        """Messages whose parent_header.msg_id does not match are skipped."""
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('other-msg-id', 'stream', name='stdout', text='not mine\n'),
            _msg('test-msg-id', 'stream', name='stdout', text='mine\n'),
            _msg('test-msg-id', 'status', execution_state='idle'),
        ]

        result = km.execute("print('mine')")

        assert result['stdout'] == 'mine\n'

    def test_execute_timeout(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = _queue.Empty()

        result = km.execute('while True: pass')

        assert result['success'] is False
        assert 'Timeout' in result['stderr']


# --------------------------------------------------------------------------- #
#  Streaming execution (new SSE API)                                           #
# --------------------------------------------------------------------------- #

class TestKernelManagerStream:
    """execute_stream(): stream / display_data / error / status / edge cases."""

    def test_stream_yields_stdout_messages(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('test-msg-id', 'status', execution_state='busy'),
            _msg('test-msg-id', 'stream', name='stdout', text='line1\n'),
            _msg('test-msg-id', 'stream', name='stdout', text='line2\n'),
            _msg('test-msg-id', 'status', execution_state='idle'),
        ]

        msgs = list(km.execute_stream("print('line1'); print('line2')"))

        assert len(msgs) == 4
        assert msgs[0] == {'type': 'status', 'execution_state': 'busy'}
        assert msgs[1] == {'type': 'stream', 'name': 'stdout', 'text': 'line1\n'}
        assert msgs[2]['text'] == 'line2\n'
        assert msgs[3]['execution_state'] == 'idle'

    def test_stream_yields_display_data(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('test-msg-id', 'display_data',
                 data={'image/png': 'PNG'}, metadata={'width': 100}),
            _msg('test-msg-id', 'status', execution_state='idle'),
        ]

        msgs = list(km.execute_stream("plt.show()"))

        display = [m for m in msgs if m['type'] == 'display_data']
        assert len(display) == 1
        assert display[0]['data'] == {'image/png': 'PNG'}
        assert display[0]['metadata'] == {'width': 100}

    def test_stream_yields_error(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('test-msg-id', 'error', ename='ZeroDivisionError',
                 evalue='division by zero', traceback=['tb1', 'tb2']),
            _msg('test-msg-id', 'status', execution_state='idle'),
        ]

        msgs = list(km.execute_stream('1/0'))

        err = [m for m in msgs if m['type'] == 'error']
        assert len(err) == 1
        assert err[0]['ename'] == 'ZeroDivisionError'
        assert err[0]['traceback'] == ['tb1', 'tb2']

    def test_stream_yields_execute_result(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('test-msg-id', 'execute_result',
                 data={'text/plain': '4'}, execution_count=3),
            _msg('test-msg-id', 'status', execution_state='idle'),
        ]

        msgs = list(km.execute_stream('2+2'))

        result_msgs = [m for m in msgs if m['type'] == 'execute_result']
        assert len(result_msgs) == 1
        assert result_msgs[0]['execution_count'] == 3

    def test_stream_when_kernel_not_started(self, mocker):
        km = KernelManager()
        km._km = mocker.MagicMock()
        km._km.is_alive.return_value = True
        # _kc stays None

        msgs = list(km.execute_stream('print(1)'))

        assert len(msgs) == 1
        assert msgs[0]['type'] == 'error'
        assert msgs[0]['evalue'] == 'Kernel not started'

    def test_stream_empty_code_yields_idle(self, mocker):
        km = _make_km_with_mock_client(mocker)

        msgs = list(km.execute_stream('   '))

        assert msgs == [{'type': 'status', 'execution_state': 'idle'}]
        km._kc.execute.assert_not_called()

    def test_stream_terminates_on_idle(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('test-msg-id', 'stream', name='stdout', text='hi\n'),
            _msg('test-msg-id', 'status', execution_state='idle'),
            # Would be consumed if the loop did not break:
            _msg('test-msg-id', 'stream', name='stdout', text='should not see\n'),
        ]

        msgs = list(km.execute_stream("print('hi')"))

        assert all(m.get('text') != 'should not see\n' for m in msgs)
        assert msgs[-1]['execution_state'] == 'idle'

    def test_stream_timeout(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.iopub_channel.get_msg.side_effect = _queue.Empty()

        msgs = list(km.execute_stream('while True: pass'))

        assert len(msgs) == 1
        assert msgs[0]['type'] == 'error'
        assert msgs[0]['ename'] == 'TimeoutError'


# --------------------------------------------------------------------------- #
#  Interrupt                                                                    #
# --------------------------------------------------------------------------- #

class TestKernelManagerInterrupt:
    """interrupt(): success / no-kernel / failure."""

    def test_interrupt_success(self, mocker):
        km = _make_km_with_mock_client(mocker)

        assert km.interrupt() is True
        km._km.interrupt_kernel.assert_called_once()

    def test_interrupt_no_kernel(self):
        km = KernelManager()
        assert km.interrupt() is False

    def test_interrupt_failure_returns_false(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._km.interrupt_kernel.side_effect = RuntimeError('channel closed')

        assert km.interrupt() is False


# --------------------------------------------------------------------------- #
#  Variables                                                                    #
# --------------------------------------------------------------------------- #

class TestKernelManagerVariables:
    """get_variables / set_variables cache + _fetch_variables parsing."""

    def test_get_set_variables_cache(self):
        km = KernelManager()
        assert km.get_variables() == []

        km.set_variables([
            {'name': 'x', 'type': 'int', 'repr': '1', 'shape': None}
        ])
        assert km.get_variables() == [
            {'name': 'x', 'type': 'int', 'repr': '1', 'shape': None}
        ]
        # get_variables returns a copy, not the internal list
        km.get_variables().append({'name': 'y'})
        assert km.get_variables() == [
            {'name': 'x', 'type': 'int', 'repr': '1', 'shape': None}
        ]

    def test_set_variables_none_clears(self):
        km = KernelManager()
        km.set_variables([{'name': 'x', 'type': 'int', 'repr': '1', 'shape': None}])
        km.set_variables(None)
        assert km.get_variables() == []

    def test_fetch_variables_parses_json_stdout(self, mocker):
        km = KernelManager()
        km._km = mocker.MagicMock()
        km._km.is_alive.return_value = True
        km._kc = mocker.MagicMock()
        km._kc.execute.return_value = 'var-msg-id'
        import json
        payload = [{'name': 'a', 'type': 'int', 'repr': '1', 'shape': None}]
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('var-msg-id', 'stream', name='stdout', text=json.dumps(payload)),
            _msg('var-msg-id', 'status', execution_state='idle'),
        ]

        assert km._fetch_variables() == payload

    def test_fetch_variables_empty_when_no_output(self, mocker):
        km = KernelManager()
        km._km = mocker.MagicMock()
        km._km.is_alive.return_value = True
        km._kc = mocker.MagicMock()
        km._kc.execute.return_value = 'var-msg-id'
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('var-msg-id', 'status', execution_state='idle'),
        ]

        assert km._fetch_variables() == []

    def test_fetch_variables_invalid_json_returns_empty(self, mocker):
        km = KernelManager()
        km._km = mocker.MagicMock()
        km._km.is_alive.return_value = True
        km._kc = mocker.MagicMock()
        km._kc.execute.return_value = 'var-msg-id'
        km._kc.iopub_channel.get_msg.side_effect = [
            _msg('var-msg-id', 'stream', name='stdout', text='not json'),
            _msg('var-msg-id', 'status', execution_state='idle'),
        ]

        assert km._fetch_variables() == []

    def test_fetch_variables_no_client(self):
        km = KernelManager()
        assert km._fetch_variables() == []


# --------------------------------------------------------------------------- #
#  Watchdog                                                                     #
# --------------------------------------------------------------------------- #

class TestKernelManagerWatchdog:
    """Watchdog thread start / stop / idempotency."""

    def test_start_watchdog_is_idempotent(self):
        km = KernelManager()
        km.start_watchdog()
        first = km._watchdog_thread
        km.start_watchdog()  # second call must not spawn another thread

        assert km._watchdog_thread is first
        km.stop_watchdog()

    def test_stop_watchdog_sets_event(self):
        km = KernelManager()
        km.start_watchdog()
        assert km.is_watchdog_alive() is True

        km.stop_watchdog()
        km._watchdog_thread.join(timeout=5)

        assert km.is_watchdog_alive() is False

    def test_is_watchdog_alive_false_when_never_started(self):
        km = KernelManager()
        assert km.is_watchdog_alive() is False


# --------------------------------------------------------------------------- #
#  Completion (P3)                                                             #
# --------------------------------------------------------------------------- #

class TestKernelManagerComplete:
    """complete(): happy path / no kernel / exception / empty content."""

    def test_complete_returns_matches_and_cursor_range(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.complete.return_value = {
            'content': {
                'matches': ['DataFrame', 'DataFrameGroupBy', 'DateOffset'],
                'cursor_start': 3,
                'cursor_end': 5,
                'metadata': {'_jupyter_types_experimental': []},
            }
        }

        result = km.complete('pd.Da', 5)

        km._kc.complete.assert_called_once_with(
            'pd.Da', 5, reply=True, timeout=KernelManager.COMPLETE_TIMEOUT
        )
        assert result['matches'] == ['DataFrame', 'DataFrameGroupBy', 'DateOffset']
        assert result['cursor_start'] == 3
        assert result['cursor_end'] == 5
        assert result['metadata'] == {'_jupyter_types_experimental': []}

    def test_complete_returns_empty_when_no_kernel(self):
        km = KernelManager()
        # _kc stays None — no kernel ever started
        result = km.complete('pd.', 3)

        assert result['matches'] == []
        assert result['cursor_start'] == 3
        assert result['cursor_end'] == 3
        assert result['metadata'] == {}

    def test_complete_returns_empty_on_kernel_exception(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.complete.side_effect = RuntimeError('shell channel closed')

        result = km.complete('pd.Da', 5)

        assert result['matches'] == []
        # On failure the cursor range defaults to cursor_pos so the frontend
        # doesn't accidentally delete code when applying an empty match list.
        assert result['cursor_start'] == 5
        assert result['cursor_end'] == 5

    def test_complete_handles_missing_content_key(self, mocker):
        """A reply without a `content` key degrades to an empty result."""
        km = _make_km_with_mock_client(mocker)
        km._kc.complete.return_value = {}  # malformed reply

        result = km.complete('pd.', 3)

        assert result['matches'] == []
        assert result['cursor_start'] == 3

    def test_complete_handles_non_dict_reply(self, mocker):
        """If jupyter_client ever returns a non-dict, we don't crash."""
        km = _make_km_with_mock_client(mocker)
        km._kc.complete.return_value = None

        result = km.complete('pd.', 3)

        assert result['matches'] == []

    def test_complete_passes_cursor_pos_through(self, mocker):
        """The kernel layer does not validate cursor_pos; the route layer does.

        Documents that any clamping of negative / non-int cursor_pos happens
        at the route boundary, not inside KernelManager.complete.
        """
        km = _make_km_with_mock_client(mocker)
        km._kc.complete.return_value = {'content': {'matches': []}}

        result = km.complete('pd.', 3)

        # cursor_pos is forwarded as-is to the kernel client.
        assert km._kc.complete.call_args.args[0:2] == ('pd.', 3)
        # When the kernel returns matches=[] without cursor_start, the result
        # falls back to cursor_pos.
        assert result['cursor_start'] == 3
        assert result['cursor_end'] == 3

    def test_complete_with_zero_matches_returns_empty_list(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.complete.return_value = {
            'content': {'matches': [], 'cursor_start': 0, 'cursor_end': 3}
        }

        result = km.complete('nonexistent_token_', 3)

        assert result['matches'] == []
        assert result['cursor_start'] == 0
        assert result['cursor_end'] == 3


# --------------------------------------------------------------------------- #
#  Inspection (P3)                                                             #
# --------------------------------------------------------------------------- #

class TestKernelManagerInspect:
    """inspect(): found / not-found / no kernel / exception / detail levels."""

    def test_inspect_returns_found_with_data(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.inspect.return_value = {
            'content': {
                'found': True,
                'data': {
                    'text/plain': 'DataFrame([data, index, columns, dtype, copy])',
                    'text/html': '<table><tr><td>...</td></tr></table>',
                },
                'metadata': {},
            }
        }

        result = km.inspect('pd.DataFrame', 12, detail_level=0)

        km._kc.inspect.assert_called_once_with(
            'pd.DataFrame', 12, detail_level=0,
            reply=True, timeout=KernelManager.INSPECT_TIMEOUT,
        )
        assert result['found'] is True
        assert 'text/plain' in result['data']
        assert 'text/html' in result['data']
        assert result['metadata'] == {}

    def test_inspect_detail_level_1_passes_through(self, mocker):
        """detail_level=1 (??) must be forwarded to the kernel client."""
        km = _make_km_with_mock_client(mocker)
        km._kc.inspect.return_value = {
            'content': {
                'found': True,
                'data': {'text/plain': 'def foo():\n    return 42\n'},
                'metadata': {},
            }
        }

        km.inspect('foo', 3, detail_level=1)

        _, kwargs = km._kc.inspect.call_args
        assert kwargs['detail_level'] == 1

    def test_inspect_returns_not_found_when_kernel_says_so(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.inspect.return_value = {
            'content': {'found': False, 'data': {}, 'metadata': {}}
        }

        result = km.inspect('does_not_exist', 14)

        assert result['found'] is False
        assert result['data'] == {}

    def test_inspect_returns_not_found_when_no_kernel(self):
        km = KernelManager()
        result = km.inspect('x', 1)

        assert result['found'] is False
        assert result['data'] == {}
        assert result['metadata'] == {}

    def test_inspect_returns_not_found_on_exception(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.inspect.side_effect = RuntimeError('channel closed')

        result = km.inspect('pd.DataFrame', 12)

        assert result['found'] is False
        assert result['data'] == {}

    def test_inspect_handles_missing_content_key(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.inspect.return_value = {}  # malformed

        result = km.inspect('pd.DataFrame', 12)

        assert result['found'] is False

    def test_inspect_coerces_found_to_bool(self, mocker):
        """`found` may come back as truthy non-bool; we normalise to bool."""
        km = _make_km_with_mock_client(mocker)
        km._kc.inspect.return_value = {
            'content': {'found': 1, 'data': {'text/plain': 'x'}, 'metadata': {}}
        }

        result = km.inspect('x', 1)

        assert result['found'] is True  # not the int 1

    def test_inspect_default_detail_level_is_zero(self, mocker):
        km = _make_km_with_mock_client(mocker)
        km._kc.inspect.return_value = {'content': {'found': False}}

        km.inspect('x', 1)  # no detail_level arg

        _, kwargs = km._kc.inspect.call_args
        assert kwargs['detail_level'] == 0
