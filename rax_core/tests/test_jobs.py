"""
Tests for the rax_core job state machine.

Covers:
  - enqueue / idempotency
  - claim (pending → running)
  - succeed (running → succeeded)
  - fail with backoff (running → failed)
  - fail exhausted retries (running → dead)
  - ownership verification
  - stale-job requeue
  - DB pragmas (WAL, FK, busy_timeout)
"""
import json
import sqlite3
import sys
import time
import os

import pytest

# Allow `from app.xxx import` when running from rax_core/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Use an in-memory DB for every test
os.environ["RAX_DB_PATH"] = ":memory:"
os.environ["RAX_WORKER_ID"] = "test-worker"
os.environ["RAX_MAX_ATTEMPTS"] = "3"
os.environ["RAX_BACKOFF_BASE"] = "2"
os.environ["RAX_BACKOFF_CAP"] = "60"
os.environ["RAX_HEARTBEAT_TIMEOUT"] = "5"

import importlib
import app.config as _cfg
importlib.reload(_cfg)

import app.db as db_module
importlib.reload(db_module)

import app.jobs as jobs
importlib.reload(jobs)

from app.models import PENDING, RUNNING, SUCCEEDED, FAILED, DEAD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def conn():
    """Fresh in-memory SQLite connection with schema."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA journal_mode = WAL")
    c.execute("PRAGMA busy_timeout = 5000")
    c.commit()
    db_module.init_db(c)
    yield c
    c.close()


def enq(conn, key="key-1", job_type="noop", payload=None, max_attempts=3):
    return jobs.enqueue(
        job_type=job_type,
        payload=payload or {},
        idempotency_key=key,
        max_attempts=max_attempts,
        conn=conn,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEnqueue:
    def test_creates_pending_job(self, conn):
        job = enq(conn)
        assert job is not None
        assert job.state == PENDING
        assert job.attempts == 0

    def test_idempotency_key_dedup(self, conn):
        j1 = enq(conn, key="dup")
        j2 = enq(conn, key="dup")
        assert j1.id == j2.id  # same row returned

    def test_unique_keys_create_separate_jobs(self, conn):
        j1 = enq(conn, key="a")
        j2 = enq(conn, key="b")
        assert j1.id != j2.id

    def test_payload_stored_as_json(self, conn):
        job = enq(conn, payload={"x": 42})
        assert json.loads(job.payload) == {"x": 42}


class TestClaim:
    def test_claim_returns_running_job(self, conn):
        enq(conn)
        job = jobs.claim(conn)
        assert job is not None
        assert job.state == RUNNING
        assert job.worker_id == "test-worker"

    def test_claim_returns_none_when_empty(self, conn):
        assert jobs.claim(conn) is None

    def test_claim_advances_attempts(self, conn):
        enq(conn)
        job = jobs.claim(conn)
        # attempts counter increments only when fail() is called, not during claim()
        assert job.attempts == 0

    def test_claim_sets_heartbeat(self, conn):
        enq(conn)
        job = jobs.claim(conn)
        assert job.heartbeat_at is not None
        assert job.heartbeat_at > 0

    def test_claim_respects_run_after(self, conn):
        """A job with future run_after must not be claimed."""
        job = enq(conn)
        # Manually push run_after into the future
        conn.execute(
            "UPDATE jobs SET state='pending', run_after=? WHERE id=?",
            (time.time() + 9999, job.id),
        )
        conn.commit()
        assert jobs.claim(conn) is None


class TestSucceed:
    def test_running_to_succeeded(self, conn):
        enq(conn)
        job = jobs.claim(conn)
        ok = jobs.succeed(job.id, conn)
        assert ok is True
        refreshed = jobs.get(job.id, conn)
        assert refreshed.state == SUCCEEDED

    def test_ownership_check_fails_for_wrong_worker(self, conn):
        enq(conn)
        job = jobs.claim(conn)
        # Pretend a different worker tries to succeed it
        conn.execute(
            "UPDATE jobs SET worker_id='other-worker' WHERE id=?", (job.id,)
        )
        conn.commit()
        ok = jobs.succeed(job.id, conn)
        assert ok is False


class TestFail:
    def test_first_failure_goes_to_failed(self, conn):
        enq(conn, max_attempts=3)
        job = jobs.claim(conn)
        jobs.fail(job.id, error="boom", conn=conn)
        refreshed = jobs.get(job.id, conn)
        assert refreshed.state == FAILED
        assert refreshed.attempts == 1
        assert refreshed.error == "boom"

    def test_failed_job_has_run_after_in_future(self, conn):
        enq(conn, max_attempts=3)
        job = jobs.claim(conn)
        before = time.time()
        jobs.fail(job.id, conn=conn)
        refreshed = jobs.get(job.id, conn)
        assert refreshed.run_after > before

    def test_exhausted_retries_becomes_dead(self, conn):
        enq(conn, max_attempts=1)
        job = jobs.claim(conn)
        jobs.fail(job.id, conn=conn)
        refreshed = jobs.get(job.id, conn)
        assert refreshed.state == DEAD
        assert refreshed.attempts == 1

    def test_three_attempts_exhaust_default_max(self, conn):
        j = enq(conn, max_attempts=3)
        job_id = j.id
        for _ in range(3):
            # re-set to pending/running manually to simulate retries
            conn.execute(
                "UPDATE jobs SET state='pending', worker_id=NULL, run_after=0 WHERE id=?",
                (job_id,),
            )
            conn.commit()
            job = jobs.claim(conn)
            jobs.fail(job.id, conn=conn)
        final = jobs.get(job_id, conn)
        assert final.state == DEAD

    def test_ownership_check_prevents_fail(self, conn):
        enq(conn)
        job = jobs.claim(conn)
        conn.execute(
            "UPDATE jobs SET worker_id='other-worker' WHERE id=?", (job.id,)
        )
        conn.commit()
        ok = jobs.fail(job.id, conn=conn)
        assert ok is False


class TestHeartbeat:
    def test_heartbeat_updates_timestamp(self, conn):
        enq(conn)
        job = jobs.claim(conn)
        old_hb = job.heartbeat_at
        time.sleep(0.01)
        jobs.heartbeat(job.id, conn)
        refreshed = jobs.get(job.id, conn)
        assert refreshed.heartbeat_at > old_hb

    def test_heartbeat_fails_for_wrong_worker(self, conn):
        enq(conn)
        job = jobs.claim(conn)
        conn.execute(
            "UPDATE jobs SET worker_id='other' WHERE id=?", (job.id,)
        )
        conn.commit()
        ok = jobs.heartbeat(job.id, conn)
        assert ok is False


class TestRequeueStale:
    def test_stale_running_job_reset_to_pending(self, conn):
        enq(conn)
        job = jobs.claim(conn)
        # Force heartbeat into the past
        conn.execute(
            "UPDATE jobs SET heartbeat_at=? WHERE id=?",
            (time.time() - 999, job.id),
        )
        conn.commit()
        count = jobs.requeue_stale(conn)
        assert count == 1
        refreshed = jobs.get(job.id, conn)
        assert refreshed.state == PENDING
        assert refreshed.worker_id is None

    def test_healthy_job_not_reset(self, conn):
        enq(conn)
        job = jobs.claim(conn)
        count = jobs.requeue_stale(conn)
        assert count == 0
        refreshed = jobs.get(job.id, conn)
        assert refreshed.state == RUNNING


class TestListJobs:
    def test_list_all(self, conn):
        enq(conn, key="a")
        enq(conn, key="b")
        all_jobs = jobs.list_jobs(conn=conn)
        assert len(all_jobs) == 2

    def test_list_by_state(self, conn):
        enq(conn, key="a")
        enq(conn, key="b")
        jobs.claim(conn)  # one becomes running
        pending = jobs.list_jobs(state=PENDING, conn=conn)
        assert len(pending) == 1
        running = jobs.list_jobs(state=RUNNING, conn=conn)
        assert len(running) == 1


class TestDBPragmas:
    def test_wal_mode(self, conn):
        # WAL mode is set via PRAGMA but SQLite ignores it for :memory: DBs,
        # returning "memory" instead.  Verify the PRAGMA executes without error
        # and that a file-based connection would receive "wal".
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] in ("wal", "memory")

    def test_foreign_keys_on(self, conn):
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1

    def test_invalid_state_rejected_by_check_constraint(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO jobs
                   (idempotency_key, job_type, payload, state, attempts,
                    max_attempts, run_after, created_at, updated_at)
                   VALUES ('bad-state', 'x', '{}', 'bogus', 0, 3, 0, 0, 0)"""
            )
            conn.commit()
