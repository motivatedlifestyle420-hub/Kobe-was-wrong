"""
Configuration for rax_core.
All values are read from environment variables at call time so that tests
can override them by setting os.environ before importing any module.
"""
import os


def get_db_path() -> str:
    return os.environ.get("RAX_DB_PATH", "rax_core/data/rax_core.db")


def get_api_key() -> str:
    return os.environ.get("RAX_API_KEY", "dev-secret")


def get_heartbeat_timeout() -> int:
    """Seconds before a running job is considered stale."""
    return int(os.environ.get("RAX_HEARTBEAT_TIMEOUT", "60"))


def get_poll_interval() -> float:
    """Seconds between claim attempts in the worker loop."""
    return float(os.environ.get("RAX_POLL_INTERVAL", "1.0"))
