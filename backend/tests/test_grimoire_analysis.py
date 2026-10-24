"""Writing grimoire's analysis back: encrypted, bounded, tied to the text it read.

Fixture text is invented. The summary marker is what a plaintext leak would look like.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import engine
from app.main import app
from app.models import WorkItem
from app.services.crypto import generate_encryption_key
from app.services.graph import persist_signals
from app.services.promotion import promote_signals

LOCAL = {"Authorization": "Bearer test-local-agent-token"}
GRIMOIRE = {"Authorization": "Bearer g-token"}
SUMMARY = "Needs the widget renewed before the audit-summary-marker-42e1."
DETAILS_MARKER = "details-marker-9b77f0"
OWNER = "owner-account"


def details(**overrides) -> dict:
    body = {"asked": f"Renew the widget. {DETAILS_MARKER}", "systems": ["billing"], "known": "It expires soon.",
            "next_step": "Ask the owner.", "open_questions": ["Who owns it?"]}
    return {**body, **overrides}


@pytest.fixture(autouse=True)
def grimoire_token(monkeypatch):
    monkeypatch.setenv("GRIMOIRE_API_TOKEN", "g-token")
    get_settings.cache_clear()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _create(client: TestClient, excerpt: str | None = "Please renew the widget.") -> str:
    created = client.post("/api/work-items", headers=LOCAL, json={
        "title": "Renew the widget", "source_kind": "jira", "source_external_id": "jira:renew",
        "evidence": [{"source_kind": "jira", "external_id": "jira:renew", "excerpt": excerpt}]})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _fingerprint(client: TestClient, item_id: str) -> str:
    return client.get(f"/api/grimoire/items/{item_id}/context", headers=GRIMOIRE).json()["fingerprint"]


def _put(client: TestClient, item_id: str, **overrides):
    body = {"summary": SUMMARY, "details": details(), "source_fingerprint": _fingerprint(client, item_id), **overrides}
    return client.put(f"/api/grimoire/items/{item_id}/analysis", headers=GRIMOIRE, json=body)


def _rows(sql: str) -> list[tuple]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(sql))]


def test_analysis_is_saved_and_read_back(client):
    item_id = _create(client)

    saved = _put(client, item_id, analyzer="grimoire-test")

    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (body["summary"], body["details"], body["analyzer"], body["stale"]) == (
        SUMMARY, details(), "grimoire-test", False)
    assert body["analyzed_at"].endswith("Z") or "+" in body["analyzed_at"]


def test_analysis_is_encrypted_at_rest(client):
    item_id = _create(client)
    assert _put(client, item_id).status_code == 200

    [(summary, stored_details)] = _rows("SELECT summary, details FROM work_item_analyses")

    for column in (summary, stored_details):
        assert column.startswith("aesgcm.v1:")
        assert "audit-summary-marker" not in column and DETAILS_MARKER not in column


def test_stale_fingerprint_is_409_and_saves_nothing(client):
    item_id = _create(client)
    stale = _fingerprint(client, item_id)
    evidence = client.get(f"/api/work-items/{item_id}", headers=LOCAL).json()["evidence"][0]["id"]
    client.delete(f"/api/work-items/{item_id}/evidence/{evidence}", headers=LOCAL)

    response = _put(client, item_id, source_fingerprint=stale)

    assert response.status_code == 409
    assert response.json()["detail"] == "source changed since it was read"
    assert _rows("SELECT count(*) FROM work_item_analyses") == [(0,)]


def test_writing_an_analysis_leaves_status_dismissal_and_promotion_unchanged(client):
    signal = {"external_id": "jira:promoted-1", "source_kind": "jira", "title": "Invented issue",
              "excerpt": "Some text.", "source_url": "https://example.test/browse/OPS-2",
              "observed_at": "2026-09-18T08:30:00Z", "assignee_account_id": OWNER}
    with Session(engine) as session:
        persist_signals(session, [signal])
        assert promote_signals(session, [signal], owner_account_id=OWNER) == 1
        item_id = str(session.query(WorkItem).one().id)
    state = ("SELECT status, updated_at FROM work_items", "SELECT * FROM source_promotions", "SELECT count(*) FROM work_items")
    before = [_rows(sql) for sql in state]

    assert _put(client, item_id).status_code == 200

    assert [_rows(sql) for sql in state] == before


@pytest.mark.parametrize("override", [
    {"summary": "x" * 601},
    {"summary": "   "},
    {"summary": ""},
    {"details": {**details(), "mood": "cheerful"}},
    {"details": details(known="k" * 8001)},
    {"details": {key: value for key, value in details().items() if key != "asked"}},
    {"details": details(systems=["s" * 81])},
    {"analyzer": "grimoire\nINFO forged line"},
])
def test_analysis_limits_are_enforced(client, override):
    item_id = _create(client)

    response = _put(client, item_id, **override)

    assert response.status_code == 422, response.text
    assert _rows("SELECT count(*) FROM work_item_analyses") == [(0,)]


def test_the_limits_allow_their_exact_maximums(client):
    item_id = _create(client)
    fits = details(known="", next_step="", open_questions=[], systems=["s" * 80])
    fits["asked"] = "a" * (8000 - len(json.dumps({**fits, "asked": ""}, separators=(",", ":"), ensure_ascii=False)))

    assert _put(client, item_id, summary="s" * 600, details=fits).status_code == 200


def test_second_write_replaces_the_first(client):
    item_id = _create(client)

    assert _put(client, item_id, summary="First reading.").status_code == 200
    assert _put(client, item_id, summary="Second reading.").status_code == 200

    assert _rows("SELECT count(*) FROM work_item_analyses") == [(1,)]
    read = client.get(f"/api/grimoire/items/{item_id}/context", headers=GRIMOIRE)
    assert read.status_code == 200
    with Session(engine) as session:
        assert session.get(WorkItem, UUID(item_id)).analysis.summary == "Second reading."


def test_analysis_of_a_dismissed_or_missing_item_is_404(client):
    item_id = _create(client)
    fingerprint_value = _fingerprint(client, item_id)
    client.post(f"/api/work-items/{item_id}/dismiss", headers=LOCAL)
    body = {"summary": SUMMARY, "details": details(), "source_fingerprint": fingerprint_value}

    assert client.put(f"/api/grimoire/items/{item_id}/analysis", headers=GRIMOIRE, json=body).status_code == 404
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.put(f"/api/grimoire/items/{missing}/analysis", headers=GRIMOIRE, json=body).status_code == 404


def test_missing_encryption_key_is_503_and_stores_no_plaintext(client, monkeypatch):
    """No key means no write. The item has no excerpt so the read side needs no key either."""
    item_id = _create(client, excerpt=None)
    fingerprint_value = _fingerprint(client, item_id)
    monkeypatch.delenv("APP_ENCRYPTION_KEY")
    get_settings.cache_clear()

    with TestClient(app, raise_server_exceptions=False) as keyless:
        response = keyless.put(f"/api/grimoire/items/{item_id}/analysis", headers=GRIMOIRE, json={
            "summary": SUMMARY, "details": details(), "source_fingerprint": fingerprint_value})

    assert response.status_code == 503, response.text
    monkeypatch.setenv("APP_ENCRYPTION_KEY", generate_encryption_key())
    assert _rows("SELECT count(*) FROM work_item_analyses") == [(0,)]


def test_write_logs_the_item_id_not_the_text(client, caplog):
    item_id = _create(client)
    caplog.set_level(logging.INFO)

    assert _put(client, item_id, analyzer="grimoire-test").status_code == 200

    assert item_id in caplog.text and "grimoire-test" in caplog.text
    assert "audit-summary-marker" not in caplog.text and DETAILS_MARKER not in caplog.text
    assert "Please renew the widget" not in caplog.text
