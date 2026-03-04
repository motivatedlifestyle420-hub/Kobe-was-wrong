"""FastAPI application – rax_core Local Automation Kernel."""
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from rax_core.app import config, jobs
from rax_core.app.handlers.demo import register as register_demo
from rax_core.app.handlers.supplier import register as register_supplier
from rax_core.app.models import init_db
from rax_core.app.router import registry
from rax_core.app import runner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=True)


def _require_api_key(key: str = Depends(_api_key_header)) -> str:
    if key != config.API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")
    return key


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    register_demo()
    register_supplier()
    runner.start()
    logger.info("rax_core started  registered_types=%s", registry.job_types())
    yield
    runner.stop()
    logger.info("rax_core stopped")


app = FastAPI(title="rax_core", description="Local Automation Kernel", lifespan=_lifespan)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class EnqueueRequest(BaseModel):
    job_type: str
    payload: dict = {}
    idempotency_key: Optional[str] = None
    priority: int = 0
    max_attempts: int = 5
    run_after: Optional[float] = None


class EnqueueResponse(BaseModel):
    job_id: Optional[str]
    deduplicated: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/jobs", response_model=EnqueueResponse, dependencies=[Depends(_require_api_key)])
def enqueue_job(req: EnqueueRequest):
    job_id = jobs.enqueue(
        req.job_type,
        req.payload,
        idempotency_key=req.idempotency_key,
        priority=req.priority,
        max_attempts=req.max_attempts,
        run_after=req.run_after,
    )
    return EnqueueResponse(job_id=job_id, deduplicated=job_id is None)


@app.get("/jobs", dependencies=[Depends(_require_api_key)])
def list_jobs_route(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
):
    return jobs.list_jobs(status=status, limit=limit)


@app.get("/jobs/{job_id}", dependencies=[Depends(_require_api_key)])
def get_job_route(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/jobs/{job_id}/events", dependencies=[Depends(_require_api_key)])
def get_job_events(job_id: str):
    return jobs.list_events(job_id)


@app.get("/job-types", dependencies=[Depends(_require_api_key)])
def list_job_types():
    return {"job_types": registry.job_types()}
