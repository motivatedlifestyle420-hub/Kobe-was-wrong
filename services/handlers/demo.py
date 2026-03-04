import logging
import sqlite3

logger = logging.getLogger(__name__)


def handle(conn: sqlite3.Connection, job_id: str, payload: dict) -> None:
    """Proof-of-concept handler: logs that the named subject was wrong."""
    subject = payload.get("subject", "Kobe")
    logger.info("Job %s — %s was wrong. Proved.", job_id, subject)
    # The runner marks the job succeeded on successful return.
