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

# Message content lives in encrypted columns (``Source.excerpt``,
# ``WorkEvidence.excerpt``) and every write of one fails closed without a key, so
# the suite has to be configured the way a deployment is. A key generated per
# pytest process keeps this out of the repository and out of any other run; the
# tests that assert the keyless 503 delete the variable again through monkeypatch.
from app.services.crypto import generate_encryption_key

os.environ["APP_ENCRYPTION_KEY"] = generate_encryption_key()

import pytest

from app.config import Settings, get_settings

# ``Settings`` reads ``.env`` relative to the working directory, and the suite must
# be run from ``backend/`` -- which is exactly where a developer who has connected
# Microsoft Graph keeps their real one. Every test that asserts a fail-closed path
# deletes a variable through monkeypatch and rebuilds the settings; without this,
# the file hands the deleted value straight back and the assertion never fires. The
# environment this module sets above is the suite's whole configuration, so a file
# it cannot see is a file it does not need.
Settings.model_config["env_file"] = None
from app.database import Base, engine
from app.security import _sessions, _sessions_lock


def _clear_session_store() -> None:
    """Empty the module-level browser session store through its own lock.

    Clearing in place (rather than rebinding ``_sessions`` to a new dict)
    keeps every module that already imported the object in sync with it.
    """
    with _sessions_lock:
        _sessions.clear()


@pytest.fixture(autouse=True)
def clean_database_and_settings():
    """Give every API test a fresh schema and uncached environment settings.

    The schema is built with ``create_all`` rather than by running the Alembic
    chain. A per-test ``drop_all`` + ``upgrade head`` would leave a stale
    ``alembic_version`` row behind and cost far more than it proves: API tests
    that pass against ``create_all`` but whose author forgot to add a revision
    would still pass, because both mechanisms read the same ``app.models``.
    ``tests/test_migrations.py`` covers the real risk instead -- it applies the
    chain to an empty database and asserts the result has not drifted from the
    metadata -- so the two mechanisms cannot silently disagree.
    """
    get_settings.cache_clear()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _clear_session_store()
    yield
    get_settings.cache_clear()
    Base.metadata.drop_all(bind=engine)
    _clear_session_store()
