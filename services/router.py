import json
import sqlite3
from typing import Callable, Dict

_HANDLERS: Dict[str, Callable] = {}


def register(job_type: str, handler: Callable) -> None:
    """Map a job type string to a handler callable."""
    _HANDLERS[job_type] = handler


def dispatch(conn: sqlite3.Connection, job: sqlite3.Row) -> None:
    """Look up the handler for job['type'] and call it."""
    handler = _HANDLERS.get(job["type"])
    if handler is None:
        raise ValueError(f"No handler registered for job type {job['type']!r}")
    handler(conn, job["id"], json.loads(job["payload"]))
