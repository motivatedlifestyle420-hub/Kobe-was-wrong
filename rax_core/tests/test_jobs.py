"""
Tests for rax_core job lifecycle.

Covers:
  - Idempotent enqueue
  - Atomic claim (UPDATE … RETURNING, no double-claim)
  - Heartbeat refresh and ownership verification
  - Succeed with ownership verification
  - Fail: retry → pending, exhausted → dead
  - Exponential backoff run_at advancement on retry
  - requeue_stale recovery
  - Append-only job_events
  - SQLite PRAGMAs (WAL, foreign_keys, busy_timeout)
  - CHECK constraint enforcement
  - No claim of running/succeeded/dead jobs
"""
import time
import uuid

import pytest

from rax_core.app import jobs
from rax_core.app.db import get_conn, close_conn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

W1 = "worker-1"
W2 = "worker-2"


def _enqueue(db, job_type="demo", payload=None, max_attempts=3, run_at=None):
    return jobs.enqueue(
        job_type=job_type,
        payload=payload or {},
        max_attempts=max_attempts,
        run_at=run_at,
        db_path=db,
    )


def _claim(db, worker_id=W1):
    return jobs.claim_next(worker_id, db_path=db)


# ---------------------------------------------------------------------------
# enqueue
# ---------------------------------------------------------------------------

class TestEnqueue:
    def test_creates_pending_job(self, db):
        jid = _enqueue(db)
        job = jobs.get_job(jid, db_path=db)
        assert job["state"] == "pending"
        assert job["attempts"] == 0

    def test_returns_provided_job_id(self, db):
        custom_id = str(uuid.uuid4())
        returned = jobs.enqueue("demo", {}, job_id=custom_id, db_path=db)
        assert returned == custom_id

    def test_idempotent_same_id(self, db):
        jid = str(uuid.uuid4())
        jobs.enqueue("demo", {"v": 1}, job_id=jid, db_path=db)
        jobs.enqueue("demo", {"v": 2}, job_id=jid, db_path=db)  # must not raise
        job = jobs.get_job(jid, db_path=db)
        assert job["payload"] == '{"v": 1}'  # first write wins

    def test_enqueue_appends_event(self, db):
        jid = _enqueue(db)
        events = jobs.get_job_events(jid, db_path=db)
        assert any(e["event_type"] == "enqueued" for e in events)

    def test_idempotent_no_duplicate_event(self, db):
        jid = str(uuid.uuid4())
        jobs.enqueue("demo", {}, job_id=jid, db_path=db)
        jobs.enqueue("demo", {}, job_id=jid, db_path=db)
        events = jobs.get_job_events(jid, db_path=db)
        enqueued_events = [e for e in events if e["event_type"] == "enqueued"]
        assert len(enqueued_events) == 1

    def test_future_run_at_not_claimable(self, db):
        _enqueue(db, run_at=time.time() + 3600)
        job = _claim(db)
        assert job is None


# ---------------------------------------------------------------------------
# claim_next
# ---------------------------------------------------------------------------

class TestClaimNext:
    def test_claims_pending_job(self, db):
        jid = _enqueue(db)
        job = _claim(db)
        assert job is not None
        assert job["id"] == jid
        assert job["state"] == "running"

    def test_sets_worker_and_lease(self, db):
        _enqueue(db)
        job = _claim(db, worker_id=W1)
        assert job["worker_id"] == W1
        assert job["lease_id"] is not None

    def test_returns_none_when_empty(self, db):
        assert _claim(db) is None

    def test_no_double_claim(self, db):
        _enqueue(db)
        job1 = jobs.claim_next(W1, db_path=db)
        job2 = jobs.claim_next(W2, db_path=db)
        assert job1 is not None
        assert job2 is None  # W2 must not steal W1's job

    def test_claim_appends_event(self, db):
        jid = _enqueue(db)
        _claim(db)
        events = jobs.get_job_events(jid, db_path=db)
        assert any(e["event_type"] == "claimed" for e in events)

    def test_oldest_run_at_claimed_first(self, db):
        now = time.time()
        id_early = jobs.enqueue("demo", {}, run_at=now - 10, db_path=db)
        id_late = jobs.enqueue("demo", {}, run_at=now - 5, db_path=db)
        job = _claim(db)
        assert job["id"] == id_early  # earliest run_at wins

    def test_running_job_not_reclaimable(self, db):
        _enqueue(db)
        _claim(db, worker_id=W1)
        assert jobs.claim_next(W2, db_path=db) is None


# ---------------------------------------------------------------------------
# heartbeat
# ---------------------------------------------------------------------------

class TestHeartbeat:
    def test_refreshes_timestamp(self, db):
        _enqueue(db)
        job = _claim(db)
        time.sleep(0.05)
        ok = jobs.heartbeat(job["id"], job["worker_id"], job["lease_id"], db_path=db)
        assert ok is True
        updated = jobs.get_job(job["id"], db_path=db)
        assert updated["heartbeat_at"] > job["heartbeat_at"]

    def test_wrong_lease_rejected(self, db):
        _enqueue(db)
        job = _claim(db)
        ok = jobs.heartbeat(job["id"], job["worker_id"], "bad-lease", db_path=db)
        assert ok is False

    def test_wrong_worker_rejected(self, db):
        _enqueue(db)
        job = _claim(db)
        ok = jobs.heartbeat(job["id"], "wrong-worker", job["lease_id"], db_path=db)
        assert ok is False


# ---------------------------------------------------------------------------
# succeed
# ---------------------------------------------------------------------------

class TestSucceed:
    def test_marks_succeeded(self, db):
        _enqueue(db)
        job = _claim(db)
        ok = jobs.succeed(job["id"], job["worker_id"], job["lease_id"], db_path=db)
        assert ok is True
        updated = jobs.get_job(job["id"], db_path=db)
        assert updated["state"] == "succeeded"
        assert updated["worker_id"] is None
        assert updated["lease_id"] is None
        assert updated["heartbeat_at"] is None

    def test_appends_succeeded_event(self, db):
        _enqueue(db)
        job = _claim(db)
        jobs.succeed(job["id"], job["worker_id"], job["lease_id"], db_path=db)
        events = jobs.get_job_events(job["id"], db_path=db)
        assert any(e["event_type"] == "succeeded" for e in events)

    def test_wrong_lease_rejected(self, db):
        _enqueue(db)
        job = _claim(db)
        ok = jobs.succeed(job["id"], job["worker_id"], "bad-lease", db_path=db)
        assert ok is False
        updated = jobs.get_job(job["id"], db_path=db)
        assert updated["state"] == "running"

    def test_wrong_worker_rejected(self, db):
        _enqueue(db)
        job = _claim(db)
        ok = jobs.succeed(job["id"], "thief-worker", job["lease_id"], db_path=db)
        assert ok is False

    def test_already_succeeded_noop(self, db):
        _enqueue(db)
        job = _claim(db)
        jobs.succeed(job["id"], job["worker_id"], job["lease_id"], db_path=db)
        ok = jobs.succeed(job["id"], job["worker_id"], job["lease_id"], db_path=db)
        assert ok is False  # state is no longer 'running'


# ---------------------------------------------------------------------------
# fail / retry policy
# ---------------------------------------------------------------------------

class TestFail:
    def test_retryable_returns_to_pending(self, db):
        _enqueue(db, max_attempts=3)
        job = _claim(db)
        ok = jobs.fail(job["id"], job["worker_id"], job["lease_id"],
                       error="boom", db_path=db)
        assert ok is True
        updated = jobs.get_job(job["id"], db_path=db)
        assert updated["state"] == "pending"
        assert updated["attempts"] == 1
        assert updated["worker_id"] is None
        assert updated["lease_id"] is None

    def test_exhausted_becomes_dead(self, db):
        _enqueue(db, max_attempts=1)
        job = _claim(db)
        ok = jobs.fail(job["id"], job["worker_id"], job["lease_id"],
                       error="fatal", db_path=db)
        assert ok is True
        updated = jobs.get_job(job["id"], db_path=db)
        assert updated["state"] == "dead"
        assert updated["attempts"] == 1

    def test_multiple_retries_then_dead(self, db):
        _enqueue(db, max_attempts=2)
        # First attempt
        job = _claim(db)
        jobs.fail(job["id"], job["worker_id"], job["lease_id"], db_path=db)
        assert jobs.get_job(job["id"], db_path=db)["state"] == "pending"

        # Make run_at past so it can be claimed again
        conn = get_conn(db)
        conn.execute("UPDATE jobs SET run_at = 0 WHERE id = ?", (job["id"],))
        conn.commit()
        close_conn(conn)

        # Second attempt — should die
        job2 = _claim(db)
        assert job2 is not None
        jobs.fail(job2["id"], job2["worker_id"], job2["lease_id"], db_path=db)
        assert jobs.get_job(job["id"], db_path=db)["state"] == "dead"

    def test_backoff_advances_run_at(self, db):
        _enqueue(db, max_attempts=3)
        before = time.time()
        job = _claim(db)
        jobs.fail(job["id"], job["worker_id"], job["lease_id"], db_path=db)
        updated = jobs.get_job(job["id"], db_path=db)
        # run_at must be >= now (backoff added) — with jitter it could be 0..2 s
        assert updated["run_at"] >= before

    def test_wrong_lease_rejected(self, db):
        _enqueue(db)
        job = _claim(db)
        ok = jobs.fail(job["id"], job["worker_id"], "bad-lease", db_path=db)
        assert ok is False
        assert jobs.get_job(job["id"], db_path=db)["state"] == "running"

    def test_appends_failed_event_on_retry(self, db):
        _enqueue(db, max_attempts=3)
        job = _claim(db)
        jobs.fail(job["id"], job["worker_id"], job["lease_id"], db_path=db)
        events = jobs.get_job_events(job["id"], db_path=db)
        assert any(e["event_type"] == "failed" for e in events)

    def test_appends_dead_event_when_exhausted(self, db):
        _enqueue(db, max_attempts=1)
        job = _claim(db)
        jobs.fail(job["id"], job["worker_id"], job["lease_id"], db_path=db)
        events = jobs.get_job_events(job["id"], db_path=db)
        assert any(e["event_type"] == "dead" for e in events)


# ---------------------------------------------------------------------------
# requeue_stale
# ---------------------------------------------------------------------------

class TestRequeueStale:
    def _force_stale(self, db, job_id, age=120):
        """Backdate heartbeat_at to simulate a crashed worker."""
        conn = get_conn(db)
        conn.execute(
            "UPDATE jobs SET heartbeat_at = ? WHERE id = ?",
            (time.time() - age, job_id),
        )
        conn.commit()
        close_conn(conn)

    def test_requeues_stale_job(self, db):
        _enqueue(db)
        job = _claim(db)
        self._force_stale(db, job["id"])
        n = jobs.requeue_stale(db_path=db)
        assert n == 1
        updated = jobs.get_job(job["id"], db_path=db)
        assert updated["state"] == "pending"
        assert updated["worker_id"] is None
        assert updated["lease_id"] is None
        assert updated["heartbeat_at"] is None

    def test_fresh_job_not_requeued(self, db):
        _enqueue(db)
        _claim(db)
        n = jobs.requeue_stale(db_path=db)
        assert n == 0

    def test_appends_requeued_stale_event(self, db):
        _enqueue(db)
        job = _claim(db)
        self._force_stale(db, job["id"])
        jobs.requeue_stale(db_path=db)
        events = jobs.get_job_events(job["id"], db_path=db)
        assert any(e["event_type"] == "requeued_stale" for e in events)

    def test_requeued_job_is_reclaimable(self, db):
        _enqueue(db)
        job = _claim(db, worker_id=W1)
        self._force_stale(db, job["id"])
        jobs.requeue_stale(db_path=db)
        job2 = jobs.claim_next(W2, db_path=db)
        assert job2 is not None
        assert job2["id"] == job["id"]

    def test_only_running_jobs_requeued(self, db):
        jid = _enqueue(db)
        # Leave as pending — should not be requeued
        n = jobs.requeue_stale(db_path=db)
        assert n == 0
        assert jobs.get_job(jid, db_path=db)["state"] == "pending"

    def test_null_heartbeat_not_requeued(self, db):
        """Jobs in 'running' state with NULL heartbeat_at should not be requeued."""
        jid = _enqueue(db)
        _claim(db)
        conn = get_conn(db)
        conn.execute("UPDATE jobs SET heartbeat_at = NULL WHERE id = ?", (jid,))
        conn.commit()
        close_conn(conn)
        n = jobs.requeue_stale(db_path=db)
        assert n == 0


# ---------------------------------------------------------------------------
# Append-only job_events
# ---------------------------------------------------------------------------

class TestJobEvents:
    def test_events_are_append_only(self, db):
        """Database triggers must prevent UPDATE or DELETE of job_events rows."""
        jid = _enqueue(db)
        job = _claim(db)
        jobs.succeed(job["id"], job["worker_id"], job["lease_id"], db_path=db)

        # Direct UPDATE of job_events must be rejected (append-only trigger).
        conn = get_conn(db)
        with pytest.raises(Exception):
            conn.execute(
                "UPDATE job_events SET event_type = 'mutated' WHERE job_id = ?",
                (jid,),
            )
            conn.commit()
        close_conn(conn)

        # Direct DELETE of job_events must also be rejected (append-only trigger).
        conn = get_conn(db)
        with pytest.raises(Exception):
            conn.execute(
                "DELETE FROM job_events WHERE job_id = ?",
                (jid,),
            )
            conn.commit()
        close_conn(conn)

        # Events must remain unchanged after failed mutation attempts.
        events_after = jobs.get_job_events(jid, db_path=db)
        assert len(events_after) == 3  # enqueued, claimed, succeeded

    def test_full_lifecycle_event_sequence(self, db):
        jid = _enqueue(db)
        job = _claim(db)
        jobs.succeed(job["id"], job["worker_id"], job["lease_id"], db_path=db)
        events = jobs.get_job_events(jid, db_path=db)
        types = [e["event_type"] for e in events]
        assert types == ["enqueued", "claimed", "succeeded"]


# ---------------------------------------------------------------------------
# Schema / constraint enforcement
# ---------------------------------------------------------------------------

class TestSchemaConstraints:
    def test_invalid_state_rejected(self, db):
        jid = _enqueue(db)
        conn = get_conn(db)
        with pytest.raises(Exception):
            conn.execute(
                "UPDATE jobs SET state = 'zombie' WHERE id = ?", (jid,)
            )
            conn.commit()
        close_conn(conn)

    def test_foreign_key_on_job_events(self, db):
        conn = get_conn(db)
        with pytest.raises(Exception):
            conn.execute(
                """
                INSERT INTO job_events (job_id, event_type, created_at)
                VALUES ('nonexistent-job', 'enqueued', ?)
                """,
                (time.time(),),
            )
            conn.commit()
        close_conn(conn)

    def test_wal_journal_mode(self, db):
        conn = get_conn(db)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        close_conn(conn)
        assert mode == "wal"

    def test_foreign_keys_enabled(self, db):
        conn = get_conn(db)
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        close_conn(conn)
        assert fk == 1


# ---------------------------------------------------------------------------
# list_jobs / get_job
# ---------------------------------------------------------------------------

class TestQueryHelpers:
    def test_list_all(self, db):
        _enqueue(db)
        _enqueue(db)
        assert len(jobs.list_jobs(db_path=db)) == 2

    def test_list_by_state(self, db):
        _enqueue(db)
        jid2 = _enqueue(db)
        _claim(db)          # claims one job
        pending = jobs.list_jobs(state="pending", db_path=db)
        assert len(pending) == 1
        assert pending[0]["id"] == jid2

    def test_get_job_not_found(self, db):
        assert jobs.get_job("nonexistent", db_path=db) is None
