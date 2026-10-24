"""The Freshservice sync handler: resolves the owner agent, fetches their tickets,
stores them as ``Source`` rows and dispatches through the same envelope every
registered kind returns (``app/services/sync.py:sync``).

The Freshservice counterpart to ``test_jira_sync.py``. No test here reaches the
network -- everything goes through the injectable ``freshservice_client`` kwarg,
built on a stub transport, the seam ``test_freshservice_client.py`` uses. What the
promotion rule accepts and refuses is pinned in ``test_freshservice_promotion.py``;
the wiring is pinned here. All hosts, keys, names and ticket text are invented.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import engine
from app.integrations.freshservice import FRESHSERVICE_PAGE_SIZE, FreshserviceClient, FreshserviceError
from app.main import app
from app.models import Source, SourceKind, WorkItem
from app.services import freshservice_sync
from app.services.freshservice_sync import (
    FRESHSERVICE_SOURCE_KIND,
    _normalize_ticket,
    _sync_freshservice,
    since_date,
)
from app.services.sync import SyncError, sync
from app.services.sync_all import sync_ready_sources
from app.services.sync_cursor import last_success, record_success
from app.services.sync_registry import get_sync_handler, ready_kinds, registered_kinds

BASE = "https://example.freshservice.com"
OWNER_AGENT_ID = 4001
COLLEAGUE_AGENT_ID = 4002
OWNER_EMAIL = "agent@example.com"
API_KEY = "a-real-key"
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
LOCAL_TOKEN = {"Authorization": "Bearer test-local-agent-token"}


def _configured_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"freshservice_url": BASE, "freshservice_api_key": API_KEY}
    values.update(overrides)
    return Settings(**values)


def _ticket(ticket_id: int, responder_id: int | None = OWNER_AGENT_ID, status: int = 2, **fields: Any) -> dict[str, Any]:
    return {"id": ticket_id, "subject": f"Invented ticket {ticket_id}", "status": status, "priority": 2,
            "responder_id": responder_id, "updated_at": "2026-10-20T08:30:00Z", **fields}


OPEN_TICKET = _ticket(101)
ASSIGNED_ELSEWHERE = _ticket(102, responder_id=COLLEAGUE_AGENT_ID)
RESOLVED_TICKET = _ticket(103, status=4)


class _Transport:
    """Answers the three calls a sync makes and remembers them.

    ``pages`` are the filter responses by page number (a single list is page 1 only);
    ``me`` and ``agents`` are the two owner-lookup bodies; ``fail_lookup`` and
    ``fail_search`` make the matching call raise a ``FreshserviceError`` whose message,
    like the real transport's, names no URL, key or address.
    """

    def __init__(self, tickets: list[dict[str, Any]] | None = None, *, pages: list[list[dict[str, Any]]] | None = None,
                 me: Any = None, agents: Any = None, fail_lookup: bool = False, fail_search: bool = False) -> None:
        self.pages = pages if pages is not None else [tickets or []]
        self.me = me if me is not None else {"agent": {"id": OWNER_AGENT_ID, "first_name": "Ada", "last_name": "Example"}}
        self.agents = agents if agents is not None else {"agents": [
            {"id": OWNER_AGENT_ID, "first_name": "Ada", "last_name": "Example", "email": OWNER_EMAIL}]}
        self.fail_lookup = fail_lookup
        self.fail_search = fail_search
        self.paths: list[str] = []
        self.queries: list[str] = []

    def __call__(self, method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        parsed = urlparse(url)
        self.paths.append(parsed.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/api/v2/agents/me":
            if self.fail_lookup:
                raise FreshserviceError("Freshservice request failed with status 503")
            return self.me
        if parsed.path == "/api/v2/agents":
            if self.fail_lookup:
                raise FreshserviceError("Freshservice request failed with status 503")
            return self.agents
        assert parsed.path == "/api/v2/tickets/filter", url
        if self.fail_search:
            raise FreshserviceError("Freshservice request failed with status 500")
        self.queries.append(params["query"][0])
        index = int(params["page"][0]) - 1
        return {"tickets": self.pages[index] if index < len(self.pages) else []}

    @property
    def searched(self) -> bool:
        return "/api/v2/tickets/filter" in self.paths

    def client(self, **settings_overrides: Any) -> FreshserviceClient:
        return FreshserviceClient.from_settings(_configured_settings(**settings_overrides), transport=self)


def _client_with(tickets: list[dict[str, Any]]) -> FreshserviceClient:
    return _Transport(tickets).client()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Freeze the handler's notion of now at ``NOW``. Set ``step`` to make every
    reading later than the one before, to tell the start of a sync from its end."""
    state: dict[str, Any] = {"now": NOW, "step": timedelta(0)}

    def now() -> datetime:
        reading = state["now"]
        state["now"] = reading + state["step"]
        return reading

    monkeypatch.setattr(freshservice_sync, "_utc_now", now)
    return state


# --- registration and the envelope ------------------------------------------------------


def test_freshservice_sync_is_registered_under_the_generic_dispatch() -> None:
    assert FRESHSERVICE_SOURCE_KIND in registered_kinds()


def test_freshservice_sync_uses_the_freshservice_spelling_source_kind() -> None:
    """Spelled identically in the enum and the handler, or
    ``scripts/deaddocs_check.py`` reads the connector as retired."""
    assert FRESHSERVICE_SOURCE_KIND == SourceKind.freshservice.value == "freshservice"


def test_freshservice_sync_fails_closed_naming_what_is_missing() -> None:
    with pytest.raises(SyncError, match="Freshservice is not configured: missing FRESHSERVICE_URL, FRESHSERVICE_API_KEY"):
        sync(Settings(), kind=FRESHSERVICE_SOURCE_KIND)


def test_freshservice_sync_names_only_the_variable_that_is_missing() -> None:
    with pytest.raises(SyncError, match="Freshservice is not configured: missing FRESHSERVICE_API_KEY$"):
        sync(_configured_settings(freshservice_api_key=""), kind=FRESHSERVICE_SOURCE_KIND)


def test_freshservice_sync_is_ready_only_once_its_url_and_key_are_set() -> None:
    assert FRESHSERVICE_SOURCE_KIND not in ready_kinds(Settings())
    assert FRESHSERVICE_SOURCE_KIND not in ready_kinds(_configured_settings(freshservice_api_key=""))
    assert FRESHSERVICE_SOURCE_KIND in ready_kinds(_configured_settings())


def test_freshservice_sync_fetches_through_the_handler_the_registry_hands_back() -> None:
    """Registration and the handler proven together: every other test here calls
    ``_sync_freshservice`` directly, which would still pass if the registry held some
    other callable under ``"freshservice"``."""
    handler = get_sync_handler(FRESHSERVICE_SOURCE_KIND)

    with Session(engine) as session:
        result = handler(_configured_settings(), db=session, freshservice_client=_client_with([OPEN_TICKET]))

        assert result["new_sources"] == 1
        assert session.query(Source).filter_by(external_id="freshservice:101").one().kind == SourceKind.freshservice


def test_freshservice_sync_ignores_the_graph_only_client_kwarg() -> None:
    """What ``sync()`` always forwards as ``client`` must never be touched here."""
    with Session(engine) as session:
        result = _sync_freshservice(_configured_settings(), db=session, client=object(), freshservice_client=_client_with([]))

    assert result["count"] == 0


def test_freshservice_sync_returns_the_envelope_every_registered_kind_returns(clock: dict[str, Any]) -> None:
    with Session(engine) as session:
        result = _sync_freshservice(_configured_settings(), db=session, freshservice_client=_client_with([OPEN_TICKET]))

    assert result["mode"] == "read-only"
    assert set(result) == {"mode", "synced_at", "count", "new_sources", "new_work_items", "since", "truncated", "filtered_out"}
    assert result["count"] == 1
    assert result["since"] == "2026-10-08"
    assert result["truncated"] is False
    assert result["filtered_out"] == 0


def test_freshservice_sync_handler_registers_via_the_main_import_alone() -> None:
    """``app/main.py`` must itself trigger registration. A fresh interpreter is the only
    way to isolate that: within this pytest process some other module has already
    imported the handler directly."""
    script = "import app.main\nfrom app.services.sync_registry import registered_kinds\nassert 'freshservice' in registered_kinds(), registered_kinds()\n"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parent.parent,
        env=os.environ,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr


# --- storing and promoting ---------------------------------------------------------------


def test_freshservice_sync_stores_a_ticket_as_a_source_with_the_kind_id_external_id() -> None:
    with Session(engine) as session:
        result = _sync_freshservice(_configured_settings(), db=session, freshservice_client=_client_with([OPEN_TICKET]))

        assert result["new_sources"] == 1
        source = session.query(Source).filter_by(external_id="freshservice:101").one()
        assert source.kind == SourceKind.freshservice
        assert source.subject == "Invented ticket 101"
        assert source.url == f"{BASE}/a/tickets/101"
        # The ticket's own ``updated_at``, not the time of the sync: it is the column
        # the queue lists and sorts on.
        assert source.observed_at == datetime(2026, 10, 20, 8, 30)


def test_freshservice_sync_stores_a_ticket_with_no_subject_under_a_placeholder() -> None:
    with Session(engine) as session:
        _sync_freshservice(_configured_settings(), db=session, freshservice_client=_client_with([_ticket(7, subject=None)]))

        assert session.query(Source).filter_by(external_id="freshservice:7").one().subject == "(no subject)"


def test_freshservice_sync_skips_a_row_that_has_no_usable_id() -> None:
    """``freshservice:None`` would be one shared external id for every such row."""
    rows = [{"subject": "no id"}, {"id": None}, {"id": "12"}, {"id": True}, "nope", None, OPEN_TICKET]

    with Session(engine) as session:
        result = _sync_freshservice(_configured_settings(), db=session, freshservice_client=_client_with(rows))

        assert result["count"] == 1
        assert [source.external_id for source in session.query(Source).all()] == ["freshservice:101"]


def test_freshservice_sync_keeps_one_signal_for_a_ticket_repeated_across_two_pages() -> None:
    """Pages are fetched one at a time, so a ticket updated in between can shift and
    arrive twice; the dedup keeps the envelope's ``count`` honest."""
    first_page = [_ticket(1000 + index) for index in range(FRESHSERVICE_PAGE_SIZE - 1)] + [OPEN_TICKET]
    transport = _Transport(pages=[first_page, [OPEN_TICKET]])

    with Session(engine) as session:
        result = _sync_freshservice(_configured_settings(), db=session, freshservice_client=transport.client())

    assert result["count"] == FRESHSERVICE_PAGE_SIZE


def test_freshservice_sync_promotes_only_the_owners_unfinished_tickets() -> None:
    """The handler reaches the queue through ``promote_signals`` with the owner it
    resolved: the owner's open ticket becomes work; another agent's and a resolved
    one are stored and browsable without being queued."""
    tickets = [OPEN_TICKET, ASSIGNED_ELSEWHERE, RESOLVED_TICKET, _ticket(104, responder_id=None)]

    with Session(engine) as session:
        result = _sync_freshservice(_configured_settings(), db=session, freshservice_client=_client_with(tickets))

        assert result["new_sources"] == 4
        assert result["new_work_items"] == 1
        work_item = session.query(WorkItem).one()
        assert work_item.source_external_id == "freshservice:101"
        assert work_item.source_kind == SourceKind.freshservice


def test_freshservice_sync_is_idempotent_across_repeated_syncs_of_the_same_ticket() -> None:
    with Session(engine) as session:
        first = _sync_freshservice(_configured_settings(), db=session, freshservice_client=_client_with([OPEN_TICKET]))
        second = _sync_freshservice(_configured_settings(), db=session, freshservice_client=_client_with([OPEN_TICKET]))

    assert (first["new_sources"], first["new_work_items"]) == (1, 1)
    assert (second["new_sources"], second["new_work_items"]) == (0, 0)


def test_freshservice_sync_without_a_database_fetches_and_counts_but_stores_nothing() -> None:
    result = _sync_freshservice(_configured_settings(), db=None, freshservice_client=_client_with([OPEN_TICKET]))

    assert result["count"] == 1
    assert result["new_sources"] == 0 and result["new_work_items"] == 0


def test_freshservice_sync_envelope_says_when_the_search_was_cut_off() -> None:
    full_page = [_ticket(index) for index in range(FRESHSERVICE_PAGE_SIZE)]
    endless = _Transport(pages=[full_page] * 50)

    with Session(engine) as session:
        result = _sync_freshservice(_configured_settings(), db=session, freshservice_client=endless.client())

    assert result["truncated"] is True


@pytest.mark.parametrize(
    ("ticket", "expected"),
    [
        (_ticket(5), {"external_id": "freshservice:5", "source_kind": "freshservice", "title": "Invented ticket 5",
                      "source_url": f"{BASE}/a/tickets/5", "observed_at": "2026-10-20T08:30:00Z",
                      "responder_id": OWNER_AGENT_ID, "ticket_status": 2}),
        (_ticket(5, responder_id=None, status=4), {"responder_id": None, "ticket_status": 4}),
        (_ticket(5, responder_id="4001", status="2"), {"responder_id": None, "ticket_status": None}),
        (_ticket(5, responder_id=True, status=True), {"responder_id": None, "ticket_status": None}),
        ({"id": 5}, {"title": "(no subject)", "observed_at": None, "responder_id": None, "ticket_status": None}),
        (_ticket(5, subject="   "), {"title": "(no subject)"}),
        (_ticket(5, subject=42), {"title": "(no subject)"}),
    ],
)
def test_freshservice_normalize_ticket_builds_the_signal_promotion_reads(ticket: dict[str, Any], expected: dict[str, Any]) -> None:
    """``responder_id`` and ``ticket_status`` are what rule B decides on, so anything
    that is not a real integer is carried as ``None`` rather than guessed at."""
    signal = _normalize_ticket(ticket, BASE)

    assert {key: signal[key] for key in expected} == expected


@pytest.mark.parametrize(
    ("fields", "excerpt"),
    [
        ({"description_text": "Printer on  floor 3\r\nis offline.\n\nInvented request."},
         "Printer on floor 3 is offline. Invented request."),
        ({"description_text": "   \n "}, None),
        ({"description_text": None}, None),
        ({"description_text": 42}, None),
        ({"description": "<div>html only</div>"}, None),
        ({}, None),
    ],
)
def test_freshservice_normalize_ticket_takes_the_excerpt_from_the_plain_text_description(
    fields: dict[str, Any], excerpt: str | None,
) -> None:
    """Only ``description_text`` is read (the HTML ``description`` would put markup in
    the queue); a ticket without it, as the filter endpoint may return, has no excerpt."""
    assert _normalize_ticket(_ticket(5, **fields), BASE)["excerpt"] == excerpt


def test_freshservice_sync_stores_the_description_as_the_source_and_evidence_excerpt() -> None:
    ticket = _ticket(111, description_text="Reset the invented VPN token\nfor the demo account.")

    with Session(engine) as session:
        _sync_freshservice(_configured_settings(), db=session, freshservice_client=_client_with([ticket]))

        source = session.query(Source).filter_by(external_id="freshservice:111").one()
        item = session.query(WorkItem).filter_by(source_external_id="freshservice:111").one()
        evidence_excerpts = [evidence.excerpt for evidence in item.evidence]

    assert source.excerpt == "Reset the invented VPN token for the demo account."
    assert evidence_excerpts == [source.excerpt]


# --- the owner -----------------------------------------------------------------------------


def test_freshservice_sync_without_an_agent_email_takes_the_owner_from_the_api_key() -> None:
    transport = _Transport([OPEN_TICKET])

    with Session(engine) as session:
        _sync_freshservice(_configured_settings(), db=session, freshservice_client=transport.client())

    assert "/api/v2/agents/me" in transport.paths
    assert "/api/v2/agents" not in transport.paths


def test_freshservice_sync_with_an_agent_email_takes_the_owner_from_that_address() -> None:
    transport = _Transport([OPEN_TICKET])
    settings = _configured_settings(freshservice_agent_email=OWNER_EMAIL)

    with Session(engine) as session:
        result = _sync_freshservice(settings, db=session, freshservice_client=transport.client())

    assert "/api/v2/agents" in transport.paths
    assert "/api/v2/agents/me" not in transport.paths
    assert result["new_work_items"] == 1


def test_freshservice_sync_searches_for_the_resolved_owners_id() -> None:
    transport = _Transport([], me={"agent": {"id": 777}})

    with Session(engine) as session:
        _sync_freshservice(_configured_settings(), db=session, freshservice_client=transport.client())

    assert transport.queries[0].startswith("\"agent_id:777 AND (")


# --- the optional custom-field filter ---------------------------------------------------

FIELD_SETTINGS = {"freshservice_ticket_field": "technician", "freshservice_ticket_field_value": "Jane Example"}


def _owned(ticket_id: int, value: Any = "Jane Example", **fields: Any) -> dict[str, Any]:
    return _ticket(ticket_id, custom_fields={"technician": value}, **fields)


def test_freshservice_sync_with_a_half_set_field_filter_fails_closed_naming_the_missing_one() -> None:
    transport = _Transport([_owned(1)])
    settings = _configured_settings(freshservice_ticket_field="technician")

    with pytest.raises(SyncError, match="^Freshservice is not configured: missing FRESHSERVICE_TICKET_FIELD_VALUE$"):
        _sync_freshservice(settings, db=None, freshservice_client=transport.client())

    assert not transport.searched
    assert FRESHSERVICE_SOURCE_KIND not in ready_kinds(settings)


def test_freshservice_sync_with_an_unusable_field_value_fails_closed_without_echoing_it() -> None:
    transport = _Transport([_owned(1)])
    settings = _configured_settings(freshservice_ticket_field="technician", freshservice_ticket_field_value="Jane's Team")

    with pytest.raises(SyncError) as error:
        _sync_freshservice(settings, db=None, freshservice_client=transport.client())

    assert "FRESHSERVICE_TICKET_FIELD_VALUE" in str(error.value)
    assert "Jane" not in str(error.value)
    assert "missing" not in str(error.value)
    assert not transport.searched
    assert FRESHSERVICE_SOURCE_KIND not in ready_kinds(settings)


def test_freshservice_sync_is_ready_with_a_complete_field_filter() -> None:
    assert FRESHSERVICE_SOURCE_KIND in ready_kinds(_configured_settings(**FIELD_SETTINGS))


def test_freshservice_sync_puts_the_field_clause_in_the_search_query() -> None:
    transport = _Transport([])

    _sync_freshservice(_configured_settings(**FIELD_SETTINGS), db=None, freshservice_client=transport.client())

    assert transport.queries[0].startswith("\"agent_id:4001 AND technician:'Jane Example' AND (status:2 OR")


def test_freshservice_sync_without_a_field_filter_sends_no_field_clause() -> None:
    transport = _Transport([])

    _sync_freshservice(_configured_settings(), db=None, freshservice_client=transport.client())

    assert "technician" not in transport.queries[0]


def test_freshservice_sync_drops_tickets_the_server_returned_that_do_not_hold_the_value() -> None:
    """The query asks the server to filter; a server that ignores the clause must not
    get the colleague's tickets stored or promoted."""
    tickets = [
        _owned(101),
        _owned(102, value="  Jane Example "),
        _owned(103, value="Someone Else"),
        _ticket(104),
        _ticket(105, custom_fields=None),
        _ticket(106, custom_fields="Jane Example"),
        _owned(107, value=None),
    ]

    with Session(engine) as session:
        result = _sync_freshservice(_configured_settings(**FIELD_SETTINGS), db=session, freshservice_client=_client_with(tickets))

        stored = {row.external_id for row in session.query(Source).filter_by(kind=SourceKind.freshservice)}
        assert stored == {"freshservice:101", "freshservice:102"}
        assert session.query(WorkItem).count() == 2

    assert result["count"] == 2
    assert result["new_sources"] == 2
    assert result["new_work_items"] == 2
    assert result["filtered_out"] == 5


def test_freshservice_sync_counts_a_dropped_ticket_repeated_across_pages_once() -> None:
    first_page = [_owned(101), _owned(103, value="Someone Else")] + [_owned(200 + index) for index in range(28)]
    transport = _Transport(pages=[first_page, [_owned(103, value="Someone Else")]])

    result = _sync_freshservice(_configured_settings(**FIELD_SETTINGS), db=None, freshservice_client=transport.client())

    assert result["filtered_out"] == 1
    assert result["count"] == 29


def test_freshservice_sync_does_not_count_a_row_with_no_usable_id_as_filtered_out() -> None:
    rows: list[Any] = [_owned(101), {"subject": "no id"}, "junk"]

    result = _sync_freshservice(_configured_settings(**FIELD_SETTINGS), db=None, freshservice_client=_client_with(rows))

    assert (result["count"], result["filtered_out"]) == (1, 0)


def test_freshservice_sync_without_a_field_filter_keeps_every_ticket_whatever_its_custom_fields() -> None:
    tickets = [_owned(101, value="Someone Else"), _ticket(102)]

    result = _sync_freshservice(_configured_settings(), db=None, freshservice_client=_client_with(tickets))

    assert (result["count"], result["filtered_out"]) == (2, 0)


@pytest.mark.parametrize(
    "transport",
    [
        _Transport(fail_lookup=True),
        _Transport(me={}),
        _Transport(me={"agent": "nope"}),
        _Transport(me={"agent": {"first_name": "Ada"}}),
        _Transport(me=["not", "an", "object"]),
    ],
    ids=["lookup-error", "empty-body", "agent-not-an-object", "agent-without-id", "body-not-an-object"],
)
def test_freshservice_sync_with_an_unknown_owner_fails_closed_before_fetching_anything(transport: _Transport, clock: dict[str, Any]) -> None:
    """The owner's id is needed for the query, so an owner nobody can name means
    nothing is fetched, stored or promoted and the cursor does not move."""
    previous = NOW - timedelta(hours=2)

    with Session(engine) as session:
        record_success(session, FRESHSERVICE_SOURCE_KIND, previous)
        with pytest.raises(SyncError, match="^Freshservice agent lookup for the API key's own agent failed: ") as raised:
            _sync_freshservice(_configured_settings(), db=session, freshservice_client=transport.client())

        assert not transport.searched
        assert session.query(Source).count() == 0
        assert last_success(session, FRESHSERVICE_SOURCE_KIND) == previous
    assert API_KEY not in str(raised.value)


@pytest.mark.parametrize(
    "transport",
    [
        _Transport(fail_lookup=True),
        _Transport(agents={"agents": []}),
        _Transport(agents={"agents": [{"id": 1, "email": "someone-else@example.com"}]}),
        _Transport(agents="nope"),
    ],
    ids=["lookup-error", "no-agents", "no-matching-address", "body-not-an-object"],
)
def test_freshservice_sync_with_an_agent_email_nobody_matches_fails_closed_without_naming_it(transport: _Transport) -> None:
    settings = _configured_settings(freshservice_agent_email=OWNER_EMAIL)

    with Session(engine) as session:
        with pytest.raises(SyncError, match="^Freshservice agent lookup by FRESHSERVICE_AGENT_EMAIL failed: ") as raised:
            _sync_freshservice(settings, db=session, freshservice_client=transport.client(freshservice_agent_email=OWNER_EMAIL))

        assert not transport.searched
    assert OWNER_EMAIL not in str(raised.value)
    assert API_KEY not in str(raised.value)


def test_freshservice_sync_email_lookup_failure_names_the_setting_and_carries_the_clients_reason() -> None:
    settings = _configured_settings(freshservice_agent_email=OWNER_EMAIL)
    transport = _Transport(fail_lookup=True)

    with pytest.raises(SyncError) as raised:
        _sync_freshservice(settings, db=None, freshservice_client=transport.client(freshservice_agent_email=OWNER_EMAIL))

    assert str(raised.value) == "Freshservice agent lookup by FRESHSERVICE_AGENT_EMAIL failed: Freshservice request failed with status 503"


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        (None, "Freshservice agent lookup for the API key's own agent failed: no agent matched"),
        (OWNER_EMAIL, "Freshservice agent lookup by FRESHSERVICE_AGENT_EMAIL failed: no agent matched"),
    ],
)
def test_freshservice_sync_no_agent_matched_says_which_lookup_ran(email: str | None, expected: str) -> None:
    overrides = {"freshservice_agent_email": email} if email else {}

    with pytest.raises(SyncError) as raised:
        _sync_freshservice(_configured_settings(**overrides), db=None, freshservice_client=_Transport(me={}, agents={"agents": []}).client(**overrides))

    assert str(raised.value) == expected


def test_freshservice_sync_agent_lookup_failure_carries_the_clients_reason() -> None:
    with pytest.raises(SyncError, match="Freshservice agent lookup for the API key's own agent failed: Freshservice request failed with status 503") as raised:
        _sync_freshservice(_configured_settings(), db=None, freshservice_client=_Transport(fail_lookup=True).client())

    assert isinstance(raised.value.__cause__, FreshserviceError)


# --- the search window and the sync cursor -------------------------------------------------


@pytest.mark.parametrize(
    ("last_success_at", "expected"),
    [
        # no cursor: the whole lookback (14 days -> 2026-10-10), minus two days of overlap
        (None, date(2026, 10, 8)),
        # a recent cursor: its own date, minus two days of overlap
        (NOW - timedelta(hours=2), date(2026, 10, 22)),
        (NOW - timedelta(days=3), date(2026, 10, 19)),
        # exactly the lookback old is still inside it
        (NOW - timedelta(days=14), date(2026, 10, 8)),
        # older than the lookback: capped at it, so an outage cannot ask for years
        (NOW - timedelta(days=14, seconds=1), date(2026, 10, 8)),
        (NOW - timedelta(days=60), date(2026, 10, 8)),
        # a cursor in the future means the clock stepped back: search the whole lookback
        (NOW + timedelta(seconds=1), date(2026, 10, 8)),
        (NOW + timedelta(days=1), date(2026, 10, 8)),
    ],
)
def test_since_date_is_the_cursors_day_minus_two_capped_at_the_lookback(last_success_at: datetime | None, expected: date) -> None:
    """The filter compares dates only, so ``since`` is a day, and two days of overlap
    cover both that granularity and an account whose timezone is behind UTC."""
    assert since_date(last_success_at, NOW, 14) == expected


def test_since_date_honours_the_configured_lookback() -> None:
    assert since_date(None, NOW, 3) == date(2026, 10, 19)
    assert since_date(NOW - timedelta(days=5), NOW, 3) == date(2026, 10, 19)


def test_freshservice_sync_without_a_cursor_searches_the_lookback(clock: dict[str, Any]) -> None:
    transport = _Transport()

    with Session(engine) as session:
        _sync_freshservice(_configured_settings(), db=session, freshservice_client=transport.client())

    assert "updated_at:>'2026-10-08'" in transport.queries[0]


def test_freshservice_sync_uses_the_lookback_setting(clock: dict[str, Any]) -> None:
    transport = _Transport()
    settings = _configured_settings(freshservice_sync_lookback_days=3)

    with Session(engine) as session:
        result = _sync_freshservice(settings, db=session, freshservice_client=transport.client())

    assert "updated_at:>'2026-10-19'" in transport.queries[0]
    assert result["since"] == "2026-10-19"


def test_freshservice_sync_searches_from_the_day_of_the_last_success(clock: dict[str, Any]) -> None:
    transport = _Transport()

    with Session(engine) as session:
        record_success(session, FRESHSERVICE_SOURCE_KIND, NOW - timedelta(days=3))
        result = _sync_freshservice(_configured_settings(), db=session, freshservice_client=transport.client())

    assert "updated_at:>'2026-10-19'" in transport.queries[0]
    assert result["since"] == "2026-10-19"


def test_freshservice_sync_without_a_database_searches_the_lookback_and_keeps_no_cursor(clock: dict[str, Any]) -> None:
    transport = _Transport()

    _sync_freshservice(_configured_settings(), db=None, freshservice_client=transport.client())

    assert "updated_at:>'2026-10-08'" in transport.queries[0]


def test_freshservice_sync_records_the_moment_it_started_as_the_cursor(clock: dict[str, Any]) -> None:
    """Anything updated while the sync ran lands in the next window."""
    clock["step"] = timedelta(minutes=5)

    with Session(engine) as session:
        _sync_freshservice(_configured_settings(), db=session, freshservice_client=_client_with([OPEN_TICKET]))

        assert last_success(session, FRESHSERVICE_SOURCE_KIND) == NOW


def test_freshservice_sync_advances_the_cursor_so_the_next_sync_asks_for_less(clock: dict[str, Any]) -> None:
    first, second = _Transport(), _Transport()

    with Session(engine) as session:
        _sync_freshservice(_configured_settings(), db=session, freshservice_client=first.client())
        clock["now"] = NOW + timedelta(days=5)
        _sync_freshservice(_configured_settings(), db=session, freshservice_client=second.client())

    assert "updated_at:>'2026-10-08'" in first.queries[0]
    assert "updated_at:>'2026-10-22'" in second.queries[0]


def test_freshservice_sync_whose_search_fails_leaves_the_cursor_where_it_was(clock: dict[str, Any]) -> None:
    previous = NOW - timedelta(days=2)
    failing = _Transport(fail_search=True)

    with Session(engine) as session:
        record_success(session, FRESHSERVICE_SOURCE_KIND, previous)
        with pytest.raises(SyncError, match="Freshservice request failed with status 500") as raised:
            _sync_freshservice(_configured_settings(), db=session, freshservice_client=failing.client())

        assert isinstance(raised.value.__cause__, FreshserviceError)
        assert last_success(session, FRESHSERVICE_SOURCE_KIND) == previous

        # and the retry still covers everything since the last success
        retry = _Transport()
        _sync_freshservice(_configured_settings(), db=session, freshservice_client=retry.client())

    assert "updated_at:>'2026-10-20'" in retry.queries[0]


def test_freshservice_sync_whose_search_fails_with_no_cursor_does_not_invent_one(clock: dict[str, Any]) -> None:
    with Session(engine) as session:
        with pytest.raises(SyncError):
            _sync_freshservice(_configured_settings(), db=session, freshservice_client=_Transport(fail_search=True).client())

        assert last_success(session, FRESHSERVICE_SOURCE_KIND) is None


def test_freshservice_sync_whose_promotion_fails_leaves_the_cursor_where_it_was(clock: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """The cursor means "everything up to here was judged": it moves only after
    the tickets were stored *and* promoted."""
    previous = NOW - timedelta(days=2)

    def boom(*_: Any, **__: Any) -> int:
        raise RuntimeError("promotion blew up")

    monkeypatch.setattr(freshservice_sync, "promote_signals", boom)

    with Session(engine) as session:
        record_success(session, FRESHSERVICE_SOURCE_KIND, previous)
        with pytest.raises(RuntimeError, match="promotion blew up"):
            _sync_freshservice(_configured_settings(), db=session, freshservice_client=_client_with([OPEN_TICKET]))
        session.rollback()

        assert last_success(session, FRESHSERVICE_SOURCE_KIND) == previous


def test_a_misconfigured_url_is_a_sync_error_not_a_traceback() -> None:
    with pytest.raises(SyncError, match="FRESHSERVICE_URL must be a full https URL"):
        _sync_freshservice(_configured_settings(freshservice_url="http://example.freshservice.com"), db=None)


# --- through the API ------------------------------------------------------------------------


@pytest.fixture
def lookup_down(monkeypatch: pytest.MonkeyPatch) -> str:
    """The registered handler, with a client whose owner lookup fails; returns the sync's message."""
    failing = _Transport(fail_lookup=True).client()
    monkeypatch.setattr(freshservice_sync, "FreshserviceClient", SimpleNamespace(from_settings=lambda settings: failing))
    return "Freshservice agent lookup for the API key's own agent failed: Freshservice request failed with status 503"


def test_post_sync_for_freshservice_answers_409_naming_what_is_missing_when_unconfigured() -> None:
    with TestClient(app) as client:
        response = client.post("/api/sync", params={"kind": "freshservice"}, headers=LOCAL_TOKEN)

    assert response.status_code == 409
    assert response.json() == {"detail": "Freshservice is not configured: missing FRESHSERVICE_URL, FRESHSERVICE_API_KEY"}


def test_post_sync_for_freshservice_answers_409_with_the_reason_when_the_owner_lookup_fails(lookup_down: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.sync.get_settings", _configured_settings)

    with TestClient(app) as client:
        response = client.post("/api/sync", params={"kind": "freshservice"}, headers=LOCAL_TOKEN)

    assert response.status_code == 409
    assert response.json() == {"detail": lookup_down}


def test_post_sync_all_leaves_freshservice_out_when_it_is_not_configured() -> None:
    with TestClient(app) as client:
        response = client.post("/api/sync/all", headers=LOCAL_TOKEN)

    assert response.status_code == 200
    assert "freshservice" not in response.json()["results"]


def test_post_sync_all_reports_a_freshservice_owner_lookup_failure_as_its_message(lookup_down: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.sync.get_settings", _configured_settings)

    with TestClient(app) as client:
        response = client.post("/api/sync/all", headers=LOCAL_TOKEN)

    assert response.status_code == 200
    assert response.json()["results"]["freshservice"] == {"error": lookup_down}


def test_sync_all_reports_a_freshservice_failure_without_logging_a_traceback(lookup_down: str, caplog: pytest.LogCaptureFixture) -> None:
    with Session(engine) as session, caplog.at_level(logging.ERROR):
        results = sync_ready_sources(_configured_settings(), session)

    assert results["freshservice"] == {"error": lookup_down}
    assert not [record for record in caplog.records if record.exc_info]


def test_sync_all_syncs_a_configured_freshservice_beside_the_other_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    working = _client_with([OPEN_TICKET])
    monkeypatch.setattr(freshservice_sync, "FreshserviceClient", SimpleNamespace(from_settings=lambda settings: working))

    with Session(engine) as session:
        results = sync_ready_sources(_configured_settings(), session)

        assert results["freshservice"]["new_work_items"] == 1
        assert session.query(WorkItem).one().source_external_id == "freshservice:101"
