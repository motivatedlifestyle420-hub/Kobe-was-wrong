import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .db import connect
from .models import migrate
from . import jobs as job_store
from . import runner
import services.handlers  # noqa: F401 – triggers handler registration

_INDEX_PATH = pathlib.Path(__file__).parent.parent / "index.html"
_INDEX_HTML = _INDEX_PATH.read_text(encoding="utf-8")

_runner_stop = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _runner_stop
    # Initialise schema with a short-lived connection, then start the runner
    # (which owns its own long-lived connection).
    with connect() as _init_conn:
        migrate(_init_conn)
    _runner_stop = runner.start(connect)
    yield
    _runner_stop.set()


app = FastAPI(lifespan=lifespan)


class EnqueueRequest(BaseModel):
    type: str
    payload: dict = {}


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def index():
    return _INDEX_HTML


@app.post("/jobs", status_code=201)
async def enqueue_job(req: EnqueueRequest):
    with connect() as conn:
        job_id = job_store.enqueue(conn, req.type, req.payload)
    return {"id": job_id}


@app.get("/jobs")
async def list_jobs():
    with connect() as conn:
        return [dict(r) for r in job_store.list_all(conn)]


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    with connect() as conn:
        row = job_store.get(conn, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    return dict(row)
