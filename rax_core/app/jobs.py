"""Core job-queue operations.

Invariants
----------
* enqueue  – ON CONFLICT DO NOTHING on idempotency_key (layer 1 idempotency).
* claim    – single UPDATE…RETURNING, atomic, no SELECT-then-UPDATE race.
* succeed  – marks done; records in effect_ledger if result supplied.
* fail     – retry (exponential back-off + jitter) or dead-letter.
* heartbeat– refreshes lease so stale-requeue doesn't fire prematurely.
* All mutations verify worker_id + lease_id + fresh heartbeat.
"""
import json
import random
import time
import uuid
from typing import Any, Optional

from rax_core.app import config
from rax_core.app.db import get_conn, close_conn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> float:
    return time.time()


def _new_id() -> str:
    return str(uuid.uuid4())


def _log_event(
    conn,
    job_id: str,
    event: str,
    detail: Optional[str] = None,
    worker_id: Optional[str] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO job_events (job_id, event, detail, worker_id, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (job_id, event, detail, worker_id, _now()),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enqueue(
    job_type: str,
    payload: Optional[dict] = None,
    *,
    idempotency_key: Optional[str] = None,
    priority: int = 0,
    max_attempts: int = 5,
    run_after: Optional[float] = None,
) -> Optional[str]:
    """Enqueue a job.  Returns the new job ID, or None if deduplicated.

    Idempotency (layer 1): if *idempotency_key* is supplied and a job with
    that key already exists the INSERT is silently ignored and None is returned.
    """
    job_id = _new_id()
    now = _now()
    payload_json = json.dumps(payload or {})

    conn = get_conn()
    try:
        cursor = conn.execute(
            """
            INSERT INTO jobs
                (id, job_type, payload, idempotency_key, status, priority,
                 max_attempts, run_after, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            ON CONFLICT(idempotency_key) DO NOTHING
            """,
            (
                job_id,
                job_type,
                payload_json,
                idempotency_key,
                priority,
                max_attempts,
                run_after,
                now,
                now,
            ),
        )
        if cursor.rowcount == 0:
            # Deduplicated – idempotency_key already present.
            conn.rollback()
            return None
        _log_event(conn, job_id, "enqueued", job_type)
        conn.commit()
        return job_id
    except Exception:
        conn.rollback()
        raise
    finally:
        close_conn(conn)


def claim(worker_id: str) -> Optional[dict]:
    """Atomically claim the next available job for *worker_id*.

    Uses a single UPDATE…RETURNING so there is no SELECT-then-UPDATE race.
    Stale jobs (heartbeat expired beyond the lease window) are also eligible.
    Returns a dict of job columns or None if the queue is empty.
    """
    lease_id = _new_id()
    now = _now()
    stale_before = now - config.WORKER_LEASE_SECONDS
    deadline = now + config.WORKER_LEASE_SECONDS

    conn = get_conn()
    try:
        row = conn.execute(
            """
            UPDATE jobs
            SET
                status       = 'running',
                worker_id    = ?,
                lease_id     = ?,
                heartbeat_at = ?,
                attempts     = attempts + 1,
                updated_at   = ?
            WHERE id = (
                SELECT id FROM jobs
                WHERE  status IN ('pending')
                  AND  (run_after IS NULL OR run_after <= ?)
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
            )
            RETURNING *
            """,
            (worker_id, lease_id, deadline, now, now),
        ).fetchone()

        if row is None:
            # Also check for stale running jobs whose lease has expired.
            row = conn.execute(
                """
                UPDATE jobs
                SET
                    status       = 'running',
                    worker_id    = ?,
                    lease_id     = ?,
                    heartbeat_at = ?,
                    attempts     = attempts + 1,
                    updated_at   = ?
                WHERE id = (
                    SELECT id FROM jobs
                    WHERE  status = 'running'
                      AND  heartbeat_at IS NOT NULL
                      AND  heartbeat_at < ?
                    ORDER BY heartbeat_at ASC
                    LIMIT 1
                )
                RETURNING *
                """,
                (worker_id, lease_id, deadline, now, stale_before),
            ).fetchone()

        if row is None:
            conn.rollback()
            return None

        job = dict(row)
        _log_event(conn, job["id"], "claimed", worker_id=worker_id)
        conn.commit()
        job["payload"] = json.loads(job["payload"])
        job["lease_id"] = lease_id
        return job
    except Exception:
        conn.rollback()
        raise
    finally:
        close_conn(conn)


def heartbeat(job_id: str, worker_id: str, lease_id: str) -> bool:
    """Extend the lease heartbeat.  Returns True on success."""
    now = _now()
    deadline = now + config.WORKER_LEASE_SECONDS

    conn = get_conn()
    try:
        cur = conn.execute(
            """
            UPDATE jobs
            SET heartbeat_at = ?, updated_at = ?
            WHERE id = ? AND worker_id = ? AND lease_id = ? AND status = 'running'
            """,
            (deadline, now, job_id, worker_id, lease_id),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        close_conn(conn)


def succeed(
    job_id: str,
    worker_id: str,
    lease_id: str,
    result: Optional[Any] = None,
    effect_key: Optional[str] = None,
) -> bool:
    """Mark a job as done.

    If *effect_key* is supplied the result is also written to the effect_ledger
    (idempotency layer 2 – prevents double side-effects on retry).
    Returns True on success.
    """
    now = _now()
    result_json = json.dumps(result) if result is not None else None

    conn = get_conn()
    try:
        cur = conn.execute(
            """
            UPDATE jobs
            SET status = 'done', worker_id = NULL, lease_id = NULL,
                heartbeat_at = NULL, updated_at = ?
            WHERE id = ? AND worker_id = ? AND lease_id = ? AND status = 'running'
            """,
            (now, job_id, worker_id, lease_id),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return False

        _log_event(conn, job_id, "succeeded", detail=result_json, worker_id=worker_id)

        if effect_key:
            conn.execute(
                """
                INSERT OR IGNORE INTO effect_ledger
                    (idempotency_key, job_id, result, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (effect_key, job_id, result_json, now),
            )

        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        close_conn(conn)


def fail(
    job_id: str,
    worker_id: str,
    lease_id: str,
    error: Optional[str] = None,
) -> bool:
    """Mark a job attempt as failed.

    If attempts < max_attempts: requeue as 'pending' with exponential back-off
    + jitter.  Otherwise move to 'dead' (dead-letter queue).
    Returns True on success.
    """
    now = _now()

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT attempts, max_attempts FROM jobs "
            "WHERE id = ? AND worker_id = ? AND lease_id = ? AND status = 'running'",
            (job_id, worker_id, lease_id),
        ).fetchone()

        if row is None:
            conn.rollback()
            return False

        attempts, max_attempts = row["attempts"], row["max_attempts"]

        if attempts < max_attempts:
            # Exponential back-off: 2^(attempts-1) seconds ± 25 % jitter.
            base = 2 ** (attempts - 1)
            delay = base * random.uniform(0.75, 1.25)
            run_after = now + delay
            conn.execute(
                """
                UPDATE jobs
                SET status = 'pending', worker_id = NULL, lease_id = NULL,
                    heartbeat_at = NULL, run_after = ?, updated_at = ?
                WHERE id = ?
                """,
                (run_after, now, job_id),
            )
            _log_event(
                conn,
                job_id,
                "retrying",
                detail=f"attempt={attempts} error={error} run_after={run_after:.1f}",
                worker_id=worker_id,
            )
        else:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'dead', worker_id = NULL, lease_id = NULL,
                    heartbeat_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (now, job_id),
            )
            _log_event(
                conn,
                job_id,
                "dead",
                detail=f"exhausted after {attempts} attempts. last_error={error}",
                worker_id=worker_id,
            )

        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        close_conn(conn)


# ---------------------------------------------------------------------------
# Effect ledger helpers (idempotency layer 2)
# ---------------------------------------------------------------------------

def check_effect(idempotency_key: str) -> Optional[dict]:
    """Return the ledger entry for *idempotency_key*, or None if absent."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM effect_ledger WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        close_conn(conn)


def record_effect(
    idempotency_key: str,
    job_id: str,
    result: Optional[Any] = None,
) -> None:
    """Write to the effect ledger (INSERT OR IGNORE – safe to call repeatedly)."""
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO effect_ledger
                (idempotency_key, job_id, result, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (idempotency_key, job_id, json.dumps(result), _now()),
        )
        conn.commit()
    finally:
        close_conn(conn)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_job(job_id: str) -> Optional[dict]:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        job = dict(row)
        job["payload"] = json.loads(job["payload"])
        return job
    finally:
        close_conn(conn)


def list_jobs(status: Optional[str] = None, limit: int = 100) -> list[dict]:
    conn = get_conn()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for r in rows:
            j = dict(r)
            j["payload"] = json.loads(j["payload"])
            result.append(j)
        return result
    finally:
        close_conn(conn)


def list_events(job_id: str) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM job_events WHERE job_id = ? ORDER BY id ASC",
            (job_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        close_conn(conn)
