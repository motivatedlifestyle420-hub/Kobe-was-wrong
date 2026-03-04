"""Job CRUD — enqueue, claim, heartbeat, succeed, fail, query."""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

_STALE_SECONDS = 60  # running jobs with no heartbeat for this long are re-queued
_BASE_BACKOFF_SECONDS = 5  # base for exponential backoff: 2^attempts * BASE


def enqueue(
    conn: sqlite3.Connection,
    job_type: str,
    payload: dict | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
    run_after: int = 0,
) -> int:
    payload_json = json.dumps(payload or {})
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO jobs
            (job_type, payload_json, idempotency_key, max_attempts, run_after)
        VALUES (?, ?, ?, ?, ?)
        """,
        (job_type, payload_json, idempotency_key, max_attempts, run_after),
    )
    conn.commit()
    if cur.lastrowid:
        return cur.lastrowid
    # idempotency: row already existed
    row = conn.execute(
        "SELECT id FROM jobs WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    return row["id"]


def claim_next(conn: sqlite3.Connection, worker_id: str) -> sqlite3.Row | None:
    now = int(time.time())
    stale_cutoff = now - _STALE_SECONDS
    # re-queue stale running jobs
    conn.execute(
        """
        UPDATE jobs
        SET state = 'pending', worker_id = NULL, heartbeat_at = NULL,
            updated_at = ?
        WHERE state = 'running' AND heartbeat_at < ?
        """,
        (now, stale_cutoff),
    )
    row = conn.execute(
        """
        SELECT * FROM jobs
        WHERE state = 'pending' AND run_after <= ?
        ORDER BY id
        LIMIT 1
        """,
        (now,),
    ).fetchone()
    if row is None:
        conn.commit()
        return None
    conn.execute(
        """
        UPDATE jobs
        SET state = 'running', worker_id = ?, heartbeat_at = ?, updated_at = ?
        WHERE id = ? AND state = 'pending'
        """,
        (worker_id, now, now, row["id"]),
    )
    conn.commit()
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()


def heartbeat(conn: sqlite3.Connection, job_id: int) -> None:
    now = int(time.time())
    conn.execute(
        "UPDATE jobs SET heartbeat_at = ?, updated_at = ? WHERE id = ?",
        (now, now, job_id),
    )
    conn.commit()


def succeed(conn: sqlite3.Connection, job_id: int) -> None:
    now = int(time.time())
    conn.execute(
        "UPDATE jobs SET state = 'succeeded', updated_at = ? WHERE id = ?",
        (now, job_id),
    )
    conn.commit()


def fail(conn: sqlite3.Connection, job_id: int, error: str) -> None:
    now = int(time.time())
    row = conn.execute(
        "SELECT attempts, max_attempts FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    attempts = row["attempts"] + 1
    max_att = row["max_attempts"]
    if attempts >= max_att:
        state = "dead"
        run_after = 0
    else:
        state = "pending"
        backoff = (2**attempts) * _BASE_BACKOFF_SECONDS
        run_after = now + backoff
    conn.execute(
        """
        UPDATE jobs
        SET state = ?, attempts = ?, last_error = ?, run_after = ?,
            worker_id = NULL, heartbeat_at = NULL, updated_at = ?
        WHERE id = ?
        """,
        (state, attempts, error, run_after, now, job_id),
    )
    conn.commit()


def get_job(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def list_jobs(
    conn: sqlite3.Connection, state: str | None = None
) -> list[sqlite3.Row]:
    if state:
        return conn.execute(
            "SELECT * FROM jobs WHERE state = ? ORDER BY id", (state,)
        ).fetchall()
    return conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()
