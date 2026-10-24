"""``FreshserviceClient``: a narrow, read-only Freshservice client with an injectable
transport, shaped like ``JiraClient`` (``test_jira_client.py`` and ``test_jira_query.py``).

Freshservice authenticates with Basic auth over ``<api key>:X`` against
``https://<domain>.freshservice.com``, pages its ticket filter 30 at a time with a
``total`` it reports itself, and wants the filter query wrapped in double quotes and
URL-encoded. Each rule is falsified individually: a stub transport or a monkeypatched
``urlopen`` isolates exactly one of them per test, and nothing here reaches the network.
All hosts, keys and addresses are invented.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import date
from email.message import Message
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlparse

import pytest

import app.integrations.freshservice as freshservice_module
from app.config import Settings
from app.integrations.freshservice import (
    FRESHSERVICE_FILTER_MAX_PAGES,
    FRESHSERVICE_PAGE_SIZE,
    FreshserviceAgent,
    FreshserviceClient,
    FreshserviceConfigurationError,
    FreshserviceError,
    FreshserviceRateLimitError,
    assigned_tickets_query,
    default_transport,
)

BASE = "https://example.freshservice.com"


def _client(transport: Any) -> FreshserviceClient:
    return FreshserviceClient(BASE, "a-real-key", transport=transport)


def _tickets(first_id: int, count: int) -> list[dict[str, Any]]:
    return [{"id": first_id + offset, "subject": f"Invented ticket {first_id + offset}"} for offset in range(count)]


def _page_of(url: str) -> int:
    return int(parse_qs(urlparse(url).query)["page"][0])


# --- construction, auth, URL ------------------------------------------------------------


def test_freshservice_client_builds_basic_auth_header_from_the_key_and_x() -> None:
    client = _client(lambda *_: {})
    expected = base64.b64encode(b"a-real-key:X").decode()
    assert client._headers["Authorization"] == f"Basic {expected}"


def test_freshservice_client_asks_for_json() -> None:
    assert _client(lambda *_: {})._headers["Accept"] == "application/json"


def test_freshservice_client_requests_against_the_configured_url() -> None:
    calls: list[tuple[str, str]] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append((method, url))
        return {"agent": {}}

    _client(transport).current_agent()

    assert calls == [("GET", f"{BASE}/api/v2/agents/me")]


@pytest.mark.parametrize("url", ["example.freshservice.com", "http://example.freshservice.com", "https://", ""])
def test_freshservice_client_rejects_a_url_that_is_not_a_full_https_url(url: str) -> None:
    """A schemeless value would otherwise reach ``urlopen`` and fail with an opaque
    ``URLError``."""
    with pytest.raises(FreshserviceConfigurationError) as error:
        FreshserviceClient(url, "a-real-key")

    assert "FRESHSERVICE_URL" in str(error.value)


def test_freshservice_client_configuration_error_names_the_setting_not_the_value() -> None:
    with pytest.raises(FreshserviceConfigurationError) as error:
        FreshserviceClient("http://internal-name-only.example", "a-real-key")

    assert "internal-name-only" not in str(error.value)


def test_freshservice_client_strips_a_path_from_the_configured_url() -> None:
    """A URL pasted with a trailing path or slash must not double up when a request
    path is appended to it."""
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        return {}

    FreshserviceClient(f"{BASE}/a/dashboard/", "a-real-key", transport=transport).current_agent()

    assert calls == [f"{BASE}/api/v2/agents/me"]


def test_freshservice_client_exposes_the_validated_base_url_for_building_ticket_links() -> None:
    assert FreshserviceClient(f"{BASE}/a/", "a-real-key", transport=lambda *_: {}).base_url == BASE


def test_freshservice_client_from_settings_builds_a_working_client() -> None:
    settings = Settings(freshservice_url=BASE, freshservice_api_key="a-real-key")
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        return {}

    FreshserviceClient.from_settings(settings, transport=transport).current_agent()

    assert calls == [f"{BASE}/api/v2/agents/me"]


def test_freshservice_client_from_settings_fails_closed_on_missing_configuration() -> None:
    with pytest.raises(FreshserviceConfigurationError) as error:
        FreshserviceClient.from_settings(Settings())

    assert "FRESHSERVICE_URL" in str(error.value)
    assert "FRESHSERVICE_API_KEY" in str(error.value)


# --- default transport ------------------------------------------------------------------


def test_freshservice_default_transport_rejects_non_get_methods() -> None:
    with pytest.raises(FreshserviceError, match="GET"):
        default_transport("POST", f"{BASE}/api/v2/tickets", {}, {"subject": "x"})


def test_freshservice_default_transport_handles_429_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    headers = Message()
    headers["Retry-After"] = "42"

    def fake_urlopen(request: object, **_: object) -> object:
        raise HTTPError(f"{BASE}/api/v2/tickets/filter", 429, "Too Many Requests", headers, None)

    monkeypatch.setattr(freshservice_module._opener, "open", fake_urlopen)

    with pytest.raises(FreshserviceRateLimitError) as error:
        default_transport("GET", f"{BASE}/api/v2/tickets/filter", {}, None)

    assert error.value.retry_after == "42"
    assert "42" in str(error.value)


def test_freshservice_default_transport_429_without_retry_after_still_raises_the_rate_limit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, **_: object) -> object:
        raise HTTPError(f"{BASE}/api/v2/tickets/filter", 429, "Too Many Requests", Message(), None)

    monkeypatch.setattr(freshservice_module._opener, "open", fake_urlopen)

    with pytest.raises(FreshserviceRateLimitError) as error:
        default_transport("GET", f"{BASE}/api/v2/tickets/filter", {}, None)

    assert error.value.retry_after is None


def test_freshservice_default_transport_wraps_other_http_errors_with_only_the_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, **_: object) -> object:
        raise HTTPError(f"{BASE}/api/v2/tickets/filter?query=secret", 403, "Forbidden", Message(), None)

    monkeypatch.setattr(freshservice_module._opener, "open", fake_urlopen)

    with pytest.raises(FreshserviceError) as error:
        default_transport("GET", f"{BASE}/api/v2/tickets/filter", {}, None)

    assert not isinstance(error.value, FreshserviceRateLimitError)
    assert str(error.value) == "Freshservice request failed with status 403"


def test_freshservice_default_transport_hides_the_url_and_headers_of_a_failed_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport failure's own text can carry the request URL or an auth header."""

    def fake_urlopen(request: object, **_: object) -> object:
        raise OSError(f"connection refused for {BASE}/api/v2/agents Authorization: Basic a-real-key")

    monkeypatch.setattr(freshservice_module._opener, "open", fake_urlopen)

    with pytest.raises(FreshserviceError) as error:
        default_transport("GET", f"{BASE}/api/v2/agents", {"Authorization": "Basic a-real-key"}, None)

    assert str(error.value) == "Freshservice request failed"


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
        body = b'{"agent": {"id": 7}}'
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    with _RecordingServer(answer) as server:
        yield server


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_freshservice_default_transport_refuses_a_redirect_and_never_follows_it(redirect_target: _RecordingServer, status: int) -> None:
    """``urlopen`` would replay the Authorization header at the redirect's target, on any
    host. The target here must never see a request, and the error must not name it."""

    def redirect(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(status)
        handler.send_header("Location", f"{redirect_target.url}/stolen")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    with _RecordingServer(redirect) as origin:
        with pytest.raises(FreshserviceError) as error:
            default_transport("GET", f"{origin.url}/api/v2/agents/me", {"Authorization": "Basic a-real-key"}, None)

    assert str(error.value) == "Freshservice request was redirected"
    assert len(origin.requests) == 1
    assert origin.requests[0]["authorization"] == "Basic a-real-key"
    assert redirect_target.requests == []


def test_freshservice_default_transport_still_returns_json_from_a_server_that_does_not_redirect(redirect_target: _RecordingServer) -> None:
    result = default_transport("GET", f"{redirect_target.url}/api/v2/agents/me", {"Authorization": "Basic a-real-key"}, None)

    assert result == {"agent": {"id": 7}}


def test_freshservice_default_transport_returns_parsed_json_with_a_fifteen_second_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"agent": {"id": 7}}).encode()

    def fake_urlopen(request: Any, **kwargs: Any) -> FakeResponse:
        seen["method"] = request.get_method()
        seen["timeout"] = kwargs.get("timeout")
        return FakeResponse()

    monkeypatch.setattr(freshservice_module._opener, "open", fake_urlopen)

    result = default_transport("GET", f"{BASE}/api/v2/agents/me", {}, None)

    assert result == {"agent": {"id": 7}}
    assert seen == {"method": "GET", "timeout": 15}


def test_freshservice_client_never_reaches_the_network_through_a_stub_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_: object, **__: object) -> object:
        raise AssertionError("the opener must never be called from a test")

    monkeypatch.setattr(freshservice_module._opener, "open", forbidden)

    _client(lambda *_: {"tickets": []}).search_assigned_tickets(7, date(2026, 10, 1))


def test_freshservice_client_a_response_that_is_not_an_object_is_a_freshservice_error() -> None:
    """A 200 whose body is a JSON list would otherwise raise a bare ``AttributeError``
    out of the connector's own exception hierarchy, past a sync's ``except``."""
    with pytest.raises(FreshserviceError):
        _client(lambda *_: [{"id": 1}]).search_assigned_tickets(7, date(2026, 10, 1))


# --- query builder ----------------------------------------------------------------------


def test_freshservice_query_is_assigned_and_open_or_pending_or_recently_updated() -> None:
    assert assigned_tickets_query(42, date(2026, 10, 9)) == (
        "agent_id:42 AND (status:2 OR status:3 OR updated_at:>'2026-10-09')"
    )


def test_freshservice_query_zero_pads_the_date() -> None:
    assert "updated_at:>'2026-01-05'" in assigned_tickets_query(1, date(2026, 1, 5))


@pytest.mark.parametrize("agent_id", ["42", "42 OR agent_id:1", 4.2, None, True, False])
def test_freshservice_query_refuses_an_agent_id_that_is_not_an_int(agent_id: Any) -> None:
    """The id is spliced into the query text, so a string would be injected as written
    and ``bool`` (an ``int`` subclass) is never an id anyone meant."""
    with pytest.raises(ValueError):
        assigned_tickets_query(agent_id, date(2026, 10, 9))


@pytest.mark.parametrize("since", ["2026-10-09' OR status:5", None, 20261009])
def test_freshservice_query_refuses_a_since_that_is_not_a_date(since: Any) -> None:
    with pytest.raises(ValueError):
        assigned_tickets_query(42, since)


# --- search request shape ---------------------------------------------------------------


def test_freshservice_search_requests_the_filter_endpoint_with_the_quoted_encoded_query() -> None:
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        return {"tickets": [], "total": 0}

    _client(transport).search_assigned_tickets(42, date(2026, 10, 9))

    assert len(calls) == 1
    parsed = urlparse(calls[0])
    assert parsed.path == "/api/v2/tickets/filter"
    # The query value is wrapped in double quotes, as the API requires...
    assert parse_qs(parsed.query)["query"] == [f'"{assigned_tickets_query(42, date(2026, 10, 9))}"']
    # ...and is encoded on the wire: no raw space, quote, colon-greater-than or apostrophe.
    raw_query = parsed.query
    assert " " not in raw_query and '"' not in raw_query and "'" not in raw_query and ">" not in raw_query
    assert unquote(raw_query.split("&")[0]) == f'query="{assigned_tickets_query(42, date(2026, 10, 9))}"'


def test_freshservice_search_does_not_send_a_per_page_parameter() -> None:
    """The filter endpoint pages 30 at a time and takes no ``per_page``."""
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        return {"tickets": []}

    _client(transport).search_assigned_tickets(42, date(2026, 10, 9))

    assert "per_page" not in parse_qs(urlparse(calls[0]).query)


def test_freshservice_search_sends_the_stub_transport_the_auth_headers() -> None:
    seen: list[dict[str, str]] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        seen.append(headers)
        return {"tickets": []}

    _client(transport).search_assigned_tickets(42, date(2026, 10, 9))

    assert seen[0]["Authorization"].startswith("Basic ")


# --- paging -----------------------------------------------------------------------------


def test_freshservice_search_stops_after_a_short_page() -> None:
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        return {"tickets": _tickets(1, FRESHSERVICE_PAGE_SIZE - 1)}

    tickets = _client(transport).search_assigned_tickets(42, date(2026, 10, 9))

    assert len(calls) == 1
    assert len(tickets) == FRESHSERVICE_PAGE_SIZE - 1
    assert not tickets.truncated


def test_freshservice_search_follows_pages_until_a_short_one() -> None:
    pages = {1: _tickets(1, 30), 2: _tickets(31, 30), 3: _tickets(61, 5)}
    calls: list[int] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(_page_of(url))
        return {"tickets": pages[_page_of(url)]}

    tickets = _client(transport).search_assigned_tickets(42, date(2026, 10, 9))

    assert calls == [1, 2, 3]
    assert [ticket["id"] for ticket in tickets] == list(range(1, 66))
    assert not tickets.truncated


def test_freshservice_search_stops_once_the_total_is_reached_even_on_a_full_page() -> None:
    """Exactly 30 tickets: the first page is full, so only ``total`` says there is no
    second request to make."""
    calls: list[int] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(_page_of(url))
        return {"tickets": _tickets(1, 30), "total": 30}

    tickets = _client(transport).search_assigned_tickets(42, date(2026, 10, 9))

    assert calls == [1]
    assert len(tickets) == 30
    assert not tickets.truncated


def test_freshservice_search_stops_on_an_empty_page() -> None:
    calls: list[int] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(_page_of(url))
        return {"tickets": _tickets(1, 30)} if _page_of(url) == 1 else {"tickets": []}

    tickets = _client(transport).search_assigned_tickets(42, date(2026, 10, 9))

    assert calls == [1, 2]
    assert len(tickets) == 30
    assert not tickets.truncated


@pytest.mark.parametrize("tickets", [5, 0, True, False, {"id": 1}, {}, "tickets"])
def test_freshservice_search_refuses_a_tickets_value_that_is_not_a_list(tickets: Any) -> None:
    """A dict would otherwise be counted by its keys and an int would be a ``TypeError``."""
    with pytest.raises(FreshserviceError) as error:
        _client(lambda *_: {"tickets": tickets}).search_assigned_tickets(7, date(2026, 10, 9))

    assert type(error.value) is FreshserviceError
    assert str(error.value) == "Freshservice returned an unexpected response"


@pytest.mark.parametrize("body", [{"tickets": None}, {}, {"tickets": None, "total": None}])
def test_freshservice_search_treats_a_null_or_missing_tickets_array_as_empty(body: dict[str, Any]) -> None:
    """``{"tickets": null}`` returns ``None`` for a present key, so a bare ``.get``
    default never fires and ``.extend(None)`` would raise ``TypeError`` instead of
    the ``FreshserviceError`` a sync's caller catches."""
    assert _client(lambda *_: body).search_assigned_tickets(42, date(2026, 10, 9)) == []


def test_freshservice_search_reports_the_total_the_api_gave() -> None:
    tickets = _client(lambda *_: {"tickets": _tickets(1, 3), "total": 3}).search_assigned_tickets(42, date(2026, 10, 9))

    assert tickets.total == 3


@pytest.mark.parametrize("total", [None, "3", 3.5, True])
def test_freshservice_search_total_is_none_when_the_api_gives_no_usable_count(total: Any) -> None:
    tickets = _client(lambda *_: {"tickets": _tickets(1, 3), "total": total}).search_assigned_tickets(42, date(2026, 10, 9))

    assert tickets.total is None


def test_freshservice_search_pagination_is_bounded_against_a_server_that_always_has_more() -> None:
    call_count = 0

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        nonlocal call_count
        call_count += 1
        return {"tickets": _tickets(call_count * 100, FRESHSERVICE_PAGE_SIZE), "total": 10_000}

    tickets = _client(transport).search_assigned_tickets(42, date(2026, 10, 9))

    assert call_count == FRESHSERVICE_FILTER_MAX_PAGES
    assert len(tickets) == FRESHSERVICE_FILTER_MAX_PAGES * FRESHSERVICE_PAGE_SIZE
    assert tickets.truncated


def test_freshservice_search_cut_off_by_the_page_cap_warns_naming_the_kind_not_the_query(caplog: pytest.LogCaptureFixture) -> None:
    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        return {"tickets": _tickets(1, FRESHSERVICE_PAGE_SIZE), "total": 10_000}

    with caplog.at_level(logging.WARNING, logger=freshservice_module.logger.name):
        tickets = _client(transport).search_assigned_tickets(42, date(2026, 10, 9))

    assert tickets.truncated
    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    assert "assigned" in record.getMessage()
    assert "not fetched" in record.getMessage()
    assert "older" not in record.getMessage()
    assert "agent_id" not in record.getMessage()
    assert "42" not in record.getMessage()


def test_freshservice_search_full_pages_with_no_total_are_truncated_at_the_cap() -> None:
    """Without a ``total`` there is nothing to say the last allowed page was the last."""
    tickets = _client(lambda *_: {"tickets": _tickets(1, FRESHSERVICE_PAGE_SIZE)}).search_assigned_tickets(42, date(2026, 10, 9))

    assert tickets.truncated


def test_freshservice_search_that_ends_exactly_on_the_last_allowed_page_is_not_truncated(caplog: pytest.LogCaptureFixture) -> None:
    total = FRESHSERVICE_FILTER_MAX_PAGES * FRESHSERVICE_PAGE_SIZE

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        return {"tickets": _tickets(_page_of(url) * 100, FRESHSERVICE_PAGE_SIZE), "total": total}

    with caplog.at_level(logging.WARNING, logger=freshservice_module.logger.name):
        tickets = _client(transport).search_assigned_tickets(42, date(2026, 10, 9))

    assert len(tickets) == total
    assert not tickets.truncated
    assert not caplog.records


# --- agent lookups ----------------------------------------------------------------------


def test_freshservice_find_agent_by_email_queries_the_agents_endpoint_with_the_encoded_email() -> None:
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        return {"agents": [{"id": 9, "first_name": "Ada", "last_name": "Example", "email": "agent+tag@example.com"}]}

    agent = _client(transport).find_agent_by_email("agent+tag@example.com")

    parsed = urlparse(calls[0])
    assert parsed.path == "/api/v2/agents"
    assert parse_qs(parsed.query)["email"] == ["agent+tag@example.com"]
    assert "+" not in parsed.query.split("=", 1)[1]
    assert agent == FreshserviceAgent(id=9, name="Ada Example")


def test_freshservice_find_agent_by_email_strips_the_address_before_sending_and_comparing() -> None:
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        return {"agents": [{"id": 9, "email": "agent@example.com"}]}

    agent = _client(transport).find_agent_by_email("  Agent@Example.com \n")

    assert parse_qs(urlparse(calls[0]).query)["email"] == ["Agent@Example.com"]
    assert "%20" not in calls[0] and "%0A" not in calls[0]
    assert agent is not None and agent.id == 9


def test_freshservice_find_agent_by_email_matches_the_address_case_insensitively() -> None:
    agents = {"agents": [{"id": 9, "first_name": "Ada", "last_name": "Example", "email": "Agent@Example.com"}]}

    agent = _client(lambda *_: agents).find_agent_by_email("agent@example.com")

    assert agent is not None and agent.id == 9


def test_freshservice_find_agent_by_email_ignores_entries_for_other_addresses() -> None:
    """The lookup must not hand back whoever the API happened to list first if it did
    not honour the filter: an owner picked that way would be somebody else."""
    agents = {"agents": [{"id": 1, "first_name": "Other", "last_name": "Person", "email": "other@example.com"}]}

    assert _client(lambda *_: agents).find_agent_by_email("agent@example.com") is None


def test_freshservice_find_agent_by_email_picks_the_matching_entry_among_several() -> None:
    agents = {"agents": [
        {"id": 1, "first_name": "Other", "last_name": "Person", "email": "other@example.com"},
        {"id": 2, "first_name": "Ada", "last_name": "Example", "email": "agent@example.com"},
    ]}

    agent = _client(lambda *_: agents).find_agent_by_email("agent@example.com")

    assert agent is not None and agent.id == 2


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"agents": None},
        {"agents": []},
        {"agents": {"id": 9}},
        {"agents": "nope"},
        {"agents": [None, 3, "x", []]},
        {"agents": [{"first_name": "Ada", "email": "agent@example.com"}]},
        {"agents": [{"id": "9", "email": "agent@example.com"}]},
        {"agents": [{"id": True, "email": "agent@example.com"}]},
        {"agents": [{"id": 9, "email": None}]},
    ],
)
def test_freshservice_find_agent_by_email_is_tolerant_of_any_other_shape(body: dict[str, Any]) -> None:
    """Unknown owner, never a crash: the sync turns ``None`` into a clear error."""
    assert _client(lambda *_: body).find_agent_by_email("agent@example.com") is None


def test_freshservice_current_agent_reads_the_me_endpoint() -> None:
    body = {"agent": {"id": 12, "first_name": "Ada", "last_name": "Example", "email": "agent@example.com"}}

    assert _client(lambda *_: body).current_agent() == FreshserviceAgent(id=12, name="Ada Example")


@pytest.mark.parametrize(
    "body",
    [{}, {"agent": None}, {"agent": []}, {"agent": "x"}, {"agent": {"first_name": "Ada"}}, {"agent": {"id": "12"}}, {"agent": {"id": True}}],
)
def test_freshservice_current_agent_is_tolerant_of_any_other_shape(body: dict[str, Any]) -> None:
    assert _client(lambda *_: body).current_agent() is None


@pytest.mark.parametrize(
    ("agent", "name"),
    [
        ({"id": 5, "first_name": "Ada", "last_name": "Example"}, "Ada Example"),
        ({"id": 5, "first_name": "Ada", "last_name": None}, "Ada"),
        ({"id": 5, "first_name": None, "last_name": "Example"}, "Example"),
        ({"id": 5}, ""),
        ({"id": 5, "first_name": 3, "last_name": ["x"]}, ""),
    ],
)
def test_freshservice_agent_name_is_built_from_whatever_name_parts_are_strings(agent: dict[str, Any], name: str) -> None:
    assert _client(lambda *_: {"agent": agent}).current_agent() == FreshserviceAgent(id=5, name=name)

