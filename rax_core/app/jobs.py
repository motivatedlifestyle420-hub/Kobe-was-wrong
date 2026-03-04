"""
Job lifecycle operations for rax_core.

Design constraints enforced here:
  - claim_next uses a single UPDATE … RETURNING statement (no SELECT-then-UPDATE).
  - All mutations to a running job verify state='running', worker_id, lease_id,
    AND a fresh heartbeat (heartbeat_at >= now - HEARTBEAT_TIMEOUT).
  - fail() retries → state='pending'; exhausted → state='dead'.
  - Every state transition appends a row to job_events (append-only).
  - requeue_stale recovers crashed workers via heartbeat expiry.
"""
import json
import random
import time
import uuid
from typing import Any, Dict, List, Optional

from rax_core.app import config
from rax_core.app.db import get_conn, close_conn


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _backoff_seconds(attempts: int, base: float = 2.0, cap: float = 3600.0) -> float:
    """Exponential backoff with full jitter to prevent retry storms."""
    ceiling = min(base ** attempts, cap)
    return random.uniform(0.0, ceiling)


def _append_event(
    conn,
    job_id: str,
    event_type: str,
    worker_id: Optional[str] = None,
    lease_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    now: Optional[float] = None,
) -> None:
    """Append a row to job_events. Never called outside a live transaction."""
    conn.execute(
        """
        INSERT INTO job_events (job_id, event_type, worker_id, lease_id, payload, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            event_type,
            worker_id,
            lease_id,
            json.dumps(payload) if payload is not None else None,
            now or time.time(),
        ),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enqueue(
    job_type: str,
    payload: Dict[str, Any],
    job_id: Optional[str] = None,
    max_attempts: int = 3,
    run_at: Optional[float] = None,
    db_path: Optional[str] = None,
) -> str:
    """
    Idempotent job insertion.

    If a job with the same id already exists the INSERT is silently ignored
    (ON CONFLICT DO NOTHING), making enqueue safe to call multiple times with
    the same job_id.  Returns the job id.
    """
    jid = job_id or str(uuid.uuid4())
    now = time.time()
    rat = run_at if run_at is not None else now

    conn = get_conn(db_path)
    try:
        conn.execute(
            """
            INSERT INTO jobs
                (id, job_type, payload, state, max_attempts, run_at, created_at, updated_at)
            VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (jid, job_type, json.dumps(payload), max_attempts, rat, now, now),
        )
        # Only log the event when we actually inserted (rowcount == 1).
        # sqlite3 reports rowcount=0 for the DO NOTHING path.
        if conn.execute("SELECT changes()").fetchone()[0] == 1:
            _append_event(conn, jid, "enqueued", payload=payload, now=now)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        close_conn(conn)

    return jid


def claim_next(
    worker_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Atomically claim the next pending job.

    Uses a single UPDATE … RETURNING statement — no SELECT-then-UPDATE.
    Returns the claimed job dict or None if no pending job is available.
    """
    lease_id = str(uuid.uuid4())
    now = time.time()

    conn = get_conn(db_path)
    try:
        row = conn.execute(
            """
            UPDATE jobs
            SET state        = 'running',
                worker_id    = ?,
                lease_id     = ?,
                heartbeat_at = ?,
                updated_at   = ?
            WHERE id = (
                SELECT id
                FROM   jobs
                WHERE  state  = 'pending'
                  AND  run_at <= ?
                ORDER BY run_at ASC, created_at ASC
                LIMIT 1
            )
            RETURNING id, job_type, payload, state, worker_id, lease_id,
                      attempts, max_attempts, run_at, heartbeat_at, created_at
            """,
            (worker_id, lease_id, now, now, now),
        ).fetchone()

        if row is None:
            conn.rollback()
            return None

        job = dict(row)
        _append_event(conn, job["id"], "claimed",
                      worker_id=worker_id, lease_id=lease_id, now=now)
        conn.commit()
        return job
    except Exception:
        conn.rollback()
        raise
    finally:
        close_conn(conn)


def heartbeat(
    job_id: str,
    worker_id: str,
    lease_id: str,
    db_path: Optional[str] = None,
) -> bool:
    """
    Refresh the heartbeat timestamp for a running job.

    Only succeeds when the caller owns the job (worker_id + lease_id match)
    and the existing heartbeat is still fresh.  Returns True on success.
    """
    now = time.time()
    cutoff = now - config.get_heartbeat_timeout()

    conn = get_conn(db_path)
    try:
        result = conn.execute(
            """
            UPDATE jobs
            SET heartbeat_at = ?,
                updated_at   = ?
            WHERE id          = ?
              AND state       = 'running'
              AND worker_id   = ?
              AND lease_id    = ?
              AND heartbeat_at >= ?
            """,
            (now, now, job_id, worker_id, lease_id, cutoff),
        )
        conn.commit()
        return result.rowcount == 1
    except Exception:
        conn.rollback()
        raise
    finally:
        close_conn(conn)


def succeed(
    job_id: str,
    worker_id: str,
    lease_id: str,
    result: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> bool:
    """
    Mark a running job as succeeded.

    Verifies full ownership (state=running, worker_id, lease_id, fresh
    heartbeat) before writing.  Returns True on success.
    """
    now = time.time()
    cutoff = now - config.get_heartbeat_timeout()

    conn = get_conn(db_path)
    try:
        res = conn.execute(
            """
            UPDATE jobs
            SET state        = 'succeeded',
                worker_id    = NULL,
                lease_id     = NULL,
                heartbeat_at = NULL,
                updated_at   = ?
            WHERE id          = ?
              AND state       = 'running'
              AND worker_id   = ?
              AND lease_id    = ?
              AND heartbeat_at >= ?
            """,
            (now, job_id, worker_id, lease_id, cutoff),
        )
        if res.rowcount != 1:
            conn.rollback()
            return False

        _append_event(conn, job_id, "succeeded",
                      worker_id=worker_id, lease_id=lease_id,
                      payload=result or {}, now=now)
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
    db_path: Optional[str] = None,
) -> bool:
    """
    Mark a running job as failed with retry semantics.

    Ownership is verified (state=running, worker_id, lease_id, fresh
    heartbeat).  Then:
      - attempts is incremented.
      - if attempts >= max_attempts → state = 'dead'  (terminal).
      - else                        → state = 'pending' with exponential
                                      backoff + jitter on run_at.

    Returns True on success.
    """
    now = time.time()
    cutoff = now - config.get_heartbeat_timeout()

    conn = get_conn(db_path)
    try:
        # Read current counters while verifying ownership (within transaction).
        row = conn.execute(
            """
            SELECT attempts, max_attempts
            FROM   jobs
            WHERE  id          = ?
              AND  state       = 'running'
              AND  worker_id   = ?
              AND  lease_id    = ?
              AND  heartbeat_at >= ?
            """,
            (job_id, worker_id, lease_id, cutoff),
        ).fetchone()

        if row is None:
            return False

        new_attempts = row["attempts"] + 1

        if new_attempts >= row["max_attempts"]:
            new_state = "dead"
            new_run_at = now
        else:
            new_state = "pending"
            new_run_at = now + _backoff_seconds(new_attempts)

        res = conn.execute(
            """
            UPDATE jobs
            SET state        = ?,
                attempts     = ?,
                worker_id    = NULL,
                lease_id     = NULL,
                heartbeat_at = NULL,
                run_at       = ?,
                updated_at   = ?
            WHERE id        = ?
              AND state     = 'running'
              AND worker_id = ?
              AND lease_id  = ?
            """,
            (new_state, new_attempts, new_run_at, now,
             job_id, worker_id, lease_id),
        )
        if res.rowcount != 1:
            conn.rollback()
            return False

        event_type = "dead" if new_state == "dead" else "failed"
        _append_event(conn, job_id, event_type,
                      worker_id=worker_id, lease_id=lease_id,
                      payload={"error": error}, now=now)
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        close_conn(conn)


def requeue_stale(db_path: Optional[str] = None) -> int:
    """
    Recover stale running jobs after a worker crash.

    Only requeues jobs where:
      - state = 'running'
      - heartbeat_at IS NOT NULL
      - heartbeat_at < now - HEARTBEAT_TIMEOUT

    Clears worker_id, lease_id, heartbeat_at on each recovered job.
    Returns the number of jobs requeued.
    """
    now = time.time()
    cutoff = now - config.get_heartbeat_timeout()

    conn = get_conn(db_path)
    try:
        # Select candidates first to capture the old worker/lease for event logging.
        candidates = conn.execute(
            """
            SELECT id, worker_id, lease_id
            FROM   jobs
            WHERE  state        = 'running'
              AND  heartbeat_at IS NOT NULL
              AND  heartbeat_at < ?
            """,
            (cutoff,),
        ).fetchall()

        count = 0
        for row in candidates:
            res = conn.execute(
                """
                UPDATE jobs
                SET state        = 'pending',
                    worker_id    = NULL,
                    lease_id     = NULL,
                    heartbeat_at = NULL,
                    updated_at   = ?
                WHERE id          = ?
                  AND state       = 'running'
                  AND heartbeat_at IS NOT NULL
                  AND heartbeat_at < ?
                """,
                (now, row["id"], cutoff),
            )
            if res.rowcount == 1:
                _append_event(conn, row["id"], "requeued_stale",
                              worker_id=row["worker_id"],
                              lease_id=row["lease_id"], now=now)
                count += 1

        conn.commit()
        return count
    except Exception:
        conn.rollback()
        raise
    finally:
        close_conn(conn)


def get_job(
    job_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return a single job dict or None."""
    conn = get_conn(db_path)
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        close_conn(conn)


def list_jobs(
    state: Optional[str] = None,
    limit: int = 100,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return a list of job dicts, optionally filtered by state."""
    conn = get_conn(db_path)
    try:
        if state:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE state = ? ORDER BY created_at DESC LIMIT ?",
                (state, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        close_conn(conn)


def get_job_events(
    job_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return all events for a job in chronological order."""
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM job_events WHERE job_id = ? ORDER BY id ASC",
            (job_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        close_conn(conn)
