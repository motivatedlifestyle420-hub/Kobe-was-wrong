"""Demo job handlers — proves end-to-end pipeline."""
from __future__ import annotations

from services.router import register


def noop(payload: dict) -> dict:
    """Does nothing. Proves enqueue → running → succeeded works."""
    return {"ok": True}


register("noop", noop)
