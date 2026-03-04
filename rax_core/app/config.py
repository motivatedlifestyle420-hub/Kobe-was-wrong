"""
rax_core configuration.
All tunables live here so every other module imports from one place.
"""
import os

# Path to the SQLite database file.  Override with RAX_DB_PATH env var.
DB_PATH: str = os.environ.get("RAX_DB_PATH", "rax_core.db")

# SQLite busy-timeout in milliseconds.  How long to wait for a locked DB.
DB_BUSY_TIMEOUT_MS: int = int(os.environ.get("RAX_DB_BUSY_TIMEOUT_MS", "5000"))

# Worker identity for this process (used for job ownership).
import socket
WORKER_ID: str = os.environ.get("RAX_WORKER_ID", socket.gethostname())

# How often (seconds) the runner renews its heartbeat while a job is active.
HEARTBEAT_INTERVAL: float = float(os.environ.get("RAX_HEARTBEAT_INTERVAL", "10"))

# A job whose heartbeat is older than this many seconds is considered stale.
HEARTBEAT_TIMEOUT: float = float(os.environ.get("RAX_HEARTBEAT_TIMEOUT", "60"))

# Maximum number of retry attempts before a job is moved to 'dead'.
MAX_ATTEMPTS: int = int(os.environ.get("RAX_MAX_ATTEMPTS", "3"))

# Exponential-backoff base (seconds).  Delay = min(base ** attempt, cap).
BACKOFF_BASE: float = float(os.environ.get("RAX_BACKOFF_BASE", "2"))
BACKOFF_CAP: float = float(os.environ.get("RAX_BACKOFF_CAP", "60"))
