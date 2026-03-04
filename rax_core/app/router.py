"""
REST API router for rax_core.

Endpoints
---------
POST   /jobs                 Enqueue a new job
GET    /jobs                 List jobs (optional ?state= filter)
GET    /jobs/{job_id}        Get a single job
POST   /jobs/{job_id}/claim  Manually claim a job (for testing / external runners)

All responses are JSON.
"""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from . import jobs as job_store
from .db import init_db


def _json_response(handler: BaseHTTPRequestHandler, status: int, body: object) -> None:
    payload = json.dumps(body).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length)
    return json.loads(raw) if raw else {}


class RaxRequestHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler wired to the jobs layer."""

    def log_message(self, fmt, *args):  # suppress default access log noise
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]

        if parts == ["jobs"]:
            qs = parse_qs(parsed.query)
            state = qs.get("state", [None])[0]
            jobs = job_store.list_jobs(state=state)
            _json_response(self, 200, [j.as_dict() for j in jobs])

        elif len(parts) == 2 and parts[0] == "jobs" and parts[1].isdigit():
            job = job_store.get(int(parts[1]))
            if job:
                _json_response(self, 200, job.as_dict())
            else:
                _json_response(self, 404, {"error": "not found"})

        else:
            _json_response(self, 404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]

        if parts == ["jobs"]:
            body = _read_json(self)
            required = {"idempotency_key", "job_type", "payload"}
            missing = required - body.keys()
            if missing:
                _json_response(self, 400, {"error": f"missing fields: {missing}"})
                return
            job = job_store.enqueue(
                job_type=body["job_type"],
                payload=body["payload"],
                idempotency_key=body["idempotency_key"],
                max_attempts=body.get("max_attempts", 3),
            )
            _json_response(self, 200, job.as_dict() if job else {})

        else:
            _json_response(self, 404, {"error": "not found"})


def make_app():
    """Return the request handler class (used by main.py)."""
    init_db()
    return RaxRequestHandler
