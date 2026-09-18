"""Promotion of normalized signals into the triage queue.

``persist_signals`` stores every signal a sync sees; this module decides which of
them are work and writes those as ``WorkItem`` rows, so the queue the GUI renders
is no longer empty after a sync.

The decision is one function, :func:`should_promote`, and it is deliberately
rule-based: no LLM, no network, no stored state. The same signal always decides the
same way, which is what lets the heuristic be scored against a labeled sample of
real mail and corrected by hand when it gets one wrong.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Any

from pydantic import HttpUrl, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Source, SourceKind, SourcePromotion, WorkItem
from ..schemas import EvidenceInput, WorkItemCreate
from .graph import parse_observed_at
from .work_items import conflict, create_work_item

# Matched against the local part with separators removed, so ``no-reply@``,
# ``no_reply@`` and ``noreply-github@`` are all the same address shape.
AUTOMATED_SENDER_MARKERS = ("noreply", "donotreply", "autoreply", "mailerdaemon", "postmaster",
                            "bounce", "newsletter", "marketing", "campaign", "mailinglist")
BULK_HEADERS = ("list-unsubscribe", "list-id", "list-post", "x-campaign-id")
# Senders whose mail is work despite being machine-generated. A ticket system
# raising a comment or an assignment is a request someone made of the owner; it
# only reaches them through a robot. Matched against the whole address, because the
# marker lives in the domain (``jira@acme.atlassian.net``,
# ``helpdesk@acme.freshservice.com``) as often as in the local part. Measured
# against a labeled sample: rules 2 and 3 rejected every ticket mail in it, and the
# owner had labeled all of them work.
TICKET_SENDER_MARKERS = ("jira", "atlassian", "freshservice")
PRECEDENCE_HEADER = "precedence"
AUTO_SUBMITTED_HEADER = "auto-submitted"
BULK_PRECEDENCE = frozenset({"bulk", "list", "junk"})
# Every header name ``_is_bulk_mail`` looks at, lowercased, derived from the names the
# rule itself uses so the two cannot drift apart. ``persist_signals`` stores these and
# discards the rest of Graph's header block: a name no rule reads is message metadata
# kept on disk for nothing.
HEURISTIC_HEADERS = frozenset(BULK_HEADERS) | {PRECEDENCE_HEADER, AUTO_SUBMITTED_HEADER}

TITLE_LIMIT = 500
# The same bound ``persist_signals`` puts on ``Source.excerpt``; the evidence copy
# is the same text and should not be able to grow past it.
EXCERPT_LIMIT = 2_000
FALLBACK_TITLE = "(no subject)"

# The same validator ``WorkItemCreate.source_url`` applies; a link it would reject
# (wrong scheme, no host, over 2083 characters) is dropped rather than truncated,
# because a truncated URL is a wrong one.
_HTTP_URL = TypeAdapter(HttpUrl)


def _local_part(sender: str) -> str:
    return re.sub(r"[^a-z0-9]", "", sender.split("@", 1)[0].lower())


def _is_automated_sender(sender: str | None) -> bool:
    return bool(sender) and any(marker in _local_part(str(sender)) for marker in AUTOMATED_SENDER_MARKERS)


def _is_ticket_system(sender: str | None) -> bool:
    """True for a sender whose machine-generated mail is nonetheless somebody's request."""
    return bool(sender) and any(marker in str(sender).lower() for marker in TICKET_SENDER_MARKERS)


def _is_allowlisted(sender: str | None, allowlisted_senders: Collection[str]) -> bool:
    """True for an address the owner has declared work whatever the rules decide.

    Compared whole and case-insensitively, not by substring: an allowlist is the
    owner naming one mailbox, and a substring match on a short name would quietly
    cover addresses they never named.
    """
    if not sender:
        return False
    return str(sender).strip().lower() in {address.strip().lower() for address in allowlisted_senders if address.strip()}


def _is_bulk_mail(headers: dict[str, Any]) -> bool:
    lowered = {str(name).lower(): str(value).strip().lower() for name, value in headers.items()}
    if any(header in lowered for header in BULK_HEADERS):
        return True
    if lowered.get(PRECEDENCE_HEADER) in BULK_PRECEDENCE:
        return True
    return lowered.get(AUTO_SUBMITTED_HEADER, "no") != "no"


def _is_only_copied(signal: dict[str, Any], owner_addresses: Collection[str]) -> bool:
    """True when the owner is known, there is a To list, and none of the owner's addresses is in it."""
    recipients = signal.get("to_recipients") or []
    owners = {address.strip().lower() for address in owner_addresses}
    if not owners or not recipients:
        return False
    return owners.isdisjoint(str(address).strip().lower() for address in recipients)


def should_promote(signal: dict[str, Any], owner_addresses: Collection[str] = (),
                   allowlisted_senders: Collection[str] = ()) -> bool:
    """Decide whether one normalized signal belongs in the triage queue.

    The rules, in order; the first that matches decides:

    0. Promote an allowlisted sender, whatever every later rule would say. This is
       the owner naming a mailbox the rules get wrong -- an internal robot whose
       output they act on -- and it overrides even rule 4, because such mail often
       arrives through a list rather than addressed to them.
    1. Skip anything posted by an application rather than a person. A Teams bot
       relaying build output is not work addressed to anybody.
    2. Skip an automated sender -- a local part carrying ``noreply``, ``donotreply``,
       ``autoreply``, ``mailer-daemon``, ``postmaster``, ``bounce``, ``newsletter``,
       ``marketing``, ``campaign`` or ``mailinglist``, compared with separators
       removed so punctuation cannot dodge the rule. The domain is not consulted:
       a person at a marketing agency is still a person.
    3. Skip bulk mail identified by the headers a mass mailing is obliged to carry:
       ``List-Unsubscribe``, ``List-Id``, ``List-Post``, ``X-Campaign-Id``,
       ``Precedence: bulk|list|junk``, or an ``Auto-Submitted`` other than ``no``.
       Leaning on headers is what lets rule 2 stay short and leave ``info@``,
       ``news@`` and ``updates@`` -- addresses real people also write from -- alone.
    4. Skip mail the owner was only copied on: the owner is known, the message
       carries a To list, and none of the owner's addresses is in it. Cc is an FYI,
       not a request. Teams messages carry no To list, so this rule cannot reject them.
    5. Otherwise promote: it reached the owner's own mailbox or chat, from a person.

    Rule 3 alone is skipped for a ticket-system sender (see
    ``TICKET_SENDER_MARKERS``): Jira and Freshservice mail carries the
    ``Auto-Submitted`` and ``Precedence`` a mass mailing carries, and rule 3 read it
    as bulk. Rules 2 and 4 still apply to them. Rule 2 costs a ticket system
    nothing -- ``jira@`` and ``helpdesk@`` carry no automated marker -- and keeping
    it in force means a ``noreply@`` on a ticket domain is still rejected. Rule 4
    means a ticket notification the owner was only copied on is as much an FYI as
    any other.

    ``owner_addresses`` are the signed-in user's own addresses -- both the principal
    name and the mail address, since alias-domain tenants hand out different ones.
    Without any, rule 4 is skipped rather than guessed at, so a missing profile
    costs recall, never silence.
    """
    sender = signal.get("sender")
    if _is_allowlisted(sender, allowlisted_senders):
        return True
    if signal.get("sender_kind") == "application":
        return False
    if _is_automated_sender(sender):
        return False
    if not _is_ticket_system(sender) and _is_bulk_mail(signal.get("headers") or {}):
        return False
    return not _is_only_copied(signal, owner_addresses)


def _source_url(value: object) -> HttpUrl | None:
    """Keep a source URL only when ``HttpUrl`` accepts it; one bad link must not abort the sync."""
    try:
        return _HTTP_URL.validate_python(str(value))
    except ValidationError:
        return None


def _work_item(signal: dict[str, Any]) -> WorkItemCreate:
    """Build the create payload, carrying the message excerpt across as evidence."""
    kind = SourceKind(str(signal["source_kind"]))
    external_id = str(signal["external_id"])
    return WorkItemCreate(
        title=(str(signal.get("title") or "").strip() or FALLBACK_TITLE)[:TITLE_LIMIT],
        source_kind=kind,
        source_external_id=external_id,
        source_url=_source_url(signal.get("source_url")),
        evidence=[EvidenceInput(
            source_kind=kind,
            external_id=external_id,
            excerpt=str(signal.get("excerpt") or "")[:EXCERPT_LIMIT] or None,
            observed_at=parse_observed_at(signal.get("observed_at")),
        )],
    )


def _record_considered(db: Session, external_id: str) -> None:
    """Record that promotion judged this signal's stored ``Source``, whatever it decided.

    Written for rejections as much as for promotions: a rejected ``Source`` is the
    one case ``work_items`` cannot describe on its own, and without this row the
    backfill in ``app/services/backfill.py`` would read it as a source promotion
    had never seen and promote it after all.

    Only a stored source can be recorded. ``promote_signals`` is also called with
    signals whose ``Source`` row was never written -- by the unit tests in
    ``tests/test_promotion.py``, and by any future caller that promotes without
    persisting -- and those have nothing for the backfill to reconsider anyway.
    """
    source_id = db.scalar(select(Source.id).where(Source.external_id == external_id))
    if source_id is not None and db.get(SourcePromotion, source_id) is None:
        db.add(SourcePromotion(source_id=source_id))


def promote_source(db: Session, source: Source) -> WorkItem:
    """Promote a ``Source`` by hand, overriding whatever ``should_promote`` decided (T08, AC10).

    This is the owner's correction for the heuristic's false negatives: a source
    ``promote_signals`` rejected, or one it has not judged at all yet. Neither
    :func:`should_promote` nor ``owner_addresses`` are consulted -- the owner
    looking at the message is the decision here, not the heuristic.

    Writes the same ``SourcePromotion`` ledger row :func:`_record_considered`
    would have written on a live judgement (B44). Without it, this source would
    still read as "never judged" to ``app.services.backfill.backfill_promoted_sources``,
    which would offer it to the heuristic again and report a promotion this
    endpoint already made.

    Refuses with 409 rather than a duplicate when a work item for this source
    already exists -- promoted, dismissed, or otherwise -- the same conflict
    ``create_work_item`` would hit against the ``source_external_id`` unique
    constraint, raised earlier so nothing is written first.
    """
    if db.scalar(select(WorkItem.id).where(WorkItem.source_external_id == source.external_id)) is not None:
        raise conflict("A work item for this source already exists")
    if db.get(SourcePromotion, source.id) is None:
        db.add(SourcePromotion(source_id=source.id))
    return create_work_item(db, WorkItemCreate(
        title=(str(source.subject or "").strip() or FALLBACK_TITLE)[:TITLE_LIMIT],
        source_kind=source.kind,
        source_external_id=source.external_id,
        source_url=_source_url(source.url) if source.url else None,
        evidence=[EvidenceInput(
            source_kind=source.kind,
            external_id=source.external_id,
            excerpt=str(source.excerpt or "")[:EXCERPT_LIMIT] or None,
            observed_at=source.observed_at,
        )],
    ))


def promote_signals(db: Session, signals: list[dict[str, Any]], owner_addresses: Collection[str] = (),
                    allowlisted_senders: Collection[str] = ()) -> int:
    """Create a pending work item for every actionable signal; return how many are new.

    Idempotent through ``work_items.source_external_id``: a signal already promoted
    is skipped, so re-running a sync over the same inbox window adds nothing and the
    unique constraint is never reached.

    Every signal whose source is stored is also recorded as judged (see
    ``_record_considered``), so the backfill can later tell a source this function
    rejected from one it was never shown. That record is committed here rather than
    left to whatever ``create_work_item`` happens to commit: a batch that rejects
    every signal never calls ``create_work_item`` at all, and without an explicit
    commit here the judged-rows it added would be discarded when the caller's
    session closes, silently reopening the door this table exists to close.
    """
    created = 0
    for signal in signals:
        external_id = str(signal["external_id"])
        _record_considered(db, external_id)
        if not should_promote(signal, owner_addresses, allowlisted_senders):
            continue
        if db.scalar(select(WorkItem.id).where(WorkItem.source_external_id == external_id)) is not None:
            continue
        create_work_item(db, _work_item(signal))
        created += 1
    db.commit()
    return created
