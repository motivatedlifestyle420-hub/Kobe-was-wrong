"""Database schema and initialisation.

Tables
------
jobs          – the work queue
job_events    – immutable audit log of every status transition
effect_ledger – idempotency layer 2: records a side-effect has been applied
"""
import sqlite3
from rax_core.app.db import get_conn, close_conn

DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT    PRIMARY KEY,
    job_type        TEXT    NOT NULL,
    payload         TEXT    NOT NULL DEFAULT '{}',
    idempotency_key TEXT    UNIQUE,
    status          TEXT    NOT NULL DEFAULT 'pending',
    priority        INTEGER NOT NULL DEFAULT 0,
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 5,
    worker_id       TEXT,
    lease_id        TEXT,
    heartbeat_at    REAL,
    run_after       REAL,
    created_at      REAL    NOT NULL,
    updated_at      REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS job_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT    NOT NULL,
    event       TEXT    NOT NULL,
    detail      TEXT,
    worker_id   TEXT,
    created_at  REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS effect_ledger (
    idempotency_key TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL,
    result          TEXT,
    created_at      REAL NOT NULL
);
"""


def init_db() -> None:
    """Create all tables (idempotent – safe to call on every startup)."""
    conn = get_conn()
    try:
        conn.executescript(DDL)
        conn.commit()
    finally:
        close_conn(conn)
