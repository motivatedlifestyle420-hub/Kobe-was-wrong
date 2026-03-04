"""
Integration (smoke) test for rax_core.

Starts the Runner in a background thread, enqueues a noop job via the jobs
layer, and asserts that the job reaches 'succeeded' within a reasonable
timeout.  Uses a real file-based SQLite DB (via pytest's tmp_path fixture)
so the runner thread and test assertions share persistent storage.
"""
import importlib
import os
import sqlite3
import sys
import time

import pytest

# Add repo root to sys.path so `rax_core` is importable as a package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ---------------------------------------------------------------------------
# Fixture: isolated modules backed by a real (temp) SQLite file
# ---------------------------------------------------------------------------

@pytest.fixture()
def smoke_env(tmp_path, monkeypatch):
    """
    Reload rax_core modules with a fresh file-based DB and short timeouts
    to keep the smoke test fast.
    """
    db_file = str(tmp_path / "smoke.db")
    monkeypatch.setenv("RAX_DB_PATH", db_file)
    monkeypatch.setenv("RAX_WORKER_ID", "smoke-worker")
    monkeypatch.setenv("RAX_HEARTBEAT_INTERVAL", "1")
    monkeypatch.setenv("RAX_HEARTBEAT_TIMEOUT", "30")
    monkeypatch.setenv("RAX_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("RAX_BACKOFF_BASE", "2")
    monkeypatch.setenv("RAX_BACKOFF_CAP", "60")

    # Reload in dependency order so each module picks up the updated env vars.
    import rax_core.app.config as cfg
    import rax_core.app.db as db_mod
    import rax_core.app.jobs as jobs_mod
    import rax_core.app.runner as runner_mod

    importlib.reload(cfg)
    importlib.reload(db_mod)
    importlib.reload(jobs_mod)
    importlib.reload(runner_mod)

    db_mod.init_db()

    yield jobs_mod, runner_mod


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def test_noop_job_succeeds_end_to_end(smoke_env):
    """
    Full pipeline: enqueue → claim → execute → succeed.
    The Runner runs in a daemon background thread so the test can assert the
    terminal state without blocking.
    """
    jobs_mod, runner_mod = smoke_env

    runner = runner_mod.Runner()

    @runner.register("noop")
    def handle_noop(payload: dict) -> None:
        pass  # intentionally does nothing

    runner.start(block=False)

    try:
        job = jobs_mod.enqueue(
            job_type="noop",
            payload={"smoke": True},
            idempotency_key="smoke-noop-001",
        )
        assert job is not None, "enqueue returned None"

        # Poll for up to 10 seconds; the runner polls every 1 s by default.
        deadline = time.time() + 10
        final_state = None
        while time.time() < deadline:
            refreshed = jobs_mod.get(job.id)
            if refreshed and refreshed.state == "succeeded":
                final_state = refreshed.state
                break
            time.sleep(0.2)

        assert final_state == "succeeded", (
            f"Expected job to reach 'succeeded' within 10 s, got: {final_state}"
        )
    finally:
        runner.stop()


def test_failing_job_reaches_dead(smoke_env):
    """
    A handler that always raises should exhaust retries (max_attempts=1) and
    land in 'dead'.
    """
    jobs_mod, runner_mod = smoke_env

    runner = runner_mod.Runner()

    @runner.register("always_fail")
    def handle_fail(payload: dict) -> None:
        raise RuntimeError("intentional failure")

    runner.start(block=False)

    try:
        job = jobs_mod.enqueue(
            job_type="always_fail",
            payload={},
            idempotency_key="smoke-fail-001",
            max_attempts=1,
        )
        assert job is not None

        deadline = time.time() + 10
        final_state = None
        while time.time() < deadline:
            refreshed = jobs_mod.get(job.id)
            if refreshed and refreshed.state == "dead":
                final_state = refreshed.state
                break
            time.sleep(0.2)

        assert final_state == "dead", (
            f"Expected job to reach 'dead' within 10 s, got: {final_state}"
        )
    finally:
        runner.stop()
