"""
rax_core entry point.

Starts the HTTP API server and the job runner together.
The runner is started in a background thread so both coexist.

Usage
-----
    cd rax_core
    python -m app.main            # default port 8080
    RAX_PORT=9000 python -m app.main
"""
import logging
import os
from http.server import HTTPServer

from app.db import init_db
from app.router import make_app
from app.runner import Runner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("RAX_PORT", "8080"))


def main() -> None:
    init_db()

    runner = Runner()
    runner.start(block=False)
    logger.info("Runner started in background thread")

    handler_class = make_app()
    server = HTTPServer(("0.0.0.0", PORT), handler_class)
    logger.info("API server listening on http://0.0.0.0:%d", PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down…")
    finally:
        runner.stop()
        server.server_close()


if __name__ == "__main__":
    main()
