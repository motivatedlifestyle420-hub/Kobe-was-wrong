"""
SQLite connection factory.

Every connection applies the three mandatory PRAGMAs:
  - PRAGMA busy_timeout   — avoids "database is locked" errors under concurrency
  - PRAGMA foreign_keys   — enforces referential integrity
  - PRAGMA journal_mode   — WAL for concurrent read/write safety
"""
import sqlite3
from typing import Optional

from rax_core.app import config


def get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open and configure a SQLite connection."""
    path = db_path or config.get_db_path()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def close_conn(conn: sqlite3.Connection) -> None:
    """Close a connection, suppressing errors (used in finally blocks)."""
    try:
        conn.close()
    except Exception:
        pass
