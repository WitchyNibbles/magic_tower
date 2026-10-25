"""Graph pages large results and throttles busy clients; the client must cope with both.

Each test drives the real ``GraphClient`` through a scripted transport and records
the delays it asks a fake ``sleep`` for, so no test waits on a real clock.
"""

import io
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pytest

from app.config import Settings
from app.integrations import graph as graph_module
from app.integrations.graph import (
    GRAPH_ROOT, MAX_RETRIES, MAX_RETRY_AFTER_SECONDS, GraphClient, GraphError, GraphThrottledError, default_transport,
)
from app.services.crypto import EncryptedTokenStore, generate_encryption_key
from app.services.sync import SyncError, sync

INBOX = f"{GRAPH_ROOT}/me/mailFolders/inbox/messages"


def _messages(*ids: str) -> list[dict[str, str]]:
    return [{"id": message_id} for message_id in ids]


class ScriptedTransport:
    """Answers each request with the next scripted response, or raises it if it is an exception."""

    def __init__(self, *responses: dict[str, Any] | Exception) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []

    def __call__(self, method: str, url: str, headers: dict[str, str], payload: object) -> dict[str, Any]:
        self.urls.append(url)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _client(transport: ScriptedTransport, sleeps: list[float]) -> GraphClient:
    return GraphClient("token", transport, sleep=sleeps.append)


def test_inbox_follows_next_link_until_the_limit_is_reached() -> None:
    next_link = f"{INBOX}?$skiptoken=page2"
    transport = ScriptedTransport(
        {"value": _messages("m1", "m2"), "@odata.nextLink": next_link},
        {"value": _messages("m3", "m4"), "@odata.nextLink": f"{INBOX}?$skiptoken=page3"},
    )
    rows = _client(transport, []).inbox_messages(limit=4)
    assert [row["id"] for row in rows] == ["m1", "m2", "m3", "m4"]
    assert transport.urls[1] == next_link
    assert len(transport.urls) == 2


def test_inbox_stops_when_graph_has_no_more_pages() -> None:
    transport = ScriptedTransport({"value": _messages("m1", "m2"), "@odata.nextLink": f"{INBOX}?$skiptoken=2"}, {"value": _messages("m3")})
    rows = _client(transport, []).inbox_messages(limit=50)
    assert [row["id"] for row in rows] == ["m1", "m2", "m3"]


def test_inbox_never_returns_more_than_the_limit() -> None:
    transport = ScriptedTransport({"value": _messages("m1", "m2", "m3"), "@odata.nextLink": f"{INBOX}?$skiptoken=2"})
    assert len(_client(transport, []).inbox_messages(limit=2)) == 2
    assert len(transport.urls) == 1


def test_inbox_stops_on_an_empty_page_instead_of_looping() -> None:
    transport = ScriptedTransport({"value": [], "@odata.nextLink": f"{INBOX}?$skiptoken=2"})
    assert _client(transport, []).inbox_messages(limit=5) == []
    assert len(transport.urls) == 1


def test_inbox_refuses_a_next_link_that_leaves_graph() -> None:
    """Following it would send the bearer token to whatever host the link names."""
    transport = ScriptedTransport({"value": _messages("m1"), "@odata.nextLink": "https://graph.microsoft.com.evil.example/v1.0/x"})
    with pytest.raises(GraphError):
        _client(transport, []).inbox_messages(limit=5)
    assert len(transport.urls) == 1


def test_throttled_request_waits_for_retry_after_then_succeeds() -> None:
    transport = ScriptedTransport(GraphThrottledError(retry_after=7), {"id": "oid"})
    sleeps: list[float] = []
    assert _client(transport, sleeps).me() == {"id": "oid"}
    assert sleeps == [7]


def test_throttled_request_without_retry_after_backs_off_exponentially() -> None:
    transport = ScriptedTransport(GraphThrottledError(), GraphThrottledError(), {"id": "oid"})
    sleeps: list[float] = []
    _client(transport, sleeps).me()
    assert sleeps == [1, 2]


def test_retry_after_is_capped() -> None:
    transport = ScriptedTransport(GraphThrottledError(retry_after=3600), {"id": "oid"})
    sleeps: list[float] = []
    _client(transport, sleeps).me()
    assert sleeps == [MAX_RETRY_AFTER_SECONDS]


def test_throttling_gives_up_after_the_retry_budget() -> None:
    transport = ScriptedTransport(*[GraphThrottledError(retry_after=1) for _ in range(MAX_RETRIES + 1)])
    sleeps: list[float] = []
    with pytest.raises(GraphThrottledError):
        _client(transport, sleeps).me()
    assert len(sleeps) == MAX_RETRIES
    assert len(transport.urls) == MAX_RETRIES + 1


def test_throttling_mid_paging_retries_only_that_page() -> None:
    next_link = f"{INBOX}?$skiptoken=2"
    transport = ScriptedTransport(
        {"value": _messages("m1"), "@odata.nextLink": next_link},
        GraphThrottledError(retry_after=2),
        {"value": _messages("m2")},
    )
    sleeps: list[float] = []
    rows = _client(transport, sleeps).inbox_messages(limit=5)
    assert [row["id"] for row in rows] == ["m1", "m2"]
    assert transport.urls[1:] == [next_link, next_link]
    assert sleeps == [2]


@pytest.mark.parametrize("status", [429, 503])
def test_default_transport_reports_throttling_with_its_retry_after(status: int, monkeypatch: pytest.MonkeyPatch) -> None:
    def throttled(request: Any, **_: object) -> None:
        raise HTTPError(request.full_url, status, "Too Many Requests", {"Retry-After": "7"}, io.BytesIO(b""))

    monkeypatch.setattr(graph_module._opener, "open", throttled)
    with pytest.raises(GraphThrottledError) as raised:
        default_transport("GET", f"{GRAPH_ROOT}/me", {}, None)
    assert raised.value.retry_after == 7


def test_default_transport_ignores_an_unparseable_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    def throttled(request: Any, **_: object) -> None:
        raise HTTPError(request.full_url, 429, "Too Many Requests", {"Retry-After": "soon"}, io.BytesIO(b""))

    monkeypatch.setattr(graph_module._opener, "open", throttled)
    with pytest.raises(GraphThrottledError) as raised:
        default_transport("GET", f"{GRAPH_ROOT}/me", {}, None)
    assert raised.value.retry_after is None


def test_sync_reports_persistent_throttling_as_a_sync_error(tmp_path: Path) -> None:
    key = generate_encryption_key()
    settings = Settings(
        microsoft_tenant_id="tenant", microsoft_client_id="client", microsoft_client_secret="secret",
        microsoft_target_user_id="expected-oid", app_encryption_key=key, token_store_path=tmp_path / "tokens",
    )
    EncryptedTokenStore(settings.token_store_path, key).save({"access_token": "token"})
    transport = ScriptedTransport(*[GraphThrottledError() for _ in range(MAX_RETRIES + 1)])

    with pytest.raises(SyncError, match="throttling"):
        sync(settings, client=GraphClient("token", transport, sleep=lambda _: None))
