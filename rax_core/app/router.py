"""
Handler registry for rax_core.

Usage:
    from rax_core.app.router import register

    @register("my_job_type")
    def handle_my_job(payload: dict) -> dict:
        ...
        return {"result": "ok"}
"""
from typing import Callable, Dict

_HANDLERS: Dict[str, Callable] = {}


def register(job_type: str) -> Callable:
    """Decorator to register a handler function for a job type."""
    def decorator(fn: Callable) -> Callable:
        _HANDLERS[job_type] = fn
        return fn
    return decorator


def get_handler(job_type: str) -> Callable:
    """
    Return the handler for a job type.

    Raises ValueError if no handler is registered — errors are never swallowed.
    """
    handler = _HANDLERS.get(job_type)
    if handler is None:
        raise ValueError(f"No handler registered for job_type: {job_type!r}")
    return handler
