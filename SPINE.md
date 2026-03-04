# Spine

**Local-First Automation Kernel** — minimal surface area, maximum control.

---

## Hardware Requirement

| Component | Minimum                             | Recommended (shop server)        |
|-----------|-------------------------------------|----------------------------------|
| CPU       | Any modern 4-core (x86-64 / ARM64) | Intel N100/N305 mini-PC or equiv |
| RAM       | 8 GB                                | 16 GB                            |
| Storage   | SSD (any)                           | 512 GB NVMe                      |
| OS        | Linux (Ubuntu 22.04+) or macOS 13+ | Linux preferred                  |
| Python    | 3.11+                               | 3.11+                            |
| Network   | Local LAN only                      | Wired ethernet + UPS             |

> Hardware is not the constraint yet. Architecture is.

---

## Stack

| Layer        | Choice                    | Reason                                     |
|--------------|---------------------------|--------------------------------------------|
| Language     | Python 3.11+              | Fast iteration, rich ecosystem             |
| HTTP layer   | FastAPI + Uvicorn         | Lightweight, typed, async-ready            |
| Persistence  | SQLite (WAL mode)         | Zero-config, survives restarts, local-first|
| Job engine   | `services/jobs.py`        | State machine: pending→running→succeeded/failed/dead |
| Runner       | `services/runner.py`      | Daemon thread — isolated from API process  |
| Handler reg. | `services/router.py`      | Job-type → callable mapping                |
| Auth         | `X-API-Key` header        | Guards all job endpoints, even local       |
| Logging      | Loguru                    | Structured, one-line setup                 |
| Config       | python-dotenv             | `.env` file, no secrets in code            |
| Tests        | Pytest + HTTPX            | Fast, minimal                              |

---

## First Executable Milestone

```bash
API_KEY=dev-local-key uvicorn services.app:app --reload
```

| Method | Endpoint          | Auth | Purpose                          |
|--------|-------------------|------|----------------------------------|
| GET    | `/`               | none | Health check                     |
| POST   | `/jobs`           | yes  | Enqueue a job                    |
| GET    | `/jobs/{id}`      | yes  | Poll job state                   |
| GET    | `/jobs?state=...` | yes  | Filter jobs by state             |

**End-to-end proof:**
```
POST /jobs {"job_type":"noop"}  →  state: pending
  runner claims job             →  state: running
  handler returns               →  state: succeeded
GET /jobs/{id}                  →  {"state": "succeeded"}
```

---

## Build Plan

1. ✅ **Spine** — SQLite job table, state machine, daemon runner, job API, API-key auth
2. ☐ **First real automation** — health-check job (ping self, write result to DB)
3. ☐ **Scheduler** — `run_after` epoch + periodic enqueue loop
4. ☐ **Integrations** — plug external APIs in as handler modules
5. ☐ **Dashboard** — read-only status view (`dashboards/`)

> No step adds surface area beyond what the next milestone requires.

