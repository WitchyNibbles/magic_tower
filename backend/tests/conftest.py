"""Shared test configuration, loaded before individual test modules."""

import atexit
import os
import shutil
import tempfile

# ``app.database`` builds its engine at import time from an ``@lru_cache``d
# ``get_settings()``, so ``DATABASE_URL`` has to be set before any test module
# imports application code -- a session-scoped ``tmp_path_factory`` fixture would
# run long after collection has already imported ``app.database``. Choosing the
# directory here, at conftest import time, gives every pytest process its own
# SQLite file, so parallel runs cannot drop each other's tables.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="workboard-tests-")
atexit.register(shutil.rmtree, _TEST_DB_DIR, ignore_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_DIR}/workboard-tests.db"
os.environ["LOCAL_API_TOKEN"] = "test-local-agent-token"

import pytest

from app.config import get_settings
from app.database import Base, engine


@pytest.fixture(autouse=True)
def clean_database_and_settings():
    """Give every API test a fresh schema and uncached environment settings."""
    get_settings.cache_clear()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    get_settings.cache_clear()
    Base.metadata.drop_all(bind=engine)
