"""Promotion of ``Source`` rows that were stored before promotion existed.

``persist_signals`` has written ``Source`` rows since the first release; promotion
only arrived later. Those earlier rows were never offered to the heuristic, so the
queue stays empty for them until a backfill offers them once.

The whole difficulty is that "never offered" is not the same as "offered and
declined", and ``work_items`` cannot tell the two apart on its own -- both leave a
``Source`` with no matching ``WorkItem``. A selection predicate of "every source
with no work item" therefore re-promotes exactly the newsletters and no-reply mail
the heuristic deliberately threw away (blocked twice, attempt 1), and a queue-level
gate that stops once anything has ever been promoted silently disables the
backfill forever after the first ordinary sync (blocked twice, attempt 2).
``source_promotions`` is the row that breaks the tie, written by ``promote_signals``
for every signal it judges, either verdict; the tests below hold each of those
failure shapes shut, built -- where the fixture matters -- through the real
writers, ``persist_signals`` and ``promote_signals``, rather than bare ``Source``
rows, because only a source the heuristic has genuinely seen and turned down can
catch attempt 1's bug.

Every fixture here is synthetic; no real mail content lives in this repository.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import engine
from app.main import app
from app.models import Source, SourceKind, SourcePromotion, WorkItem, WorkStatus
from app.services.backfill import backfill_promoted_sources
from app.services.graph import persist_signals
from app.services.promotion import promote_signals

MAILBOX = "owner@contoso.com"
OWNER = (MAILBOX,)
BEARER = {"Authorization": "Bearer test-local-agent-token"}

# Distinctive enough that finding it on a work item cannot be a coincidence.
MARKER = "backfilled-excerpt-marker-91c4ae"


def _stored_source(external_id: str, subject: str, excerpt: str = MARKER) -> Source:
    """A ``Source`` exactly as a pre-promotion release left it: no context, no ledger row."""
    return Source(
        kind=SourceKind.outlook_email,
        external_id=external_id,
        subject=subject,
        url="https://outlook.office.com/mail/" + external_id,
        excerpt=excerpt,
        observed_at=datetime(2026, 9, 1, 8, 30),
    )


def _email(**overrides: Any) -> dict[str, Any]:
    """A normalized inbox message a colleague sent to the owner, by default."""
    return {
        "external_id": "outlook:direct-1",
        "source_kind": "outlook_email",
        "title": "Can you review the migration plan?",
        "excerpt": MARKER,
        "source_url": "https://outlook.office.com/mail/direct-1",
        "observed_at": "2026-09-18T08:30:00Z",
        "sender": "colleague@contoso.com",
        "sender_kind": "user",
        "to_recipients": [MAILBOX],
        "headers": {},
        **overrides,
    }


def _newsletter(**overrides: Any) -> dict[str, Any]:
    """Bulk mail the live heuristic rejects on its sender alone."""
    return _email(external_id="outlook:newsletter-1", title="Your weekly product digest",
                  sender="newsletter@vendor.example", **overrides)


def _cc_only(**overrides: Any) -> dict[str, Any]:
    """Mail from a person that the owner was only copied on; the live heuristic rejects it on rule 4."""
    return _email(external_id="outlook:cc-only-1", title="FYI: the migration plan",
                  to_recipients=["someone.else@contoso.com"], **overrides)


def test_backfill_promotes_a_source_stored_before_promotion_existed() -> None:
    """AC8: a row the heuristic was never given a chance to judge gets one."""
    with Session(engine) as session:
        session.add(_stored_source("outlook:legacy-1", "Can you review the migration plan?"))
        session.commit()

        result = backfill_promoted_sources(session)

        assert result == {"considered": 1, "new_work_items": 1, "judged_without_context": 1, "promoted_without_owner_check": 0}
        item = session.query(WorkItem).one()
        assert item.source_external_id == "outlook:legacy-1"
        assert item.status == WorkStatus.pending
        assert item.evidence[0].excerpt == MARKER


def test_backfill_leaves_a_source_the_live_heuristic_declined_unpromoted() -> None:
    """Attempt 1's bug: a rejected source must not come back through the backfill door.

    Both rows are stored by the same sync; the live heuristic promotes the direct
    message and declines the newsletter. Afterwards the newsletter is a ``Source``
    with no work item -- the very shape a naive backfill looks for -- so a backfill
    selecting on that alone would undo the rejection.
    """
    with Session(engine) as session:
        signals = [_email(), _newsletter()]
        persist_signals(session, signals)
        assert promote_signals(session, signals, OWNER) == 1, "the newsletter should have been declined"

        result = backfill_promoted_sources(session)

        assert result == {"considered": 0, "new_work_items": 0, "judged_without_context": 0, "promoted_without_owner_check": 0}
        items = session.query(WorkItem).all()
        assert [item.source_external_id for item in items] == ["outlook:direct-1"]


def test_backfill_promotes_pre_promotion_sources_after_an_ordinary_promoting_sync() -> None:
    """Attempt 2's bug: two pre-T05 sources plus one ordinary sync must not disable the backfill.

    A queue-level gate ("stop if anything, anywhere, already has a work item")
    reports 0 here and leaves both legacy rows unreachable forever; the per-source
    ledger must still reach them.
    """
    with Session(engine) as session:
        session.add(_stored_source("outlook:legacy-1", "Can you review the migration plan?"))
        session.add(_stored_source("outlook:legacy-2", "Budget sign-off needed"))
        session.commit()

        signals = [_email(external_id="outlook:fresh-1", title="Approve the release")]
        persist_signals(session, signals)
        promote_signals(session, signals, OWNER)
        assert session.query(WorkItem).count() == 1, "the ordinary sync should have promoted its own signal"

        result = backfill_promoted_sources(session)

        assert result["new_work_items"] == 2
        promoted_ids = {item.source_external_id for item in session.query(WorkItem).all()}
        assert promoted_ids == {"outlook:fresh-1", "outlook:legacy-1", "outlook:legacy-2"}


def test_backfill_does_not_resurrect_a_work_item_the_owner_hand_deleted() -> None:
    """B36: ``promote_signals`` records the judgement independently of the ``WorkItem`` it wrote.

    Deleting the work item through the API must not erase that a source was ever
    judged, or a later backfill would read the gap left behind as "never seen" and
    promote it right back.
    """
    with Session(engine) as session:
        signals = [_email()]
        persist_signals(session, signals)
        assert promote_signals(session, signals, OWNER) == 1
        item_id = session.query(WorkItem).one().id

    with TestClient(app) as client:
        assert client.delete(f"/api/work-items/{item_id}", headers=BEARER).status_code == 204

    with Session(engine) as session:
        assert session.query(WorkItem).count() == 0
        assert session.query(SourcePromotion).count() == 1, "the judgement ledger must survive the deletion"

        result = backfill_promoted_sources(session)

        assert result == {"considered": 0, "new_work_items": 0, "judged_without_context": 0, "promoted_without_owner_check": 0}
        assert session.query(WorkItem).count() == 0, "the hand-deleted item must not come back"


def test_backfill_is_safe_to_re_run_across_independent_sessions() -> None:
    """Re-running is the operator path, and the second run must add nothing."""
    with Session(engine) as session:
        session.add(_stored_source("outlook:legacy-1", "Can you review the migration plan?"))
        session.add(_stored_source("outlook:legacy-2", "Budget sign-off needed"))
        session.commit()

    with Session(engine) as session:
        first = backfill_promoted_sources(session)
    with Session(engine) as session:
        second = backfill_promoted_sources(session)

    assert (first["new_work_items"], second["new_work_items"]) == (2, 0)
    assert (first["considered"], second["considered"]) == (2, 0)
    with Session(engine) as session:
        assert session.query(WorkItem).count() == 2


def test_backfill_on_a_database_with_no_sources_reports_nothing_left_to_do() -> None:
    """The "nothing to do" state, told apart from "judged and declined everything"."""
    with Session(engine) as session:
        result = backfill_promoted_sources(session)

    assert result == {"considered": 0, "new_work_items": 0, "judged_without_context": 0, "promoted_without_owner_check": 0}


def test_backfill_uses_stored_signal_context_to_genuinely_judge_an_unjudged_source() -> None:
    """A source written after ``SourceSignalContext`` existed must be judged for real, not blindly promoted.

    ``persist_signals`` stores sender/headers for every source now; a source that
    has them must have its rules 1-4 actually evaluated by the backfill rather than
    falling back to "no data, promote by default".
    """
    with Session(engine) as session:
        persist_signals(session, [_newsletter()])
        assert session.query(WorkItem).count() == 0

        result = backfill_promoted_sources(session)

        assert result == {"considered": 1, "new_work_items": 0, "judged_without_context": 0, "promoted_without_owner_check": 0}
        assert session.query(WorkItem).count() == 0, "a bulk sender must still be declined when context is available"


def test_backfill_reports_the_promotions_it_could_not_apply_the_cc_rule_to() -> None:
    """The backfill knows no owner addresses, so rule 4 cannot fire; the envelope must say so.

    Rule 4 ("skip mail the owner was only copied on") needs the owner's own
    addresses, and the only place they exist is the live Graph profile a sync
    fetches -- nothing stores them, so ``backfill_promoted_sources`` has none to
    pass. This message is therefore promoted here although a live sync declines
    it, which is a real recall gap. ``judged_without_context`` cannot report it:
    the source has full stored context, so by that measure it was judged on its
    merits. The envelope needs its own count, or the gap is silent.
    """
    with Session(engine) as session:
        signals = [_cc_only()]
        persist_signals(session, signals)

        result = backfill_promoted_sources(session)

        assert result == {"considered": 1, "new_work_items": 1,
                          "judged_without_context": 0, "promoted_without_owner_check": 1}
        assert [item.source_external_id for item in session.query(WorkItem).all()] == ["outlook:cc-only-1"]


def test_backfill_does_not_flag_promotions_rule_4_could_not_have_changed() -> None:
    """The count is the rows rule 4 might have rejected, not every row it was skipped on.

    Rule 4 only ever rejects a signal that carries a To list and survived rules
    1-3, so counting anything else as unchecked would bury the rows an operator
    should actually look at. A bulk sender is rejected before rule 4 is reached,
    and a message with no To list is one rule 4 declines to judge even when the
    owner is known.
    """
    with Session(engine) as session:
        persist_signals(session, [_newsletter(), _email(external_id="outlook:no-to-list", to_recipients=[])])

        result = backfill_promoted_sources(session)

        assert result == {"considered": 2, "new_work_items": 1,
                          "judged_without_context": 0, "promoted_without_owner_check": 0}


def test_backfill_marks_a_source_with_no_stored_context_as_judged_without_context() -> None:
    """The permanent gap: a genuinely pre-T05 row has no sender/headers to judge from."""
    with Session(engine) as session:
        session.add(_stored_source("outlook:legacy-newsletter", "Your weekly product digest"))
        session.commit()

        result = backfill_promoted_sources(session)

        assert result == {"considered": 1, "new_work_items": 1, "judged_without_context": 1, "promoted_without_owner_check": 0}


def test_backfill_runs_from_an_explicit_endpoint_and_reports_the_full_envelope() -> None:
    """Where it runs: an operator-triggered endpoint, never application startup."""
    with Session(engine) as session:
        session.add(_stored_source("outlook:legacy-1", "Can you review the migration plan?"))
        session.commit()

    with TestClient(app) as client:
        response = client.post("/api/sync/backfill", headers=BEARER)

        assert response.status_code == 200
        assert response.json() == {"considered": 1, "new_work_items": 1, "judged_without_context": 1, "promoted_without_owner_check": 0}
        assert client.post("/api/sync/backfill", headers=BEARER).json() == {
            "considered": 0, "new_work_items": 0, "judged_without_context": 0, "promoted_without_owner_check": 0,
        }


def test_backfill_endpoint_refuses_a_caller_without_local_write_access() -> None:
    """It writes work items, so it sits behind the same guard as ``POST /api/sync``."""
    with TestClient(app) as client:
        assert client.post("/api/sync/backfill").status_code == 401


def test_promote_signals_records_a_judgement_even_when_every_signal_is_declined() -> None:
    """Pins the ``db.commit()`` at the end of ``promote_signals``.

    ``create_work_item`` commits, but a batch that declines everything never calls
    it, so nothing would persist the added ``SourcePromotion`` rows without an
    explicit commit of its own -- they would vanish when this session closes and
    the newsletter would be reconsidered, and re-promoted by rule 5, on every
    future backfill on a genuinely pre-T05 row that happened to share its shape.
    """
    with Session(engine) as session:
        signals = [_newsletter()]
        persist_signals(session, signals)
        assert promote_signals(session, signals, OWNER) == 0

    with Session(engine) as session:
        assert session.query(SourcePromotion).count() == 1
