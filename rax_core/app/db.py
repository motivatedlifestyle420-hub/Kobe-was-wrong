"""SQLite connection helper.

Every connection is opened with:
  - check_same_thread=False   (safe because we use WAL + busy_timeout)
  - PRAGMA journal_mode=WAL   (concurrent readers + one writer)
  - PRAGMA busy_timeout=5000  (wait up to 5 s on lock contention)
  - PRAGMA foreign_keys=ON
"""
import sqlite3
from rax_core.app import config


def get_conn() -> sqlite3.Connection:
    """Return a new SQLite connection configured for WAL mode."""
    db_path = config.DB_PATH
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def close_conn(conn: sqlite3.Connection) -> None:
    """Close a connection, swallowing errors (idempotent)."""
    try:
        conn.close()
    except Exception:
        pass
