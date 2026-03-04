"""
Local-First Automation Kernel

Spine: task registry + synchronous runner.
No drift. No extra features. Just spine.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from loguru import logger


@dataclass
class Task:
    name: str
    fn: Callable[[], Any]


@dataclass
class KernelResult:
    task_name: str
    success: bool
    output: Any = None
    error: str = ""
    ran_at: str = ""


class Kernel:
    """Minimal local-first task runner."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def register(self, name: str, fn: Callable[[], Any]) -> None:
        self._tasks[name] = Task(name=name, fn=fn)
        logger.info(f"[kernel] registered task: {name}")

    def run(self, name: str) -> KernelResult:
        task = self._tasks.get(name)
        if task is None:
            return KernelResult(
                task_name=name,
                success=False,
                error=f"unknown task: {name}",
                ran_at=datetime.now(timezone.utc).isoformat(),
            )
        ran_at = datetime.now(timezone.utc).isoformat()
        try:
            output = task.fn()
            logger.success(f"[kernel] {name} OK")
            return KernelResult(task_name=name, success=True, output=output, ran_at=ran_at)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[kernel] {name} FAILED: {exc}")
            return KernelResult(task_name=name, success=False, error=str(exc), ran_at=ran_at)

    def run_all(self) -> list[KernelResult]:
        return [self.run(name) for name in self._tasks]

    def task_names(self) -> list[str]:
        return list(self._tasks.keys())


# Module-level singleton — import and use directly
kernel = Kernel()
