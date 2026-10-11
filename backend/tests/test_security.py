"""Security boundary tests; Graph credentials are intentionally out of scope."""

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_workboard_fails_closed_without_a_configured_token(monkeypatch):
    monkeypatch.delenv("LOCAL_API_TOKEN", raising=False)
    get_settings.cache_clear()
    with TestClient(app) as client:
        response = client.get("/api/work-items")
    assert response.status_code == 503
    assert "LOCAL_API_TOKEN" in response.json()["detail"]


def test_browser_session_protects_reads_and_requires_csrf_on_writes(monkeypatch):
    monkeypatch.setenv("LOCAL_API_TOKEN", "unit-test-token")
    get_settings.cache_clear()
    with TestClient(app) as client:
        denied = client.get("/api/work-items")
        assert denied.status_code == 401
        assert denied.headers["www-authenticate"] == "Bearer"
        assert client.get("/api/work-items", headers={"Authorization": "Bearer wrong"}).status_code == 401
        login = client.post("/api/session", headers={"Authorization": "Bearer unit-test-token"})
        assert login.status_code == 201
        assert "httponly" in login.headers["set-cookie"].lower()
        csrf = login.json()["csrf_token"]
        assert client.get("/api/work-items").status_code == 200
        assert client.post("/api/work-items", json={"title": "CSRF protected"}).status_code == 403
        created = client.post("/api/work-items", json={"title": "CSRF protected"}, headers={"X-CSRF-Token": csrf})
        assert created.status_code == 201
        # Installed agents can continue using the bearer protocol without a browser cookie.
        assert client.get("/api/agent-context/" + created.json()["id"], headers={"Authorization": "Bearer unit-test-token"}).status_code == 200


def test_api_sets_non_persistent_browser_headers_and_rejects_large_json(monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "64")
    get_settings.cache_clear()
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.headers["cache-control"] == "no-store"
        assert health.headers["x-content-type-options"] == "nosniff"
        too_large = client.post("/api/work-items", content=b'{"title":"' + b"x" * 100 + b'"}', headers={"Content-Type": "application/json"})
    assert too_large.status_code == 413
