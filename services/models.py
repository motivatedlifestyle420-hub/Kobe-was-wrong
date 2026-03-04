"""Jobs table DDL and state constants."""
from __future__ import annotations

import sqlite3

STATES = ("pending", "running", "succeeded", "failed", "dead")

_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT    UNIQUE,
    job_type        TEXT    NOT NULL,
    payload_json    TEXT    NOT NULL DEFAULT '{}',
    state           TEXT    NOT NULL DEFAULT 'pending'
                            CHECK(state IN ('pending','running','succeeded','failed','dead')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    run_after       INTEGER NOT NULL DEFAULT 0,
    worker_id       TEXT,
    heartbeat_at    INTEGER,
    last_error      TEXT    NOT NULL DEFAULT '',
    created_at      INTEGER NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER)),
    updated_at      INTEGER NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER))
);
"""


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)
    conn.commit()
