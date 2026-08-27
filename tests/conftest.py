"""Shared pytest fixtures.

``import app`` triggers ``core.user_config.apply_saved_config()``, which reads
and seeds ``~/.Iluvatar-AI-Notebook/config.yaml``. ``pytest_configure`` runs
before test-module collection, so redirecting ``HOME`` here keeps that
module-level side effect inside a throwaway directory instead of the real
host home.
"""

import os
import tempfile

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    os.environ['HOME'] = tempfile.mkdtemp(prefix='iluvatar-test-home-')
