"""
DDL for the rax_core schema.

jobs
────
  - State enforced by CHECK constraint: pending | running | succeeded | failed | dead
  - No other states may be introduced.

job_events
──────────
  - Append-only audit log; rows are never updated or deleted.
"""
from typing import Optional

from rax_core.app.db import get_conn, close_conn

_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT    PRIMARY KEY,
    job_type     TEXT    NOT NULL,
    payload      TEXT    NOT NULL DEFAULT '{}',
    state        TEXT    NOT NULL DEFAULT 'pending'
                         CHECK(state IN ('pending','running','succeeded','failed','dead')),
    worker_id    TEXT,
    lease_id     TEXT,
    attempts     INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    run_at       REAL    NOT NULL DEFAULT (unixepoch('now')),
    heartbeat_at REAL,
    created_at   REAL    NOT NULL DEFAULT (unixepoch('now')),
    updated_at   REAL    NOT NULL DEFAULT (unixepoch('now'))
);

CREATE TABLE IF NOT EXISTS job_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT    NOT NULL REFERENCES jobs(id),
    event_type TEXT    NOT NULL,
    worker_id  TEXT,
    lease_id   TEXT,
    payload    TEXT,
    created_at REAL    NOT NULL DEFAULT (unixepoch('now'))
);

CREATE TRIGGER IF NOT EXISTS job_events_no_update
BEFORE UPDATE ON job_events
BEGIN
    SELECT RAISE(ABORT, 'job_events rows are append-only and cannot be updated');
END;

CREATE TRIGGER IF NOT EXISTS job_events_no_delete
BEFORE DELETE ON job_events
BEGIN
    SELECT RAISE(ABORT, 'job_events rows are append-only and cannot be deleted');
END;
"""


def init_db(db_path: Optional[str] = None) -> None:
    """Create tables if they do not already exist."""
    conn = get_conn(db_path)
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        close_conn(conn)
