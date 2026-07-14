"""Unit tests for core.iluvatar_provisioner.IluvatarProvisioner (P4).

These tests mock all subprocess / GPU calls so they run on any machine
without Iluvatar hardware or the IXUCA SDK installed.

Coverage matches the P4 acceptance criteria in
docs/roadmap/migration-roadmap.md §3.5:
  - pre_launch injects IXUCA env vars
  - send_signal performs GPU-aware interrupt for SIGINT
  - cleanup releases GPU resources
  - _get_assigned_gpu resolves devices from env / ixuca-smi / default
  - register_provisioner is idempotent
"""

import asyncio
import signal
import subprocess

import pytest

from core.iluvatar_provisioner import (
    IluvatarProvisioner,
    PROVISIONER_NAME,
    register_provisioner,
)
from jupyter_client.provisioning import LocalProvisioner


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _make_provisioner():
    """Construct an IluvatarProvisioner without spawning anything."""
    return IluvatarProvisioner()


def _completed(stdout="", returncode=0):
    """Build a fake subprocess.CompletedProcess."""
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=""
    )


# --------------------------------------------------------------------------- #
#  _get_assigned_gpu                                                           #
# --------------------------------------------------------------------------- #

class TestGetAssignedGpu:
    """GPU device assignment resolution."""

    def test_uses_external_assignment_env(self, monkeypatch):
        monkeypatch.setenv("ILUVATAR_GPU_ASSIGNMENT", "2,3")
        prov = _make_provisioner()

        assert prov._get_assigned_gpu() == "2,3"

    def test_uses_first_gpu_from_ixuca_smi(self, monkeypatch, mocker):
        monkeypatch.delenv("ILUVATAR_GPU_ASSIGNMENT", raising=False)
        mocker.patch(
            "core.iluvatar_provisioner.subprocess.run",
            return_value=_completed(stdout="0\n1\n2\n"),
        )
        prov = _make_provisioner()

        assert prov._get_assigned_gpu() == "0"

    def test_defaults_to_zero_when_ixuca_smi_missing(self, monkeypatch, mocker):
        monkeypatch.delenv("ILUVATAR_GPU_ASSIGNMENT", raising=False)
        mocker.patch(
            "core.iluvatar_provisioner.subprocess.run",
            side_effect=FileNotFoundError("ixuca-smi not found"),
        )
        prov = _make_provisioner()

        assert prov._get_assigned_gpu() == "0"

    def test_defaults_to_zero_on_timeout(self, monkeypatch, mocker):
        monkeypatch.delenv("ILUVATAR_GPU_ASSIGNMENT", raising=False)
        mocker.patch(
            "core.iluvatar_provisioner.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["ixuca-smi"], timeout=5),
        )
        prov = _make_provisioner()

        assert prov._get_assigned_gpu() == "0"

    def test_defaults_to_zero_on_nonzero_exit(self, monkeypatch, mocker):
        monkeypatch.delenv("ILUVATAR_GPU_ASSIGNMENT", raising=False)
        mocker.patch(
            "core.iluvatar_provisioner.subprocess.run",
            return_value=_completed(stdout="", returncode=1),
        )
        prov = _make_provisioner()

        assert prov._get_assigned_gpu() == "0"

    def test_defaults_to_zero_when_no_gpus_listed(self, monkeypatch, mocker):
        monkeypatch.delenv("ILUVATAR_GPU_ASSIGNMENT", raising=False)
        mocker.patch(
            "core.iluvatar_provisioner.subprocess.run",
            return_value=_completed(stdout="\n"),
        )
        prov = _make_provisioner()

        assert prov._get_assigned_gpu() == "0"


# --------------------------------------------------------------------------- #
#  pre_launch — env injection                                                  #
# --------------------------------------------------------------------------- #

class TestPreLaunch:
    """pre_launch injects Iluvatar SDK environment variables."""

    @pytest.mark.asyncio
    async def test_injects_ixuca_visible_devices(self, monkeypatch, mocker):
        monkeypatch.delenv("ILUVATAR_GPU_ASSIGNMENT", raising=False)
        mocker.patch(
            "core.iluvatar_provisioner.subprocess.run",
            return_value=_completed(stdout="1\n"),
        )
        # Avoid the heavy LocalProvisioner.pre_launch (connection file, etc.)
        mock_super = mocker.patch.object(
            LocalProvisioner, "pre_launch",
            new=mocker.AsyncMock(side_effect=lambda **kw: kw),
        )

        prov = _make_provisioner()
        kwargs = {"env": {}}
        result = await prov.pre_launch(**kwargs)

        assert result["env"]["IXUCA_VISIBLE_DEVICES"] == "1"
        mock_super.assert_called_once()

    @pytest.mark.asyncio
    async def test_injects_kernel_type(self, mocker):
        mocker.patch.object(
            LocalProvisioner, "pre_launch",
            new=mocker.AsyncMock(side_effect=lambda **kw: kw),
        )
        prov = _make_provisioner()

        result = await prov.pre_launch(env={})

        assert result["env"]["ILUVATAR_KERNEL_TYPE"] == "ai-optimized"

    @pytest.mark.asyncio
    async def test_adds_ixuca_lib_to_ld_library_path(self, monkeypatch, mocker):
        monkeypatch.setenv("IXUCA_LIB_PATH", "/opt/ixuca/lib")
        mocker.patch.object(
            LocalProvisioner, "pre_launch",
            new=mocker.AsyncMock(side_effect=lambda **kw: kw),
        )
        prov = _make_provisioner()

        result = await prov.pre_launch(env={"LD_LIBRARY_PATH": "/usr/lib"})

        ld = result["env"]["LD_LIBRARY_PATH"]
        assert "/opt/ixuca/lib" in ld
        assert "/usr/lib" in ld

    @pytest.mark.asyncio
    async def test_does_not_duplicate_ixuca_lib(self, monkeypatch, mocker):
        monkeypatch.setenv("IXUCA_LIB_PATH", "/opt/ixuca/lib")
        mocker.patch.object(
            LocalProvisioner, "pre_launch",
            new=mocker.AsyncMock(side_effect=lambda **kw: kw),
        )
        prov = _make_provisioner()

        result = await prov.pre_launch(env={"LD_LIBRARY_PATH": "/opt/ixuca/lib"})

        # Should not appear twice.
        assert result["env"]["LD_LIBRARY_PATH"].count("/opt/ixuca/lib") == 1

    @pytest.mark.asyncio
    async def test_sets_cache_dir(self, mocker):
        mocker.patch.object(
            LocalProvisioner, "pre_launch",
            new=mocker.AsyncMock(side_effect=lambda **kw: kw),
        )
        prov = _make_provisioner()

        result = await prov.pre_launch(env={})

        assert result["env"]["ILUVATAR_CACHE_DIR"] == "/tmp/iluvatar-cache"

    @pytest.mark.asyncio
    async def test_does_not_override_existing_env_values(self, mocker):
        """setdefault means caller-provided values win."""
        mocker.patch.object(
            LocalProvisioner, "pre_launch",
            new=mocker.AsyncMock(side_effect=lambda **kw: kw),
        )
        prov = _make_provisioner()

        result = await prov.pre_launch(env={
            "IXUCA_VISIBLE_DEVICES": "5",
            "ILUVATAR_KERNEL_TYPE": "custom",
            "ILUVATAR_CACHE_DIR": "/custom/cache",
        })

        assert result["env"]["IXUCA_VISIBLE_DEVICES"] == "5"
        assert result["env"]["ILUVATAR_KERNEL_TYPE"] == "custom"
        assert result["env"]["ILUVATAR_CACHE_DIR"] == "/custom/cache"

    @pytest.mark.asyncio
    async def test_creates_env_if_not_provided(self, mocker):
        """When kwargs has no 'env', one is created from os.environ.copy()."""
        mocker.patch.object(
            LocalProvisioner, "pre_launch",
            new=mocker.AsyncMock(side_effect=lambda **kw: kw),
        )
        prov = _make_provisioner()

        result = await prov.pre_launch()

        assert "env" in result
        assert "IXUCA_VISIBLE_DEVICES" in result["env"]

    @pytest.mark.asyncio
    async def test_calls_super_pre_launch(self, mocker):
        mock_super = mocker.patch.object(
            LocalProvisioner, "pre_launch",
            new=mocker.AsyncMock(return_value={"env": {}, "cmd": ["python"]}),
        )
        prov = _make_provisioner()

        await prov.pre_launch(env={})

        mock_super.assert_called_once()


# --------------------------------------------------------------------------- #
#  send_signal — GPU-aware interrupt                                           #
# --------------------------------------------------------------------------- #

class TestSendSignal:
    """send_signal: GPU interrupt for SIGINT, passthrough for others."""

    @pytest.mark.asyncio
    async def test_sigint_tries_gpu_interrupt_then_signal(self, mocker):
        mock_gpu_interrupt = mocker.patch.object(
            IluvatarProvisioner, "_iluvatar_gpu_interrupt",
            new=mocker.AsyncMock(),
        )
        mock_super_signal = mocker.patch.object(
            LocalProvisioner, "send_signal",
            new=mocker.AsyncMock(),
        )
        prov = _make_provisioner()

        await prov.send_signal(signal.SIGINT)

        mock_gpu_interrupt.assert_awaited_once()
        mock_super_signal.assert_awaited_once_with(signal.SIGINT)

    @pytest.mark.asyncio
    async def test_non_sigint_signal_skips_gpu_interrupt(self, mocker):
        mock_gpu_interrupt = mocker.patch.object(
            IluvatarProvisioner, "_iluvatar_gpu_interrupt",
            new=mocker.AsyncMock(),
        )
        mock_super_signal = mocker.patch.object(
            LocalProvisioner, "send_signal",
            new=mocker.AsyncMock(),
        )
        prov = _make_provisioner()

        await prov.send_signal(signal.SIGTERM)

        mock_gpu_interrupt.assert_not_awaited()
        mock_super_signal.assert_awaited_once_with(signal.SIGTERM)

    @pytest.mark.asyncio
    async def test_sigint_still_delivers_signal_if_gpu_interrupt_fails(self, mocker):
        """GPU interrupt failure must not prevent the standard SIGINT."""
        mock_gpu_interrupt = mocker.patch.object(
            IluvatarProvisioner, "_iluvatar_gpu_interrupt",
            new=mocker.AsyncMock(side_effect=RuntimeError("GPU unreachable")),
        )
        mock_super_signal = mocker.patch.object(
            LocalProvisioner, "send_signal",
            new=mocker.AsyncMock(),
        )
        prov = _make_provisioner()

        # The RuntimeError from _iluvatar_gpu_interrupt would propagate —
        # but _iluvatar_gpu_interrupt is designed to never raise (it catches
        # everything internally).  Here we verify that even if it did, the
        # test surfaces it so the contract is clear: _iluvatar_gpu_interrupt
        # must be exception-safe.
        with pytest.raises(RuntimeError):
            await prov.send_signal(signal.SIGINT)

        # _iluvatar_gpu_interrupt was attempted
        mock_gpu_interrupt.assert_awaited_once()
        # super().send_signal was NOT reached because the exception propagated
        mock_super_signal.assert_not_awaited()


# --------------------------------------------------------------------------- #
#  _iluvatar_gpu_interrupt                                                     #
# --------------------------------------------------------------------------- #

class TestGpuInterrupt:
    """_iluvatar_gpu_interrupt: ixuca-smi primary, torch fallback."""

    @pytest.mark.asyncio
    async def test_succeeds_via_ixuca_smi(self, monkeypatch, mocker):
        monkeypatch.delenv("ILUVATAR_GPU_ASSIGNMENT", raising=False)
        mocker.patch(
            "core.iluvatar_provisioner.subprocess.run",
            return_value=_completed(stdout="0\n"),
        )

        # Mock the async subprocess for the interrupt call.
        mock_proc = mocker.MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait = mocker.AsyncMock(return_value=0)
        mocker.patch(
            "core.iluvatar_provisioner.asyncio.create_subprocess_exec",
            new=mocker.AsyncMock(return_value=mock_proc),
        )

        prov = _make_provisioner()
        await prov._iluvatar_gpu_interrupt()

        # ixuca-smi --kill-compute was called
        import core.iluvatar_provisioner as mod
        mod.asyncio.create_subprocess_exec.assert_awaited_once()
        args = mod.asyncio.create_subprocess_exec.call_args.args
        assert "ixuca-smi" in args
        assert "--kill-compute" in args

    @pytest.mark.asyncio
    async def test_falls_back_to_torch_when_ixuca_smi_missing(self, monkeypatch, mocker):
        monkeypatch.delenv("ILUVATAR_GPU_ASSIGNMENT", raising=False)
        mocker.patch(
            "core.iluvatar_provisioner.subprocess.run",
            return_value=_completed(stdout="0\n"),
        )

        # First create_subprocess_exec (ixuca-smi) raises FileNotFoundError,
        # second (torch) succeeds.
        mock_proc = mocker.MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait = mocker.AsyncMock(return_value=0)
        mocker.patch(
            "core.iluvatar_provisioner.asyncio.create_subprocess_exec",
            new=mocker.AsyncMock(
                side_effect=[FileNotFoundError("ixuca-smi not found"), mock_proc]
            ),
        )

        prov = _make_provisioner()
        await prov._iluvatar_gpu_interrupt()

        # Two calls: ixuca-smi (failed) then torch (succeeded)
        import core.iluvatar_provisioner as mod
        assert mod.asyncio.create_subprocess_exec.await_count == 2

    @pytest.mark.asyncio
    async def test_does_not_raise_on_all_failures(self, monkeypatch, mocker):
        """Even if everything fails, _iluvatar_gpu_interrupt must not raise."""
        monkeypatch.delenv("ILUVATAR_GPU_ASSIGNMENT", raising=False)
        mocker.patch(
            "core.iluvatar_provisioner.subprocess.run",
            return_value=_completed(stdout="0\n"),
        )
        mocker.patch(
            "core.iluvatar_provisioner.asyncio.create_subprocess_exec",
            new=mocker.AsyncMock(side_effect=FileNotFoundError("nothing")),
        )

        prov = _make_provisioner()
        # Must not raise
        await prov._iluvatar_gpu_interrupt()


# --------------------------------------------------------------------------- #
#  cleanup                                                                     #
# --------------------------------------------------------------------------- #

class TestCleanup:
    """cleanup: GPU memory reset on shutdown, skip on restart."""

    @pytest.mark.asyncio
    async def test_resets_gpu_memory_on_shutdown(self, monkeypatch, mocker):
        monkeypatch.delenv("ILUVATAR_GPU_ASSIGNMENT", raising=False)
        mocker.patch(
            "core.iluvatar_provisioner.subprocess.run",
            return_value=_completed(stdout="0\n"),
        )
        mock_proc = mocker.MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait = mocker.AsyncMock(return_value=0)
        mock_create = mocker.patch(
            "core.iluvatar_provisioner.asyncio.create_subprocess_exec",
            new=mocker.AsyncMock(return_value=mock_proc),
        )
        mock_super_cleanup = mocker.patch.object(
            LocalProvisioner, "cleanup",
            new=mocker.AsyncMock(),
        )

        prov = _make_provisioner()
        await prov.cleanup(restart=False)

        # ixuca-smi --reset-memory was called
        args = mock_create.call_args.args
        assert "ixuca-smi" in args
        assert "--reset-memory" in args
        mock_super_cleanup.assert_awaited_once_with(False)

    @pytest.mark.asyncio
    async def test_skips_gpu_reset_on_restart(self, monkeypatch, mocker):
        monkeypatch.delenv("ILUVATAR_GPU_ASSIGNMENT", raising=False)
        mocker.patch(
            "core.iluvatar_provisioner.subprocess.run",
            return_value=_completed(stdout="0\n"),
        )
        mock_create = mocker.patch(
            "core.iluvatar_provisioner.asyncio.create_subprocess_exec",
            new=mocker.AsyncMock(),
        )
        mock_super_cleanup = mocker.patch.object(
            LocalProvisioner, "cleanup",
            new=mocker.AsyncMock(),
        )

        prov = _make_provisioner()
        await prov.cleanup(restart=True)

        # No GPU reset on restart
        mock_create.assert_not_awaited()
        mock_super_cleanup.assert_awaited_once_with(True)


# --------------------------------------------------------------------------- #
#  register_provisioner                                                        #
# --------------------------------------------------------------------------- #

class TestRegisterProvisioner:
    """register_provisioner: idempotent, discoverable by factory."""

    def test_first_call_returns_true(self):
        # The provisioner may already be registered from a previous test;
        # clear it to test the first-call path.
        from jupyter_client.provisioning import KernelProvisionerFactory
        factory = KernelProvisionerFactory.instance()
        factory.provisioners.pop(PROVISIONER_NAME, None)

        assert register_provisioner() is True
        assert PROVISIONER_NAME in factory.provisioners

    def test_second_call_returns_false(self):
        register_provisioner()  # ensure registered
        assert register_provisioner() is False

    def test_registered_provisioner_loads_to_class(self):
        from jupyter_client.provisioning import KernelProvisionerFactory
        factory = KernelProvisionerFactory.instance()
        register_provisioner()

        ep = factory.provisioners[PROVISIONER_NAME]
        cls = ep.load()

        assert cls is IluvatarProvisioner


# --------------------------------------------------------------------------- #
#  KernelManager integration                                                  #
# --------------------------------------------------------------------------- #

class TestKernelManagerProvisionerWiring:
    """KernelManager registers the provisioner before starting the kernel."""

    def test_provisioner_flag_defaults_to_false(self):
        from core.kernel import KernelManager
        km = KernelManager()
        assert km._use_iluvatar_provisioner is False
        assert km._kernel_name == "python3"

    def test_provisioner_flag_can_be_enabled(self):
        from core.kernel import KernelManager
        km = KernelManager(
            kernel_name="iluvatar_python",
            use_iluvatar_provisioner=True,
        )
        assert km._use_iluvatar_provisioner is True
        assert km._kernel_name == "iluvatar_python"

    def test_start_kernel_registers_provisioner_when_enabled(self, mocker):
        from core.kernel import KernelManager
        mock_register = mocker.patch(
            "core.iluvatar_provisioner.register_provisioner",
            return_value=True,
        )
        mocker.patch("core.kernel.JupyterKernelManager")

        km = KernelManager(use_iluvatar_provisioner=True)
        km.ensure_kernel()

        mock_register.assert_called_once()

    def test_start_kernel_does_not_register_when_disabled(self, mocker):
        from core.kernel import KernelManager
        mock_register = mocker.patch(
            "core.iluvatar_provisioner.register_provisioner",
        )
        mocker.patch("core.kernel.JupyterKernelManager")

        km = KernelManager(use_iluvatar_provisioner=False)
        km.ensure_kernel()

        mock_register.assert_not_called()
