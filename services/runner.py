"""Background runner — daemon thread that claims and executes jobs."""
from __future__ import annotations

import json
import threading
import uuid

from loguru import logger

POLL_INTERVAL = 1.0  # seconds between polls when queue is empty


class Runner(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True, name="rax-runner")
        self._worker_id = str(uuid.uuid4())
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        from services.db import get_conn
        from services.jobs import claim_next, fail, succeed
        from services.router import get as get_handler

        conn = get_conn()
        logger.info(f"[runner] started worker_id={self._worker_id}")

        while not self._stop.is_set():
            job = claim_next(conn, self._worker_id)
            if job is None:
                self._stop.wait(POLL_INTERVAL)
                continue

            job_id = job["id"]
            job_type = job["job_type"]
            payload = json.loads(job["payload_json"])
            handler = get_handler(job_type)

            if handler is None:
                fail(conn, job_id, f"no handler for job_type: {job_type}")
                logger.warning(f"[runner] no handler for {job_type}, job {job_id} -> failed")
                continue

            logger.info(f"[runner] executing job {job_id} type={job_type}")
            try:
                handler(payload)
                succeed(conn, job_id)
                logger.success(f"[runner] job {job_id} -> succeeded")
            except Exception as exc:  # noqa: BLE001
                fail(conn, job_id, str(exc))
                logger.error(f"[runner] job {job_id} -> failed: {exc}")

        conn.close()
        logger.info("[runner] stopped")
