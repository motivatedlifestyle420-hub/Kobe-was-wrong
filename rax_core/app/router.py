"""Job-type handler registry.

Usage
-----
    from rax_core.app.router import registry
    registry.register("my.job_type", my_handler_fn)

Handler signature:  fn(job: dict) -> Any
"""
from typing import Any, Callable, Dict, Optional

HandlerFn = Callable[[dict], Any]


class Registry:
    def __init__(self) -> None:
        self._handlers: Dict[str, HandlerFn] = {}

    def register(self, job_type: str, fn: HandlerFn) -> None:
        self._handlers[job_type] = fn

    def get(self, job_type: str) -> Optional[HandlerFn]:
        return self._handlers.get(job_type)

    def job_types(self) -> list[str]:
        return list(self._handlers.keys())


registry = Registry()
