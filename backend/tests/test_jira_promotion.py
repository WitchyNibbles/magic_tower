"""AC7: only a Jira issue assigned to the owner is promoted into the queue.

T06 left promotion to the *email* heuristic, which finds no sender, no headers and
no recipients on a Jira signal and so promotes every fetched issue through its last,
permissive rule. This module pins the rule that replaces that: a signal whose
``source_kind`` is ``jira`` is decided by one question -- is it assigned to the
owner -- and never by the mail rules, none of which have anything to read on it.

**How the owner is recognised.** By the ``accountId`` of the account the configured
API token belongs to, read from ``GET /rest/api/3/myself`` at sync time. Jira
identifies people by ``accountId``, never by email, so ``JIRA_ACCOUNT_EMAIL``
cannot be compared against ``fields.assignee``; and the participation window is
already defined by ``currentUser()`` in ``JIRA_PARTICIPATION_JQL``, so the token
owner is the only identity this connector has ever meant by "the owner".
Recognising them from the same account the JQL already speaks of keeps the two
from drifting, and costs the owner no extra setting to fill in with an opaque ID.

**Fail closed.** When the owner cannot be recognised -- ``/myself`` unreachable,
or no ``accountId`` in its response -- nothing is promoted, rather than everything.
The rejected issues are still stored: the tests below assert the ``Source`` row and
its ledger entry survive, because AC7 suppresses promotion only. Reporter, creator,
watcher and voter involvement stays browsable exactly this way.

Each clause is falsifiable on its own; the fixtures vary one field at a time.
Every fixture is synthetic and no test here reaches the network -- the client is
built on an injectable transport, the seam ``tests/test_jira_client.py`` uses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.database import engine
from app.integrations.jira import JiraClient, JiraError
from app.models import Source, SourceKind, SourcePromotion, WorkItem
from app.services.backfill import backfill_promoted_sources
from app.services.jira_sync import JIRA_SOURCE_KIND, _sync_jira
from app.services.promotion import should_promote

# Atlassian account IDs are opaque; these two only have to be distinguishable.
OWNER_ACCOUNT_ID = "5b10a2844c20165700ede21g"
COLLEAGUE_ACCOUNT_ID = "6d21b3955d31276811fef32h"


def _configured_settings(**overrides: str) -> Settings:
    values = {
        "jira_site_url": "https://example.atlassian.net",
        "jira_account_email": "owner@example.com",
        "jira_api_token": "a-real-token",
    }
    values.update(overrides)
    return Settings(**values)


def _issue(issue_id: str, assignee_account_id: str | None, **fields: Any) -> dict[str, Any]:
    """One ``/search/jql`` row. ``assignee`` is ``null`` on an unassigned issue --
    the key is present and empty, not absent, which is why the normalizer cannot
    lean on ``.get("assignee", {})``."""
    assignee = {"accountId": assignee_account_id} if assignee_account_id else None
    return {"id": issue_id, "key": f"OPS-{issue_id}",
            "fields": {"summary": f"Issue {issue_id}", "updated": "2026-09-18T08:30:00.000+0000",
                       "assignee": assignee, **fields}}


def _client(issues: list[dict[str, Any]], account_id: str | None = OWNER_ACCOUNT_ID,
            myself_fails: bool = False) -> JiraClient:
    """A stub transport answering both calls the sync makes: the participation
    search, and the ``/myself`` lookup that names the owner."""

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        if url.endswith("/myself"):
            if myself_fails:
                raise JiraError("Jira request failed")
            return {"accountId": account_id} if account_id is not None else {}
        return {"issues": issues}

    return JiraClient.from_settings(_configured_settings(), transport=transport)


def _signal(**overrides: Any) -> dict[str, Any]:
    """A normalized Jira signal as ``jira_sync._normalize_issue`` builds one."""
    return {
        "external_id": "jira:10001",
        "source_kind": JIRA_SOURCE_KIND,
        "title": "Fix the thing",
        "source_url": "https://example.atlassian.net/browse/OPS-1",
        "observed_at": "2026-09-18T08:30:00.000+0000",
        "assignee_account_id": OWNER_ACCOUNT_ID,
        **overrides,
    }


def test_jira_promotion_accepts_an_issue_assigned_to_the_owner() -> None:
    assert should_promote(_signal(), owner_account_id=OWNER_ACCOUNT_ID) is True


def test_jira_promotion_skips_an_issue_assigned_to_somebody_else() -> None:
    """Reporter, creator, watcher and voter involvement all arrive this way: the
    participation window fetched the issue, and somebody else owes the work."""
    assert should_promote(_signal(assignee_account_id=COLLEAGUE_ACCOUNT_ID),
                          owner_account_id=OWNER_ACCOUNT_ID) is False


def test_jira_promotion_skips_an_unassigned_issue() -> None:
    """An issue nobody is assigned is owed by nobody, least of all the owner."""
    assert should_promote(_signal(assignee_account_id=None), owner_account_id=OWNER_ACCOUNT_ID) is False


def test_jira_promotion_fails_closed_when_the_owner_cannot_be_recognised() -> None:
    """The crux of AC7: an unrecognised owner must promote nothing, not everything.

    Without this clause the rule degrades to the permissive default T07 exists to
    remove, and every watched issue lands in the queue the moment ``/myself`` fails.
    """
    assert should_promote(_signal(), owner_account_id=None) is False
    # Both sides unknown is the dangerous pair: absent equals absent, so without
    # the emptiness check every unassigned issue in the window promotes on exactly
    # the sync where the owner could not be named.
    assert should_promote(_signal(assignee_account_id=None), owner_account_id=None) is False


def test_jira_promotion_never_falls_through_to_the_mail_rules() -> None:
    """A Jira signal is decided by assignment alone, ahead of every mail rule.

    Both directions matter. A signal the mail rules would wave through (a human
    sender, no bulk headers) must still be rejected when it is assigned elsewhere;
    and one they would reject must still be promoted when it is the owner's.
    """
    mail_shaped = {"sender": "colleague@contoso.com", "sender_kind": "user",
                   "to_recipients": ["owner@contoso.com"], "headers": {}}
    bulk_shaped = {"sender": "noreply@example.atlassian.net", "sender_kind": "application",
                   "headers": {"Auto-Submitted": "auto-generated", "Precedence": "bulk"}}

    assert should_promote(_signal(assignee_account_id=COLLEAGUE_ACCOUNT_ID, **mail_shaped),
                          owner_account_id=OWNER_ACCOUNT_ID) is False
    assert should_promote(_signal(**bulk_shaped), owner_account_id=OWNER_ACCOUNT_ID) is True


def test_jira_promotion_leaves_the_mail_heuristic_untouched() -> None:
    """The new rule is reached by ``source_kind`` alone; mail keeps its own verdict.

    A known owner account must not start rejecting mail, which carries no assignee
    and would fail the assignment rule if the branch were keyed on anything looser.
    """
    email = {"external_id": "outlook:1", "source_kind": "outlook_email", "title": "Release window",
             "sender": "colleague@contoso.com", "sender_kind": "user",
             "to_recipients": ["owner@contoso.com"], "headers": {}}

    assert should_promote(email, ("owner@contoso.com",), owner_account_id=OWNER_ACCOUNT_ID) is True


def test_jira_promotion_recognises_the_owner_from_the_myself_endpoint() -> None:
    """Sync-level proof that the ``accountId`` compared against is the token
    owner's, read from ``/rest/api/3/myself`` -- not the configured email, which
    Jira never puts in ``fields.assignee``."""
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        if url.endswith("/myself"):
            return {"accountId": OWNER_ACCOUNT_ID}
        return {"issues": [_issue("10001", OWNER_ACCOUNT_ID)]}

    client = JiraClient.from_settings(_configured_settings(), transport=transport)
    with Session(engine) as session:
        result = _sync_jira(_configured_settings(), db=session, jira_client=client)

    assert "https://example.atlassian.net/rest/api/3/myself" in calls
    assert result["new_work_items"] == 1


def test_jira_promotion_stores_a_non_assigned_issue_without_promoting_it() -> None:
    """AC7 in one run: involvement is stored and browsable, never queued.

    The ``Source`` row is what the browse view reads, and the ``SourcePromotion``
    ledger row is what stops ``backfill_promoted_sources`` from offering the issue
    again later and promoting what this rule just declined.
    """
    with Session(engine) as session:
        result = _sync_jira(_configured_settings(), db=session,
                            jira_client=_client([_issue("10002", COLLEAGUE_ACCOUNT_ID)]))

        assert result["new_sources"] == 1
        assert result["new_work_items"] == 0
        source = session.query(Source).filter_by(external_id="jira:10002").one()
        assert source.kind == SourceKind.jira
        assert session.get(SourcePromotion, source.id) is not None
        assert session.query(WorkItem).filter_by(source_external_id="jira:10002").one_or_none() is None


def test_jira_promotion_promotes_only_the_assigned_issue_of_a_mixed_window() -> None:
    """The participation window returns all five involvements at once; exactly the
    assigned one becomes work."""
    issues = [_issue("1", OWNER_ACCOUNT_ID), _issue("2", COLLEAGUE_ACCOUNT_ID), _issue("3", None)]

    with Session(engine) as session:
        result = _sync_jira(_configured_settings(), db=session, jira_client=_client(issues))

        assert result["new_sources"] == 3
        assert result["new_work_items"] == 1
        assert [item.source_external_id for item in session.query(WorkItem).all()] == ["jira:1"]


def test_jira_promotion_stores_everything_and_promotes_nothing_when_myself_fails() -> None:
    """A failed owner lookup costs promotion, never storage, and never the sync.

    ``/myself`` is not the participation query; an issue already fetched must not be
    thrown away because the identity call failed, and it must not be promoted on the
    strength of an owner nobody could name.
    """
    with Session(engine) as session:
        result = _sync_jira(_configured_settings(), db=session,
                            jira_client=_client([_issue("10001", OWNER_ACCOUNT_ID)], myself_fails=True))

        assert result["new_sources"] == 1
        assert result["new_work_items"] == 0
        assert session.query(Source).filter_by(external_id="jira:10001").one().subject == "Issue 10001"


def test_jira_promotion_fails_closed_when_myself_names_no_account_id() -> None:
    """A 200 with an unexpected body is as unrecognised as a failed call."""
    with Session(engine) as session:
        result = _sync_jira(_configured_settings(), db=session,
                            jira_client=_client([_issue("10001", OWNER_ACCOUNT_ID)], account_id=None))

        assert result["new_sources"] == 1
        assert result["new_work_items"] == 0


def test_jira_promotion_does_not_let_the_backfill_promote_a_stored_jira_source() -> None:
    """The backfill has neither the stored assignee nor an owner ``accountId``, so
    the assignment rule cannot be satisfied there and the issue stays out of the
    queue. That is the fail-closed direction: the owner's manual promote (T08) is
    the way a Jira issue enters the queue outside a live sync, not a guess made
    from a row that never kept who it was assigned to.
    """
    with Session(engine) as session:
        session.add(Source(kind=SourceKind.jira, external_id="jira:99", subject="Watched issue",
                           url="https://example.atlassian.net/browse/OPS-99",
                           observed_at=datetime(2026, 9, 1, 8, 30)))
        session.commit()

        result = backfill_promoted_sources(session)

        assert result["considered"] == 1
        assert result["new_work_items"] == 0
