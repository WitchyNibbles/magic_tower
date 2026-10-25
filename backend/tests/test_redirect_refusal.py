"""Graph and the Microsoft token endpoint must never follow a redirect.

``urlopen`` follows a 3xx and copies the request's headers, the bearer token
included, to wherever it points. Each test runs two throwaway servers on 127.0.0.1:
the origin answers with a redirect, the target must never be contacted. For the
token endpoint's POST, the target seeing nothing also proves the authorization code,
client secret and refresh token in the body went nowhere else.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.config import Settings
from app.integrations.graph import GraphError, default_transport
from app.services import oauth as oauth_module
from app.services.crypto import generate_encryption_key
from app.services.oauth import OAuthError, exchange_code, refresh_access_token

REDIRECT_STATUSES = [301, 302, 303, 307, 308]
SECRET = "a-client-secret-value"
REFRESH_TOKEN = "a-refresh-token-value"


class _RecordingServer:
    """A throwaway HTTP server on 127.0.0.1 that records every request it receives."""

    def __init__(self, respond: Callable[[BaseHTTPRequestHandler], None]) -> None:
        self.requests: list[dict[str, str]] = []
        self.bodies: list[bytes] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _record(self) -> None:
                outer.requests.append({key.lower(): value for key, value in self.headers.items()})
                outer.bodies.append(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                respond(self)

            do_GET = do_POST = _record

            def log_message(self, *_: object) -> None:
                return None

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "_RecordingServer":
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _json_answer(body: dict[str, object]) -> Callable[[BaseHTTPRequestHandler], None]:
    def answer(handler: BaseHTTPRequestHandler) -> None:
        payload = json.dumps(body).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)

    return answer


def _redirect_to(location: str, status: int) -> Callable[[BaseHTTPRequestHandler], None]:
    def redirect(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(status)
        handler.send_header("Location", location)
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    return redirect


@pytest.fixture
def target() -> Iterator[_RecordingServer]:
    with _RecordingServer(_json_answer({"access_token": "stolen", "id": "stolen"})) as server:
        yield server


@pytest.fixture
def settings() -> Settings:
    return Settings(
        microsoft_tenant_id="tenant", microsoft_client_id="client", microsoft_client_secret=SECRET,
        microsoft_target_user_id="expected-oid", app_encryption_key=generate_encryption_key(),
    )


@pytest.mark.parametrize("status", REDIRECT_STATUSES)
def test_graph_default_transport_refuses_a_redirect_and_never_follows_it(target: _RecordingServer, status: int) -> None:
    with _RecordingServer(_redirect_to(f"{target.url}/stolen", status)) as origin:
        with pytest.raises(GraphError) as error:
            default_transport("GET", f"{origin.url}/v1.0/me", {"Authorization": "Bearer a-real-token"}, None)

    assert str(error.value) == "Microsoft Graph request was redirected"
    assert len(origin.requests) == 1
    assert origin.requests[0]["authorization"] == "Bearer a-real-token"
    assert target.requests == []


def test_graph_default_transport_still_returns_json_from_a_server_that_does_not_redirect() -> None:
    with _RecordingServer(_json_answer({"id": "abc"})) as server:
        result = default_transport("GET", f"{server.url}/v1.0/me", {"Authorization": "Bearer a-real-token"}, None)

    assert result == {"id": "abc"}


@pytest.mark.parametrize("status", REDIRECT_STATUSES)
@pytest.mark.parametrize("call", ["exchange_code", "refresh_access_token"])
def test_token_endpoint_refuses_a_redirect_and_sends_no_secret_to_its_target(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, target: _RecordingServer, status: int, call: str,
) -> None:
    with _RecordingServer(_redirect_to(f"{target.url}/stolen", status)) as origin:
        monkeypatch.setattr(oauth_module, "LOGIN_ROOT", origin.url)
        with pytest.raises(OAuthError) as error:
            if call == "exchange_code":
                exchange_code(settings, "an-authorization-code", "a-verifier")
            else:
                refresh_access_token(settings, REFRESH_TOKEN)

    assert str(error.value) == "Microsoft token exchange was redirected"
    assert len(origin.requests) == 1
    assert SECRET.encode() in origin.bodies[0]
    assert target.requests == []
    assert target.bodies == []


def test_token_endpoint_still_returns_the_token_from_a_server_that_does_not_redirect(
    settings: Settings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _RecordingServer(_json_answer({"access_token": "a1", "expires_in": 3600})) as server:
        monkeypatch.setattr(oauth_module, "LOGIN_ROOT", server.url)
        token = refresh_access_token(settings, REFRESH_TOKEN)

    assert token["access_token"] == "a1"
    assert token["refresh_token"] == REFRESH_TOKEN
    assert server.requests[0]["content-type"] == "application/x-www-form-urlencoded"
