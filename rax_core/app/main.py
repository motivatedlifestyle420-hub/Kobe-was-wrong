"""
FastAPI application for rax_core.

Endpoints:
  POST /jobs            — enqueue a job
  GET  /jobs            — list jobs (optional ?state= filter)
  GET  /jobs/{job_id}   — get a single job
  GET  /jobs/{job_id}/events — get audit events for a job

All endpoints require the X-Api-Key header.
"""
import threading
import uuid
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel

from rax_core.app import config
from rax_core.app.models import init_db
from rax_core.app import jobs as job_ops
from rax_core.app.runner import run_worker
from rax_core.app.handlers import demo  # noqa: F401  registers the demo handler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise DB and start background worker on startup."""
    init_db()
    worker_id = f"worker-{uuid.uuid4().hex[:8]}"
    t = threading.Thread(target=run_worker, kwargs={"worker_id": worker_id}, daemon=True)
    t.start()
    logger.info("Background worker %s started", worker_id)
    yield


app = FastAPI(title="rax_core", version="1.0.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _require_api_key(x_api_key: str = Header(...)) -> None:
    if x_api_key != config.get_api_key():
        raise HTTPException(status_code=401, detail="Invalid API key")


_auth = Depends(_require_api_key)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class EnqueueRequest(BaseModel):
    job_type: str
    payload: Dict[str, Any] = {}
    job_id: Optional[str] = None
    max_attempts: int = 3
    run_at: Optional[float] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/jobs", dependencies=[_auth], status_code=201)
def create_job(req: EnqueueRequest) -> Dict[str, str]:
    jid = job_ops.enqueue(
        job_type=req.job_type,
        payload=req.payload,
        job_id=req.job_id,
        max_attempts=req.max_attempts,
        run_at=req.run_at,
    )
    return {"job_id": jid}


@app.get("/jobs", dependencies=[_auth])
def list_jobs_endpoint(
    state: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    return job_ops.list_jobs(state=state, limit=limit)


@app.get("/jobs/{job_id}", dependencies=[_auth])
def get_job_endpoint(job_id: str) -> Dict[str, Any]:
    job = job_ops.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/jobs/{job_id}/events", dependencies=[_auth])
def get_job_events_endpoint(job_id: str) -> List[Dict[str, Any]]:
    if job_ops.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_ops.get_job_events(job_id)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
