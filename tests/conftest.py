"""Set test environment variables before any app module is imported."""
import os
import tempfile

_tmpdb = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmpdb.close()

os.environ.setdefault("DB_PATH", _tmpdb.name)
os.environ.setdefault("API_KEY", "test-key")
