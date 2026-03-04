"""
Shared pytest fixtures for rax_core tests.

Integration tests reload rax_core modules with a different DB/worker
configuration.  This conftest uses an autouse fixture to reload modules
back to the unit-test defaults (in-memory DB, test-worker) before each
test, making test order irrelevant.
"""
import importlib
import os
import sys

import pytest

# Ensure repo root is on the path for `rax_core` package imports.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_UNIT_DEFAULTS = {
    "RAX_DB_PATH": ":memory:",
    "RAX_WORKER_ID": "test-worker",
    "RAX_MAX_ATTEMPTS": "3",
    "RAX_BACKOFF_BASE": "2",
    "RAX_BACKOFF_CAP": "60",
    "RAX_HEARTBEAT_TIMEOUT": "5",
}


@pytest.fixture(autouse=True)
def _reset_rax_modules():
    """
    Reload rax_core modules with unit-test defaults before every test so that
    integration tests (which reconfigure modules at runtime) don't leak state
    into unit tests.  Runs before test-specific fixtures are set up.
    """
    for k, v in _UNIT_DEFAULTS.items():
        os.environ[k] = v

    import rax_core.app.config as cfg
    import rax_core.app.db as db_mod
    import rax_core.app.jobs as jobs_mod
    import rax_core.app.runner as runner_mod

    importlib.reload(cfg)
    importlib.reload(db_mod)
    importlib.reload(jobs_mod)
    importlib.reload(runner_mod)

    yield
