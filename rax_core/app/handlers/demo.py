"""Demo handler – a no-op that logs its payload.

Register with:
    from rax_core.app.handlers.demo import register
    register()
"""
import logging
from rax_core.app.router import registry

logger = logging.getLogger(__name__)


def _handle_demo(job: dict):
    logger.info("demo handler  payload=%r", job["payload"])
    return {"ok": True}


def register() -> None:
    registry.register("demo.noop", _handle_demo)
