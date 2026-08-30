"""Shared pytest fixtures.

``HOME`` is redirected to a throwaway directory before test-module
collection, so anything touching ``~/.Iluvatar-AI-Notebook`` (e.g. the
LiteLLM proxy config) stays inside a temporary home instead of the real
host home.
"""

import os
import tempfile

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    os.environ['HOME'] = tempfile.mkdtemp(prefix='iluvatar-test-home-')
