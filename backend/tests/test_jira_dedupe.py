"""AC9: one issue, one work item, whether it arrives as mail or over the API.

Jira notification mail already promotes on its own -- ``TICKET_SENDER_MARKERS``
(``app/services/promotion.py``) exists so a ticket robot's mail is treated as
somebody's request rather than as bulk. Once the participation query fetches the
same issue, the queue holds it twice under two ``external_id``s: ``outlook:{id}``
for the mail and ``jira:{id}`` for the issue.

**The ordering the owner chose.** Mail promotes immediately and the API replaces
it when the poll catches up, so nothing is invisible while waiting. "Replaces"
means the same ``WorkItem`` row is re-pointed at the issue -- the tests below
assert its ``id`` does not change. The replacement rewrites the title, kind,
``source_external_id`` and link and nothing else, so a dismissal survives it --
as do ``priority``, ``summary``, ``assigned_agent`` and ``due_at``.

**What matches the two.** The Jira issue key: taken from the issue itself on the
API side, and extracted from notification mail on the other. Extraction is gated
on a Jira sender, because a bare ``ABC-123`` in a colleague's subject line is not
an issue key -- the tests below pin both directions of that gate.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import SessionLocal, engine
from app.integrations.jira import JiraClient
from app.models import SourceKind, WorkItem, WorkStatus
from app.schemas import WorkItemCreate
from app.services.graph import persist_signals
from app.services.jira_dedupe import issue_key, link_issue
from app.services.jira_sync import JIRA_SOURCE_KIND, _normalize_issue, _sync_jira
from app.services.promotion import promote_signals
from app.services.work_items import create_work_item, dismiss_work_item

OWNER_ACCOUNT_ID = "5b10a2844c20165700ede21g"
OWNER_ADDRESS = "owner@contoso.com"
SITE_URL = "https://example.atlassian.net"


def _configured_settings() -> Settings:
    return Settings(jira_site_url=SITE_URL, jira_account_email="owner@example.com",
                    jira_api_token="a-real-token")


def _issue(issue_id: str, key: str) -> dict[str, Any]:
    """One ``/search/jql`` row assigned to the owner, so it promotes (AC7)."""
    return {"id": issue_id, "key": key,
            "fields": {"summary": f"Issue {key}", "updated": "2026-09-18T08:30:00.000+0000",
                       "assignee": {"accountId": OWNER_ACCOUNT_ID}}}


def _client(issues: list[dict[str, Any]]) -> JiraClient:
    """A stub transport answering the participation search and the ``/myself``
    lookup that names the owner; no test here reaches the network."""

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        if url.endswith("/myself"):
            return {"accountId": OWNER_ACCOUNT_ID}
        return {"issues": issues}

    return JiraClient.from_settings(_configured_settings(), transport=transport)


def _mail_signal(external_id: str = "outlook:1", title: str = "(OPS-1) Fix the thing",
                 excerpt: str = "Dana assigned an issue to you.",
                 sender: str = "jira@example.atlassian.net") -> dict[str, Any]:
    """A Jira notification as ``graph.normalize_email`` hands it to promotion.

    ``Auto-Submitted`` is what a real one carries, and what rule 3 would reject
    were the sender not a ticket system.
    """
    return {"external_id": external_id, "source_kind": "outlook_email", "title": title,
            "excerpt": excerpt, "source_url": "https://outlook.office.com/mail/id/AAQ",
            "observed_at": "2026-09-18T08:00:00+00:00", "sender": sender, "sender_kind": "user",
            "to_recipients": [OWNER_ADDRESS], "headers": {"Auto-Submitted": "auto-generated"}}


def _promote_mail(session: Session, signal: dict[str, Any]) -> int:
    """Store and promote one notification mail, the way a Graph sync does."""
    persist_signals(session, [signal])
    return promote_signals(session, [signal], (OWNER_ADDRESS,))


def _the_item(session: Session) -> WorkItem:
    return session.query(WorkItem).one()


def test_jira_dedupe_takes_the_key_from_a_notification_subject() -> None:
    assert issue_key(_mail_signal(title="(OPS-42) Fix the thing")) == "OPS-42"


def test_jira_dedupe_takes_the_key_from_a_browse_link_in_the_body() -> None:
    """Modern Atlassian notifications name the issue in the subject only as prose
    ("Dana assigned an issue to you"); the link in the body is what identifies it."""
    mail = _mail_signal(title="Dana assigned an issue to you",
                        excerpt=f"Open it at {SITE_URL}/browse/OPS-42 to get started.")

    assert issue_key(mail) == "OPS-42"


def test_jira_dedupe_prefers_the_browse_link_over_a_key_in_the_subject() -> None:
    """The documented precedence: when the subject and the body's link name
    different issues, the link is the one the notification is about."""
    mail = _mail_signal(title="(OPS-7) blocks the release",
                        excerpt=f"See {SITE_URL}/browse/OPS-42 for the fix.")

    assert issue_key(mail) == "OPS-42"


def test_jira_dedupe_reads_no_key_from_mail_that_is_not_from_jira() -> None:
    """A bare key-shaped word is not an issue key. Sent by a colleague, ``OPS-42``
    could be a release name or a dated report, and merging on it would fold an
    unrelated message into somebody's ticket."""
    assert issue_key(_mail_signal(sender="colleague@contoso.com")) is None


def test_jira_dedupe_reads_no_key_from_jira_mail_that_names_no_issue() -> None:
    """A digest or an account notice from the same robot matches nothing and must
    not be merged into whichever ticket was queued first."""
    assert issue_key(_mail_signal(title="Your Jira summary", excerpt="You have 3 updates.")) is None


def test_jira_dedupe_takes_the_key_of_an_api_signal_from_the_issue_itself() -> None:
    """No extraction on this side: the issue says what its key is."""
    assert issue_key(_normalize_issue(_issue("10001", "OPS-42"), SITE_URL)) == "OPS-42"


def test_jira_dedupe_lets_the_api_replace_the_item_mail_already_promoted() -> None:
    """Mail-first, the ordering the owner chose: visible at once, replaced later.

    The same row is re-pointed at the issue rather than deleted and recreated, so
    the item never blinks out of the queue and anything hanging off it survives.
    """
    with Session(engine) as session:
        assert _promote_mail(session, _mail_signal()) == 1
        mail_item_id = _the_item(session).id
        assert _the_item(session).source_external_id == "outlook:1"

        result = _sync_jira(_configured_settings(), db=session,
                            jira_client=_client([_issue("10001", "OPS-1")]))

        assert result["new_work_items"] == 0
        item = _the_item(session)
        assert item.id == mail_item_id
        assert item.source_kind == SourceKind.jira
        assert item.source_external_id == "jira:10001"
        assert item.source_url == f"{SITE_URL}/browse/OPS-1"
        assert item.title == "Issue OPS-1"
        assert sorted(evidence.external_id for evidence in item.evidence) == ["jira:10001", "outlook:1"]


def test_jira_dedupe_keeps_mail_out_of_the_queue_once_the_api_has_the_issue() -> None:
    """API-first: the notification adds its evidence and nothing else."""
    with Session(engine) as session:
        result = _sync_jira(_configured_settings(), db=session,
                            jira_client=_client([_issue("10001", "OPS-1")]))
        assert result["new_work_items"] == 1

        assert _promote_mail(session, _mail_signal()) == 0

        item = _the_item(session)
        assert item.source_external_id == "jira:10001"
        assert sorted(evidence.external_id for evidence in item.evidence) == ["jira:10001", "outlook:1"]


def test_jira_dedupe_keeps_a_dismissal_when_the_api_replaces_the_mail_item() -> None:
    """The half a delete-and-recreate replacement would lose: a ticket the owner
    dismissed while only its mail existed stays dismissed once the poll catches up."""
    with Session(engine) as session:
        _promote_mail(session, _mail_signal())
        dismiss_work_item(session, _the_item(session).id)

        _sync_jira(_configured_settings(), db=session, jira_client=_client([_issue("10001", "OPS-1")]))

        item = _the_item(session)
        assert item.status == WorkStatus.dismissed
        assert item.source_external_id == "jira:10001"


def test_jira_dedupe_keeps_a_dismissal_when_the_mail_arrives_after_the_api() -> None:
    """The same guarantee in the other order: a dismissed issue must not come back
    as a fresh pending item because its notification mail was synced afterwards."""
    with Session(engine) as session:
        _sync_jira(_configured_settings(), db=session, jira_client=_client([_issue("10001", "OPS-1")]))
        dismiss_work_item(session, _the_item(session).id)

        assert _promote_mail(session, _mail_signal()) == 0
        assert _the_item(session).status == WorkStatus.dismissed


def test_jira_dedupe_carries_the_same_mail_across_as_evidence_only_once() -> None:
    """Re-syncing is the normal case, and the mail's own ``external_id`` no longer
    matches the item once the API has replaced it -- so the idempotency promotion
    gets from ``source_external_id`` has to be repeated on the evidence."""
    with Session(engine) as session:
        _promote_mail(session, _mail_signal())
        _sync_jira(_configured_settings(), db=session, jira_client=_client([_issue("10001", "OPS-1")]))

        assert _promote_mail(session, _mail_signal()) == 0

        assert len(_the_item(session).evidence) == 2


def test_jira_dedupe_folds_two_notifications_for_one_issue_from_one_sync() -> None:
    """Assigned, then commented on: two notifications for one issue in a single
    inbox window, run through the session the API serves requests with.

    ``SessionLocal`` is built with ``autoflush=False``; every other test here uses
    ``Session(engine)``, whose default flushes before each query. Under the
    production session the second mail has to find the link the first one added
    a moment earlier in the same batch -- otherwise the batch creates a second
    work item, and the final commit trips the ``issue_key`` uniqueness that is
    meant to be the floor, not the common path.
    """
    assigned = _mail_signal(external_id="outlook:1", title="(OPS-1) assigned to you")
    comment = _mail_signal(external_id="outlook:2", title="(OPS-1) new comment")
    with SessionLocal() as session:
        persist_signals(session, [assigned, comment])

        assert promote_signals(session, [assigned, comment], (OWNER_ADDRESS,)) == 1

        item = _the_item(session)
        assert item.source_external_id == "outlook:1"
        assert sorted(evidence.external_id for evidence in item.evidence) == ["outlook:1", "outlook:2"]


def test_jira_dedupe_keeps_two_different_issues_apart() -> None:
    """Dedupe matches on the key, not on "is Jira mail": two tickets stay two."""
    with Session(engine) as session:
        _promote_mail(session, _mail_signal(external_id="outlook:1", title="(OPS-1) First"))
        _promote_mail(session, _mail_signal(external_id="outlook:2", title="(OPS-2) Second"))

        _sync_jira(_configured_settings(), db=session,
                   jira_client=_client([_issue("10001", "OPS-1"), _issue("10002", "OPS-2")]))

        assert sorted(item.source_external_id for item in session.query(WorkItem).all()) == [
            "jira:10001", "jira:10002"]


def test_jira_dedupe_refuses_a_second_work_item_for_one_issue() -> None:
    """The floor under the lookup: even a caller that never asks which item holds
    an issue cannot end up with two, because ``issue_key`` is unique."""
    with Session(engine) as session:
        _promote_mail(session, _mail_signal(title="(OPS-1) Fix the thing"))
        elsewhere = create_work_item(session, WorkItemCreate(title="Typed in by hand"))

        link_issue(session, elsewhere, "OPS-1")

        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_jira_dedupe_still_promotes_notification_mail_the_api_has_not_reached() -> None:
    """The point of the ordering: dedupe must not cost the mail its promotion while
    the poll has not caught up. An unrelated issue's sync leaves it alone."""
    with Session(engine) as session:
        assert _promote_mail(session, _mail_signal(title="(OPS-1) Fix the thing")) == 1

        _sync_jira(_configured_settings(), db=session, jira_client=_client([_issue("10002", "OPS-2")]))

        assert sorted(item.source_external_id for item in session.query(WorkItem).all()) == [
            "jira:10002", "outlook:1"]
        assert session.query(WorkItem).filter_by(source_external_id=JIRA_SOURCE_KIND + ":10002").one()
