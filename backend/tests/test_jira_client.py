"""``JiraClient`` mirrors the Graph client's shape (``app/integrations/graph.py``):
an injectable transport, a GET-only guard, and no network reachable from tests.

Jira differs from Graph in one respect the tests below pin: there is no OAuth
token exchange in front of it, so the client authenticates straight off
``Settings`` with a classic API token as Basic auth over ``email:token``
against ``https://<site>.atlassian.net`` -- never the scoped-token host,
which would 401. Each behaviour is falsified individually: a stub transport
or a monkeypatched ``urlopen`` isolates exactly one rule per test.
"""

from __future__ import annotations

import base64
import json
from email.message import Message
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


def test_jira_client_search_issues_sends_jql_and_returns_the_issue_list() -> None:
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        assert method == "GET"
        return {"issues": [{"key": "PROJ-1"}, {"key": "PROJ-2"}]}

    client = JiraClient("https://example.atlassian.net", "owner@example.com", "token", transport=transport)
    issues = client.search_issues("assignee=currentUser()", fields=("summary", "status"))

    assert issues == [{"key": "PROJ-1"}, {"key": "PROJ-2"}]
    assert len(calls) == 1
    assert calls[0].startswith("https://example.atlassian.net/rest/api/3/search?")
    assert "jql=assignee%3DcurrentUser%28%29" in calls[0]
    assert "fields=summary,status" in calls[0]


def test_jira_client_default_transport_rejects_non_get_methods() -> None:
    """The GET-only guard lives in the transport actually used against the network,
    not only in the client -- a caller cannot smuggle a write past it."""
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

    monkeypatch.setattr(jira_module, "urlopen", fake_urlopen)

    try:
        default_transport("GET", "https://example.atlassian.net/rest/api/3/myself", {}, None)
    except JiraRateLimitError as error:
        assert error.retry_after == "42"
    else:
        raise AssertionError("429 was not raised as JiraRateLimitError")


def test_jira_client_default_transport_wraps_non_2xx_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, **_: object) -> object:
        raise HTTPError("https://example.atlassian.net/rest/api/3/myself", 404, "Not Found", Message(), None)

    monkeypatch.setattr(jira_module, "urlopen", fake_urlopen)

    try:
        default_transport("GET", "https://example.atlassian.net/rest/api/3/myself", {}, None)
    except JiraError as error:
        assert not isinstance(error, JiraRateLimitError)
        assert "404" in str(error)
    else:
        raise AssertionError("a non-2xx response was not raised as JiraError")


def test_jira_client_default_transport_never_reaches_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The client is exercised end to end through a stub transport in every other
    test; this one pins that ``default_transport`` is the only path that would
    ever touch the network, and that path is never taken here."""

    def forbidden(*_: object, **__: object) -> object:
        raise AssertionError("urlopen must never be called from a test")

    monkeypatch.setattr(jira_module, "urlopen", forbidden)

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

    monkeypatch.setattr(jira_module, "urlopen", lambda request, **_: FakeResponse())

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
