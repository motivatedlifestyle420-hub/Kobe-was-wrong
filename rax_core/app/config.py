"""
Configuration for rax_core.
All values are read from environment variables at call time so that tests
can override them by setting os.environ before importing any module.
"""
import os


def get_db_path() -> str:
    return os.environ.get("RAX_DB_PATH", "rax_core/data/rax_core.db")


def get_api_key() -> str:
    try:
        return os.environ["RAX_API_KEY"]
    except KeyError:
        raise RuntimeError(
            "RAX_API_KEY environment variable must be set for API authentication"
        ) from None


def get_heartbeat_timeout() -> int:
    """Seconds before a running job is considered stale."""
    raw_value = os.environ.get("RAX_HEARTBEAT_TIMEOUT", "60")
    timeout = int(raw_value)
    if timeout <= 0:
        raise RuntimeError(
            "RAX_HEARTBEAT_TIMEOUT must be a positive integer number of seconds "
            f"(got {raw_value!r})"
        )
    return timeout


def get_poll_interval() -> float:
    """Seconds between claim attempts in the worker loop."""
    return float(os.environ.get("RAX_POLL_INTERVAL", "1.0"))
