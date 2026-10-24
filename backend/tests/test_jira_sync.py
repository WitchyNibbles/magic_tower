"""The Jira sync handler: fetches the participation window, stores it as
``Source`` rows and dispatches through the same envelope every registered kind
returns (``app/services/sync.py:sync``).

Dropping the enum member, the registration call, or any line of the normalization
step reddens exactly the test that pins it. That is not yet true of every line
here -- ``synced_at`` and the two ``db is not None`` guards survive mutation,
mirroring gaps ``_sync_graph``'s own tests have (B128). The ``new_work_items``
count was listed among them until T07; it is pinned now, measured by replacing
``promoted`` with ``0`` in the envelope and watching the assigned-issue test below
fail. Which issues that count may include is pinned in ``test_jira_promotion.py``.
No test here reaches the network -- everything goes through the injectable
``jira_client`` kwarg, the same seam ``test_jira_query.py`` and
``test_jira_client.py`` use.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import engine
from app.main import app
from app.integrations.jira import JiraClient, JiraError
from app.models import Source, SourceKind, WorkItem
from app.services import jira_sync
from app.services.jira_sync import JIRA_SOURCE_KIND, _sync_jira, participation_window_minutes
from app.services.sync_cursor import last_success, record_success
from app.services.sync import SyncError, sync
from app.services.sync_all import sync_ready_sources
from app.services.sync_registry import get_sync_handler, registered_kinds


def _configured_settings(**overrides: str) -> Settings:
    values = {
        "jira_site_url": "https://example.atlassian.net",
        "jira_account_email": "owner@example.com",
        "jira_api_token": "a-real-token",
    }
    values.update(overrides)
    return Settings(**values)


def _client_with(issues: list[dict[str, Any]]) -> JiraClient:
    """Answers the two calls a sync makes: the participation search, and the
    ``/myself`` lookup promotion recognises the owner by
    (``tests/test_jira_promotion.py`` owns what that identity decides)."""

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        if url.endswith("/myself"):
            return {"accountId": OWNER_ACCOUNT_ID}
        return {"issues": issues}

    return JiraClient.from_settings(_configured_settings(), transport=transport)


def _paging_client_with(pages: list[list[dict[str, Any]]]) -> JiraClient:
    """A stub that walks ``nextPageToken`` the way ``search_participation_issues``
    does, so a test can hand the handler more than one page. The token is just the
    index of the page it asks for."""

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        index = int(parse_qs(urlparse(url).query).get("nextPageToken", ["0"])[0])
        body: dict[str, Any] = {"issues": pages[index]}
        if index + 1 < len(pages):
            body["nextPageToken"] = str(index + 1)
        return body

    return JiraClient.from_settings(_configured_settings(), transport=transport)


OWNER_ACCOUNT_ID = "5b10a2844c20165700ede21g"
ISSUE = {"id": "10001", "key": "OPS-1", "fields": {"summary": "Fix the thing", "updated": "2026-09-18T08:30:00.000+0000"}}
# The same issue with the owner named as its assignee -- the only shape promotion
# accepts (AC7), so it is what a test about reaching the queue has to use.
ASSIGNED_ISSUE = {"id": "10002", "key": "OPS-2",
                  "fields": {"summary": "Fix the thing", "updated": "2026-09-18T08:30:00.000+0000",
                             "assignee": {"accountId": OWNER_ACCOUNT_ID}}}


def test_jira_sync_is_registered_under_the_generic_dispatch() -> None:
    assert JIRA_SOURCE_KIND in registered_kinds()


def test_jira_sync_uses_the_jira_spelling_source_kind() -> None:
    """Spelled identically in the enum and the handler, or
    ``scripts/deaddocs_check.py`` reads the connector as retired."""
    assert JIRA_SOURCE_KIND == SourceKind.jira.value


def test_jira_sync_fails_closed_when_jira_is_not_configured() -> None:
    with pytest.raises(SyncError, match="Jira is not configured"):
        sync(Settings(), kind=JIRA_SOURCE_KIND)


def test_jira_sync_ignores_the_graph_only_client_kwarg() -> None:
    """A non-``JiraClient`` object passed as ``client`` (what ``sync()`` always
    forwards, per its own signature) must never be touched by this handler."""
    settings = _configured_settings()
    graph_shaped_sentinel = object()

    with Session(engine) as session:
        result = _sync_jira(settings, db=session, client=graph_shaped_sentinel, jira_client=_client_with([]))

    assert result["count"] == 0


def test_jira_sync_stores_a_fetched_issue_as_a_source_with_the_kind_id_external_id() -> None:
    settings = _configured_settings()

    with Session(engine) as session:
        result = _sync_jira(settings, db=session, jira_client=_client_with([ISSUE]))

        assert result["new_sources"] == 1
        source = session.query(Source).filter_by(external_id="jira:10001").one()
        assert source.kind == SourceKind.jira
        assert source.subject == "Fix the thing"
        assert source.url == "https://example.atlassian.net/browse/OPS-1"
        # The issue's own ``updated``, not the time of the sync. ``observed_at`` is
        # the indexed column the queue lists and sorts on (``alembic 0006``), so
        # dropping it would silently reorder every Jira issue to "arrived now"
        # (``parse_observed_at`` falls back to ``datetime.now()``).
        assert source.observed_at == datetime(2026, 9, 18, 8, 30)


def test_jira_sync_stores_an_issue_with_no_key_and_no_fields_block() -> None:
    """``/search/jql`` guarantees only ``id``: a row can arrive with no ``fields``
    block at all (the endpoint's own default) and no ``key``. Neither may crash the
    sync, invent a browse link for an issue that has no key, or store an untitled
    issue with no title -- the queue renders ``subject`` and ``url`` directly."""
    settings = _configured_settings()

    with Session(engine) as session:
        result = _sync_jira(settings, db=session, jira_client=_client_with([{"id": "2"}]))

        assert result["new_sources"] == 1
        source = session.query(Source).filter_by(external_id="jira:2").one()
        assert source.subject == "(no summary)"
        assert source.url is None


def test_jira_sync_keeps_one_signal_for_an_issue_repeated_across_two_pages() -> None:
    """``search_participation_issues`` follows ``nextPageToken`` cursors, and
    ``/search/jql`` guarantees nothing about consistency across pages while the
    ``updated >= -{N}m`` window is re-evaluated per request -- so the same ``id``
    can arrive twice. This pins the handling, not any particular cause: the dedup
    in ``_fetch_issue_signals`` is what keeps the envelope's ``count`` honest."""
    settings = _configured_settings()

    with Session(engine) as session:
        result = _sync_jira(settings, db=session, jira_client=_paging_client_with([[ISSUE], [ISSUE]]))

    assert result["count"] == 1
    assert result["new_sources"] == 1


def test_jira_sync_names_the_missing_env_var_when_jira_is_not_configured() -> None:
    """AC12: fail closed naming the variable to set, never a bare refusal --
    ``jira_configuration_errors()`` returns the names precisely so the message can
    carry them, and a caller reading the 409 has nothing else to go on."""
    settings = _configured_settings(jira_api_token="")

    with pytest.raises(SyncError, match="Jira is not configured: missing JIRA_API_TOKEN"):
        sync(settings, kind=JIRA_SOURCE_KIND)


def test_jira_sync_fetches_through_the_handler_the_registry_hands_back() -> None:
    """Registration and the handler proven together: every other test here calls
    ``_sync_jira`` directly, which would still pass if the registry held some other
    callable under ``"jira"``."""
    handler = get_sync_handler(JIRA_SOURCE_KIND)

    with Session(engine) as session:
        result = handler(_configured_settings(), db=session, jira_client=_client_with([ISSUE]))

        assert result["new_sources"] == 1
        assert session.query(Source).filter_by(external_id="jira:10001").one().kind == SourceKind.jira


def test_jira_sync_returns_the_same_envelope_shape_every_registered_kind_returns() -> None:
    settings = _configured_settings()

    with Session(engine) as session:
        result = _sync_jira(settings, db=session, jira_client=_client_with([ISSUE]))

    assert result["mode"] == "read-only"
    assert set(("mode", "synced_at", "count", "new_sources", "new_work_items")) <= result.keys()
    assert result["count"] == 1


def test_jira_sync_promotes_an_assigned_issue_via_the_shared_heuristic() -> None:
    """The handler reaches the queue through ``promote_signals``, not around it.

    Only the assignment rule decides which issues arrive there; what that rule
    accepts and refuses is pinned in ``tests/test_jira_promotion.py``. This one
    holds the wiring shut: the work item carries the Jira kind, so a promotion
    that went through some other path would be visible here.
    """
    settings = _configured_settings()

    with Session(engine) as session:
        result = _sync_jira(settings, db=session, jira_client=_client_with([ASSIGNED_ISSUE]))

        assert result["new_work_items"] == 1
        work_item = session.query(WorkItem).filter_by(source_external_id="jira:10002").one()
        assert work_item.source_kind == SourceKind.jira


def test_jira_sync_is_idempotent_across_repeated_syncs_of_the_same_issue() -> None:
    settings = _configured_settings()

    with Session(engine) as session:
        first = _sync_jira(settings, db=session, jira_client=_client_with([ISSUE]))
        second = _sync_jira(settings, db=session, jira_client=_client_with([ISSUE]))

    assert first["new_sources"] == 1
    assert second["new_sources"] == 0
    assert second["new_work_items"] == 0


def test_jira_sync_handler_registers_via_the_main_import_alone() -> None:
    """``app/main.py`` must itself trigger registration -- not merely importing
    ``app.services.jira_sync`` directly, the way every other test in this file
    does. A fresh interpreter is the only way to isolate that: within this
    pytest process, some other test module has already imported ``app.main``
    (or ``app.services.jira_sync`` directly) before this one runs, which would
    make the registry non-empty regardless of whether ``main.py`` itself
    imports the registering module.
    """
    script = "import app.main\nfrom app.services.sync_registry import registered_kinds\nassert 'jira' in registered_kinds(), registered_kinds()\n"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parent.parent,
        env=os.environ,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr


# --- the search window and the sync cursor ----------------------------------

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def _window_of(jql: str) -> int:
    match = re.search(r"updated >= -(\d+)m", jql)
    assert match is not None, jql
    return int(match.group(1))


class _WindowRecordingTransport:
    """Answers like ``_client_with`` and remembers the window each participation
    search asked for; ``fail`` makes the search raise a ``JiraError`` and
    ``myself_fails`` does the same for the ``/myself`` lookup."""

    def __init__(self, issues: list[dict[str, Any]] | None = None, fail: bool = False, myself_fails: bool = False) -> None:
        self.windows: list[int] = []
        self._issues = issues or []
        self._fail = fail
        self._myself_fails = myself_fails

    def __call__(self, method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        if url.endswith("/myself"):
            if self._myself_fails:
                raise JiraError("Jira request failed with status 503")
            return {"accountId": OWNER_ACCOUNT_ID}
        jql = parse_qs(urlparse(url).query)["jql"][0]
        if jql.startswith("project ="):
            return {"issues": []}
        self.windows.append(_window_of(jql))
        if self._fail:
            raise JiraError("Jira request failed with status 500")
        return {"issues": self._issues}

    def client(self, **settings_overrides: Any) -> JiraClient:
        return JiraClient.from_settings(_configured_settings(**settings_overrides), transport=self)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Freeze ``jira_sync``'s notion of now at ``NOW``. Set ``step`` to make every
    reading later than the one before, to tell the start of a sync from its end."""
    state: dict[str, Any] = {"now": NOW, "step": timedelta(0)}

    def now() -> datetime:
        reading = state["now"]
        state["now"] = reading + state["step"]
        return reading

    monkeypatch.setattr(jira_sync, "_utc_now", now)
    return state


@pytest.mark.parametrize(
    ("gap", "expected_minutes"),
    [
        (timedelta(minutes=30), 35),
        (timedelta(seconds=90), 7),
        (timedelta(seconds=60), 6),
        (timedelta(0), 5),
        (timedelta(days=-1), 5),
        (timedelta(days=14), 14 * 1440),
        (timedelta(days=60), 14 * 1440),
    ],
)
def test_participation_window_is_the_gap_plus_overlap_capped_at_the_lookback(gap: timedelta, expected_minutes: int) -> None:
    assert participation_window_minutes(NOW - gap, NOW, lookback_days=14) == expected_minutes


def test_participation_window_without_a_cursor_is_the_whole_lookback() -> None:
    assert participation_window_minutes(None, NOW, lookback_days=3) == 3 * 1440


def test_jira_sync_without_a_cursor_searches_the_lookback_window(clock) -> None:
    transport = _WindowRecordingTransport()

    with Session(engine) as session:
        result = _sync_jira(_configured_settings(jira_sync_lookback_days=3), db=session, jira_client=transport.client())

    assert transport.windows == [4320]
    assert result["window_minutes"] == 4320


def test_jira_sync_uses_the_gap_since_the_last_success_plus_overlap(clock) -> None:
    transport = _WindowRecordingTransport()

    with Session(engine) as session:
        record_success(session, JIRA_SOURCE_KIND, NOW - timedelta(minutes=30))
        result = _sync_jira(_configured_settings(), db=session, jira_client=transport.client())

    assert transport.windows == [35]
    assert result["window_minutes"] == 35


def test_jira_sync_after_a_long_gap_is_capped_at_the_lookback(clock) -> None:
    transport = _WindowRecordingTransport()

    with Session(engine) as session:
        record_success(session, JIRA_SOURCE_KIND, NOW - timedelta(days=90))
        result = _sync_jira(_configured_settings(jira_sync_lookback_days=2), db=session, jira_client=transport.client())

    assert transport.windows == [2 * 1440]
    assert result["window_minutes"] == 2 * 1440


def test_jira_sync_without_a_database_searches_the_lookback_window_and_keeps_no_cursor(clock) -> None:
    transport = _WindowRecordingTransport()

    result = _sync_jira(_configured_settings(), db=None, jira_client=transport.client())

    assert transport.windows == [14 * 1440]
    assert result["window_minutes"] == 14 * 1440
    with Session(engine) as session:
        assert last_success(session, JIRA_SOURCE_KIND) is None


def test_jira_sync_records_the_moment_it_started_as_the_cursor(clock) -> None:
    """Not the moment it finished: an issue updated while the sync ran has to fall
    inside the next window rather than in the gap between the two."""
    clock["step"] = timedelta(minutes=1)

    with Session(engine) as session:
        result = _sync_jira(_configured_settings(), db=session, jira_client=_WindowRecordingTransport().client())
        assert last_success(session, JIRA_SOURCE_KIND) == NOW

    assert result["synced_at"] > NOW.isoformat()


def test_jira_sync_advances_the_cursor_so_the_next_sync_asks_for_less(clock) -> None:
    transport = _WindowRecordingTransport()

    with Session(engine) as session:
        _sync_jira(_configured_settings(), db=session, jira_client=transport.client())
        clock["now"] = NOW + timedelta(minutes=10)
        _sync_jira(_configured_settings(), db=session, jira_client=transport.client())

    assert transport.windows == [14 * 1440, 15]


def test_jira_sync_that_fails_leaves_the_cursor_where_it_was(clock) -> None:
    previous = NOW - timedelta(hours=2)
    failing = _WindowRecordingTransport(fail=True)

    with Session(engine) as session:
        record_success(session, JIRA_SOURCE_KIND, previous)
        with pytest.raises(SyncError, match="Jira request failed with status 500"):
            _sync_jira(_configured_settings(), db=session, jira_client=failing.client())
        assert last_success(session, JIRA_SOURCE_KIND) == previous

        # and the retry still covers everything since the last success
        retry = _WindowRecordingTransport()
        _sync_jira(_configured_settings(), db=session, jira_client=retry.client())

    assert retry.windows == [125]


def test_jira_sync_that_fails_with_no_cursor_does_not_invent_one(clock) -> None:
    with Session(engine) as session:
        with pytest.raises(SyncError, match="Jira request failed with status 500"):
            _sync_jira(_configured_settings(), db=session, jira_client=_WindowRecordingTransport(fail=True).client())
        assert last_success(session, JIRA_SOURCE_KIND) is None


def test_jira_sync_keeps_the_envelope_keys_it_always_had_beside_the_window(clock) -> None:
    with Session(engine) as session:
        result = _sync_jira(_configured_settings(), db=session, jira_client=_client_with([ISSUE]))

    assert set(("mode", "synced_at", "count", "new_sources", "new_work_items", "window_minutes")) <= result.keys()


def test_jira_sync_whose_owner_lookup_fails_stores_the_issues_but_leaves_the_cursor(clock) -> None:
    """Nothing was judged for promotion without the owner's id, so the window is not
    covered: moving the cursor would make the next sync skip these issues for good."""
    previous = NOW - timedelta(hours=2)
    lookup_down = _WindowRecordingTransport(issues=[ASSIGNED_ISSUE], myself_fails=True)

    with Session(engine) as session:
        record_success(session, JIRA_SOURCE_KIND, previous)
        result = _sync_jira(_configured_settings(), db=session, jira_client=lookup_down.client())

        assert result["new_sources"] == 1 and result["new_work_items"] == 0
        assert last_success(session, JIRA_SOURCE_KIND) == previous

        # the next sync, with /myself back, re-covers the same window and promotes
        recovered = _WindowRecordingTransport(issues=[ASSIGNED_ISSUE])
        retry = _sync_jira(_configured_settings(), db=session, jira_client=recovered.client())
        assert last_success(session, JIRA_SOURCE_KIND) == NOW

    assert recovered.windows == [125]
    assert retry["new_work_items"] == 1


def test_jira_sync_whose_owner_lookup_fails_with_no_cursor_does_not_invent_one(clock) -> None:
    with Session(engine) as session:
        _sync_jira(_configured_settings(), db=session, jira_client=_WindowRecordingTransport(myself_fails=True).client())
        assert last_success(session, JIRA_SOURCE_KIND) is None


@pytest.fixture
def jira_search_down(monkeypatch: pytest.MonkeyPatch) -> str:
    """The registered Jira handler, with a client whose search fails; returns the message Jira's error carries."""
    failing = _WindowRecordingTransport(fail=True).client()
    monkeypatch.setattr(jira_sync, "JiraClient", SimpleNamespace(from_settings=lambda settings: failing))
    return "Jira request failed with status 500"


def test_a_jira_search_failure_is_a_sync_error_carrying_jiras_message(jira_search_down: str) -> None:
    with pytest.raises(SyncError, match=jira_search_down) as raised:
        _sync_jira(_configured_settings(), db=None)

    assert isinstance(raised.value.__cause__, JiraError)


def test_post_sync_for_jira_answers_409_with_the_reason_when_the_search_fails(jira_search_down: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.sync.get_settings", _configured_settings)

    with TestClient(app) as client:
        response = client.post("/api/sync", params={"kind": "jira"}, headers={"Authorization": "Bearer test-local-agent-token"})

    assert response.status_code == 409
    assert response.json() == {"detail": jira_search_down}


def test_sync_all_reports_a_jira_search_failure_as_jiras_message_without_logging_a_traceback(
    jira_search_down: str, caplog: pytest.LogCaptureFixture
) -> None:
    with Session(engine) as session, caplog.at_level(logging.ERROR):
        results = sync_ready_sources(_configured_settings(), session)

    assert results["jira"] == {"error": jira_search_down}
    assert not [record for record in caplog.records if record.exc_info]


def _always_another_page(include_project: bool, include_participation: bool = True):
    """A transport whose project and/or participation search never runs out of pages."""

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        if url.endswith("/myself"):
            return {"accountId": OWNER_ACCOUNT_ID}
        is_project = parse_qs(urlparse(url).query)["jql"][0].startswith("project =")
        if (is_project and include_project) or (not is_project and include_participation):
            return {"issues": [], "nextPageToken": "more"}
        return {"issues": []}

    return JiraClient.from_settings(_configured_settings(), transport=transport)


@pytest.mark.parametrize(
    ("project_key", "client", "truncated"),
    [
        (None, _always_another_page(include_project=False), True),
        ("OPS", _always_another_page(include_project=True, include_participation=False), True),
        ("OPS", _always_another_page(include_project=False, include_participation=False), False),
    ],
    ids=["participation-cut-off", "project-cut-off", "neither-cut-off"],
)
def test_jira_sync_envelope_says_whether_either_search_was_cut_off(project_key: str | None, client: JiraClient, truncated: bool) -> None:
    settings = _configured_settings(**({"jira_management_project_key": project_key} if project_key else {}))

    with Session(engine) as session:
        result = _sync_jira(settings, db=session, jira_client=client)

    assert result["truncated"] is truncated
