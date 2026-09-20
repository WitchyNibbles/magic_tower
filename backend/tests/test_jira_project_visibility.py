"""AC10: a named project syncs browse-only -- its issues become ``Source`` rows
that are never promoted, so a management view over a whole project cannot flood
the actionable queue.

**Mechanism.** ``Settings.jira_management_project_key`` (configuration, read by
``app/services/jira_sync.py``), not a per-source flag in ``SourceSignalContext``.
Issues in the configured project are fetched through
``JiraClient.search_project_issues`` (T09) -- the 2000 most recently updated of
them, which is where that call's pagination cap falls -- alongside the existing
participation window, and stored the same way ``_normalize_issue`` already stores any other Jira
issue. No new rule decides whether a project-fetched issue is promoted: the
assignee rule ``promotion.should_promote`` already pins (``test_jira_promotion.py``)
is the only thing that ever promotes a Jira signal, and it does not read which
query found the issue -- so an issue in the visible project is promoted if and
only if it is assigned to the owner, exactly like every other Jira issue. This
file exists to pin that a project-only fetch cannot promote on its own, and that
an issue reachable through both the participation and the project fetch is not
promoted twice.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import SessionLocal, engine
from app.integrations.jira import JiraClient
from app.models import Source, WorkItem
from app.services.jira_sync import _sync_jira

OWNER_ACCOUNT_ID = "5b10a2844c20165700ede21g"
COLLEAGUE_ACCOUNT_ID = "6d21b3955d31276811fef32h"
MANAGEMENT_PROJECT_KEY = "OPS"


def _configured_settings(**overrides: Any) -> Settings:
    values = {
        "jira_site_url": "https://example.atlassian.net",
        "jira_account_email": "owner@example.com",
        "jira_api_token": "a-real-token",
        "jira_management_project_key": MANAGEMENT_PROJECT_KEY,
    }
    values.update(overrides)
    return Settings(**values)


def _issue(issue_id: str, assignee_account_id: str | None) -> dict[str, Any]:
    assignee = {"accountId": assignee_account_id} if assignee_account_id else None
    return {"id": issue_id, "key": f"OPS-{issue_id}",
            "fields": {"summary": f"Issue {issue_id}", "updated": "2026-09-18T08:30:00.000+0000",
                       "assignee": assignee}}


def _client(participation_issues: list[dict[str, Any]], project_issues: list[dict[str, Any]]) -> JiraClient:
    """Answers the three calls a management-visible sync can make: ``/myself``,
    the participation search, and the project search -- routed by whether the
    request's ``jql`` carries the project clause, exactly as
    ``JiraClient.search_project_issues`` builds it."""

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        if url.endswith("/myself"):
            return {"accountId": OWNER_ACCOUNT_ID}
        jql = parse_qs(urlparse(url).query).get("jql", [""])[0]
        if jql.startswith("project ="):
            return {"issues": project_issues}
        return {"issues": participation_issues}

    return JiraClient.from_settings(_configured_settings(), transport=transport)


def test_jira_project_visibility_stores_a_project_issue_as_a_browsable_source() -> None:
    with Session(engine) as session:
        result = _sync_jira(_configured_settings(), db=session,
                             jira_client=_client([], [_issue("30001", None)]))

        assert result["new_sources"] == 1
        assert session.query(Source).filter_by(external_id="jira:30001").one() is not None


def test_jira_project_visibility_never_promotes_an_unassigned_project_issue() -> None:
    with Session(engine) as session:
        result = _sync_jira(_configured_settings(), db=session,
                             jira_client=_client([], [_issue("30002", None)]))

        assert result["new_work_items"] == 0
        assert session.query(WorkItem).filter_by(source_external_id="jira:30002").first() is None


def test_jira_project_visibility_never_promotes_a_project_issue_assigned_to_somebody_else() -> None:
    """A colleague's ticket in the visible project is browsable, not owed by the
    owner -- rule A refuses it exactly as it would outside the project."""
    with Session(engine) as session:
        result = _sync_jira(_configured_settings(), db=session,
                             jira_client=_client([], [_issue("30003", COLLEAGUE_ACCOUNT_ID)]))

        assert result["new_work_items"] == 0
        assert session.query(WorkItem).filter_by(source_external_id="jira:30003").first() is None


def test_jira_project_visibility_still_promotes_an_issue_assigned_to_the_owner_in_the_visible_project() -> None:
    """The one exception this task pins: an issue both assigned to the owner and
    inside the visible project must still reach the queue.

    A real Jira project search returns every issue in the project, including ones
    the participation query's ``assignee = currentUser()`` clause already found --
    so the stub hands the same issue back from both calls, and this asserts the
    sync promotes it exactly once rather than twice.
    """
    issue = _issue("30004", OWNER_ACCOUNT_ID)

    with SessionLocal() as session:
        result = _sync_jira(_configured_settings(), db=session, jira_client=_client([issue], [issue]))

        assert result["new_work_items"] == 1
        assert session.query(WorkItem).filter(WorkItem.source_external_id == "jira:30004").count() == 1


def test_jira_project_visibility_promotes_an_owner_assigned_issue_only_the_project_fetch_returns() -> None:
    """The same exception, with the project fetch as the *only* query that finds
    the issue -- which is what makes it load-bearing.

    ``JIRA_PARTICIPATION_JQL`` bounds every one of its clauses, ``assignee =
    currentUser()`` included, with ``AND updated >= -15m``
    (``app/integrations/jira.py``). An issue assigned to the owner but last
    updated before that window is therefore absent from the participation
    response and present only in the project one, so the copy that reaches
    ``promote_signals`` is the project copy. It must still promote, once.

    The sibling test above hands the same issue back from both calls, which the
    participation copy alone satisfies; this one stubs participation empty, so
    deleting the project fetch reddens it.
    """
    with SessionLocal() as session:
        result = _sync_jira(_configured_settings(), db=session,
                            jira_client=_client([], [_issue("30005", OWNER_ACCOUNT_ID)]))

        assert result["new_work_items"] == 1
        assert session.query(WorkItem).filter(WorkItem.source_external_id == "jira:30005").count() == 1


def test_jira_project_visibility_is_skipped_entirely_when_no_project_is_configured() -> None:
    """Without ``JIRA_MANAGEMENT_PROJECT_KEY`` set, the project search must never
    be called at all -- a sync that only wants the participation window pays no
    extra request for a feature it did not turn on."""

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        if url.endswith("/myself"):
            return {"accountId": OWNER_ACCOUNT_ID}
        jql = parse_qs(urlparse(url).query).get("jql", [""])[0]
        assert not jql.startswith("project ="), "project search must not run without a configured project key"
        return {"issues": []}

    settings = _configured_settings(jira_management_project_key=None)
    client = JiraClient.from_settings(settings, transport=transport)

    with Session(engine) as session:
        result = _sync_jira(settings, db=session, jira_client=client)

    assert result["count"] == 0


def test_jira_project_visibility_quotes_the_configured_project_key_in_the_jql() -> None:
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        return {"issues": []}

    JiraClient("https://example.atlassian.net", "owner@example.com", "token",
               transport=transport).search_project_issues(MANAGEMENT_PROJECT_KEY)

    query = parse_qs(urlparse(calls[0]).query)
    assert query["jql"] == [f'project = "{MANAGEMENT_PROJECT_KEY}" ORDER BY updated DESC']


@pytest.mark.parametrize(
    ("project_key", "expected_jql"),
    [
        # A trailing backslash. Escaping the quote alone would emit
        # ``project = "OPS\" ORDER BY updated DESC``, where the closing quote is
        # itself escaped and the string never terminates.
        ("OPS\\", 'project = "OPS\\\\" ORDER BY updated DESC'),
        # An embedded quote, spelled to break out of the clause if it survives.
        ('OPS" OR assignee is not EMPTY OR project = "X',
         'project = "OPS\\" OR assignee is not EMPTY OR project = \\"X" ORDER BY updated DESC'),
    ],
)
def test_jira_project_visibility_escapes_backslashes_and_quotes_in_the_project_key(
    project_key: str, expected_jql: str
) -> None:
    """``JIRA_MANAGEMENT_PROJECT_KEY`` is configuration, not a fixed literal, so
    the JQL it lands in has to survive whatever it holds.

    JQL's string escapes are ``\\\\`` and ``\\"``, so a backslash must be doubled
    *before* quotes are escaped -- otherwise the backslash the escaper emits is
    consumed by the one already in the value and the quoting is undone. Both keys
    here must come back as one quoted literal that ends where the escaper put its
    closing quote, leaving no unquoted JQL the key controls.
    """
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        return {"issues": []}

    JiraClient("https://example.atlassian.net", "owner@example.com", "token",
               transport=transport).search_project_issues(project_key)

    assert parse_qs(urlparse(calls[0]).query)["jql"] == [expected_jql]
