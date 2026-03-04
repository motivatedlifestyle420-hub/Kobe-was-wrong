"""
Job persistence layer for rax_core.

Responsibilities:
  - enqueue      : insert with idempotency key (UNIQUE constraint handles dedup)
  - claim        : atomically move pending → running, record worker_id
  - heartbeat    : renew heartbeat_at for a running job
  - succeed      : mark running → succeeded (ownership verified)
  - fail         : mark running → failed/dead with exponential backoff (ownership verified)
  - get          : fetch a single job by id
  - list_jobs    : list jobs optionally filtered by state
  - requeue_stale: reclaim orphaned running jobs whose heartbeat has expired
"""
import json
import time
import sqlite3
from typing import Optional

from app.config import (
    WORKER_ID,
    MAX_ATTEMPTS,
    BACKOFF_BASE,
    BACKOFF_CAP,
    HEARTBEAT_TIMEOUT,
)
from app.db import get_conn
from app.models import Job, PENDING, RUNNING, SUCCEEDED, FAILED, DEAD


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enqueue(
    job_type: str,
    payload: dict,
    idempotency_key: str,
    max_attempts: int = MAX_ATTEMPTS,
    conn: sqlite3.Connection | None = None,
) -> Optional[Job]:
    """
    Insert a new job.  If a job with the same idempotency_key already exists
    the existing row is returned unchanged (idempotent).
    """
    c = conn or get_conn()
    now = time.time()
    payload_str = json.dumps(payload)
    try:
        c.execute(
            """
            INSERT INTO jobs
                (idempotency_key, job_type, payload, state, attempts,
                 max_attempts, run_after, created_at, updated_at)
            VALUES (?, ?, ?, 'pending', 0, ?, 0, ?, ?)
            """,
            (idempotency_key, job_type, payload_str, max_attempts, now, now),
        )
        c.commit()
    except sqlite3.IntegrityError:
        pass  # duplicate idempotency key — not an error
    row = c.execute(
        "SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    return Job.from_row(row) if row else None


def claim(conn: sqlite3.Connection | None = None) -> Optional[Job]:
    """
    Atomically claim the oldest eligible pending job for this worker.
    Returns the claimed Job or None if nothing is available.
    """
    c = conn or get_conn()
    now = time.time()
    row = c.execute(
        """
        SELECT * FROM jobs
        WHERE state = 'pending' AND run_after <= ?
        ORDER BY run_after ASC, id ASC
        LIMIT 1
        """,
        (now,),
    ).fetchone()
    if row is None:
        return None
    job_id = row["id"]
    updated = c.execute(
        """
        UPDATE jobs
        SET state = 'running', worker_id = ?, heartbeat_at = ?, updated_at = ?
        WHERE id = ? AND state = 'pending'
        """,
        (WORKER_ID, now, now, job_id),
    ).rowcount
    c.commit()
    if updated == 0:
        return None  # another worker claimed it first
    row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return Job.from_row(row) if row else None


def heartbeat(job_id: int, conn: sqlite3.Connection | None = None) -> bool:
    """Renew the heartbeat timestamp for a running job owned by this worker."""
    c = conn or get_conn()
    now = time.time()
    updated = c.execute(
        """
        UPDATE jobs
        SET heartbeat_at = ?, updated_at = ?
        WHERE id = ? AND state = 'running' AND worker_id = ?
        """,
        (now, now, job_id, WORKER_ID),
    ).rowcount
    c.commit()
    return updated == 1


def succeed(job_id: int, conn: sqlite3.Connection | None = None) -> bool:
    """Mark a running job as succeeded.  Verifies ownership."""
    c = conn or get_conn()
    now = time.time()
    updated = c.execute(
        """
        UPDATE jobs
        SET state = 'succeeded', worker_id = NULL, updated_at = ?
        WHERE id = ? AND state = 'running' AND worker_id = ?
        """,
        (now, job_id, WORKER_ID),
    ).rowcount
    c.commit()
    return updated == 1


def fail(
    job_id: int,
    error: str = "",
    conn: sqlite3.Connection | None = None,
) -> bool:
    """
    Mark a running job as failed or dead.
    - Increments attempts.
    - If attempts >= max_attempts → state = 'dead'.
    - Otherwise              → state = 'failed', schedules run_after with
                               exponential backoff.
    Verifies ownership before any change.
    """
    c = conn or get_conn()
    now = time.time()
    row = c.execute(
        "SELECT attempts, max_attempts FROM jobs WHERE id = ? AND state = 'running' AND worker_id = ?",
        (job_id, WORKER_ID),
    ).fetchone()
    if row is None:
        return False  # ownership check failed

    attempts = row["attempts"] + 1
    max_att = row["max_attempts"]

    if attempts >= max_att:
        new_state = DEAD
        run_after = now
    else:
        new_state = FAILED
        delay = min(BACKOFF_BASE ** attempts, BACKOFF_CAP)
        run_after = now + delay

    updated = c.execute(
        """
        UPDATE jobs
        SET state = ?, attempts = ?, error = ?, run_after = ?,
            worker_id = NULL, updated_at = ?
        WHERE id = ? AND state = 'running' AND worker_id = ?
        """,
        (new_state, attempts, error, run_after, now, job_id, WORKER_ID),
    ).rowcount
    c.commit()
    return updated == 1


def requeue_stale(conn: sqlite3.Connection | None = None) -> int:
    """
    Reset orphaned running jobs (heartbeat expired) back to 'pending' so they
    can be reclaimed.  Returns the number of rows reset.
    """
    c = conn or get_conn()
    threshold = time.time() - HEARTBEAT_TIMEOUT
    updated = c.execute(
        """
        UPDATE jobs
        SET state = 'pending', worker_id = NULL, heartbeat_at = NULL, updated_at = ?
        WHERE state = 'running' AND heartbeat_at < ?
        """,
        (time.time(), threshold),
    ).rowcount
    c.commit()
    return updated


def get(job_id: int, conn: sqlite3.Connection | None = None) -> Optional[Job]:
    """Fetch a single job by primary key."""
    c = conn or get_conn()
    row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return Job.from_row(row) if row else None


def list_jobs(
    state: Optional[str] = None,
    limit: int = 100,
    conn: sqlite3.Connection | None = None,
) -> list[Job]:
    """List jobs, optionally filtered by state."""
    c = conn or get_conn()
    if state:
        rows = c.execute(
            "SELECT * FROM jobs WHERE state = ? ORDER BY id DESC LIMIT ?",
            (state, limit),
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [Job.from_row(r) for r in rows]
