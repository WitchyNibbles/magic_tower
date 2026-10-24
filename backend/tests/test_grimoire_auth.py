"""The grimoire token opens ``/api/grimoire/*`` and nothing else, and nothing else opens it.

Fixture tokens are invented. The enumeration test walks ``app.routes``, so a route added
later that wrongly accepts the grimoire token fails here without anyone remembering to add it.
"""

from uuid import uuid4

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.security import require_grimoire_token

GRIMOIRE_TOKEN = "g-token"
LOCAL_TOKEN = "l-token"
GRIMOIRE_PREFIX = "/api/grimoire"
PING = f"{GRIMOIRE_PREFIX}/items"  # any guarded grimoire route; the router's placeholder ping is gone


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


def test_a_grimoire_token_equal_to_the_local_one_is_a_configuration_error(monkeypatch):
    shared = "shared-invented-token"
    monkeypatch.setenv("GRIMOIRE_API_TOKEN", shared)
    monkeypatch.setenv("LOCAL_API_TOKEN", shared)
    get_settings.cache_clear()
    with TestClient(app) as client:
        response = client.get(PING, headers=bearer(shared))
        assert client.get("/api/work-items", headers=bearer(shared)).status_code == 200, "the local routes keep working"
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail == "GRIMOIRE_API_TOKEN must differ from LOCAL_API_TOKEN"
    assert shared not in response.text


def _grimoire_routes() -> list[tuple[str, APIRoute]]:
    return sorted(((method, route) for route in app.routes
                   if isinstance(route, APIRoute) and route.path.startswith(GRIMOIRE_PREFIX) for method in route.methods),
                  key=lambda pair: (pair[1].path, pair[0]))


def _nested(dependant: Dependant) -> list[Dependant]:
    return [inner for sub in dependant.dependencies for inner in (sub, *_nested(sub))]


def _guards(dependant: Dependant) -> set:
    return {dependency.call for dependency in _nested(dependant)}


def test_every_grimoire_route_is_guarded_by_the_grimoire_token_dependency():
    routes = _grimoire_routes()
    assert {(method, route.path) for method, route in routes} >= {
        ("GET", f"{GRIMOIRE_PREFIX}/items"), ("PUT", f"{GRIMOIRE_PREFIX}/projects"),
        ("PUT", f"{GRIMOIRE_PREFIX}/items/{{item_id}}/analysis"), ("POST", f"{GRIMOIRE_PREFIX}/sync")}
    for method, route in routes:
        assert require_grimoire_token in _guards(route.dependant), f"{method} {route.path} is not guarded by require_grimoire_token"


@pytest.mark.usefixtures("tokens")
def test_every_grimoire_route_refuses_no_credentials_the_local_token_and_a_browser_session():
    routes = _grimoire_routes()
    with TestClient(app) as client:
        for method, route in routes:
            assert _call(client, method, route.path, {}).status_code == 401, f"{method} {route.path} without credentials"
            assert _call(client, method, route.path, bearer(LOCAL_TOKEN)).status_code == 401, f"{method} {route.path} with the local token"
        assert client.post("/api/session", headers=bearer(LOCAL_TOKEN)).status_code == 201
        for method, route in routes:
            assert _call(client, method, route.path, {}).status_code == 401, f"{method} {route.path} with a browser session"
