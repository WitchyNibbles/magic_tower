"""grimoire asks Magic Tower to pull fresh data before it analyses."""

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

GRIMOIRE = {"Authorization": "Bearer g-token"}
LOCAL = {"Authorization": "Bearer test-local-agent-token"}
CANNED = {"jira": {"stored": 3}, "freshservice": {"error": "Freshservice is not reachable"}}


@pytest.fixture(autouse=True)
def grimoire_token(monkeypatch):
    monkeypatch.setenv("GRIMOIRE_API_TOKEN", "g-token")
    get_settings.cache_clear()


def test_grimoire_sync_runs_the_ready_sources(monkeypatch):
    calls = []

    def fake_sync(settings, db):
        calls.append(settings)
        return CANNED

    monkeypatch.setattr("app.api.grimoire.sync_ready_sources", fake_sync)
    with TestClient(app) as client:
        response = client.post("/api/grimoire/sync", headers=GRIMOIRE)

    assert response.status_code == 200, response.text
    assert response.json() == {"results": CANNED}
    assert len(calls) == 1


def test_grimoire_sync_with_nothing_set_up_is_an_empty_result():
    with TestClient(app) as client:
        response = client.post("/api/grimoire/sync", headers=GRIMOIRE)

    assert response.status_code == 200, response.text
    assert response.json() == {"results": {}}


def test_grimoire_sync_refuses_the_local_token_and_no_credentials(monkeypatch):
    monkeypatch.setattr("app.api.grimoire.sync_ready_sources", lambda settings, db: pytest.fail("synced without the grimoire token"))
    with TestClient(app) as client:
        assert client.post("/api/grimoire/sync", headers=LOCAL).status_code == 401
        assert client.post("/api/grimoire/sync").status_code == 401
