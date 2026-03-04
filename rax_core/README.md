# rax_core — Local Automation Kernel

A minimal, hardened job-execution engine built on SQLite.
Everything becomes a **job type** inside this kernel.

---

## Philosophy

> Without deterministic execution, replay safety, state integrity, crash
> recovery, and observability — your automation is decorative.

`rax_core` provides the foundation that every other subsystem depends on.
Features (email scanning, supplier alerts, roster imports, etc.) are added
*after* this kernel passes stress tests.

---

## Directory layout

```
rax_core/
├── app/
│   ├── config.py    — all tunables (env-var overrides)
│   ├── db.py        — SQLite bootstrap (WAL, FK, busy_timeout)
│   ├── models.py    — Job dataclass + canonical state constants
│   ├── jobs.py      — persistence layer (enqueue, claim, succeed, fail, …)
│   ├── runner.py    — executor with heartbeat + exponential-backoff retry
│   ├── router.py    — HTTP API (stdlib only, no framework)
│   └── main.py      — entry point (server + runner together)
├── tests/
│   └── test_jobs.py — state-machine unit tests
├── requirements.txt
└── README.md
```

---

## Canonical job states

| State       | Meaning                         |
|-------------|---------------------------------|
| `pending`   | queued, waiting to be claimed   |
| `running`   | actively executing              |
| `succeeded` | finished successfully           |
| `failed`    | execution error, will be retried |
| `dead`      | exceeded max retry attempts     |

Enforced by a SQLite `CHECK` constraint — no other states are possible.

---

## Non-negotiable hardening

Every SQLite connection applies these on open:

```sql
PRAGMA busy_timeout = 5000;   -- wait up to 5 s on a locked DB
PRAGMA foreign_keys = ON;     -- referential integrity
PRAGMA journal_mode = WAL;    -- concurrent reads during writes
```

Additional guarantees:

- **Idempotency key** — `UNIQUE` constraint prevents duplicate job insertion.
- **Heartbeat renewal** — runner thread renews `heartbeat_at` every 10 s
  while a job is active.
- **Ownership verification** — `worker_id` is checked before any state
  transition; another process cannot steal or double-complete a job.
- **Stale-job recovery** — `requeue_stale()` resets orphaned `running` jobs
  whose heartbeat has expired, so they can be reclaimed after a crash.
- **Exponential backoff** — retry delay = `min(2 ** attempts, 60)` seconds.
- **Dead-letter** — after `MAX_ATTEMPTS` failures the job becomes `dead`
  instead of looping forever.

---

## Quick start

```bash
cd rax_core
pip install -r requirements.txt

# Run the API server + background runner (default port 8080):
python -m app.main

# Enqueue a job:
curl -s -X POST http://localhost:8080/jobs \
  -H 'Content-Type: application/json' \
  -d '{"idempotency_key":"job-001","job_type":"noop","payload":{}}'

# List all jobs:
curl -s http://localhost:8080/jobs | python -m json.tool

# Filter by state:
curl -s "http://localhost:8080/jobs?state=pending"
```

---

## Configuration (env vars)

| Variable                  | Default        | Description                              |
|---------------------------|----------------|------------------------------------------|
| `RAX_DB_PATH`             | `rax_core.db`  | SQLite file path                         |
| `RAX_DB_BUSY_TIMEOUT_MS`  | `5000`         | SQLite busy-timeout (ms)                 |
| `RAX_WORKER_ID`           | hostname       | Identity of this worker process          |
| `RAX_HEARTBEAT_INTERVAL`  | `10`           | Seconds between heartbeat renewals       |
| `RAX_HEARTBEAT_TIMEOUT`   | `60`           | Seconds before a running job is stale    |
| `RAX_MAX_ATTEMPTS`        | `3`            | Max retries before moving to `dead`      |
| `RAX_BACKOFF_BASE`        | `2`            | Exponential-backoff base (seconds)       |
| `RAX_BACKOFF_CAP`         | `60`           | Maximum backoff delay (seconds)          |
| `RAX_PORT`                | `8080`         | HTTP server port                         |

---

## Adding a job handler

```python
from app.runner import Runner

runner = Runner()

@runner.register("send_email")
def handle_send_email(payload: dict) -> None:
    # payload is already a Python dict
    print(f"Sending email to {payload['to']}")

runner.start()   # blocks; use block=False for background thread
```

---

## Running tests

```bash
cd rax_core
python -m pytest tests/ -v
```
