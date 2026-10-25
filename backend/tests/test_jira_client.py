"""``JiraClient`` mirrors the Graph client's shape (``app/integrations/graph.py``):
an injectable transport, a GET-only guard, and no network reachable from tests.

Jira differs from Graph in one respect the tests below pin: there is no OAuth
token exchange in front of it, so the client authenticates straight off
``Settings`` with a classic API token as Basic auth over ``email:token``
against ``https://<site>.atlassian.net``. Each behaviour is falsified
individually: a stub transport or a monkeypatched ``urlopen`` isolates
exactly one rule per test.
"""

from __future__ import annotations

import base64
import json
import threading
from collections.abc import Iterator
from email.message import Message
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.error import HTTPError

import pytest

import app.integrations.jira as jira_module
from app.config import Settings
from app.integrations.jira import (
    JiraClient,
    JiraConfigurationError,
    JiraError,
    JiraRateLimitError,
    default_transport,
)


def _configured_settings(**overrides: str) -> Settings:
    values = {
        "jira_site_url": "https://example.atlassian.net",
        "jira_account_email": "owner@example.com",
        "jira_api_token": "a-real-token",
    }
    values.update(overrides)
    return Settings(**values)


def test_jira_client_builds_basic_auth_header_from_email_and_token() -> None:
    client = JiraClient("https://example.atlassian.net", "owner@example.com", "a-real-token", transport=lambda *_: {})
    expected = base64.b64encode(b"owner@example.com:a-real-token").decode()
    assert client._headers["Authorization"] == f"Basic {expected}"


def test_jira_client_requests_against_the_configured_site_url() -> None:
    calls: list[tuple[str, str]] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append((method, url))
        return {"accountId": "abc"}

    client = JiraClient("https://example.atlassian.net", "owner@example.com", "token", transport=transport)
    client.myself()

    assert calls == [("GET", "https://example.atlassian.net/rest/api/3/myself")]


def test_jira_client_rejects_a_site_url_missing_the_https_scheme() -> None:
    """A bare host (no scheme) would otherwise reach ``urlopen`` and fail with an
    obscure ``URLError`` instead of a clear, fail-closed configuration error."""
    try:
        JiraClient("example.atlassian.net", "owner@example.com", "token")
    except JiraConfigurationError as error:
        assert "JIRA_SITE_URL" in str(error)
    else:
        raise AssertionError("schemeless site URL was accepted")


def test_jira_client_rejects_a_non_https_site_url() -> None:
    try:
        JiraClient("http://example.atlassian.net", "owner@example.com", "token")
    except JiraConfigurationError:
        pass
    else:
        raise AssertionError("non-https site URL was accepted")


def test_jira_client_strips_a_path_from_the_configured_site_url() -> None:
    """A site URL pasted with a trailing path or slash must not double up when a
    request path is appended to it."""
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        return {}

    client = JiraClient("https://example.atlassian.net/jira/", "owner@example.com", "token", transport=transport)
    client.myself()

    assert calls == ["https://example.atlassian.net/rest/api/3/myself"]


def test_jira_client_default_transport_rejects_non_get_methods() -> None:
    """The client only ever issues GET; the guard that enforces it lives in
    ``default_transport``, the transport actually used against the network."""
    try:
        default_transport("POST", "https://example.atlassian.net/rest/api/3/issue", {}, {"fields": {}})
    except JiraError as error:
        assert "GET" in str(error)
    else:
        raise AssertionError("a non-GET method was not rejected")


def test_jira_client_default_transport_handles_429_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    headers = Message()
    headers["Retry-After"] = "42"

    def fake_urlopen(request: object, **_: object) -> object:
        raise HTTPError("https://example.atlassian.net/rest/api/3/myself", 429, "Too Many Requests", headers, None)

    monkeypatch.setattr(jira_module._opener, "open", fake_urlopen)

    try:
        default_transport("GET", "https://example.atlassian.net/rest/api/3/myself", {}, None)
    except JiraRateLimitError as error:
        assert error.retry_after == "42"
    else:
        raise AssertionError("429 was not raised as JiraRateLimitError")


def test_jira_client_default_transport_wraps_non_2xx_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, **_: object) -> object:
        raise HTTPError("https://example.atlassian.net/rest/api/3/myself", 404, "Not Found", Message(), None)

    monkeypatch.setattr(jira_module._opener, "open", fake_urlopen)

    try:
        default_transport("GET", "https://example.atlassian.net/rest/api/3/myself", {}, None)
    except JiraError as error:
        assert not isinstance(error, JiraRateLimitError)
        assert "404" in str(error)
    else:
        raise AssertionError("a non-2xx response was not raised as JiraError")


class _RecordingServer:
    """A throwaway HTTP server on 127.0.0.1 that records the headers of every request."""

    def __init__(self, respond: Any) -> None:
        self.requests: list[dict[str, str]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                outer.requests.append({key.lower(): value for key, value in self.headers.items()})
                respond(self)

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


@pytest.fixture
def redirect_target() -> Iterator[_RecordingServer]:
    def answer(handler: BaseHTTPRequestHandler) -> None:
        body = b'{"accountId": "abc"}'
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    with _RecordingServer(answer) as server:
        yield server


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_jira_client_default_transport_refuses_a_redirect_and_never_follows_it(redirect_target: _RecordingServer, status: int) -> None:
    """``urlopen`` would replay the Authorization header at the redirect's target, on any
    host. The target here must never see a request, and the error must not name it."""

    def redirect(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(status)
        handler.send_header("Location", f"{redirect_target.url}/stolen")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    with _RecordingServer(redirect) as origin:
        with pytest.raises(JiraError) as error:
            default_transport("GET", f"{origin.url}/rest/api/3/myself", {"Authorization": "Basic a-real-token"}, None)

    assert str(error.value) == "Jira request was redirected"
    assert len(origin.requests) == 1
    assert origin.requests[0]["authorization"] == "Basic a-real-token"
    assert redirect_target.requests == []


def test_jira_client_default_transport_still_returns_json_from_a_server_that_does_not_redirect(redirect_target: _RecordingServer) -> None:
    result = default_transport("GET", f"{redirect_target.url}/rest/api/3/myself", {"Authorization": "Basic a-real-token"}, None)

    assert result == {"accountId": "abc"}


def test_jira_client_default_transport_never_reaches_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The client is exercised end to end through a stub transport in every other
    test; this one pins that ``default_transport`` is the only path that would
    ever touch the network, and that path is never taken here."""

    def forbidden(*_: object, **__: object) -> object:
        raise AssertionError("the opener must never be called from a test")

    monkeypatch.setattr(jira_module._opener, "open", forbidden)

    client = JiraClient("https://example.atlassian.net", "owner@example.com", "token", transport=lambda *_: {"accountId": "x"})
    client.myself()


def test_jira_client_default_transport_returns_parsed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"accountId": "abc"}).encode()

    monkeypatch.setattr(jira_module._opener, "open", lambda request, **_: FakeResponse())

    result = default_transport("GET", "https://example.atlassian.net/rest/api/3/myself", {}, None)

    assert result == {"accountId": "abc"}


def test_jira_client_from_settings_builds_a_working_client() -> None:
    settings = _configured_settings()

    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        return {"accountId": "abc"}

    client = JiraClient.from_settings(settings, transport=transport)
    client.myself()

    assert calls == ["https://example.atlassian.net/rest/api/3/myself"]


def test_jira_client_from_settings_fails_closed_on_missing_configuration() -> None:
    """Construction is the one call site every future caller has to go through, so
    it reuses ``Settings.jira_configuration_errors()`` rather than re-deriving the
    presence check -- a stack trace is not an acceptable failure mode here."""
    settings = Settings()

    try:
        JiraClient.from_settings(settings)
    except JiraConfigurationError as error:
        assert "JIRA_SITE_URL" in str(error)
        assert "JIRA_ACCOUNT_EMAIL" in str(error)
        assert "JIRA_API_TOKEN" in str(error)
    else:
        raise AssertionError("missing Jira configuration was not rejected")
