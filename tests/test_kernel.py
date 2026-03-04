from fastapi.testclient import TestClient

from services.app import app
from services.kernel import Kernel

client = TestClient(app)


# ── Kernel unit tests ────────────────────────────────────────────────────────

def test_register_and_list():
    k = Kernel()
    k.register("ping", lambda: "pong")
    assert k.task_names() == ["ping"]


def test_run_success():
    k = Kernel()
    k.register("add", lambda: 1 + 1)
    result = k.run("add")
    assert result.success is True
    assert result.output == 2
    assert result.error == ""


def test_run_unknown_task():
    k = Kernel()
    result = k.run("does_not_exist")
    assert result.success is False
    assert result.error == "unknown task: does_not_exist"


def test_run_failing_task():
    k = Kernel()
    k.register("boom", lambda: 1 / 0)
    result = k.run("boom")
    assert result.success is False
    assert result.error != ""


def test_run_all():
    k = Kernel()
    k.register("a", lambda: "A")
    k.register("b", lambda: "B")
    results = k.run_all()
    assert len(results) == 2
    assert all(r.success for r in results)


# ── HTTP health check ────────────────────────────────────────────────────────

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "running"}

