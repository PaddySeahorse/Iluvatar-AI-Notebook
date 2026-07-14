"""Iluvatar GPU kernel provisioner (P4).

Extends :class:`jupyter_client.provisioning.LocalProvisioner` to deep-integrate
Iluvatar (天数智芯) GPU resource management into the kernel lifecycle:

1. ``pre_launch`` — injects IXUCA SDK environment variables and assigns a GPU
   device to the kernel subprocess before it starts.
2. ``send_signal`` — for ``SIGINT`` it first tries an Iluvatar GPU-specific
   interrupt (``ixuca-smi --kill-compute``) which can break out of GPU
   compute that would otherwise block a plain POSIX signal; on any failure it
   falls back to the standard process-group signal.
3. ``cleanup`` — releases GPU resources (resets device memory) before the
   standard subprocess cleanup runs.

The provisioner is registered as a ``jupyter_client.kernel_provisioners`` entry
point (see ``pyproject.toml``) and referenced by
``kernels/iluvatar_python/kernel.json``.  When the entry point is not installed
(e.g. running via ``python app.py`` without ``pip install -e .``) call
:func:`register_provisioner` at startup to inject it into the
``KernelProvisionerFactory`` cache programmatically.

Design reference: docs/design/kernel-refactoring-design.md §3.3
"""

import asyncio
import logging
import os
import signal
import subprocess
from typing import Any, Dict, Optional

from jupyter_client.connect import KernelConnectionInfo
from jupyter_client.provisioning import (
    KernelProvisionerFactory,
    LocalProvisioner,
)

logger = logging.getLogger(__name__)

# Entry-point name under which this provisioner is registered.  Must match the
# ``metadata.kernel_provisioner.provisioner_name`` field in ``kernel.json``.
PROVISIONER_NAME = "iluvatar-provisioner"

# Default library path for the IXUCA SDK when ILUVATAR_LIB_PATH is unset.
_DEFAULT_IXUCA_LIB_PATH = "/usr/local/ixuca/lib"

# How long (seconds) to wait for ixuca-smi subprocess calls before giving up
# and falling back to the default behaviour.
_GPU_CMD_TIMEOUT = 5


class IluvatarProvisioner(LocalProvisioner):
    """Local subprocess provisioner with Iluvatar GPU resource management.

    Inherits full process lifecycle management (``poll`` / ``wait`` / ``kill`` /
    ``terminate`` / ``launch_kernel``) from :class:`LocalProvisioner` and only
    customises the three hooks that need GPU awareness:

    - :meth:`pre_launch` — GPU env injection + device assignment
    - :meth:`send_signal` — GPU-aware interrupt with SIGINT fallback
    - :meth:`cleanup` — GPU resource release
    """

    # ------------------------------------------------------------------ #
    #  GPU device assignment                                              #
    # ------------------------------------------------------------------ #

    def _get_assigned_gpu(self) -> str:
        """Return the GPU device id(s) this kernel should be pinned to.

        Resolution order:
        1. ``ILUVATAR_GPU_ASSIGNMENT`` env var (set by an external scheduler).
        2. The first device reported by ``ixuca-smi`` (if available).
        3. ``"0"`` as a last-resort default.

        Returning a string keeps the result compatible with the
        ``IXUCA_VISIBLE_DEVICES`` env var format (comma-separated ids).
        """
        # External scheduler already decided.
        assignment = os.environ.get("ILUVATAR_GPU_ASSIGNMENT")
        if assignment:
            return assignment

        # Best-effort enumeration via ixuca-smi.
        try:
            result = subprocess.run(
                ["ixuca-smi", "--query-gpu=index", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=_GPU_CMD_TIMEOUT,
            )
            if result.returncode == 0:
                gpus = [
                    g.strip()
                    for g in result.stdout.strip().splitlines()
                    if g.strip()
                ]
                if gpus:
                    return gpus[0]
        except FileNotFoundError:
            # ixuca-smi not installed — not an error, just no GPU discovery.
            logger.debug("ixuca-smi not found; defaulting GPU to '0'")
        except subprocess.TimeoutExpired:
            logger.warning("ixuca-smi timed out; defaulting GPU to '0'")
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("ixuca-smi enumeration failed (%s); defaulting to '0'", e)

        return "0"

    # ------------------------------------------------------------------ #
    #  pre_launch — GPU environment injection                            #
    # ------------------------------------------------------------------ #

    async def pre_launch(self, **kwargs: Any) -> Dict[str, Any]:
        """Inject Iluvatar SDK environment variables before the kernel starts.

        Called by ``jupyter_client`` before :meth:`launch_kernel`.  We mutate
        ``kwargs['env']`` in place and then delegate to ``LocalProvisioner``
        which handles connection-file writing and kernel command formatting.
        """
        env = kwargs.setdefault("env", os.environ.copy())

        gpu_id = self._get_assigned_gpu()
        env.setdefault("IXUCA_VISIBLE_DEVICES", gpu_id)
        env.setdefault("ILUVATAR_KERNEL_TYPE", "ai-optimized")

        # Ensure the IXUCA SDK shared libraries are on the loader path so that
        # torch-iluvatar (or any IXUCA binding) can find them at import time.
        ixuca_lib = os.environ.get("IXUCA_LIB_PATH", _DEFAULT_IXUCA_LIB_PATH)
        existing_ld = env.get("LD_LIBRARY_PATH", "")
        if ixuca_lib and ixuca_lib not in existing_ld.split(os.pathsep):
            env["LD_LIBRARY_PATH"] = f"{ixuca_lib}:{existing_ld}".strip(":")

        # GPU cache directory (avoids writing into the notebook workspace).
        env.setdefault("ILUVATAR_CACHE_DIR", "/tmp/iluvatar-cache")

        logger.info(
            "IluvatarProvisioner pre_launch: GPU=%s kernel_type=%s",
            env.get("IXUCA_VISIBLE_DEVICES"),
            env.get("ILUVATAR_KERNEL_TYPE"),
        )

        return await super().pre_launch(**kwargs)

    # ------------------------------------------------------------------ #
    #  send_signal — GPU-aware interrupt                                  #
    # ------------------------------------------------------------------ #

    async def send_signal(self, signum: int) -> None:
        """Send a signal to the kernel, with GPU-aware interrupt for SIGINT.

        For ``SIGINT`` the provisioner first attempts an Iluvatar GPU compute
        interrupt via ``ixuca-smi --kill-compute``.  GPU compute can block the
        shell channel (and therefore a plain ``SIGINT`` to the process) for a
        long time; the GPU interrupt breaks out of that state.  On any failure
        the standard process-group ``SIGINT`` is still delivered so the kernel
        always receives an interrupt — just possibly slower.
        """
        if signum == signal.SIGINT:
            await self._iluvatar_gpu_interrupt()

        # Always deliver the POSIX signal as well — the GPU interrupt only
        # unblocks compute; the Python interpreter still needs the SIGINT to
        # raise KeyboardInterrupt in the user's code.
        await super().send_signal(signum)

    async def _iluvatar_gpu_interrupt(self) -> None:
        """Attempt to interrupt GPU compute via the IXUCA driver.

        Failures are logged at ``debug`` level and silently swallowed because
        the caller (``send_signal``) always falls back to a standard SIGINT.
        """
        gpu_id = self._get_assigned_gpu()

        # Primary: ixuca-smi --kill-compute
        if await self._run_gpu_cmd(
            ["ixuca-smi", "--gpu", gpu_id, "--kill-compute"],
        ):
            logger.info("GPU compute interrupted via ixuca-smi for GPU %s", gpu_id)
            return

        # Fallback: ask torch-iluvatar to release the device.  This is a soft
        # hint rather than a hard interrupt, but it can help when ixuca-smi is
        # unavailable while the torch runtime is.
        await self._run_gpu_cmd(
            [
                "python", "-c",
                "import torch; torch.cuda.set_device("
                "torch.cuda.current_device()); "
                "print('GPU interrupt attempted')",
            ],
        )

    @staticmethod
    async def _run_gpu_cmd(cmd: list) -> bool:
        """Run a GPU CLI command asynchronously; return True on success."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=_GPU_CMD_TIMEOUT)
            return proc.returncode == 0
        except FileNotFoundError:
            logger.debug("GPU command not found: %s", cmd[0])
        except asyncio.TimeoutError:
            logger.debug("GPU command timed out: %s", cmd[0])
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("GPU command %s failed: %s", cmd[0], e)
        return False

    # ------------------------------------------------------------------ #
    #  cleanup — GPU resource release                                    #
    # ------------------------------------------------------------------ #

    async def cleanup(self, restart: bool = False) -> None:
        """Release GPU resources before standard subprocess cleanup.

        On restart we keep the device assignment (the same kernel will reuse
        it); on full shutdown we ask ixuca-smi to reset device memory.
        """
        if not restart:
            gpu_id = self._get_assigned_gpu()
            await self._run_gpu_cmd(
                ["ixuca-smi", "--gpu", gpu_id, "--reset-memory"],
            )

        await super().cleanup(restart)


# ---------------------------------------------------------------------- #
#  Programmatic registration (for non-installed usage)                   #
# ---------------------------------------------------------------------- #

def register_provisioner(name: str = PROVISIONER_NAME) -> bool:
    """Register :class:`IluvatarProvisioner` in the provisioner factory cache.

    This is a convenience for running the notebook backend via
    ``python app.py`` without installing the package (``pip install -e .``).
    When the package *is* installed the entry point already registers the
    provisioner and this function is a no-op.

    Returns ``True`` if the provisioner was registered by this call,
    ``False`` if it was already present.
    """
    factory = KernelProvisionerFactory.instance()

    if name in factory.provisioners:
        return False

    # Synthesise a minimal entry-point-like object that the factory's
    # ``load()`` call can resolve to our provisioner class.
    from importlib.metadata import EntryPoint

    ep = EntryPoint(
        name=name,
        value=f"{IluvatarProvisioner.__module__}:IluvatarProvisioner",
        group=KernelProvisionerFactory.GROUP_NAME,
    )
    factory.provisioners[name] = ep
    logger.info("Registered IluvatarProvisioner as '%s'", name)
    return True
