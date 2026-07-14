"""Integration tests for the Iluvatar GPU provisioner (P4).

These tests run against real Iluvatar GPU hardware and the IXUCA SDK.  They are
marked ``@pytest.mark.iluvatar`` so they can be deselected in CI lanes that lack
the hardware:

    pytest -m "not iluvatar"

To run them on a qualified host (天垓 100/150 server with ixuca-smi installed):

    pytest tests/integration/test_iluvatar_provisioner.py -m iluvatar -v

Prerequisites:
    - IXUCA SDK installed (ixuca-smi on PATH)
    - ``iluvatar_python`` kernelspec installed:
        jupyter kernelspec install kernels/iluvatar_python --user
    - The provisioner entry point registered (pip install -e .)
"""

import asyncio
import os
import signal

import pytest

from core.iluvatar_provisioner import (
    IluvatarProvisioner,
    PROVISIONER_NAME,
    register_provisioner,
)


pytestmark = pytest.mark.iluvatar


# --------------------------------------------------------------------------- #
#  Fixtures                                                                     #
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def provisioner():
    """A bare IluvatarProvisioner instance (no kernel launched)."""
    register_provisioner()
    return IluvatarProvisioner()


@pytest.fixture(scope="module")
def gpu_kernel():
    """Start a real kernel via KernelManager with the Iluvatar provisioner.

    Yields the running KernelManager; shuts it down at teardown.
    """
    from core.kernel import KernelManager

    register_provisioner()
    km = KernelManager(
        kernel_name="iluvatar_python",
        use_iluvatar_provisioner=True,
    )
    km.ensure_kernel()
    yield km
    km.shutdown()


# --------------------------------------------------------------------------- #
#  Hardware-level tests (no kernel needed)                                      #
# --------------------------------------------------------------------------- #

class TestIluvatarHardware:
    """Verify IXUCA SDK is reachable on this host."""

    def test_ixuca_smi_available(self):
        """ixuca-smi must be on PATH for GPU enumeration/interrupt."""
        import shutil
        assert shutil.which("ixuca-smi") is not None, (
            "ixuca-smi not found on PATH — IXUCA SDK not installed"
        )

    def test_get_assigned_gpu_returns_real_device(self, provisioner):
        gpu_id = provisioner._get_assigned_gpu()
        assert gpu_id, "GPU assignment must not be empty"
        # Must be a numeric id or comma-separated list of numeric ids
        for part in gpu_id.split(","):
            assert part.strip().isdigit(), f"GPU id '{part}' is not numeric"


# --------------------------------------------------------------------------- #
#  Provisioner lifecycle (real kernel)                                         #
# --------------------------------------------------------------------------- #

class TestProvisionerKernelLifecycle:
    """End-to-end provisioner lifecycle with a real ipykernel subprocess."""

    def test_kernel_starts_with_provisioner(self, gpu_kernel):
        """The iluvatar_python kernel (backed by IluvatarProvisioner) starts."""
        assert gpu_kernel.is_kernel_alive() is True

    def test_kernel_env_has_ixuca_vars(self, gpu_kernel):
        """The provisioner must have injected IXUCA env vars into the kernel."""
        result = gpu_kernel.execute(
            "import os; print(os.environ.get('IXUCA_VISIBLE_DEVICES', 'MISSING'))"
        )
        assert result["success"] is True
        device = result["stdout"].strip()
        assert device != "MISSING", "IXUCA_VISIBLE_DEVICES not injected"
        assert device, "IXUCA_VISIBLE_DEVICES is empty"

    def test_kernel_env_has_kernel_type(self, gpu_kernel):
        result = gpu_kernel.execute(
            "import os; print(os.environ.get('ILUVATAR_KERNEL_TYPE', 'MISSING'))"
        )
        assert result["success"] is True
        assert result["stdout"].strip() == "ai-optimized"

    def test_torch_cuda_available(self, gpu_kernel):
        """torch-iluvatar must see at least one CUDA device."""
        result = gpu_kernel.execute(
            "import torch\n"
            "print('available:', torch.cuda.is_available())\n"
            "print('count:', torch.cuda.device_count())"
        )
        assert result["success"] is True
        assert "available: True" in result["stdout"]
        assert "count: 1" in result["stdout"] or "count:" in result["stdout"]

    def test_gpu_tensor_operation(self, gpu_kernel):
        """A simple GPU tensor operation must succeed."""
        result = gpu_kernel.execute(
            "import torch\n"
            "x = torch.tensor([1.0, 2.0, 3.0]).cuda()\n"
            "print('sum:', x.sum().item())"
        )
        assert result["success"] is True
        assert "sum: 6.0" in result["stdout"]

    def test_interrupt_gpu_compute_within_3s(self, gpu_kernel):
        """P4 acceptance: GPU compute interrupt must take effect within 3 seconds.

        A busy CUDA loop blocks the shell channel (SIGINT can't reach Python),
        but the IluvatarProvisioner's GPU interrupt (ixuca-smi --kill-compute)
        should break it out.
        """
        import threading
        import time

        outcome = {}

        def run_busy():
            outcome["result"] = gpu_kernel.execute(
                "import torch\n"
                "x = torch.ones(10000, 10000, device='cuda')\n"
                "while True:\n"
                "    x = x * 1.0001 + 0.0001"
            )

        t = threading.Thread(target=run_busy, daemon=True)
        t.start()
        time.sleep(2.0)  # let the GPU loop spin up

        start = time.time()
        ok = gpu_kernel.interrupt()
        elapsed = time.time() - start

        assert ok is True
        assert elapsed < 3.0, f"Interrupt took {elapsed:.1f}s (> 3s budget)"

        t.join(timeout=10)
        assert not t.is_alive(), "GPU compute thread should have returned after interrupt"

    def test_kernel_usable_after_gpu_interrupt(self, gpu_kernel):
        """After a GPU interrupt the kernel must still accept new code."""
        result = gpu_kernel.execute("print('recovered'); 2 + 2")
        assert result["success"] is True
        assert "recovered" in result["stdout"]
        assert "4" in result["stdout"]


# --------------------------------------------------------------------------- #
#  Provisioner direct signal tests                                             #
# --------------------------------------------------------------------------- #

class TestProvisionerSignal:
    """Direct provisioner signal tests (no KernelManager wrapper)."""

    @pytest.mark.asyncio
    async def test_send_signal_does_not_raise(self, provisioner):
        """send_signal must complete without exception even with no process."""
        # provisioner has no process attached (we didn't launch_kernel directly),
        # so this is a no-op that must not raise.
        await provisioner.send_signal(signal.SIGTERM)

    @pytest.mark.asyncio
    async def test_cleanup_does_not_raise(self, provisioner):
        """cleanup must complete without exception."""
        await provisioner.cleanup(restart=False)
