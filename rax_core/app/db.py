"""
Database bootstrap for rax_core.

Every connection returned by get_conn() has:
  - PRAGMA foreign_keys = ON
  - PRAGMA journal_mode = WAL
  - PRAGMA busy_timeout = <configured ms>
  - Row factory set to sqlite3.Row for dict-like access
"""
import sqlite3
import threading
import time
import logging
from .config import DB_PATH, DB_BUSY_TIMEOUT_MS

_local = threading.local()
_log = logging.getLogger(__name__)


def get_conn() -> sqlite3.Connection:
    """Return a per-thread SQLite connection, creating it if needed."""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _apply_pragmas(conn)
        _local.conn = conn
    return _local.conn


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute(f"PRAGMA busy_timeout = {DB_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.commit()


def init_db(conn: sqlite3.Connection | None = None) -> None:
    """Create tables if they do not exist."""
    c = conn or get_conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key  TEXT    UNIQUE NOT NULL,
            job_type         TEXT    NOT NULL,
            payload          TEXT    NOT NULL DEFAULT '{}',
            state            TEXT    NOT NULL DEFAULT 'pending'
                             CHECK(state IN ('pending','running','succeeded','failed','dead')),
            attempts         INTEGER NOT NULL DEFAULT 0
                             CHECK(attempts >= 0),
            max_attempts     INTEGER NOT NULL DEFAULT 3,
            worker_id        TEXT,
            heartbeat_at     REAL,
            run_after        REAL    NOT NULL DEFAULT 0,
            created_at       REAL    NOT NULL,
            updated_at       REAL    NOT NULL,
            error            TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_state_run_after
            ON jobs (state, run_after);

        CREATE TABLE IF NOT EXISTS job_events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id     INTEGER NOT NULL REFERENCES jobs(id),
            event      TEXT    NOT NULL,
            worker_id  TEXT,
            message    TEXT,
            created_at REAL    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_job_events_job_id
            ON job_events (job_id);
    """)
    c.commit()


def close_conn() -> None:
    """Close and discard the per-thread connection (if one is open).

    Call this in a finally block when a worker thread exits so SQLite
    file handles are released promptly instead of waiting for GC.
    """
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None


def log_event(
    job_id: int,
    event: str,
    worker_id: str | None = None,
    message: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Append an event to job_events.  Fire-and-forget — never raises."""
    try:
        c = conn or get_conn()
        c.execute(
            """
            INSERT INTO job_events (job_id, event, worker_id, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, event, worker_id, message, time.time()),
        )
        c.commit()
    except Exception:
        _log.debug("log_event failed silently", exc_info=True)
