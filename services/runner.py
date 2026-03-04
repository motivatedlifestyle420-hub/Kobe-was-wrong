import logging
import threading
from typing import Callable

from . import jobs as job_store
from .router import dispatch

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 1.0  # seconds between empty-queue polls


def _loop(connect: Callable, stop: threading.Event) -> None:
    conn = connect()
    worker_id = f"worker-{threading.get_ident()}"
    try:
        while not stop.is_set():
            job = job_store.dequeue(conn, worker_id)
            if job is None:
                stop.wait(_POLL_INTERVAL)
                continue
            try:
                dispatch(conn, job)
                if not job_store.complete(conn, job["id"], worker_id):
                    logger.warning("Job %s: lost ownership, skipping complete", job["id"])
            except Exception as exc:
                logger.exception("Job %s failed: %s", job["id"], exc)
                if not job_store.fail(conn, job["id"], str(exc), worker_id):
                    logger.warning("Job %s: lost ownership, skipping fail", job["id"])
    finally:
        conn.close()


def start(connect: Callable) -> threading.Event:
    """Spawn a daemon worker thread; returns the stop Event."""
    stop = threading.Event()
    threading.Thread(
        target=_loop,
        args=(connect, stop),
        daemon=True,
        name="rax-runner",
    ).start()
    return stop
