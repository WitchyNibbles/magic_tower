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

**What "considered" can and cannot mean.** A never-judged ``Source`` is always fed
to the same :func:`should_promote` a live sync uses, so it is always judged, one
way or the other; nothing here can fail to reach a verdict. But a genuinely
pre-promotion row carries no ``SourceSignalContext`` -- ``sender``, ``sender_kind``,
``to_recipients`` and ``headers`` were never asked for before that table existed --
so on it, rules 1-4 of ``should_promote`` have nothing to read and only rule 5 can
fire: it is promoted unconditionally. That is a permanent data gap, not a bug, and
the contract's answer to it is the owner's manual dismiss (T08), not a second
heuristic guessing a sender from a subject line. The response distinguishes these
rows (``judged_without_context``) precisely so an operator knows which promotions
in a given run were a real decision and which were a coin that only ever lands
heads.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Source, SourcePromotion
from .promotion import promote_signals


def _signal_from_source(source: Source) -> dict[str, Any]:
    """Rebuild the normalized signal shape from what the row actually kept.

    A ``Source`` written after ``SourceSignalContext`` existed carries its real
    sender, sender kind, recipients and headers, and those are included here so
    rules 1-4 of ``should_promote`` can genuinely decide -- treating a source that
    has this data as if it did not would silently downgrade every backfill to
    rule 5, which is exactly the bug the permanent-gap paragraph above describes
    for rows that truly lack it. A source with no context row omits the four keys
    entirely, so ``should_promote`` reads them as unknown through ``.get()``
    instead of being handed an invented sender or an empty header block that could
    be mistaken for "checked and clean".
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


def backfill_promoted_sources(db: Session) -> dict[str, int]:
    """Offer every never-judged ``Source`` to the heuristic once; report what happened.

    Safe to re-run: ``promote_signals`` records each source it judges, so a second
    call selects nothing and every count in the response is 0. Re-running is the
    expected operator path, not an edge case -- the endpoint is a button, and
    buttons get pressed twice.

    The response never collapses to a single number, because a single
    ``new_work_items`` count cannot say which of three very different situations
    happened: nothing was left to judge (``considered`` is 0); something was judged
    and none of it was actionable (``considered`` is positive, ``new_work_items`` is
    0); or some of what was judged could not be judged on its merits at all, for
    lack of stored context (``judged_without_context`` is positive) and its verdict
    should be treated as a guess, not a decision.
    """
    unjudged = list(db.scalars(
        select(Source)
        .where(Source.id.not_in(select(SourcePromotion.source_id)))
        .order_by(Source.observed_at)
    ))
    judged_without_context = sum(1 for source in unjudged if source.signal_context is None)
    promoted = promote_signals(db, [_signal_from_source(source) for source in unjudged])
    return {
        "considered": len(unjudged),
        "new_work_items": promoted,
        "judged_without_context": judged_without_context,
    }
