"""Guards the per-test isolation of the module-level browser session store.

``app.security._sessions`` is a module-level dict, not something SQLAlchemy's
schema reset touches, so a session created by one test can otherwise survive
into the next. These two tests only pass together, in order: the first seeds
the store, the second observes it as it would look to a fresh test.
"""

from app.config import get_settings
from app.security import _sessions, create_browser_session


def test_session_store_is_isolated_seeds_a_browser_session():
    """Leave a session behind for the next test to notice, if nothing clears it."""
    session_id, _csrf_token = create_browser_session(get_settings())
    assert session_id in _sessions


def test_session_store_is_isolated_between_tests():
    """A session created by the previous test must not leak into this one."""
    assert _sessions == {}, "a session created by an earlier test leaked into this one"
