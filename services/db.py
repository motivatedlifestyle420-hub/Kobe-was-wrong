import pathlib
import sqlite3

DB_PATH = pathlib.Path(__file__).parent.parent / "data" / "rax.db"


def connect() -> sqlite3.Connection:
    """Return a WAL-enabled SQLite connection with a Row factory."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn
