"""
Worker runner for rax_core.

Each worker:
  1. Calls requeue_stale() to recover crashed peers.
  2. Calls claim_next() — a single atomic UPDATE … RETURNING.
  3. While processing, sends heartbeats from a background thread so the
     ownership lease stays fresh.
  4. On completion calls succeed() or fail() with full ownership verification.
"""
import json
import logging
import threading
import time
import uuid
from typing import Optional

from rax_core.app import config, jobs
from rax_core.app.router import get_handler

logger = logging.getLogger(__name__)


def _heartbeat_loop(
    job_id: str,
    worker_id: str,
    lease_id: str,
    stop_event: threading.Event,
    db_path: Optional[str],
) -> None:
    """Send periodic heartbeats until stop_event is set."""
    interval = config.get_heartbeat_timeout() / 3
    while not stop_event.wait(interval):
        ok = jobs.heartbeat(job_id, worker_id, lease_id, db_path=db_path)
        if not ok:
            logger.warning(
                "Heartbeat rejected for job=%s (lease expired or job gone)", job_id
            )
            break


def _process_job(job: dict, worker_id: str, db_path: Optional[str]) -> None:
    """Process a single claimed job with concurrent heartbeating."""
    job_id = job["id"]
    lease_id = job["lease_id"]

    stop_event = threading.Event()
    hb_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(job_id, worker_id, lease_id, stop_event, db_path),
        daemon=True,
    )
    hb_thread.start()

    try:
        handler = get_handler(job["job_type"])
        payload = json.loads(job["payload"])
        result = handler(payload)

        stop_event.set()
        hb_thread.join(timeout=5)

        ok = jobs.succeed(job_id, worker_id, lease_id, result=result, db_path=db_path)
        if not ok:
            logger.error(
                "succeed() rejected for job=%s — lease may have expired during processing",
                job_id,
            )
    except Exception as exc:
        stop_event.set()
        hb_thread.join(timeout=5)

        ok = jobs.fail(job_id, worker_id, lease_id, error=str(exc), db_path=db_path)
        if not ok:
            logger.error(
                "fail() rejected for job=%s — lease may have expired during processing",
                job_id,
            )


def run_worker(
    worker_id: Optional[str] = None,
    db_path: Optional[str] = None,
    poll_interval: Optional[float] = None,
) -> None:
    """
    Main worker loop.  Runs indefinitely (call from a daemon thread).

    Parameters
    ----------
    worker_id:     Stable identifier for this worker instance.
    db_path:       Path to the SQLite database file (default: config value).
    poll_interval: Seconds to sleep when no pending job is found.
    """
    wid = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
    interval = poll_interval if poll_interval is not None else config.get_poll_interval()

    logger.info("Worker %s starting", wid)

    while True:
        try:
            jobs.requeue_stale(db_path=db_path)
            job = jobs.claim_next(wid, db_path=db_path)
            if job is None:
                time.sleep(interval)
                continue
            logger.info("Worker %s claimed job=%s type=%s", wid, job["id"], job["job_type"])
            _process_job(job, wid, db_path)
        except Exception:
            logger.exception("Worker %s encountered an unhandled error", wid)
            time.sleep(interval)
