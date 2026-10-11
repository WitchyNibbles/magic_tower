"""``POST /api/sync`` accepts an optional source ``kind`` and dispatches through
the same registry ``app.services.sync.sync`` already uses (AC11).

Before this file, the route (``app/api/sync.py``) never forwarded a ``kind`` at
all, so the registry T06 built was reachable only by calling ``sync()`` from
Python -- every HTTP caller got Graph, with no way to ask for anything else and
no way to see the registry's own fail-closed error. These tests pin three
things: the parameter reaches ``sync()``, an unregistered kind answers 409 (not
500, via the existing ``UnknownSourceKindError`` -> ``SyncError`` path) rather
than crashing, and omitting the parameter still reaches Graph exactly as it did
before this route ever heard of ``kind``.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import engine
from app.main import app
from app.models import Source, SourceKind
from app.services.sync_registry import register_sync_handler, unregister_sync_handler

BEARER = {"Authorization": "Bearer test-local-agent-token"}
FAKE_KIND = "fake-connector-for-sync-kind-parameter"


def _fake_handler(settings: Any, db: Session | None = None, limit: int = 50, **_: Any) -> dict[str, Any]:
    if db is not None:
        db.add(Source(kind=SourceKind.manual, external_id="fake-api:1", subject="fake api sync"))
        db.commit()
    return {"mode": "read-only", "synced_at": "test", "count": 1, "new_sources": 1}


def test_sync_kind_parameter_dispatches_to_a_registered_alternate_kind() -> None:
    register_sync_handler(FAKE_KIND, _fake_handler)
    try:
        with TestClient(app) as client:
            response = client.post("/api/sync", params={"kind": FAKE_KIND}, headers=BEARER)
    finally:
        unregister_sync_handler(FAKE_KIND)

    assert response.status_code == 200
    assert response.json()["new_sources"] == 1
    with Session(engine) as session:
        assert session.query(Source).filter_by(external_id="fake-api:1").count() == 1


def test_sync_kind_parameter_rejects_an_unregistered_kind_with_409_not_500() -> None:
    with TestClient(app) as client:
        response = client.post("/api/sync", params={"kind": "does-not-exist"}, headers=BEARER)

    assert response.status_code == 409
    assert "does-not-exist" in response.json()["detail"]


def test_sync_kind_parameter_defaults_to_graph_when_omitted() -> None:
    """No ``kind`` on the request must still reach the Graph handler, unmodified --
    this reddens if the default ever stops being Graph."""
    with TestClient(app) as client:
        response = client.post("/api/sync", headers=BEARER)

    assert response.status_code == 409
    assert "Microsoft Graph" in response.json()["detail"]
