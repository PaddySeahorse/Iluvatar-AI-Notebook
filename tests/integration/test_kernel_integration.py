"""Integration tests for core.kernel.KernelManager against a real ipykernel.

These spawn an actual ipykernel subprocess (no mocking) to validate the
end-to-end execution / streaming / interrupt / variable paths required by the
P1 admission criteria in docs/roadmap/migration-roadmap.md.

Marked ``integration`` so they can be deselected in fast CI lanes:
    pytest -m "not integration"
"""

import threading
import time

import pytest

from core.kernel import KernelManager


@pytest.fixture(scope="module")
def kernel():
    """Module-scoped real kernel shared across tests in this module."""
    km = KernelManager()
    km.ensure_kernel()
    yield km
    km.shutdown()


@pytest.mark.integration
class TestKernelIntegration:
    """Real-kernel end-to-end behaviour."""

    def test_execute_simple_code(self, kernel):
        result = kernel.execute("x = 1 + 1\nprint(x)")

        assert result['success'] is True
        assert result['stdout'].strip() == '2'
        assert result['stderr'] == ''

    def test_execute_returns_expression_result(self, kernel):
        result = kernel.execute("2 + 3")

        assert result['success'] is True
        assert '5' in result['stdout']

    def test_execute_with_error(self, kernel):
        result = kernel.execute("1 / 0")

        assert result['success'] is False
        assert 'ZeroDivisionError' in result['stderr']

    def test_execute_stream_emits_idle_terminator(self, kernel):
        msgs = list(kernel.execute_stream("for i in range(3):\n    print(i)"))

        statuses = [m for m in msgs if m['type'] == 'status']
        assert any(m['execution_state'] == 'busy' for m in statuses)
        assert msgs[-1] == {'type': 'status', 'execution_state': 'idle'}

        stdout_text = ''.join(m['text'] for m in msgs if m['type'] == 'stream')
        for i in range(3):
            assert str(i) in stdout_text

    def test_execute_stream_yields_error(self, kernel):
        msgs = list(kernel.execute_stream("raise ValueError('boom')"))

        errs = [m for m in msgs if m['type'] == 'error']
        assert len(errs) == 1
        assert errs[0]['ename'] == 'ValueError'
        assert msgs[-1]['execution_state'] == 'idle'

    def test_interrupt_terminates_infinite_loop(self, kernel):
        """P1 admission criterion: interrupt must stop a `while True` loop."""
        outcome = {}

        def run_long():
            outcome['result'] = kernel.execute("while True:\n    pass")

        t = threading.Thread(target=run_long, daemon=True)
        t.start()
        time.sleep(1.0)  # let the loop start

        assert kernel.is_kernel_alive() is True
        ok = kernel.interrupt()
        assert ok is True

        t.join(timeout=10)
        assert not t.is_alive(), "execute thread should have returned after interrupt"
        assert outcome['result']['success'] is False
        assert 'KeyboardInterrupt' in outcome['result']['stderr']

    def test_kernel_still_usable_after_interrupt(self, kernel):
        result = kernel.execute("print('still alive'); 6 * 7")

        assert result['success'] is True
        assert 'still alive' in result['stdout']
        assert '42' in result['stdout']

    def test_display_data_plot(self, kernel):
        result = kernel.execute(
            "import matplotlib.pyplot as plt\n"
            "plt.plot([1, 2, 3])\nplt.show()"
        )

        assert result['success'] is True
        assert len(result['plots']) >= 1

    def test_magics_timeit(self, kernel):
        result = kernel.execute("%timeit 1+1")

        assert result['success'] is True
        # %timeit prints a timing line containing 'ns' or 'µs'/'us'
        assert any(unit in result['stdout'] for unit in ('ns', 'µs', 'us', 'ms', 's per loop'))

    def test_get_variables_reflects_namespace(self, kernel):
        kernel.execute("p1_var = 42")
        # execute() refreshes the cached variables via _fetch_variables;
        # underscore-prefixed names are intentionally filtered out.
        names = [v['name'] for v in kernel.get_variables()]
        assert 'p1_var' in names

    def test_state_persists_across_cells(self, kernel):
        kernel.execute("acc = 10")
        result = kernel.execute("acc += 5\nprint(acc)")

        assert result['success'] is True
        assert '15' in result['stdout']
