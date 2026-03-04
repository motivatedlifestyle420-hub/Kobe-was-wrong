"""FastAPI application — job engine API."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

import services.handlers  # noqa: F401 — registers all handlers
from services.db import get_conn
from services.jobs import enqueue, get_job, list_jobs
from services.models import init_db
from services.runner import Runner

_API_KEY = os.getenv("API_KEY", "dev-local-key")
if _API_KEY == "dev-local-key":
    import warnings
    warnings.warn(
        "API_KEY is not set — using insecure default 'dev-local-key'. "
        "Set API_KEY in your environment before exposing this service.",
        stacklevel=1,
    )


@asynccontextmanager
async def _lifespan(app: FastAPI):
    conn = get_conn()
    init_db(conn)
    conn.close()
    runner = Runner()
    runner.start()
    app.state.runner = runner
    yield
    runner.stop()


app = FastAPI(title="Automation Command Center", lifespan=_lifespan)


def _require_api_key(x_api_key: str = Header(...)) -> None:
    if x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ── public ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "running"}


# ── jobs ──────────────────────────────────────────────────────────────────────

class EnqueueRequest(BaseModel):
    job_type: str
    payload: dict = {}
    idempotency_key: str | None = None
    max_attempts: int = 3
    run_after: int = 0


@app.post("/jobs", dependencies=[Depends(_require_api_key)])
def create_job(req: EnqueueRequest):
    conn = get_conn()
    try:
        job_id = enqueue(
            conn,
            req.job_type,
            req.payload,
            req.idempotency_key,
            req.max_attempts,
            req.run_after,
        )
        return dict(get_job(conn, job_id))
    finally:
        conn.close()


@app.get("/jobs/{job_id}", dependencies=[Depends(_require_api_key)])
def job_status(job_id: int):
    conn = get_conn()
    try:
        job = get_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return dict(job)
    finally:
        conn.close()


@app.get("/jobs", dependencies=[Depends(_require_api_key)])
def list_jobs_endpoint(state: str | None = Query(None)):
    conn = get_conn()
    try:
        return {"jobs": [dict(r) for r in list_jobs(conn, state)]}
    finally:
        conn.close()


