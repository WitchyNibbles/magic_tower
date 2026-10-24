"""The grimoire token opens ``/api/grimoire/*`` and nothing else, and nothing else opens it.

Fixture tokens are invented. The enumeration test walks ``app.routes``, so a route added
later that wrongly accepts the grimoire token fails here without anyone remembering to add it.
"""

from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

GRIMOIRE_TOKEN = "g-token"
LOCAL_TOKEN = "l-token"
GRIMOIRE_PREFIX = "/api/grimoire"
PING = f"{GRIMOIRE_PREFIX}/ping"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def tokens(monkeypatch):
    monkeypatch.setenv("GRIMOIRE_API_TOKEN", GRIMOIRE_TOKEN)
    monkeypatch.setenv("LOCAL_API_TOKEN", LOCAL_TOKEN)
    get_settings.cache_clear()


def test_grimoire_route_without_configured_token_is_503(monkeypatch):
    monkeypatch.delenv("GRIMOIRE_API_TOKEN", raising=False)
    get_settings.cache_clear()
    with TestClient(app) as client:
        response = client.get(PING, headers=bearer("anything"))
    assert response.status_code == 503
    assert response.json()["detail"] == "grimoire API not configured"


def test_a_blank_grimoire_token_counts_as_unset(monkeypatch):
    monkeypatch.setenv("GRIMOIRE_API_TOKEN", "  ")
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.get(PING, headers=bearer("  ")).status_code == 503


@pytest.mark.usefixtures("tokens")
def test_grimoire_route_refuses_missing_wrong_and_local_token():
    with TestClient(app) as client:
        assert client.get(PING).status_code == 401
        assert client.get(PING, headers=bearer("wrong")).status_code == 401
        assert client.get(PING, headers=bearer(LOCAL_TOKEN)).status_code == 401
        login = client.post("/api/session", headers=bearer(LOCAL_TOKEN))
        assert login.status_code == 201
        assert client.get("/api/work-items").status_code == 200, "the browser session should be signed in"
        assert client.get(PING).status_code == 401, "a browser session must not open the grimoire routes"
        ok = client.get(PING, headers=bearer(GRIMOIRE_TOKEN))
    assert ok.status_code == 200
    assert ok.json() == {"ok": True}


def _other_routes() -> list[tuple[str, str]]:
    return sorted(
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and not route.path.startswith(GRIMOIRE_PREFIX) and route.path != "/api/health"
        for method in route.methods
    )


def _call(client: TestClient, method: str, path: str, headers: dict[str, str]):
    filled = path
    for part in path.split("/"):
        if part.startswith("{"):
            filled = filled.replace(part, str(uuid4()))
    body = {"json": {}} if method in {"POST", "PUT", "PATCH"} else {}
    return client.request(method, filled, headers=headers, follow_redirects=False, **body)


@pytest.mark.usefixtures("tokens")
def test_grimoire_token_is_refused_on_every_other_route():
    routes = _other_routes()
    assert len(routes) > 20, "the enumeration found too few routes to mean anything"
    with TestClient(app) as client:
        for method, path in routes:
            without = _call(client, method, path, {})
            with_grimoire = _call(client, method, path, bearer(GRIMOIRE_TOKEN))
            assert with_grimoire.status_code == without.status_code, (
                f"{method} {path} answers {with_grimoire.status_code} to the grimoire token "
                f"but {without.status_code} to no credentials at all")
            if without.status_code == 401:
                assert not 200 <= with_grimoire.status_code < 300, f"{method} {path} accepted the grimoire token"
