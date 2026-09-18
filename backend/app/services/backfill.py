"""One-off promotion of ``Source`` rows that were stored before promotion existed.

``persist_signals`` has been writing ``Source`` rows since the first release, but
the heuristic that turns them into work items arrived later. Those earlier rows
were never offered to it, so the queue the GUI renders stays empty for them until
something offers them once. That is all this module does.

**How it picks rows, and why not the obvious way.** The tempting predicate is
"every ``Source`` with no matching ``WorkItem``". It is wrong: a source the
heuristic deliberately rejected also has no matching work item, so that predicate
drags every newsletter and no-reply message back into the queue on the first run
that finds anything to promote. This module instead selects on the absence of a
``SourcePromotion`` row, which ``promote_signals`` writes for every signal it
judges, either verdict. Absence of that row is the one fact that means "promotion
has never decided about this source".

**Where it runs.** From ``POST /api/sync/backfill`` only, behind the same
``require_local_write_access`` guard as ``POST /api/sync``. Not from application
startup: ``main.py`` deliberately touches no table at boot
(``tests/test_migrations.py::test_application_startup_writes_no_schema_of_its_own``
pins that), and a startup hook querying ``sources`` would raise against a database
whose migrations have not run yet -- exactly the state that test runs against.
Because it is never on the boot path, boot speed on an empty database is not a
property this module has to hold; nothing here runs until an operator calls the
endpoint.

**What "considered" can and cannot mean.** A never-judged ``Source`` is fed to the
same :func:`should_promote` a live sync uses, so it always reaches a verdict;
nothing here can fail to answer. But two things make that verdict weaker than the
one a live sync reaches, and the response counts each of them separately rather
than presenting a run as a clean decision.

*No stored context.* A genuinely pre-promotion row carries no
``SourceSignalContext`` -- ``sender``, ``sender_kind``, ``to_recipients`` and
``headers`` were never asked for before that table existed -- so on it rules 1-4
have nothing to read and only rule 5 can fire: it is promoted unconditionally.
That is a permanent data gap, not a bug, and the contract's answer to it is the
owner's manual dismiss (T08), not a second heuristic guessing a sender from a
subject line. ``judged_without_context`` counts these rows, so an operator knows
which promotions in a run were a real decision and which were a coin that only
ever lands heads.

*No owner addresses.* Rule 4 skips mail the owner was only copied on, and it needs
the owner's own addresses to do that. They exist only in the live Graph profile a
sync fetches (``sync._owner_addresses``); nothing persists them and no setting
supplies them, so this module has none to pass and **rule 4 never fires here, on
any row**. Mail the owner was merely copied on is therefore promoted by the
backfill even though a live sync declines it. ``promoted_without_owner_check``
counts the promotions this actually puts at risk -- rows that carried a To list
and got past rules 1-3, so rule 4 was the one remaining rule that could have said
no. A positive count is a list of rows worth reviewing, not a failed run; closing
the gap for real needs a durable record of the owner's addresses, which does not
exist anywhere in this application yet.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Source, SourcePromotion
from .promotion import promote_signals, should_promote


def _signal_from_source(source: Source) -> dict[str, Any]:
    """Rebuild the normalized signal shape from what the row actually kept.

    A ``Source`` written after ``SourceSignalContext`` existed carries its real
    sender, sender kind, recipients and headers, and those are included here so
    rules 1-3 of ``should_promote`` can genuinely decide -- treating a source that
    has this data as if it did not would silently downgrade every backfill to
    rule 5, which is exactly the bug the permanent-gap paragraph above describes
    for rows that truly lack it. Rule 4 is not in that list: it is unreachable
    here whatever this function returns, for want of owner addresses.
    ``to_recipients`` is still carried across, because it is what
    :func:`_promoted_without_owner_check` reads to tell a promotion rule 4 might
    have overturned from one it could not have. A source with no context row omits
    the four keys entirely, so ``should_promote`` reads them as unknown through
    ``.get()`` instead of being handed an invented sender or an empty header block
    that could be mistaken for "checked and clean".
    """
    signal: dict[str, Any] = {
        "external_id": source.external_id,
        "source_kind": source.kind.value,
        "title": source.subject,
        "excerpt": source.excerpt,
        "source_url": source.url,
        "observed_at": source.observed_at.isoformat(),
    }
    context = source.signal_context
    if context is not None:
        signal["sender"] = context.sender
        signal["sender_kind"] = context.sender_kind
        signal["to_recipients"] = context.to_recipients or []
        signal["headers"] = context.headers or {}
    return signal


def _promoted_without_owner_check(signal: dict[str, Any]) -> bool:
    """True when this signal is promoted only because rule 4 had no owner addresses to check.

    Rule 4 can reject a signal only if it reaches it -- one rules 1-3 let through
    -- and only if there is a To list to look in: ``_is_only_copied`` returns
    ``False`` on an empty one, so a Teams message or a mail with no recipients is
    decided identically whether or not the owner is known. Asking
    ``should_promote`` itself, with the same empty ``owner_addresses`` the backfill
    passes to ``promote_signals``, keeps that rule ordering in the single function
    that owns it instead of restating the rules here.
    """
    return bool(signal.get("to_recipients")) and should_promote(signal)


def backfill_promoted_sources(db: Session) -> dict[str, int]:
    """Offer every never-judged ``Source`` to the heuristic once; report what happened.

    Safe to re-run: ``promote_signals`` records each source it judges, so a second
    call selects nothing and every count in the response is 0. Re-running is the
    expected operator path, not an edge case -- the endpoint is a button, and
    buttons get pressed twice.

    The response never collapses to a single number, because a single
    ``new_work_items`` count cannot say which of four very different situations
    happened: nothing was left to judge (``considered`` is 0); something was judged
    and none of it was actionable (``considered`` is positive, ``new_work_items`` is
    0); some of what was judged could not be judged on its merits at all, for lack
    of stored context (``judged_without_context`` is positive) and its verdict is a
    guess, not a decision; or something was promoted with rule 4 unavailable
    (``promoted_without_owner_check`` is positive), which a live sync might have
    declined. The last two count different rows and neither implies the other: a
    context-less row is never counted as an owner-check miss, because rule 4 would
    have had no recipients to read on it either.
    """
    unjudged = list(db.scalars(
        select(Source)
        .where(Source.id.not_in(select(SourcePromotion.source_id)))
        .order_by(Source.observed_at)
    ))
    signals = [_signal_from_source(source) for source in unjudged]
    judged_without_context = sum(1 for source in unjudged if source.signal_context is None)
    unchecked = sum(1 for signal in signals if _promoted_without_owner_check(signal))
    promoted = promote_signals(db, signals)
    return {
        "considered": len(unjudged),
        "new_work_items": promoted,
        "judged_without_context": judged_without_context,
        "promoted_without_owner_check": unchecked,
    }
