"""The Jira sync handler: fetches the participation window, stores it as
``Source`` rows and dispatches through the same envelope every registered kind
returns (``app/services/sync.py:sync``).

Each rule is falsified individually: dropping the enum member, the registration
call, or the normalization step reddens exactly the test that pins it. No test
here reaches the network -- everything goes through the injectable ``jira_client``
kwarg, the same seam ``test_jira_query.py`` and ``test_jira_client.py`` use.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import engine
from app.integrations.jira import JiraClient
from app.models import Source, SourceKind, WorkItem
from app.services.jira_sync import JIRA_SOURCE_KIND, _sync_jira
from app.services.sync import SyncError, sync
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
    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
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


ISSUE = {"id": "10001", "key": "OPS-1", "fields": {"summary": "Fix the thing", "updated": "2026-09-18T08:30:00.000+0000"}}


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
    """``search_participation_issues`` follows ``nextPageToken`` cursors over an
    ``ORDER BY updated DESC`` result, so an issue whose ``updated`` changes mid-walk
    moves back to the front and can be handed out on two pages. The dedup in
    ``_fetch_issue_signals`` is what keeps the envelope's ``count`` honest."""
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


def test_jira_sync_promotes_fetched_issues_via_the_shared_heuristic() -> None:
    """T06's known, temporary behaviour: the email heuristic
    (``app/services/promotion.py``) has nothing Jira-shaped to reject on a
    signal with no sender, headers or recipients, so it promotes every fetched
    issue unconditionally today. Restricting promotion to issues actually
    assigned to the owner is T07's job (``.companion/plan.md``), not this one's."""
    settings = _configured_settings()

    with Session(engine) as session:
        result = _sync_jira(settings, db=session, jira_client=_client_with([ISSUE]))

        assert result["new_work_items"] == 1
        work_item = session.query(WorkItem).filter_by(source_external_id="jira:10001").one()
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
