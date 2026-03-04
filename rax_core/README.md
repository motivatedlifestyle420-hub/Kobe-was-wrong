# rax_core – Local Automation Kernel

A durable, SQLite-backed job engine designed to be the kernel for automated
business operations – starting with safe, idempotent supplier ordering.

## Why a job engine?

Automated ordering is exactly the kind of work that needs:

| Requirement | How rax_core delivers it |
|---|---|
| **Retries** | Exponential back-off + jitter, configurable `max_attempts` |
| **Idempotency** | Layer 1: `idempotency_key` on enqueue (ON CONFLICT DO NOTHING) · Layer 2: `effect_ledger` prevents double side-effects on retry |
| **Audit trail** | `job_events` table logs every status transition |
| **Crash recovery** | Stale-lease requeue – any job whose heartbeat expires is re-claimed |
| **No double-run** | Atomic `UPDATE … RETURNING` claim; `lease_id` verified on every mutation |
| **Observable** | REST API to list jobs, inspect events, check job types |

---

## Package layout

```
rax_core/
├── app/
│   ├── config.py          # env-var settings
│   ├── db.py              # SQLite WAL connection helper
│   ├── models.py          # DDL: jobs / job_events / effect_ledger
│   ├── jobs.py            # enqueue / claim / succeed / fail / heartbeat / effect ledger
│   ├── runner.py          # daemon worker thread
│   ├── router.py          # job-type handler registry
│   ├── main.py            # FastAPI application
│   └── handlers/
│       ├── demo.py        # no-op demo handler
│       └── supplier.py    # six-stage Bidfood ordering pipeline
├── tests/
│   ├── conftest.py
│   ├── test_jobs.py
│   └── test_supplier.py
├── data/                  # SQLite database (gitignored)
└── requirements.txt
```

---

## Quick start

```bash
pip install -r rax_core/requirements.txt

# Run the API server
python -m rax_core.app.main

# Run tests
python -m pytest rax_core/tests/ -v
```

---

## Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `RAX_DB_PATH` | `rax_core/data/rax_core.db` | SQLite file path |
| `RAX_API_KEY` | `dev-secret` | HTTP API key (X-Api-Key header) |
| `RAX_POLL_INTERVAL` | `2` | Seconds between queue polls |
| `RAX_LEASE_SECONDS` | `30` | Stale-job timeout |
| `LOW_STOCK_THRESHOLD` | `5` | Units-on-hand trigger for reorder |
| `SMTP_HOST` | `localhost` | SMTP server for email orders |
| `SMTP_PORT` | `25` | SMTP port |
| `SMTP_USER` / `SMTP_PASS` | _(blank)_ | SMTP auth (optional) |
| `SMTP_FROM` | `orders@yourbusiness.com` | Sender address |
| `BIDFOOD_ORDER_EMAIL` | `orders@bidfood.co.uk` | Bidfood depot email |
| `BIDFOOD_API_URL` | _(blank)_ | Managed connector base URL (see below) |
| `BIDFOOD_API_KEY` | _(blank)_ | Managed connector API key |
| `IMAP_HOST` / `IMAP_USER` / `IMAP_PASS` | _(blank)_ | IMAP for order confirmations |

---

## Bidfood / Bidvest integration

Bidfood **does not publish a self-serve public REST API**.  
Integration options in priority order:

### 1. Managed connector (set `BIDFOOD_API_URL`)

| Provider | What it does |
|---|---|
| [Crossfire EDI-as-API](https://crossfireintegration.com/) | Fully managed EDI/API bridge; handles PO, invoice, credit-note |
| [Buy Force Live](https://www.tbfg.com.au/integration/bidfood/) | Direct API to Bidfood E-360 ERP (AU); live pricing + stock |
| [Apicbase](https://get.apicbase.com/integrations/bidfood-nl/) | Bidfood NL ordering + price sync |

Set `BIDFOOD_API_URL` to the connector's base URL.  
`supplier.place_order` will `POST /orders` with `X-Api-Key: $BIDFOOD_API_KEY`.

### 2. Email ordering (default)

Set `SMTP_*` vars.  Orders are sent as plain-text emails to `BIDFOOD_ORDER_EMAIL`.  
Confirmations are polled via IMAP (`IMAP_*` vars).  
When `IMAP_HOST` is blank, `supplier.confirm_order` runs in **stub mode**
(always confirmed) – useful for local dev.

### 3. EDI (EDIFACT ORDERS / AS2 or X12 850)

For large-volume partners: register at  
https://www.bidfoodsuppliers.co.uk/ to obtain EDI specs and depot AS2 endpoints.

---

## Supplier ordering pipeline

Six job types form a safe, observable, retryable pipeline:

```
supplier.parse_invoice
        ↓
supplier.detect_low_stock
        ↓
supplier.build_order_draft
        ↓
supplier.place_order        ← idempotent via effect_ledger
        ↓
supplier.confirm_order
        ↓
supplier.notify
```

### Enqueue example (idempotent key = one order per supplier per day)

```python
from rax_core.app import jobs
import time

jobs.enqueue(
    "supplier.detect_low_stock",
    payload={
        "inventory": [
            {"sku": "BF-001", "on_hand": 3, "reorder_qty": 10},
            {"sku": "BF-002", "on_hand": 50, "reorder_qty": 5},
        ]
    },
    idempotency_key=f"order:bidfood:{time.strftime('%Y-%m-%d')}",
)
```

### REST API

```bash
# Enqueue a job
curl -X POST http://localhost:8000/jobs \
  -H "X-Api-Key: dev-secret" \
  -H "Content-Type: application/json" \
  -d '{"job_type":"supplier.detect_low_stock","payload":{"inventory":[]},"idempotency_key":"order:bidfood:2026-03-05"}'

# List all pending jobs
curl http://localhost:8000/jobs?status=pending -H "X-Api-Key: dev-secret"

# Inspect a job's event log
curl http://localhost:8000/jobs/<job_id>/events -H "X-Api-Key: dev-secret"
```

---

## Database schema

```sql
-- Work queue
jobs (id, job_type, payload, idempotency_key UNIQUE,
      status, priority, attempts, max_attempts,
      worker_id, lease_id, heartbeat_at, run_after,
      created_at, updated_at)

-- Immutable audit log
job_events (id, job_id, event, detail, worker_id, created_at)

-- Idempotency layer 2 – "this side-effect was applied"
effect_ledger (idempotency_key PRIMARY KEY, job_id, result, created_at)
```
