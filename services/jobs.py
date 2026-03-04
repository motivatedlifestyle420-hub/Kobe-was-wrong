import json
import sqlite3
import uuid
from typing import Optional


def enqueue(conn: sqlite3.Connection, job_type: str, payload: dict) -> str:
    """Insert a new pending job and return its id."""
    job_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs (id, type, payload) VALUES (?, ?, ?)",
        (job_id, job_type, json.dumps(payload)),
    )
    conn.commit()
    return job_id


def dequeue(conn: sqlite3.Connection, worker_id: str) -> Optional[sqlite3.Row]:
    """Atomically lease the oldest pending job; returns the row or None."""
    cur = conn.execute(
        """
        UPDATE jobs
           SET status   = 'leased',
               leased_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'),
               worker_id = ?
         WHERE id = (
               SELECT id FROM jobs WHERE status = 'pending'
               ORDER BY created_at LIMIT 1
         )
        RETURNING *
        """,
        (worker_id,),
    )
    row = cur.fetchone()
    conn.commit()
    return row


def heartbeat(conn: sqlite3.Connection, job_id: str) -> None:
    """Refresh leased_at to signal the worker is still alive."""
    conn.execute(
        "UPDATE jobs SET leased_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (job_id,),
    )
    conn.commit()


def complete(conn: sqlite3.Connection, job_id: str) -> None:
    """Mark a job as successfully completed and record the completion timestamp."""
    conn.execute(
        """
        UPDATE jobs
           SET status  = 'done',
               done_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
         WHERE id = ?
        """,
        (job_id,),
    )
    conn.commit()


def fail(conn: sqlite3.Connection, job_id: str, error: str) -> None:
    """Mark a job as failed, recording the error message and failure timestamp."""
    conn.execute(
        """
        UPDATE jobs
           SET status  = 'failed',
               done_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'),
               error   = ?
         WHERE id = ?
        """,
        (error, job_id),
    )
    conn.commit()


def get(conn: sqlite3.Connection, job_id: str) -> Optional[sqlite3.Row]:
    """Retrieve a job by its id; returns the row or None if not found."""
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def list_all(conn: sqlite3.Connection, limit: int = 100) -> list:
    """Return up to *limit* jobs ordered by creation time (newest first)."""
    return conn.execute(
        "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
