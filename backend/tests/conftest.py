
"""Shared test configuration, loaded before individual test modules."""

import os

# ``app.database`` creates its engine at import time. Configure a writable,
# isolated database before any test module can import application code.
os.environ["DATABASE_URL"] = "sqlite:////tmp/workboard-tests.db"
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
