"""grimoire's project snapshot: written by the grimoire token, read by the signed-in user.

Fixture names are invented. The marker is what a plaintext leak would look like.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import get_settings
from app.database import engine
from app.main import app

LOCAL = {"Authorization": "Bearer test-local-agent-token"}
GRIMOIRE = {"Authorization": "Bearer g-token"}
MARKER = "snapshot-marker-5c31"


def project(code: str = "PRJ-A", **overrides) -> dict:
    body = {"code": code, "name": f"Invented project {MARKER}", "status": "active",
            "tasks": [{"title": "Draft the widget plan", "status": "in_progress", "pr_url": "https://example.test/pull/7"},
                      {"title": "Review the notes", "status": "todo", "pr_url": None}],
            "open_questions": 2, "pending_prod_steps": ["Run the widget migration"]}
    return {**body, **overrides}


@pytest.fixture(autouse=True)
def grimoire_token(monkeypatch):
    monkeypatch.setenv("GRIMOIRE_API_TOKEN", "g-token")
    get_settings.cache_clear()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _put(client: TestClient, *projects: dict):
    return client.put("/api/grimoire/projects", headers=GRIMOIRE, json={"projects": list(projects)})


def _rows(sql: str) -> list[tuple]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(sql))]


def test_snapshot_replaces_and_reads_back(client):
    first = _put(client, project("PRJ-A"), project("PRJ-B", status="waiting"))
    assert first.status_code == 200, first.text

    second = _put(client, project("PRJ-C", status="done", tasks=[], open_questions=0, pending_prod_steps=[]))
    assert second.status_code == 200

    read = client.get("/api/projects", headers=LOCAL)
    assert read.status_code == 200
    body = read.json()
    assert [entry["code"] for entry in body["projects"]] == ["PRJ-C"]
    assert body["projects"][0]["status"] == "done"
    assert body["updated_at"] == second.json()["updated_at"]
    assert _rows("SELECT count(*) FROM grimoire_project_snapshot") == [(1,)]


def test_snapshot_keeps_tasks_questions_steps_and_pr_links(client):
    assert _put(client, project()).status_code == 200

    [entry] = client.get("/api/projects", headers=LOCAL).json()["projects"]

    assert entry["tasks"] == [{"title": "Draft the widget plan", "status": "in_progress", "pr_url": "https://example.test/pull/7"},
                              {"title": "Review the notes", "status": "todo", "pr_url": None}]
    assert (entry["open_questions"], entry["pending_prod_steps"]) == (2, ["Run the widget migration"])


def test_snapshot_is_encrypted_at_rest(client):
    assert _put(client, project()).status_code == 200

    [(stored,)] = _rows("SELECT snapshot FROM grimoire_project_snapshot")

    assert stored.startswith("aesgcm.v1:")
    assert MARKER not in stored and "Draft the widget plan" not in stored


def test_snapshot_without_encryption_key_is_503_and_stores_nothing(client, monkeypatch):
    monkeypatch.delenv("APP_ENCRYPTION_KEY")
    get_settings.cache_clear()

    response = _put(client, project())

    assert response.status_code == 503
    assert _rows("SELECT count(*) FROM grimoire_project_snapshot") == [(0,)]


@pytest.mark.parametrize("body", [
    {"projects": [project(mood="cheerful")]},
    {"mood": "cheerful", "projects": []},
    {"projects": [project(code="c" * 41)]},
    {"projects": [project(name="n" * 201)]},
    {"projects": [project(status="paused")]},
    {"projects": [project(tasks=[{"title": "t" * 201, "status": "todo", "pr_url": None}])]},
    {"projects": [project(tasks=[{"title": "ok", "status": "stuck", "pr_url": None}])]},
    {"projects": [project(tasks=[{"title": "ok", "status": "todo", "pr_url": "javascript:alert(1)"}])]},
    {"projects": [project(tasks=[{"title": "ok", "status": "todo", "pr_url": None, "note": "x"}])]},
    {"projects": [project(tasks=[{"title": "ok", "status": "todo", "pr_url": None}] * 51)]},
    {"projects": [project(open_questions=-1)]},
    {"projects": [project(pending_prod_steps=["s" * 121])]},
    {"projects": [project(pending_prod_steps=["step"] * 21)]},
    {"projects": [project(f"P{number}") for number in range(51)]},
])
def test_snapshot_limits_and_unknown_keys_are_422(client, body):
    assert client.put("/api/grimoire/projects", headers=GRIMOIRE, json=body).status_code == 422
    assert _rows("SELECT count(*) FROM grimoire_project_snapshot") == [(0,)]


def test_projects_read_needs_local_access_and_refuses_grimoire_token(client):
    assert _put(client, project()).status_code == 200

    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects", headers=GRIMOIRE).status_code == 401
    assert client.get("/api/projects", headers=LOCAL).status_code == 200


def test_snapshot_write_refuses_the_local_token(client):
    assert client.put("/api/grimoire/projects", headers=LOCAL, json={"projects": []}).status_code == 401


def test_empty_snapshot_reads_as_empty_list_with_null_updated_at(client):
    response = client.get("/api/projects", headers=LOCAL)

    assert response.status_code == 200
    assert response.json() == {"projects": [], "updated_at": None}


def test_snapshot_write_logs_the_count_not_the_text(client, caplog):
    with caplog.at_level(logging.INFO, logger="app"):
        assert _put(client, project(), project("PRJ-B")).status_code == 200

    assert any("2 projects" in record.getMessage() for record in caplog.records)
    assert MARKER not in caplog.text and "Draft the widget plan" not in caplog.text
