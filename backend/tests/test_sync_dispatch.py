"""`sync()` dispatches per registered source kind instead of being hardwired to Graph.

A fake kind is registered here, at test time, purely through the public registry
API -- nothing in ``app/services/sync.py`` is touched to make this pass. That is
the behavior the registry exists to prove: a second connector (Jira, Freshservice)
can show up later without surgery on ``sync()``.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import engine
from app.models import Source, SourceKind
from app.services.sync import SyncError, sync
from app.services.sync_registry import register_sync_handler, unregister_sync_handler

FAKE_KIND = "fake-connector"


def _fake_handler(settings: Settings, db: Session | None = None, limit: int = 50, **_: Any) -> dict[str, Any]:
    if db is not None:
        db.add(Source(kind=SourceKind.manual, external_id="fake:1", subject="fake work item"))
        db.commit()
    return {"mode": "read-only", "synced_at": "test", "count": 1, "new_sources": 1}


@pytest.fixture
def fake_kind_registered():
    """Register the fake kind for one test and always unregister it after.

    Restoring the registry here -- rather than leaving it mutated -- is what
    keeps this test from leaking global state into any test that runs after it.
    """
    register_sync_handler(FAKE_KIND, _fake_handler)
    try:
        yield FAKE_KIND
    finally:
        unregister_sync_handler(FAKE_KIND)


def test_per_source_dispatch_syncs_a_newly_registered_kind_end_to_end(fake_kind_registered) -> None:
    settings = Settings()
    with Session(engine) as session:
        result = sync(settings, session, kind=fake_kind_registered)
        assert result["new_sources"] == 1
        assert session.query(Source).filter_by(external_id="fake:1").count() == 1


def test_per_source_dispatch_rejects_an_unregistered_kind() -> None:
    with pytest.raises(SyncError):
        sync(Settings(), kind="does-not-exist")


def test_per_source_dispatch_defaults_to_graph_when_no_kind_given() -> None:
    """No ``kind`` argument still routes to the Graph handler, unmodified."""
    with pytest.raises(SyncError, match="Microsoft Graph is not configured"):
        sync(Settings())
