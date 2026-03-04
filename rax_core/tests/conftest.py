"""Pytest configuration – sets up a temp DB before any imports."""
import os
import tempfile
import pytest


@pytest.fixture(autouse=True, scope="session")
def _tmp_db():
    """Point rax_core at a fresh temp database for the test session."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    os.environ["RAX_DB_PATH"] = db_path
    os.environ["RAX_API_KEY"] = "test-key"

    # Import after env vars are set so config picks them up.
    from rax_core.app import config
    config.DB_PATH = db_path

    from rax_core.app.models import init_db
    init_db()

    yield db_path

    os.unlink(db_path)
