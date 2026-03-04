# Spine

**Local-First Automation Kernel** — minimal surface area, maximum control.

---

## Hardware Requirement

| Component | Minimum                                          |
|-----------|--------------------------------------------------|
| CPU       | x86-64 or ARM64 (Raspberry Pi 4 class or better) |
| RAM       | 2 GB                                             |
| Storage   | 8 GB                                             |
| OS        | Linux (Ubuntu 22.04+) or macOS 13+               |
| Python    | 3.11+                                            |
| Network   | Local LAN only — no cloud dependency required    |

---

## Stack

| Layer       | Choice                  | Reason                                    |
|-------------|-------------------------|-------------------------------------------|
| Language    | Python 3.11+            | Fast iteration, rich ecosystem            |
| HTTP layer  | FastAPI + Uvicorn       | Lightweight, typed, async-ready           |
| Task kernel | `services/kernel.py`   | Custom — zero external deps, full control |
| Logging     | Loguru                  | Structured, one-line setup                |
| Config      | python-dotenv           | `.env` file, no secrets in code           |
| HTTP client | Requests                | Simple, reliable                          |
| Tests       | Pytest + HTTPX          | Fast, minimal                             |

---

## First Executable Milestone

```bash
uvicorn services.app:app --reload
```

| Endpoint                        | Expected response                        |
|---------------------------------|------------------------------------------|
| `GET /`                         | `{"status": "running"}`                  |
| `GET /kernel/tasks`             | `{"tasks": [...]}`                       |
| `POST /kernel/run/{task_name}`  | `{"task_name": ..., "success": ..., ...}`|

---

## Build Plan

1. ✅ **Spine** — task registry + synchronous runner (`services/kernel.py`)
2. ☐ **First automation** — health-check task (ping self, log result)
3. ☐ **Scheduler** — periodic task loop (`services/scheduler.py`)
4. ☐ **Integrations** — plug external APIs into task registry
5. ☐ **Dashboard** — read-only status view (`dashboards/`)

> No step adds surface area beyond what the next milestone requires.
