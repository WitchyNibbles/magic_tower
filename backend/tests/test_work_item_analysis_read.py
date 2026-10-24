"""The signed-in user sees grimoire's analysis on the work item endpoints they already use."""

from __future__ import annotations

import json
import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.config import get_settings
from app.database import SessionLocal, engine
from app.main import app
from app.models import WorkItemAnalysis

LOCAL = {"Authorization": "Bearer test-local-agent-token"}
GRIMOIRE = {"Authorization": "Bearer g-token"}
DETAILS = {"asked": "Renew the widget.", "systems": ["billing"], "known": "", "next_step": "Ask the owner.",
           "open_questions": []}


@pytest.fixture(autouse=True)
def grimoire_token(monkeypatch):
    monkeypatch.setenv("GRIMOIRE_API_TOKEN", "g-token")
    get_settings.cache_clear()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _create(client: TestClient, name: str) -> str:
    created = client.post("/api/work-items", headers=LOCAL, json={
        "title": f"Renew {name}", "source_kind": "jira", "source_external_id": f"jira:{name}",
        "evidence": [{"source_kind": "jira", "external_id": f"jira:{name}", "excerpt": f"Please renew {name}."}]})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _analyse(client: TestClient, item_id: str, summary: str = "Needs renewing.") -> None:
    fingerprint = client.get(f"/api/grimoire/items/{item_id}/context", headers=GRIMOIRE).json()["fingerprint"]
    saved = client.put(f"/api/grimoire/items/{item_id}/analysis", headers=GRIMOIRE, json={
        "summary": summary, "details": DETAILS, "source_fingerprint": fingerprint, "analyzer": "grimoire"})
    assert saved.status_code == 200, saved.text


def _change_the_source(client: TestClient, item_id: str, name: str) -> None:
    evidence_id = client.get(f"/api/work-items/{item_id}", headers=LOCAL).json()["evidence"][0]["id"]
    assert client.delete(f"/api/work-items/{item_id}/evidence/{evidence_id}", headers=LOCAL).status_code == 204
    added = client.post(f"/api/work-items/{item_id}/evidence", headers=LOCAL, json={
        "source_kind": "jira", "external_id": f"jira:{name}", "excerpt": "A new comment arrived."})
    assert added.status_code == 201


def test_work_item_read_includes_analysis_and_stale_flag(client):
    item_id = _create(client, "one")
    _analyse(client, item_id)

    single = client.get(f"/api/work-items/{item_id}", headers=LOCAL).json()["analysis"]
    listed = client.get("/api/work-items", headers=LOCAL).json()["items"][0]["analysis"]

    for analysis in (single, listed):
        assert (analysis["summary"], analysis["details"], analysis["analyzer"], analysis["stale"]) == (
            "Needs renewing.", DETAILS, "grimoire", False)
        assert analysis["analyzed_at"]

    _change_the_source(client, item_id, "one")

    assert client.get(f"/api/work-items/{item_id}", headers=LOCAL).json()["analysis"]["stale"] is True
    assert client.get("/api/work-items", headers=LOCAL).json()["items"][0]["analysis"]["stale"] is True


def test_other_routes_that_return_a_work_item_carry_the_analysis_too(client):
    item_id = _create(client, "two")
    _analyse(client, item_id)
    _change_the_source(client, item_id, "two")

    patched = client.patch(f"/api/work-items/{item_id}", headers=LOCAL, json={"priority": "high"})

    assert patched.status_code == 200, patched.text
    assert patched.json()["analysis"]["summary"] == "Needs renewing."
    assert patched.json()["analysis"]["stale"] is True


def test_work_item_without_analysis_has_null_analysis(client):
    item_id = _create(client, "three")

    assert client.get(f"/api/work-items/{item_id}", headers=LOCAL).json()["analysis"] is None
    assert client.get("/api/work-items", headers=LOCAL).json()["items"][0]["analysis"] is None


def _statements_for(client: TestClient, path: str) -> int:
    count = 0

    def counter(*_args) -> None:
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", counter)
    try:
        assert client.get(path, headers=LOCAL).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", counter)
    return count


def test_work_item_list_loads_analyses_without_extra_queries_per_item(client):
    _analyse(client, _create(client, "solo"))
    with_one = _statements_for(client, "/api/work-items")

    for name in ("b", "c", "d", "e"):
        _analyse(client, _create(client, name))
    with_five = _statements_for(client, "/api/work-items")

    assert len(client.get("/api/work-items", headers=LOCAL).json()["items"]) == 5
    assert with_five == with_one


def _store_details(item_id: str, details: str) -> None:
    with SessionLocal() as db:
        db.get(WorkItemAnalysis, UUID(item_id)).details = details
        db.commit()


def test_a_stored_analysis_beyond_a_limit_tightened_since_is_still_shown(client):
    item_id = _create(client, "old")
    _analyse(client, item_id)
    _store_details(item_id, json.dumps({**DETAILS, "systems": ["s" * 200]}))

    listed = client.get("/api/work-items", headers=LOCAL)

    assert listed.status_code == 200
    assert listed.json()["items"][0]["analysis"]["details"]["systems"] == ["s" * 200]
    assert client.get(f"/api/work-items/{item_id}", headers=LOCAL).status_code == 200


def test_an_unreadable_stored_analysis_is_no_analysis_and_the_log_names_only_the_item(client, caplog):
    unreadable_marker = "unreadable-marker-77d2"
    item_id = _create(client, "broken")
    _analyse(client, item_id)
    _store_details(item_id, json.dumps({"asked": ["not", "text", unreadable_marker]}))

    with caplog.at_level(logging.INFO):
        listed = client.get("/api/work-items", headers=LOCAL)

    assert listed.status_code == 200
    assert listed.json()["items"][0]["analysis"] is None
    assert item_id in caplog.text
    assert unreadable_marker not in caplog.text
