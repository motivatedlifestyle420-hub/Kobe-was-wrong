"""
Domain types for rax_core jobs.
"""
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Canonical job states — the only values the CHECK constraint allows.
# ---------------------------------------------------------------------------
PENDING = "pending"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
DEAD = "dead"

VALID_STATES = {PENDING, RUNNING, SUCCEEDED, FAILED, DEAD}


@dataclass
class Job:
    """In-memory representation of a jobs row."""
    id: int
    idempotency_key: str
    job_type: str
    payload: str                 # JSON string
    state: str
    attempts: int
    max_attempts: int
    worker_id: str | None
    heartbeat_at: float | None
    run_after: float
    created_at: float
    updated_at: float
    error: str | None = None

    @classmethod
    def from_row(cls, row: Any) -> "Job":
        return cls(
            id=row["id"],
            idempotency_key=row["idempotency_key"],
            job_type=row["job_type"],
            payload=row["payload"],
            state=row["state"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            worker_id=row["worker_id"],
            heartbeat_at=row["heartbeat_at"],
            run_after=row["run_after"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            error=row["error"],
        )

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "idempotency_key": self.idempotency_key,
            "job_type": self.job_type,
            "payload": self.payload,
            "state": self.state,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "worker_id": self.worker_id,
            "heartbeat_at": self.heartbeat_at,
            "run_after": self.run_after,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }
