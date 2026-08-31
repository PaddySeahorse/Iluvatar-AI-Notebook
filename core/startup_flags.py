"""Startup-time runtime flags: hardware detection + persisted settings.

Called once from :mod:`core.state` import (before ``KERNEL_NAME`` is decided)
this module probes the host for an Iluvatar GPU, records the outcome in
``~/.Iluvatar-AI-Notebook/setting.json`` and pins the corresponding
environment variables:

- ``USE_ILUVATAR_PROVISIONER`` — set from the detection result: ``true`` when
  ``ixsmi`` reports at least one GPU.
- ``USE_OPENAI_SDK`` — forced to ``1`` unless the deployment explicitly set
  ``0``; the ``openai`` package is a hard dependency and ``requests`` remains
  the escape hatch via that explicit ``0``.

``setting.json`` is a best-effort visibility artifact recording what was
detected and when; write failures are logged and swallowed so startup never
depends on it.
"""

import json
import logging
import os
import shutil
import subprocess
import time

from core.user_config import get_config_dir

logger = logging.getLogger(__name__)

SETTING_FILE_NAME = 'setting.json'

_GPU_CLI_PRIORITY = ('ixsmi',)
_GPU_QUERY_ARGS = ('--query-gpu=index', '--format=csv,noheader')
_GPU_CMD_TIMEOUT = 5


def detect_iluvatar_device():
    """Return the GPU CLI name that reported a device, or ``None``.

    A CLI counts only when it is on ``PATH``, exits 0 and lists at least one
    GPU index.
    """
    for cli in _GPU_CLI_PRIORITY:
        if not shutil.which(cli):
            continue
        try:
            result = subprocess.run(
                [cli, *_GPU_QUERY_ARGS],
                capture_output=True,
                text=True,
                timeout=_GPU_CMD_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.warning('%s probe failed (%s); trying next GPU CLI', cli, e)
            continue
        if result.returncode == 0 and result.stdout.strip():
            return cli
    return None


def _write_setting(payload):
    path = os.path.join(get_config_dir(), SETTING_FILE_NAME)
    try:
        os.makedirs(get_config_dir(), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.chmod(path, 0o600)
    except OSError as e:
        logger.warning('startup_flags_setting_write_failed', extra={'error': str(e)})
    return path


def apply_startup_flags():
    """Probe hardware, pin env flags and persist the outcome.

    Returns the payload that was persisted to ``setting.json``.
    """
    detector = detect_iluvatar_device()
    use_provisioner = detector is not None
    os.environ['USE_ILUVATAR_PROVISIONER'] = 'true' if use_provisioner else 'false'
    os.environ.setdefault('USE_OPENAI_SDK', '1')
    payload = {
        'detected_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'detector': detector,
        'use_iluvatar_provisioner': use_provisioner,
        'use_openai_sdk': os.environ.get('USE_OPENAI_SDK', '1'),
    }
    _write_setting(payload)
    logger.info(
        'startup_flags_applied',
        extra={'detector': detector, 'use_iluvatar_provisioner': use_provisioner},
    )
    return payload
