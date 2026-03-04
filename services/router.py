"""Job-type handler registry."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

_handlers: dict[str, Callable[[dict], Any]] = {}


def register(job_type: str, fn: Callable[[dict], Any]) -> None:
    _handlers[job_type] = fn


def get(job_type: str) -> Callable[[dict], Any] | None:
    return _handlers.get(job_type)


def registered_types() -> list[str]:
    return list(_handlers.keys())
