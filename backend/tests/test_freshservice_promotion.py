"""Rule B: only a Freshservice ticket assigned to the owner and still owed is promoted.

The Freshservice counterpart to ``test_jira_promotion.py``. A Freshservice signal
carries no sender, headers or recipients, so left to the mail rules it would fall
through to the last, permissive one and every ticket fetched would reach the queue.
Rule B replaces that with one question -- is the ticket assigned to the owner and
not yet resolved or closed -- and nothing else decides it.

**How the owner is recognised.** By agent id, passed as ``owner_agent_id`` (its own
keyword, not Jira's ``owner_account_id``: the two identities are different kinds of
value and one must never be read as the other).

**Fail closed.** An unknown owner promotes nothing, and above all ``None == None``
never promotes: an unassigned ticket has no ``responder_id`` and an unresolved owner
has no id, and those two absences must not read as a match.

Every fixture is synthetic and nothing here reaches the network.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.database import engine
from app.models import Source, SourceKind, SourcePromotion, WorkItem
from app.services.backfill import backfill_promoted_sources
from app.services.graph import persist_signals
from app.services.promotion import promote_signals, should_promote

# Freshservice agent ids are integers; these only have to be distinguishable.
OWNER_AGENT_ID = 4001
COLLEAGUE_AGENT_ID = 4002


def _signal(**overrides: Any) -> dict[str, Any]:
    """A normalized Freshservice signal, shaped as the sync handler builds one."""
    return {
        "external_id": "freshservice:101",
        "source_kind": "freshservice",
        "title": "Invented printer ticket",
        "source_url": "https://example.freshservice.com/a/tickets/101",
        "observed_at": "2026-10-20T08:30:00Z",
        "responder_id": OWNER_AGENT_ID,
        "ticket_status": 2,
        **overrides,
    }


def test_freshservice_promotion_accepts_an_open_ticket_assigned_to_the_owner() -> None:
    assert should_promote(_signal(), owner_agent_id=OWNER_AGENT_ID) is True


@pytest.mark.parametrize("status", [2, 3, 6, 7])
def test_freshservice_promotion_accepts_open_pending_and_custom_statuses(status: int) -> None:
    """Custom statuses are other integers; only Resolved and Closed are done."""
    assert should_promote(_signal(ticket_status=status), owner_agent_id=OWNER_AGENT_ID) is True


@pytest.mark.parametrize("status", [4, 5])
def test_freshservice_promotion_skips_a_resolved_or_closed_ticket(status: int) -> None:
    """The search returns tickets updated recently in any status, so a ticket the
    owner just resolved arrives assigned to them -- and is not work."""
    assert should_promote(_signal(ticket_status=status), owner_agent_id=OWNER_AGENT_ID) is False


def test_freshservice_promotion_a_missing_status_does_not_block_promotion() -> None:
    """A missing status is not Resolved or Closed, so it does not block promotion:
    the rule only declines the two statuses that mean finished."""
    assert should_promote(_signal(ticket_status=None), owner_agent_id=OWNER_AGENT_ID) is True


def test_freshservice_promotion_skips_a_ticket_assigned_to_somebody_else() -> None:
    assert should_promote(_signal(responder_id=COLLEAGUE_AGENT_ID), owner_agent_id=OWNER_AGENT_ID) is False


def test_freshservice_promotion_skips_an_unassigned_ticket() -> None:
    assert should_promote(_signal(responder_id=None), owner_agent_id=OWNER_AGENT_ID) is False


def test_freshservice_promotion_skips_a_signal_with_no_responder_key_at_all() -> None:
    signal = _signal()
    del signal["responder_id"]

    assert should_promote(signal, owner_agent_id=OWNER_AGENT_ID) is False


def test_freshservice_promotion_fails_closed_when_the_owner_is_unknown() -> None:
    """An unrecognised owner must promote nothing, not everything -- including a
    ticket assigned to nobody, where absent would otherwise equal absent."""
    assert should_promote(_signal(), owner_agent_id=None) is False
    assert should_promote(_signal(responder_id=None), owner_agent_id=None) is False
    assert should_promote(_signal(responder_id=None)) is False


def test_freshservice_promotion_does_not_read_a_jira_account_id_as_the_owner() -> None:
    """The two owner keywords are different identities; supplying only Jira's must
    leave a Freshservice signal with no recognised owner."""
    assert should_promote(_signal(), owner_account_id=str(OWNER_AGENT_ID)) is False


def test_freshservice_promotion_does_not_match_an_id_by_its_string_form() -> None:
    """Ids are compared as the integers the API reports, not by what they print as."""
    assert should_promote(_signal(responder_id=str(OWNER_AGENT_ID)), owner_agent_id=OWNER_AGENT_ID) is False


def test_freshservice_promotion_never_falls_through_to_the_mail_rules() -> None:
    """A Freshservice signal is decided by assignment and status alone, ahead of every
    mail rule. Both directions matter: a signal the mail rules would wave through must
    still be rejected when assigned elsewhere, and one they would reject must still be
    promoted when it is the owner's."""
    mail_shaped = {"sender": "colleague@contoso.com", "sender_kind": "user",
                   "to_recipients": ["owner@contoso.com"], "headers": {}}
    bulk_shaped = {"sender": "noreply@example.freshservice.com", "sender_kind": "application",
                   "headers": {"Auto-Submitted": "auto-generated", "Precedence": "bulk"}}

    assert should_promote(_signal(responder_id=COLLEAGUE_AGENT_ID, **mail_shaped), owner_agent_id=OWNER_AGENT_ID) is False
    assert should_promote(_signal(**bulk_shaped), owner_agent_id=OWNER_AGENT_ID) is True


def test_freshservice_promotion_leaves_the_mail_heuristic_untouched() -> None:
    """A known owner agent id must not start rejecting mail, which carries no
    responder and would fail rule B if the branch were keyed on anything looser."""
    email = {"external_id": "outlook:1", "source_kind": "outlook_email", "title": "Release window",
             "sender": "colleague@contoso.com", "sender_kind": "user",
             "to_recipients": ["owner@contoso.com"], "headers": {}}

    assert should_promote(email, ("owner@contoso.com",), owner_agent_id=OWNER_AGENT_ID) is True


def test_freshservice_promotion_leaves_the_jira_rule_untouched() -> None:
    jira = {"external_id": "jira:1", "source_kind": "jira", "title": "x", "assignee_account_id": "abc"}

    assert should_promote(jira, owner_account_id="abc", owner_agent_id=None) is True
    assert should_promote(jira, owner_account_id=None, owner_agent_id=OWNER_AGENT_ID) is False


def test_freshservice_promotion_promote_signals_creates_work_only_for_the_owners_open_tickets() -> None:
    signals = [
        _signal(external_id="freshservice:1"),
        _signal(external_id="freshservice:2", responder_id=COLLEAGUE_AGENT_ID),
        _signal(external_id="freshservice:3", responder_id=None),
        _signal(external_id="freshservice:4", ticket_status=4),
    ]

    with Session(engine) as session:
        persist_signals(session, signals)
        promoted = promote_signals(session, signals, owner_agent_id=OWNER_AGENT_ID)

        assert promoted == 1
        assert [item.source_external_id for item in session.query(WorkItem).all()] == ["freshservice:1"]
        # Every one of them was judged, whatever the verdict: the ledger is what
        # stops the backfill offering a declined ticket again.
        assert session.query(SourcePromotion).count() == 4


def test_freshservice_promotion_promote_signals_promotes_nothing_without_an_owner_but_keeps_the_sources() -> None:
    signals = [_signal(external_id="freshservice:1"), _signal(external_id="freshservice:2", responder_id=None)]

    with Session(engine) as session:
        persist_signals(session, signals)
        promoted = promote_signals(session, signals)

        assert promoted == 0
        assert session.query(Source).filter_by(kind=SourceKind.freshservice).count() == 2
        assert session.query(WorkItem).count() == 0


def test_freshservice_promotion_does_not_let_the_backfill_promote_a_stored_freshservice_source() -> None:
    """The backfill has neither the stored responder nor an owner agent id, so rule B
    cannot be satisfied there and the ticket stays out of the queue -- the fail-closed
    direction; the owner's manual promote is how one enters outside a live sync."""
    with Session(engine) as session:
        session.add(Source(kind=SourceKind.freshservice, external_id="freshservice:99", subject="Watched ticket",
                           url="https://example.freshservice.com/a/tickets/99",
                           observed_at=datetime(2026, 10, 1, 8, 30)))
        session.commit()

        result = backfill_promoted_sources(session)

        assert result["considered"] == 1
        assert result["new_work_items"] == 0
        assert session.query(WorkItem).count() == 0
