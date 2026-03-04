# rax_core — Deterministic SQLite Job Execution Kernel

A crash-safe, durable background job system backed by SQLite WAL.

## Architecture

| File | Responsibility |
|------|---------------|
| `app/config.py` | Reads config from environment variables at call time |
| `app/db.py` | Connection factory; applies mandatory PRAGMAs |
| `app/models.py` | DDL — jobs + job_events tables |
| `app/jobs.py` | Full job lifecycle (enqueue / claim / heartbeat / succeed / fail / requeue_stale) |
| `app/router.py` | Handler registry |
| `app/runner.py` | Worker daemon with concurrent heartbeating |
| `app/handlers/` | Job handlers (demo: no-op) |
| `app/main.py` | FastAPI HTTP API |

## Hard Constraints

### Job states
Only these five states are valid (enforced by `CHECK` constraint):
`pending` → `running` → `succeeded`  
`running` → `pending` (retryable failure)  
`running` → `dead` (attempts exhausted)

### Atomic claim
`claim_next()` uses a **single** `UPDATE … RETURNING` statement.  
No `SELECT`-then-`UPDATE` claim patterns.

### Ownership verification
Every mutation of a running job checks:
- `state = 'running'`
- `worker_id` matches
- `lease_id` matches
- `heartbeat_at >= now - HEARTBEAT_TIMEOUT`

### SQLite connection PRAGMAs
Every connection sets:
```sql
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
```

### Retry policy
- `attempts` increments on failure.
- `attempts >= max_attempts` → `state = 'dead'`.
- Otherwise → `state = 'pending'` with exponential backoff + full jitter on `run_at`.

### Observability
Every state transition appends a row to `job_events`.  
Events are never updated or deleted.

## Running

### Install dependencies
```bash
pip install -r rax_core/requirements.txt
```

### Start the API server
```bash
python -m rax_core.app.main
```

### Run tests
```bash
python -m pytest rax_core/tests/ -v
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RAX_DB_PATH` | `rax_core/data/rax_core.db` | SQLite database path |
| `RAX_API_KEY` | `dev-secret` | API authentication key |
| `RAX_HEARTBEAT_TIMEOUT` | `60` | Seconds before a job is stale |
| `RAX_POLL_INTERVAL` | `1.0` | Seconds between claim attempts |
