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
from app.config import DB_PATH, DB_BUSY_TIMEOUT_MS

_local = threading.local()


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
            attempts         INTEGER NOT NULL DEFAULT 0,
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
    """)
    c.commit()
