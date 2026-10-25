"""Graph access tokens last about an hour; sync must refresh them itself.

The token endpoint is faked by monkeypatching the opener in ``app.services.oauth``
and Graph by swapping the ``GraphClient`` that ``app.services.sync`` builds for one
with a recording transport, so every test drives the real refresh code and can see
which bearer token each Graph request actually carried.
"""

import io
import json
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs

import pytest

from app.config import Settings
from app.integrations import graph as graph_module
from app.integrations.graph import GraphAuthError, GraphClient, default_transport
from app.services import oauth as oauth_module
from app.services import sync as sync_module
from app.services.crypto import EncryptedTokenStore, generate_encryption_key
from app.services.oauth import exchange_code, refresh_access_token
from app.services.sync import SyncError, sync


class FakeResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = json.dumps(body).encode()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class FakeTokenEndpoint:
    """Stands in for ``login.microsoftonline.com``'s token endpoint."""

    def __init__(self, response: dict[str, Any] | None = None, status: int | None = None) -> None:
        self.response = response or {}
        self.status = status
        self.forms: list[dict[str, list[str]]] = []

    def __call__(self, request: Any, **_: object) -> FakeResponse:
        self.forms.append(parse_qs(request.data.decode()))
        if self.status is not None:
            raise HTTPError(request.full_url, self.status, "error", {}, io.BytesIO(b'{"error":"invalid_grant"}'))
        return FakeResponse(self.response)


class FakeGraph:
    """Answers Graph requests, rejecting any bearer token not in ``valid_tokens``."""

    def __init__(self, valid_tokens: set[str]) -> None:
        self.valid_tokens = valid_tokens
        self.bearers: list[str] = []

    def client(self, access_token: str) -> GraphClient:
        return GraphClient(access_token, self.transport)

    def transport(self, method: str, url: str, headers: dict[str, str], payload: object) -> dict[str, Any]:
        bearer = headers["Authorization"].removeprefix("Bearer ")
        self.bearers.append(bearer)
        if bearer not in self.valid_tokens:
            raise GraphAuthError("Microsoft Graph rejected the access token")
        if "/me?$select=" in url:
            return {"id": "expected-oid"}
        if "/me/mailFolders/" in url:
            return {"value": []}
        raise AssertionError(url)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        microsoft_tenant_id="tenant", microsoft_client_id="client", microsoft_client_secret="secret",
        microsoft_target_user_id="expected-oid", app_encryption_key=generate_encryption_key(),
        token_store_path=tmp_path / "tokens",
    )


def _store(settings: Settings) -> EncryptedTokenStore:
    return EncryptedTokenStore(settings.token_store_path, settings.app_encryption_key.get_secret_value())


def _install(monkeypatch: pytest.MonkeyPatch, endpoint: FakeTokenEndpoint, graph: FakeGraph) -> None:
    monkeypatch.setattr(oauth_module._opener, "open", endpoint)
    monkeypatch.setattr(sync_module, "GraphClient", graph.client)


def test_exchange_code_records_an_absolute_expiry(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oauth_module._opener, "open", FakeTokenEndpoint({"access_token": "a1", "refresh_token": "r1", "expires_in": 3600}))
    before = time.time()
    token = exchange_code(settings, "code", "verifier")
    assert before + 3600 <= token["expires_at"] <= time.time() + 3600


def test_refresh_posts_the_refresh_grant(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    endpoint = FakeTokenEndpoint({"access_token": "a2", "refresh_token": "r2", "expires_in": 3600})
    monkeypatch.setattr(oauth_module._opener, "open", endpoint)
    token = refresh_access_token(settings, "r1")
    form = endpoint.forms[0]
    assert form["grant_type"] == ["refresh_token"]
    assert form["refresh_token"] == ["r1"]
    assert "offline_access" in form["scope"][0].split()
    assert token["access_token"] == "a2"
    assert token["refresh_token"] == "r2"


def test_refresh_keeps_the_old_refresh_token_when_microsoft_does_not_rotate_it(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oauth_module._opener, "open", FakeTokenEndpoint({"access_token": "a2", "expires_in": 3600}))
    assert refresh_access_token(settings, "r1")["refresh_token"] == "r1"


def test_sync_refreshes_an_expired_token_before_calling_graph(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    _store(settings).save({"access_token": "stale", "refresh_token": "r1", "expires_at": time.time() - 10})
    graph = FakeGraph(valid_tokens={"fresh"})
    _install(monkeypatch, FakeTokenEndpoint({"access_token": "fresh", "refresh_token": "r2", "expires_in": 3600}), graph)

    sync(settings)

    assert graph.bearers and set(graph.bearers) == {"fresh"}
    saved = _store(settings).load()
    assert saved["access_token"] == "fresh"
    assert saved["refresh_token"] == "r2"
    assert b"fresh" not in settings.token_store_path.read_bytes()


def test_sync_does_not_refresh_a_token_that_is_still_valid(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    _store(settings).save({"access_token": "live", "refresh_token": "r1", "expires_at": time.time() + 3600})
    endpoint = FakeTokenEndpoint({"access_token": "unused"})
    graph = FakeGraph(valid_tokens={"live"})
    _install(monkeypatch, endpoint, graph)

    sync(settings)

    assert endpoint.forms == []
    assert set(graph.bearers) == {"live"}


def test_sync_refreshes_once_and_retries_when_graph_answers_401(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    # No ``expires_at``: a token stored before expiry tracking existed, revoked early.
    _store(settings).save({"access_token": "revoked", "refresh_token": "r1"})
    endpoint = FakeTokenEndpoint({"access_token": "fresh", "refresh_token": "r2", "expires_in": 3600})
    graph = FakeGraph(valid_tokens={"fresh"})
    _install(monkeypatch, endpoint, graph)

    result = sync(settings)

    assert result["mode"] == "read-only"
    assert len(endpoint.forms) == 1
    assert graph.bearers[0] == "revoked"
    assert set(graph.bearers[1:]) == {"fresh"}
    assert _store(settings).load()["access_token"] == "fresh"


def test_sync_gives_up_when_the_refreshed_token_is_rejected_too(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    _store(settings).save({"access_token": "revoked", "refresh_token": "r1"})
    endpoint = FakeTokenEndpoint({"access_token": "also-rejected", "expires_in": 3600})
    _install(monkeypatch, endpoint, FakeGraph(valid_tokens=set()))

    with pytest.raises(SyncError, match="reconnect"):
        sync(settings)
    assert len(endpoint.forms) == 1


def test_sync_does_not_refresh_twice_when_a_just_refreshed_token_is_rejected(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    _store(settings).save({"access_token": "stale", "refresh_token": "r1", "expires_at": time.time() - 10})
    endpoint = FakeTokenEndpoint({"access_token": "also-rejected", "expires_in": 3600})
    _install(monkeypatch, endpoint, FakeGraph(valid_tokens=set()))

    with pytest.raises(SyncError, match="reconnect"):
        sync(settings)
    assert len(endpoint.forms) == 1


def test_sync_asks_for_reconnect_when_the_refresh_token_is_refused(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    stored = {"access_token": "stale", "refresh_token": "r1", "expires_at": time.time() - 10}
    _store(settings).save(stored)
    _install(monkeypatch, FakeTokenEndpoint(status=400), FakeGraph(valid_tokens=set()))

    with pytest.raises(SyncError, match="reconnect"):
        sync(settings)
    assert _store(settings).load() == stored


def test_sync_asks_for_reconnect_when_an_expired_token_has_no_refresh_token(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    _store(settings).save({"access_token": "stale", "expires_at": time.time() - 10})
    endpoint = FakeTokenEndpoint({"access_token": "unused"})
    _install(monkeypatch, endpoint, FakeGraph(valid_tokens=set()))

    with pytest.raises(SyncError, match="reconnect"):
        sync(settings)
    assert endpoint.forms == []


def test_default_transport_reports_401_as_an_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def unauthorized(request: Any, **_: object) -> None:
        raise HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b""))

    monkeypatch.setattr(graph_module._opener, "open", unauthorized)
    with pytest.raises(GraphAuthError):
        default_transport("GET", "https://graph.microsoft.com/v1.0/me", {}, None)
