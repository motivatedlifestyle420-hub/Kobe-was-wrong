"""Background worker daemon.

Spawns a single daemon thread that polls the job queue, executes handlers,
and manages heartbeats, retries, and dead-lettering.
"""
import logging
import threading
import time
import traceback
import uuid
from typing import Optional

from rax_core.app import config, jobs
from rax_core.app.router import registry

logger = logging.getLogger(__name__)

_worker_id: str = str(uuid.uuid4())
_stop_event: threading.Event = threading.Event()
_thread: Optional[threading.Thread] = None


def _run_job(job: dict) -> None:
    job_id = job["id"]
    job_type = job["job_type"]
    worker_id = job["worker_id"]
    lease_id = job["lease_id"]

    handler = registry.get(job_type)
    if handler is None:
        jobs.fail(
            job_id,
            worker_id,
            lease_id,
            error=f"no handler registered for job_type={job_type!r}",
        )
        logger.warning("No handler for job_type=%r  job_id=%s", job_type, job_id)
        return

    # Heartbeat thread: keeps the lease alive while the handler runs.
    stop_hb = threading.Event()

    def _heartbeat_loop():
        while not stop_hb.wait(config.WORKER_HEARTBEAT_INTERVAL):
            jobs.heartbeat(job_id, worker_id, lease_id)

    hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    hb_thread.start()

    try:
        result = handler(job)
        jobs.succeed(job_id, worker_id, lease_id, result=result)
        logger.info("Job succeeded job_id=%s type=%s", job_id, job_type)
    except Exception as exc:
        error = traceback.format_exc()
        jobs.fail(job_id, worker_id, lease_id, error=error)
        logger.error(
            "Job failed job_id=%s type=%s error=%s", job_id, job_type, exc
        )
    finally:
        stop_hb.set()


def _worker_loop() -> None:
    logger.info("Worker started  worker_id=%s", _worker_id)
    while not _stop_event.is_set():
        try:
            job = jobs.claim(_worker_id)
            if job:
                _run_job(job)
            else:
                time.sleep(config.WORKER_POLL_INTERVAL)
        except Exception:
            logger.exception("Unexpected error in worker loop")
            time.sleep(config.WORKER_POLL_INTERVAL)
    logger.info("Worker stopped  worker_id=%s", _worker_id)


def start() -> None:
    """Start the background worker thread (idempotent)."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_worker_loop, daemon=True, name="rax-worker")
    _thread.start()


def stop() -> None:
    """Signal the worker thread to stop and wait for it."""
    _stop_event.set()
    if _thread:
        _thread.join(timeout=10)
