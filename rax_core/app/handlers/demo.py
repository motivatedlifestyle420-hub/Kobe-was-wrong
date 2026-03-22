"""
Demo no-op handler registered for the "demo" job type.

Importing this module has the side-effect of registering the handler,
so main.py imports it during startup.
"""
from rax_core.app.router import register


@register("demo")
def demo_handler(payload: dict) -> dict:
    """No-op handler — always succeeds immediately."""
    return {"status": "ok", "echo": payload}
