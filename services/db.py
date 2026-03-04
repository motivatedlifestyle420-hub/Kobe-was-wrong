"""SQLite connection factory — WAL mode, one connection per caller."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def get_conn() -> sqlite3.Connection:
    db_path = Path(os.getenv("DB_PATH", "data/rax.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn
