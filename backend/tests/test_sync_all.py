"""``sync_ready_sources`` and ``POST /api/sync/all``: sync every ready source, report each.

The registry is swapped for an empty one per test, so only the stub handlers
registered here exist: nothing in this file can reach Jira or Graph.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import engine
from app.main import app
from app.services import sync_registry
from app.services.sync import SyncError
from app.services.sync_all import sync_ready_sources
from app.services.sync_registry import register_sync_handler

BEARER = {"Authorization": "Bearer test-local-agent-token"}
ENVELOPE = {"mode": "read-only", "synced_at": "now", "count": 2, "new_sources": 2, "new_work_items": 1}


@pytest.fixture(autouse=True)
def only_stub_handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty registry for the test, restored by monkeypatch afterwards."""
    monkeypatch.setattr(sync_registry, "_handlers", {})
    monkeypatch.setattr(sync_registry, "_ready_checks", {})
    monkeypatch.setattr(sync_registry, "_locks", {})


def _register(kind: str, handler: Any, ready: bool = True) -> None:
    register_sync_handler(kind, handler, ready=lambda settings: ready)


def _ok(settings: Settings, db: Any = None, limit: int = 50, **_: Any) -> dict[str, Any]:
    return dict(ENVELOPE)


def _sync_error(settings: Settings, db: Any = None, limit: int = 50, **_: Any) -> dict[str, Any]:
    raise SyncError("Microsoft Graph is not connected")


def _unexpected(settings: Settings, db: Any = None, limit: int = 50, **_: Any) -> dict[str, Any]:
    raise RuntimeError("secret-token-value leaked in an exception")


def test_no_ready_source_gives_an_empty_result() -> None:
    _register("not-set-up", _ok, ready=False)

    with Session(engine) as db:
        assert sync_ready_sources(Settings(), db) == {}


def test_each_ready_source_reports_its_own_envelope() -> None:
    _register("alpha", _ok)
    _register("beta", lambda settings, db=None, limit=50, **_: {"count": 7})

    with Session(engine) as db:
        results = sync_ready_sources(Settings(), db)

    assert results == {"alpha": ENVELOPE, "beta": {"count": 7}}


def test_a_source_that_is_not_ready_is_left_out() -> None:
    _register("ready-one", _ok)
    _register("idle-one", _ok, ready=False)

    with Session(engine) as db:
        assert list(sync_ready_sources(Settings(), db)) == ["ready-one"]


def test_a_sync_error_becomes_that_sources_message_and_the_others_still_sync() -> None:
    _register("good", _ok)
    _register("broken", _sync_error)
    _register("also-good", _ok)

    with Session(engine) as db:
        results = sync_ready_sources(Settings(), db)

    assert results == {"good": ENVELOPE, "broken": {"error": "Microsoft Graph is not connected"}, "also-good": ENVELOPE}


def test_an_unexpected_error_is_logged_and_reported_without_its_message(caplog: pytest.LogCaptureFixture) -> None:
    _register("flaky", _unexpected)
    _register("good", _ok)

    with Session(engine) as db, caplog.at_level(logging.ERROR):
        results = sync_ready_sources(Settings(), db)

    assert results["flaky"] == {"error": "flaky sync failed; see the API log"}
    assert results["good"] == ENVELOPE
    assert any(record.exc_info and "flaky" in record.getMessage() for record in caplog.records)


def test_the_unexpected_error_text_never_reaches_the_result() -> None:
    _register("flaky", _unexpected)

    with Session(engine) as db:
        assert "secret-token-value" not in repr(sync_ready_sources(Settings(), db))


def test_the_sources_are_synced_with_the_given_session() -> None:
    seen: list[Any] = []

    def handler(settings: Settings, db: Any = None, limit: int = 50, **_: Any) -> dict[str, Any]:
        seen.append(db)
        return {"count": 0}

    _register("alpha", handler)
    with Session(engine) as db:
        sync_ready_sources(Settings(), db)

    assert seen == [db]


def test_post_sync_all_requires_the_local_token() -> None:
    _register("alpha", _ok)

    with TestClient(app) as client:
        assert client.post("/api/sync/all").status_code == 401
        assert client.post("/api/sync/all", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_post_sync_all_returns_results_keyed_by_kind() -> None:
    _register("alpha", _ok)
    _register("broken", _sync_error)
    _register("flaky", _unexpected)

    with TestClient(app) as client:
        response = client.post("/api/sync/all", headers=BEARER)

    assert response.status_code == 200
    assert response.json() == {
        "results": {
            "alpha": ENVELOPE,
            "broken": {"error": "Microsoft Graph is not connected"},
            "flaky": {"error": "flaky sync failed; see the API log"},
        }
    }


def test_post_sync_all_with_nothing_ready_is_an_empty_results_object() -> None:
    with TestClient(app) as client:
        response = client.post("/api/sync/all", headers=BEARER)

    assert response.status_code == 200
    assert response.json() == {"results": {}}


def test_sync_all_does_not_shadow_the_single_kind_and_backfill_routes() -> None:
    _register("alpha", _ok)

    with TestClient(app) as client:
        single = client.post("/api/sync", params={"kind": "alpha"}, headers=BEARER)
        backfill = client.post("/api/sync/backfill", headers=BEARER)

    assert single.status_code == 200
    assert single.json() == ENVELOPE
    assert backfill.status_code == 200
    assert "considered" in backfill.json()
