"""
pytest configuration for rax_core tests.

The `db` fixture provides an isolated, initialised SQLite database for each
test function. The path is passed explicitly to every job operation so that
tests never touch the default database.
"""
import pytest

from rax_core.app.models import init_db


@pytest.fixture()
def db(tmp_path):
    """Return a path to a freshly initialised test database."""
    path = str(tmp_path / "rax_test.db")
    init_db(db_path=path)
    return path
