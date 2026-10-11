"""Guards the per-test isolation of the browser session store.

Sessions are rows in ``browser_sessions``, which ``conftest.py``'s schema reset
drops between tests. These two tests only pass together, in order: the first
seeds the table, the second observes it as it would look to a fresh test.
"""

from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.models import BrowserSession
from app.security import create_browser_session


def _session_count() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(BrowserSession))


def test_session_store_is_isolated_seeds_a_browser_session():
    """Leave a session behind for the next test to notice, if nothing clears it."""
    with SessionLocal() as db:
        create_browser_session(db, get_settings())
    assert _session_count() == 1


def test_session_store_is_isolated_between_tests():
    """A session created by the previous test must not leak into this one."""
    assert _session_count() == 0, "a session created by an earlier test leaked into this one"
