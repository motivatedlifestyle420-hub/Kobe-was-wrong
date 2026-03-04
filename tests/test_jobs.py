"""Integration tests for the job engine: enqueue → pending → succeeded."""
from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from services.app import app

_AUTH = {"x-api-key": os.environ["API_KEY"]}
_BAD_AUTH = {"x-api-key": "wrong"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_root_no_auth(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {"status": "running"}


def test_auth_missing(client):
    r = client.get("/jobs")
    assert r.status_code == 422  # missing required header


def test_auth_wrong_key(client):
    r = client.get("/jobs", headers=_BAD_AUTH)
    assert r.status_code == 401


def test_enqueue_noop(client):
    r = client.post("/jobs", json={"job_type": "noop"}, headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["job_type"] == "noop"
    assert body["state"] == "pending"
    assert body["id"] > 0


def test_job_status(client):
    r = client.post("/jobs", json={"job_type": "noop"}, headers=_AUTH)
    job_id = r.json()["id"]

    r2 = client.get(f"/jobs/{job_id}", headers=_AUTH)
    assert r2.status_code == 200
    assert r2.json()["id"] == job_id


def test_job_not_found(client):
    r = client.get("/jobs/99999", headers=_AUTH)
    assert r.status_code == 404


def test_list_jobs(client):
    r = client.get("/jobs", headers=_AUTH)
    assert r.status_code == 200
    assert "jobs" in r.json()


def test_list_jobs_by_state(client):
    r = client.get("/jobs?state=pending", headers=_AUTH)
    assert r.status_code == 200
    jobs = r.json()["jobs"]
    assert all(j["state"] == "pending" for j in jobs)


def test_idempotency(client):
    r1 = client.post(
        "/jobs",
        json={"job_type": "noop", "idempotency_key": "unique-abc"},
        headers=_AUTH,
    )
    r2 = client.post(
        "/jobs",
        json={"job_type": "noop", "idempotency_key": "unique-abc"},
        headers=_AUTH,
    )
    assert r1.json()["id"] == r2.json()["id"]


def test_full_lifecycle(client):
    """Enqueue a noop job and wait for the runner to complete it."""
    r = client.post("/jobs", json={"job_type": "noop"}, headers=_AUTH)
    assert r.status_code == 200
    job_id = r.json()["id"]

    # Runner polls every 1 s — wait up to 5 s for completion
    deadline = time.time() + 5.0
    state = "pending"
    while time.time() < deadline:
        r2 = client.get(f"/jobs/{job_id}", headers=_AUTH)
        state = r2.json()["state"]
        if state == "succeeded":
            break
        time.sleep(0.2)

    assert state == "succeeded", f"job {job_id} still in state '{state}' after 5 seconds"

