"""One Jira issue, one work item, whichever door it arrives through (AC9).

A Jira issue reaches the queue twice. Its notification mail promotes as soon as
the Graph sync sees it -- ``promotion.TICKET_SENDER_MARKERS`` exists so a ticket
robot's mail counts as somebody's request rather than as bulk -- and the
participation query promotes the issue itself when the poll catches up. The two
carry unrelated identities (``outlook:{id}`` and ``jira:{id}``), so without
something matching them the same ticket sits in the queue twice.

**The owner's ordering: mail promotes, and the API replaces it.** Nothing waits
for the poll to become visible, and when the poll arrives the mail item is
re-pointed at the issue rather than deleted and recreated
(:func:`merge_into`). Keeping the row is what makes a dismissal survive: the
status is never rewritten, so an item the owner dismissed while only its mail
existed is still dismissed afterwards. In the other order there is nothing to
replace -- the mail's evidence joins the item the API already created.

**What matches the two.** The Jira issue key. On the API side the issue reports
it. On the mail side it is extracted here, and only from mail a Jira robot sent:
a bare ``ABC-123`` in a colleague's subject line is as likely to be a release
name as an issue key, and matching on it would fold an unrelated message into
somebody's ticket. Which work item holds which key is stored
(``models.WorkItemIssueKey``) rather than re-derived: the two arrivals are
separated by however long the poll takes, and by then nothing on the stored work
item says which issue it is about -- its ``external_id`` is the message's, and
the excerpt the key was read from is a column the database holds encrypted.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SourceKind, WorkEvidence, WorkItem, WorkItemIssueKey
from ..schemas import WorkItemCreate

# The Jira members of ``promotion.TICKET_SENDER_MARKERS``, matched against the
# whole address like that constant is: the marker lives in the domain
# (``jira@acme.atlassian.net``) as often as in the local part. Freshservice is
# deliberately not here -- it is a ticket system whose mail promotes, but its
# tickets have no Jira issue key and nothing on the API side to match.
JIRA_MAIL_SENDER_MARKERS = ("jira", "atlassian")

# ``PROJECT-123``: an upper-case alphanumeric project part starting with a letter,
# then the issue number. Deliberately narrow rather than a survey of what Jira
# accepts as a project key -- a missed key costs one merge, a wrongly matched one
# folds two unrelated tickets together.
_ISSUE_KEY = r"[A-Z][A-Z0-9]+-\d+"
# A link into the issue -- the form modern Atlassian notifications carry when the
# subject says only "Dana assigned an issue to you".
_BROWSE_LINK = re.compile(rf"/browse/({_ISSUE_KEY})")
_SUBJECT_KEY = re.compile(rf"\b({_ISSUE_KEY})\b")


def _is_jira_sender(sender: object) -> bool:
    return bool(sender) and any(marker in str(sender).lower() for marker in JIRA_MAIL_SENDER_MARKERS)


def _issue_key_from_mail(signal: dict[str, Any]) -> str | None:
    """The issue a Jira notification is about, or ``None``.

    The body's ``/browse/`` link is read first because it names the issue
    structurally; a key-shaped word in the subject is read only when there is no
    link. Mail from anyone but a Jira sender yields ``None`` without either being
    consulted.
    """
    if not _is_jira_sender(signal.get("sender")):
        return None
    link = _BROWSE_LINK.search(str(signal.get("excerpt") or ""))
    if link:
        return link.group(1)
    subject = _SUBJECT_KEY.search(str(signal.get("title") or ""))
    return subject.group(1) if subject else None


def issue_key(signal: dict[str, Any]) -> str | None:
    """The Jira issue this normalized signal is about, or ``None`` for one that
    names no issue.

    A Jira signal carries the key the API reported (``jira_sync._normalize_issue``);
    anything else is treated as mail and has to be read.
    """
    if str(signal.get("source_kind") or "") == SourceKind.jira.value:
        key = signal.get("issue_key")
        return str(key) if key else None
    return _issue_key_from_mail(signal)


def work_item_for_issue(db: Session, key: str) -> WorkItem | None:
    """The work item already holding this issue, from either arrival."""
    return db.scalar(
        select(WorkItem)
        .join(WorkItemIssueKey, WorkItemIssueKey.work_item_id == WorkItem.id)
        .where(WorkItemIssueKey.issue_key == key)
    )


def link_issue(db: Session, item: WorkItem, key: str) -> None:
    """Record which issue a newly created work item is about."""
    db.add(WorkItemIssueKey(work_item_id=item.id, issue_key=key))


def merge_into(db: Session, item: WorkItem, payload: WorkItemCreate) -> None:
    """Fold a second arrival of one issue into the item that already holds it.

    The API record replaces a mail item's identity -- title, kind, external id and
    link -- so the queue ends up pointing at the issue rather than at the message
    announcing it. Nothing else on the row is touched: status, priority, assignee
    and every other field the owner may have set stay as they are, which is how a
    dismissal survives the replacement.

    Mail arriving after the API replaces nothing; it only leaves its evidence.
    Evidence is added at most once per ``external_id``, because the mail's own
    identity no longer matches the item once the API has replaced it -- the
    ``source_external_id`` check that makes ``promote_signals`` idempotent cannot
    see it again, and without this the same notification would add a row on every
    sync.
    """
    if payload.source_kind == SourceKind.jira and item.source_kind != SourceKind.jira:
        item.title = payload.title
        item.source_kind = payload.source_kind
        item.source_external_id = payload.source_external_id
        item.source_url = str(payload.source_url) if payload.source_url else None
    carried = {evidence.external_id for evidence in item.evidence}
    for evidence in payload.evidence:
        if evidence.external_id in carried:
            continue
        item.evidence.append(WorkEvidence(**evidence.model_dump(exclude={"observed_at"}),
                                          observed_at=evidence.observed_at))
