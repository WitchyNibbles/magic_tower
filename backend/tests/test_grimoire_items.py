"""What grimoire may list and read: references without text, and one context route with it.

Fixture titles and text are invented. The marker string is what a leak would look like.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import engine
from app.main import app
from app.models import SourceKind, WorkItem, WorkItemAnalysis
from app.services.graph import persist_signals
from app.services.grimoire_view import context_fields, fingerprint
from app.services.promotion import promote_signals

GRIMOIRE_TOKEN = "g-token"
LOCAL = {"Authorization": "Bearer test-local-agent-token"}
GRIMOIRE = {"Authorization": f"Bearer {GRIMOIRE_TOKEN}"}
MARKER = "renew-the-widget-marker-71c9d2"
OWNER = "owner-account"
REFERENCE_KEYS = {"id", "title", "source_kind", "source_url", "status", "analyzed_at", "stale"}


@pytest.fixture(autouse=True)
def grimoire_token(monkeypatch):
    monkeypatch.setenv("GRIMOIRE_API_TOKEN", GRIMOIRE_TOKEN)
    get_settings.cache_clear()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _create(client: TestClient, title: str, *, status: str = "pending", excerpt: str | None = MARKER) -> str:
    created = client.post("/api/work-items", headers=LOCAL, json={
        "title": title, "source_kind": "jira", "source_external_id": f"jira:{title}",
        "source_url": "https://example.test/browse/OPS-1",
        "evidence": [{"source_kind": "jira", "external_id": f"jira:{title}", "excerpt": excerpt}]})
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]
    if status != "pending":
        assert client.patch(f"/api/work-items/{item_id}", headers=LOCAL, json={"status": status}).status_code == 200
    return item_id


def _needing(client: TestClient) -> dict:
    response = client.get("/api/grimoire/items?needs_analysis=true", headers=GRIMOIRE)
    assert response.status_code == 200, response.text
    return response.json()


def _analyse(item_id: str, fingerprint_value: str | None = None) -> None:
    with Session(engine) as session:
        item = session.get(WorkItem, UUID(item_id))
        session.add(WorkItemAnalysis(
            work_item_id=item.id, summary="A short summary.", details='{"asked":"x"}',
            source_fingerprint=fingerprint_value or fingerprint(context_fields(session, item)), analyzer="grimoire"))
        session.commit()


def test_needs_analysis_lists_unanalysed_open_items_without_text(client):
    pending = _create(client, "Pending one")
    in_progress = _create(client, "Working one", status="in_progress")
    _create(client, "Finished one", status="done")
    dismissed = _create(client, "Dropped one")
    assert client.post(f"/api/work-items/{dismissed}/dismiss", headers=LOCAL).status_code == 200

    page = _needing(client)

    assert {row["id"] for row in page["items"]} == {pending, in_progress}
    assert page["total"] == 2
    assert (page["limit"], page["offset"]) == (50, 0)
    for row in page["items"]:
        assert set(row) == REFERENCE_KEYS
        assert row["analyzed_at"] is None and row["stale"] is False
    assert MARKER not in client.get("/api/grimoire/items?needs_analysis=true", headers=GRIMOIRE).text


def test_the_list_pages_and_the_complement_holds_the_rest(client):
    ids = [_create(client, f"Item {n}") for n in range(3)]
    _analyse(ids[0])

    first = client.get("/api/grimoire/items?needs_analysis=true&limit=1&offset=0", headers=GRIMOIRE).json()
    second = client.get("/api/grimoire/items?needs_analysis=true&limit=1&offset=1", headers=GRIMOIRE).json()
    done = client.get("/api/grimoire/items?needs_analysis=false", headers=GRIMOIRE).json()

    assert first["total"] == second["total"] == 2
    assert len(first["items"]) == len(second["items"]) == 1
    assert {first["items"][0]["id"], second["items"][0]["id"]} == set(ids[1:])
    assert [row["id"] for row in done["items"]] == [ids[0]]
    assert done["items"][0]["analyzed_at"] is not None


def test_context_returns_text_marked_untrusted_with_a_stable_fingerprint(client):
    item_id = _create(client, "Context one")

    first = client.get(f"/api/grimoire/items/{item_id}/context", headers=GRIMOIRE)
    second = client.get(f"/api/grimoire/items/{item_id}/context", headers=GRIMOIRE)

    assert first.status_code == 200, first.text
    body = first.json()
    assert body["untrusted_content"] is True
    assert [row["excerpt"] for row in body["evidence"]] == [MARKER]
    assert body["fingerprint"] == second.json()["fingerprint"]
    with Session(engine) as session:
        item = session.get(WorkItem, UUID(item_id))
        assert body["fingerprint"] == fingerprint(context_fields(session, item))


def test_context_of_dismissed_or_missing_item_is_404(client):
    dismissed = _create(client, "Dropped two")
    assert client.post(f"/api/work-items/{dismissed}/dismiss", headers=LOCAL).status_code == 200

    assert client.get(f"/api/grimoire/items/{dismissed}/context", headers=GRIMOIRE).status_code == 404
    assert client.get("/api/grimoire/items/00000000-0000-0000-0000-000000000000/context", headers=GRIMOIRE).status_code == 404


def test_context_answers_for_a_done_item(client):
    done = _create(client, "Finished two", status="done")

    assert client.get(f"/api/grimoire/items/{done}/context", headers=GRIMOIRE).status_code == 200


def _signal(excerpt: str | None) -> dict:
    return {"external_id": "jira:late-1", "source_kind": "jira", "title": "Invented late issue", "excerpt": excerpt,
            "source_url": "https://example.test/browse/OPS-9", "observed_at": "2026-09-18T08:30:00Z",
            "assignee_account_id": OWNER}


def test_fingerprint_changes_when_an_excerpt_fills_in_late():
    with Session(engine) as session:
        persist_signals(session, [_signal(None)])
        assert promote_signals(session, [_signal(None)], owner_account_id=OWNER) == 1
        item = session.scalar(select(WorkItem).where(WorkItem.source_external_id == "jira:late-1"))
        before = fingerprint(context_fields(session, item))

    with Session(engine) as session:
        persist_signals(session, [_signal(f"Renew it. {MARKER}")])
        item = session.scalar(select(WorkItem).where(WorkItem.source_external_id == "jira:late-1"))
        after = fingerprint(context_fields(session, item))

    assert after != before


def test_the_fingerprint_of_an_item_with_no_evidence_is_still_defined():
    with Session(engine) as session:
        item = WorkItem(title="Bare", source_kind=SourceKind.manual)
        session.add(item)
        session.commit()
        assert len(fingerprint(context_fields(session, item))) == 64


def test_analysed_item_is_listed_again_once_its_source_changes(client):
    item_id = _create(client, "Edited later")
    _analyse(item_id)
    assert _needing(client)["items"] == []

    evidence_id = client.get(f"/api/work-items/{item_id}", headers=LOCAL).json()["evidence"][0]["id"]
    assert client.delete(f"/api/work-items/{item_id}/evidence/{evidence_id}", headers=LOCAL).status_code == 204
    assert client.post(f"/api/work-items/{item_id}/evidence", headers=LOCAL, json={
        "source_kind": "jira", "external_id": "jira:Edited later", "excerpt": "A new comment arrived."}).status_code == 201

    page = _needing(client)

    assert [(row["id"], row["stale"]) for row in page["items"]] == [(item_id, True)]
    assert page["items"][0]["analyzed_at"] is not None
