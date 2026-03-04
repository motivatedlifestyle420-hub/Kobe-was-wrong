"""
Job runner for rax_core.

The Runner:
  1. Polls for pending jobs via jobs.claim().
  2. Executes the registered handler in a dedicated thread.
  3. Runs a heartbeat thread that renews heartbeat_at every
     HEARTBEAT_INTERVAL seconds while the job is active.
  4. On success  → jobs.succeed()
  5. On failure  → jobs.fail()  (exponential backoff + dead after max_attempts)
  6. Periodically calls jobs.requeue_stale() to recover crashed-worker orphans.

Usage
-----
    from app.runner import Runner

    runner = Runner()

    @runner.register("send_email")
    def handle_send_email(payload: dict) -> None:
        ...

    runner.start()   # blocks; use runner.start(block=False) for background
"""
import json
import logging
import threading
import time
from typing import Callable

from app import jobs as job_store
from app.config import HEARTBEAT_INTERVAL
from app.db import get_conn, init_db

logger = logging.getLogger(__name__)

# How long to sleep between poll cycles when the queue is empty (seconds).
_POLL_INTERVAL = 1.0
# How often to check for stale (orphaned) running jobs (seconds).
_STALE_CHECK_INTERVAL = 30.0
# Extra seconds to wait for the heartbeat thread to exit after a job finishes.
_HEARTBEAT_JOIN_GRACE = 2.0


class Runner:
    """Single-process job runner with heartbeat and retry support."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[dict], None]] = {}
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, job_type: str) -> Callable:
        """Decorator: register a handler function for a job type."""
        def decorator(fn: Callable[[dict], None]) -> Callable:
            self._handlers[job_type] = fn
            return fn
        return decorator

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, block: bool = True) -> None:
        """Start the runner.  Pass block=False to run in a background thread."""
        init_db()
        if block:
            self._run_loop()
        else:
            t = threading.Thread(target=self._run_loop, daemon=True)
            t.start()

    def stop(self) -> None:
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        last_stale_check = 0.0
        while not self._stop_event.is_set():
            now = time.time()
            if now - last_stale_check >= _STALE_CHECK_INTERVAL:
                recovered = job_store.requeue_stale()
                if recovered:
                    logger.info("Requeued %d stale job(s)", recovered)
                last_stale_check = now

            job = job_store.claim()
            if job is None:
                time.sleep(_POLL_INTERVAL)
                continue

            handler = self._handlers.get(job.job_type)
            if handler is None:
                logger.error("No handler for job_type=%r (id=%d)", job.job_type, job.id)
                job_store.fail(job.id, error=f"no handler for job_type={job.job_type!r}")
                continue

            self._execute(job, handler)

    def _execute(self, job, handler: Callable[[dict], None]) -> None:
        stop_heartbeat = threading.Event()
        hb_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(job.id, stop_heartbeat),
            daemon=True,
        )
        hb_thread.start()
        try:
            payload = json.loads(job.payload)
            handler(payload)
            job_store.succeed(job.id)
            logger.info("Job %d succeeded (type=%s)", job.id, job.job_type)
        except Exception as exc:
            logger.exception("Job %d failed (type=%s): %s", job.id, job.job_type, exc)
            job_store.fail(job.id, error=str(exc))
        finally:
            stop_heartbeat.set()
            hb_thread.join(timeout=HEARTBEAT_INTERVAL + _HEARTBEAT_JOIN_GRACE)

    def _heartbeat_loop(self, job_id: int, stop: threading.Event) -> None:
        while not stop.wait(timeout=HEARTBEAT_INTERVAL):
            renewed = job_store.heartbeat(job_id)
            if not renewed:
                logger.warning("Heartbeat failed for job %d — may have been reclaimed", job_id)
                break
