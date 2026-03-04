"""Tests for the core job-queue operations (enqueue, claim, succeed, fail, etc.)"""
import time
import pytest

from rax_core.app import jobs


# ---------------------------------------------------------------------------
# enqueue
# ---------------------------------------------------------------------------

def test_enqueue_returns_id():
    job_id = jobs.enqueue("demo.noop", {"x": 1})
    assert job_id is not None
    assert len(job_id) == 36  # UUID


def test_enqueue_idempotency_key_deduplication():
    key = f"test-idem-{time.time()}"
    id1 = jobs.enqueue("demo.noop", {}, idempotency_key=key)
    id2 = jobs.enqueue("demo.noop", {}, idempotency_key=key)
    assert id1 is not None
    assert id2 is None  # deduplicated


def test_enqueue_without_idempotency_key_always_inserts():
    id1 = jobs.enqueue("demo.noop", {})
    id2 = jobs.enqueue("demo.noop", {})
    assert id1 != id2


def test_enqueued_job_is_pending():
    job_id = jobs.enqueue("demo.noop", {"hello": "world"})
    job = jobs.get_job(job_id)
    assert job["status"] == "pending"
    assert job["payload"] == {"hello": "world"}


# ---------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------

def test_claim_returns_job():
    jobs.enqueue("demo.noop", {"claim_test": True})
    job = jobs.claim("worker-1")
    assert job is not None
    assert job["status"] == "running"
    assert job["worker_id"] == "worker-1"
    assert "lease_id" in job


def test_claim_is_atomic_no_double_claim():
    """Two concurrent claims should not return the same job."""
    key = f"atomic-{time.time()}"
    job_id = jobs.enqueue("demo.noop", {}, idempotency_key=key)

    j1 = jobs.claim("worker-A")
    j2 = jobs.claim("worker-B")

    # Collect only claims that actually got the specific job we just enqueued.
    got_our_job = [j for j in [j1, j2] if j is not None and j["id"] == job_id]
    assert len(got_our_job) <= 1, "Same job was claimed by two workers simultaneously"


def test_claim_empty_queue_returns_none():
    # Drain queue first (mark all pending as running)
    while True:
        j = jobs.claim("drainer")
        if j is None:
            break
        jobs.succeed(j["id"], j["worker_id"], j["lease_id"])

    result = jobs.claim("worker-X")
    assert result is None


# ---------------------------------------------------------------------------
# succeed
# ---------------------------------------------------------------------------

def test_succeed_marks_done():
    job_id = jobs.enqueue("demo.noop", {})
    job = jobs.claim("w")
    assert job is not None
    ok = jobs.succeed(job["id"], job["worker_id"], job["lease_id"], result={"r": 1})
    assert ok is True
    updated = jobs.get_job(job["id"])
    assert updated["status"] == "done"


def test_succeed_wrong_lease_fails():
    job_id = jobs.enqueue("demo.noop", {})
    job = jobs.claim("w")
    ok = jobs.succeed(job["id"], job["worker_id"], "wrong-lease-id")
    assert ok is False


# ---------------------------------------------------------------------------
# fail / retry / dead-letter
# ---------------------------------------------------------------------------

def test_fail_retries_pending():
    job_id = jobs.enqueue("demo.noop", {}, max_attempts=3)
    job = jobs.claim("w")
    ok = jobs.fail(job["id"], job["worker_id"], job["lease_id"], error="oops")
    assert ok is True
    updated = jobs.get_job(job["id"])
    assert updated["status"] == "pending"


def test_fail_exhausted_goes_dead():
    job_id = jobs.enqueue("demo.noop", {}, max_attempts=1)
    job = jobs.claim("w")
    ok = jobs.fail(job["id"], job["worker_id"], job["lease_id"], error="fatal")
    assert ok is True
    updated = jobs.get_job(job["id"])
    assert updated["status"] == "dead"


# ---------------------------------------------------------------------------
# heartbeat
# ---------------------------------------------------------------------------

def test_heartbeat_success():
    jobs.enqueue("demo.noop", {})
    job = jobs.claim("w")
    ok = jobs.heartbeat(job["id"], job["worker_id"], job["lease_id"])
    assert ok is True


# ---------------------------------------------------------------------------
# effect ledger
# ---------------------------------------------------------------------------

def test_effect_ledger_roundtrip():
    key = f"effect-{time.time()}"
    assert jobs.check_effect(key) is None
    jobs.record_effect(key, "fake-job-id", {"placed": True})
    entry = jobs.check_effect(key)
    assert entry is not None
    assert entry["idempotency_key"] == key


def test_effect_ledger_insert_or_ignore():
    key = f"effect-idem-{time.time()}"
    jobs.record_effect(key, "job-1", {"v": 1})
    jobs.record_effect(key, "job-2", {"v": 2})  # should be silently ignored
    entry = jobs.check_effect(key)
    assert entry["job_id"] == "job-1"  # first write wins


# ---------------------------------------------------------------------------
# job events
# ---------------------------------------------------------------------------

def test_events_recorded_on_lifecycle():
    job_id = jobs.enqueue("demo.noop", {})
    job = jobs.claim("w")
    jobs.succeed(job["id"], job["worker_id"], job["lease_id"])
    events = jobs.list_events(job["id"])
    event_names = [e["event"] for e in events]
    assert "enqueued" in event_names
    assert "claimed" in event_names
    assert "succeeded" in event_names


# ---------------------------------------------------------------------------
# list_jobs
# ---------------------------------------------------------------------------

def test_list_jobs_filter_by_status():
    jobs.enqueue("demo.noop", {})
    pending = jobs.list_jobs(status="pending")
    assert all(j["status"] == "pending" for j in pending)
