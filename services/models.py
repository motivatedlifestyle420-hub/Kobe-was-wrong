import sqlite3

_CREATE_JOBS = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT    PRIMARY KEY,
    type        TEXT    NOT NULL,
    payload     TEXT    NOT NULL DEFAULT '{}',
    status      TEXT    NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','leased','succeeded','failed')),
    created_at  TEXT    NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    leased_at   TEXT,
    done_at     TEXT,
    worker_id   TEXT,
    retries     INTEGER NOT NULL DEFAULT 0,
    error       TEXT
)
"""


def migrate(conn: sqlite3.Connection) -> None:
    """Create schema if it does not already exist."""
    conn.execute(_CREATE_JOBS)
    conn.commit()
