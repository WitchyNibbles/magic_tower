"""``app/tools/freshservice_check.py``: the standalone health check run against the
owner's real Freshservice. No test here reaches the network -- every stub goes
through the same injectable transport ``app/integrations/freshservice.py`` offers,
the pattern ``test_jira_check.py`` and ``test_freshservice_sync.py`` use.

The redaction tests are the point of this file: a report or a printed line that ever
carried the API key, the agent's email address or a ticket's text would defeat the one
property the command is for (report what came back, never what authenticated it, and
nothing from the tickets themselves). All values are invented.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import Settings, get_settings
from app.integrations.freshservice import FreshserviceConfigurationError, FreshserviceError
from app.services.sync import SyncError
from app.tools import freshservice_check

SECRET_KEY = "super-secret-freshservice-key-8f2c91"
OWNER_EMAIL = "agent@example.com"
OWNER_AGENT_ID = 4001
BASE = "https://example.freshservice.com"
SECRET_SUBJECT = "Invented subject that must never be printed"
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def _configured_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"freshservice_url": BASE, "freshservice_api_key": SECRET_KEY}
    values.update(overrides)
    return Settings(**values)


def _transport(tickets: list[dict[str, Any]], total: int | None = None, calls: list[str] | None = None):
    owner = {"id": OWNER_AGENT_ID, "first_name": "Ada", "last_name": "Example", "email": OWNER_EMAIL}

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        assert method == "GET"
        if calls is not None:
            calls.append(url)
        path = urlparse(url).path
        if path == "/api/v2/agents/me":
            return {"agent": owner}
        if path == "/api/v2/agents":
            return {"agents": [owner]}
        body: dict[str, Any] = {"tickets": tickets}
        if total is not None:
            body["total"] = total
        return body

    return transport


TICKET = {"id": 101, "subject": SECRET_SUBJECT, "status": 2, "responder_id": OWNER_AGENT_ID}


def test_run_check_reports_the_owner_identity_and_the_assigned_ticket_count() -> None:
    report = freshservice_check.run_check(_configured_settings(), transport=_transport([TICKET, TICKET]), now=NOW)

    assert report["base_url"] == BASE
    assert report["agent_id"] == OWNER_AGENT_ID
    assert report["agent_name"] == "Ada Example"
    assert report["ticket_count"] == 2
    assert report["lookback_days"] == 14


def test_run_check_reports_the_total_freshservice_gives_when_it_gives_one() -> None:
    """``total`` is the whole query's count, which is the answer; the tickets in hand
    are only as many as the pages fetched."""
    page = [TICKET] * 30

    report = freshservice_check.run_check(_configured_settings(), transport=_transport(page, total=42), now=NOW)

    assert report["ticket_count"] == 42


@pytest.mark.parametrize(("lookback_days", "since"), [(14, date(2026, 10, 8)), (3, date(2026, 10, 19))])
def test_run_check_searches_the_whole_lookback_as_a_first_sync_would(lookback_days: int, since: date) -> None:
    calls: list[str] = []

    freshservice_check.run_check(
        _configured_settings(freshservice_sync_lookback_days=lookback_days), transport=_transport([], calls=calls), now=NOW)

    (search,) = [url for url in calls if urlparse(url).path == "/api/v2/tickets/filter"]
    query = parse_qs(urlparse(search).query)["query"][0]
    assert f"agent_id:{OWNER_AGENT_ID} AND " in query
    assert f"updated_at:>'{since.isoformat()}'" in query


def test_run_check_without_an_agent_email_asks_the_api_key_who_it_is() -> None:
    calls: list[str] = []

    freshservice_check.run_check(_configured_settings(), transport=_transport([], calls=calls), now=NOW)

    paths = [urlparse(url).path for url in calls]
    assert "/api/v2/agents/me" in paths
    assert "/api/v2/agents" not in paths


def test_run_check_with_an_agent_email_looks_that_agent_up() -> None:
    calls: list[str] = []

    report = freshservice_check.run_check(
        _configured_settings(freshservice_agent_email=OWNER_EMAIL), transport=_transport([], calls=calls), now=NOW)

    paths = [urlparse(url).path for url in calls]
    assert "/api/v2/agents" in paths
    assert "/api/v2/agents/me" not in paths
    assert report["agent_id"] == OWNER_AGENT_ID


def test_run_check_raises_the_configuration_error_when_freshservice_is_not_set_up() -> None:
    with pytest.raises(FreshserviceConfigurationError):
        freshservice_check.run_check(Settings(), transport=_transport([]), now=NOW)


def test_run_check_lets_a_search_error_propagate() -> None:
    inner = _transport([])

    def search_fails(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        if urlparse(url).path == "/api/v2/tickets/filter":
            raise FreshserviceError("Freshservice request failed with status 500")
        return inner(method, url, headers, payload)

    with pytest.raises(FreshserviceError, match="status 500"):
        freshservice_check.run_check(_configured_settings(), transport=search_fails, now=NOW)


def test_run_check_reports_a_failed_owner_lookup_as_a_lookup_failure() -> None:
    def failing_transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        raise FreshserviceError("Freshservice request failed with status 500")

    with pytest.raises(SyncError, match="Freshservice agent lookup for the API key's own agent failed: Freshservice request failed with status 500"):
        freshservice_check.run_check(_configured_settings(), transport=failing_transport, now=NOW)


def test_run_check_raises_when_no_agent_can_be_named() -> None:
    def nobody(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        return {}

    with pytest.raises(SyncError, match="^Freshservice agent lookup for the API key's own agent failed: "):
        freshservice_check.run_check(_configured_settings(), transport=nobody, now=NOW)


def test_run_check_report_never_carries_the_key_the_email_or_ticket_text() -> None:
    report = freshservice_check.run_check(
        _configured_settings(freshservice_agent_email=OWNER_EMAIL), transport=_transport([TICKET]), now=NOW)

    for secret in (SECRET_KEY, OWNER_EMAIL, SECRET_SUBJECT):
        assert secret not in repr(report)


# --- main(): exit codes, remedy messages, and never printing the key ---------------------


def _environment(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for name in ("FRESHSERVICE_URL", "FRESHSERVICE_API_KEY", "FRESHSERVICE_AGENT_EMAIL", "FRESHSERVICE_TICKET_FIELD",
                 "FRESHSERVICE_TICKET_FIELD_VALUE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()


def test_main_prints_the_healthy_report_lines_verbatim(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``docs/freshservice-setup.md`` quotes these lines so the owner can recognise a
    healthy result; substring assertions would leave that quotation unpinned."""
    _environment(monkeypatch, FRESHSERVICE_URL=BASE, FRESHSERVICE_API_KEY=SECRET_KEY)
    monkeypatch.setattr(freshservice_check, "default_transport", _transport([TICKET] * 3, total=3))

    exit_code = freshservice_check.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == (
        f"connected to {BASE} as 'Ada Example' (agent id {OWNER_AGENT_ID})\n"
        "assigned tickets (open, pending, or updated in the last 14 days): 3\n"
    )
    assert captured.err == ""


def test_main_names_the_lookback_the_setting_asks_for(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _environment(monkeypatch, FRESHSERVICE_URL=BASE, FRESHSERVICE_API_KEY=SECRET_KEY, FRESHSERVICE_SYNC_LOOKBACK_DAYS="3")
    monkeypatch.setattr(freshservice_check, "default_transport", _transport([]))

    freshservice_check.main()

    assert "in the last 3 days): 0" in capsys.readouterr().out


def test_main_prints_the_unconfigured_message_verbatim_and_exits_nonzero(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _environment(monkeypatch)

    exit_code = freshservice_check.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == "Freshservice is not configured: missing FRESHSERVICE_URL, FRESHSERVICE_API_KEY\n"
    assert captured.out == ""


def test_main_prints_a_request_failure_without_repeating_its_own_prefix(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _environment(monkeypatch, FRESHSERVICE_URL=BASE, FRESHSERVICE_API_KEY=SECRET_KEY)

    def failing_transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        raise FreshserviceError("Freshservice request failed with status 403")

    monkeypatch.setattr(freshservice_check, "default_transport", failing_transport)

    exit_code = freshservice_check.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == "Freshservice agent lookup for the API key's own agent failed: Freshservice request failed with status 403\n"
    assert captured.out == ""


def test_main_exits_nonzero_with_the_message_when_the_ticket_search_fails(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _environment(monkeypatch, FRESHSERVICE_URL=BASE, FRESHSERVICE_API_KEY=SECRET_KEY)
    inner = _transport([])

    def search_fails(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        if urlparse(url).path == "/api/v2/tickets/filter":
            raise FreshserviceError("Freshservice rate limit exceeded, retry after 30")
        return inner(method, url, headers, payload)

    monkeypatch.setattr(freshservice_check, "default_transport", search_fails)

    exit_code = freshservice_check.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == "Freshservice rate limit exceeded, retry after 30\n"


def test_main_never_prints_the_key_the_email_or_ticket_text_on_success(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _environment(monkeypatch, FRESHSERVICE_URL=BASE, FRESHSERVICE_API_KEY=SECRET_KEY, FRESHSERVICE_AGENT_EMAIL=OWNER_EMAIL)
    monkeypatch.setattr(freshservice_check, "default_transport", _transport([TICKET]))

    freshservice_check.main()

    captured = capsys.readouterr()
    for secret in (SECRET_KEY, OWNER_EMAIL, SECRET_SUBJECT):
        assert secret not in captured.out
        assert secret not in captured.err


def test_main_never_prints_the_key_or_the_email_on_a_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """A failing request is exactly when an over-eager error handler is tempted to name
    what it sent; this pins that ``main`` does not add it back in."""
    _environment(monkeypatch, FRESHSERVICE_URL=BASE, FRESHSERVICE_API_KEY=SECRET_KEY, FRESHSERVICE_AGENT_EMAIL=OWNER_EMAIL)

    def failing_transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        raise FreshserviceError("Freshservice request failed with status 401")

    monkeypatch.setattr(freshservice_check, "default_transport", failing_transport)

    exit_code = freshservice_check.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    for secret in (SECRET_KEY, OWNER_EMAIL):
        assert secret not in captured.out
        assert secret not in captured.err


# --- the optional custom-field filter ---------------------------------------------------

FIELD_VALUE = "Jane Example"
FIELD_SETTINGS = {"freshservice_ticket_field": "technician", "freshservice_ticket_field_value": FIELD_VALUE}


def _owned(ticket_id: int, value: object = FIELD_VALUE) -> dict[str, Any]:
    return {**TICKET, "id": ticket_id, "custom_fields": {"technician": value}}


def test_run_check_without_a_field_filter_reports_none_and_the_servers_count() -> None:
    report = freshservice_check.run_check(_configured_settings(), transport=_transport([TICKET]), now=NOW)

    assert report["field_filter"] is None
    assert report["server_ticket_count"] == report["ticket_count"] == 1


def test_run_check_with_a_field_filter_sends_the_clause_and_names_only_the_field() -> None:
    calls: list[str] = []

    report = freshservice_check.run_check(
        _configured_settings(**FIELD_SETTINGS), transport=_transport([_owned(1)], calls=calls), now=NOW)

    (search,) = [url for url in calls if urlparse(url).path == "/api/v2/tickets/filter"]
    assert f"technician:'{FIELD_VALUE}'" in parse_qs(urlparse(search).query)["query"][0]
    assert report["field_filter"] == "technician"
    assert FIELD_VALUE not in repr(report)


def test_run_check_with_a_field_filter_counts_the_tickets_that_match_it() -> None:
    tickets = [_owned(1), _owned(2, value="Someone Else"), _owned(3), TICKET]

    report = freshservice_check.run_check(_configured_settings(**FIELD_SETTINGS), transport=_transport(tickets, total=4), now=NOW)

    assert report["ticket_count"] == 2
    assert report["server_ticket_count"] == 4


def test_run_check_with_a_field_filter_counts_what_came_back_not_a_total_beyond_the_pages_read() -> None:
    page = [_owned(index) for index in range(5)]

    report = freshservice_check.run_check(_configured_settings(**FIELD_SETTINGS), transport=_transport(page, total=900), now=NOW)

    assert report["server_ticket_count"] == 5
    assert report["ticket_count"] == 5


def test_run_check_with_a_half_set_field_filter_raises_the_configuration_error() -> None:
    with pytest.raises(FreshserviceConfigurationError, match="missing FRESHSERVICE_TICKET_FIELD_VALUE$"):
        freshservice_check.run_check(_configured_settings(freshservice_ticket_field="technician"), transport=_transport([]), now=NOW)


def test_main_prints_the_filter_line_without_the_value_and_the_matched_count(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _environment(monkeypatch, FRESHSERVICE_URL=BASE, FRESHSERVICE_API_KEY=SECRET_KEY,
                 FRESHSERVICE_TICKET_FIELD="technician", FRESHSERVICE_TICKET_FIELD_VALUE=FIELD_VALUE)
    monkeypatch.setattr(freshservice_check, "default_transport", _transport([_owned(1), _owned(2)], total=2))

    exit_code = freshservice_check.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == (
        f"connected to {BASE} as 'Ada Example' (agent id {OWNER_AGENT_ID})\n"
        "ticket field filter: technician (value set)\n"
        "assigned tickets (open, pending, or updated in the last 14 days): 2\n"
    )
    assert FIELD_VALUE not in captured.out + captured.err


def test_main_says_how_many_tickets_the_server_returned_when_the_filter_dropped_some(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _environment(monkeypatch, FRESHSERVICE_URL=BASE, FRESHSERVICE_API_KEY=SECRET_KEY,
                 FRESHSERVICE_TICKET_FIELD="technician", FRESHSERVICE_TICKET_FIELD_VALUE=FIELD_VALUE)
    monkeypatch.setattr(freshservice_check, "default_transport", _transport([_owned(1), _owned(2, value="Someone Else"), TICKET], total=3))

    freshservice_check.main()

    assert capsys.readouterr().out == (
        f"connected to {BASE} as 'Ada Example' (agent id {OWNER_AGENT_ID})\n"
        "ticket field filter: technician (value set)\n"
        "assigned tickets (open, pending, or updated in the last 14 days): 1\n"
        "server returned 3, 1 matched the field filter\n"
    )


def test_main_prints_a_half_set_filter_as_a_configuration_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _environment(monkeypatch, FRESHSERVICE_URL=BASE, FRESHSERVICE_API_KEY=SECRET_KEY, FRESHSERVICE_TICKET_FIELD_VALUE=FIELD_VALUE)

    exit_code = freshservice_check.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == "Freshservice is not configured: missing FRESHSERVICE_TICKET_FIELD\n"
    assert captured.out == ""
