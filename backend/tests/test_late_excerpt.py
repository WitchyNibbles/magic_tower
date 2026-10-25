"""Excerpts that arrive after the source was first stored.

A sync that learns a source's text later (the Jira and Freshservice connectors only began
carrying descriptions after items were already stored) must fill what is still empty, in the
source and in the evidence row promotion copied from it, and nothing else: never overwrite a
non-empty excerpt, never add a row, and keep both columns sealed. Fixture text is invented.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import engine
from app.models import Source, WorkEvidence
from app.services.graph import persist_signals
from app.services.promotion import promote_signals

MARKER = "late-description-marker-5d2e9b"
OWNER = "owner-account"


def _signal(external_id: str, excerpt: str | None) -> dict:
    return {"external_id": external_id, "source_kind": "jira", "title": "Invented issue", "excerpt": excerpt,
            "source_url": "https://example.atlassian.net/browse/OPS-9", "observed_at": "2026-09-18T08:30:00Z",
            "assignee_account_id": OWNER}


def _stored(external_id: str) -> tuple[str | None, list[str | None], int]:
    """(source excerpt, evidence excerpts, source rows) as the ORM reads them."""
    with Session(engine) as session:
        sources = session.scalars(select(Source).where(Source.external_id == external_id)).all()
        evidence = session.scalars(select(WorkEvidence).where(WorkEvidence.external_id == external_id)).all()
        return sources[0].excerpt, [row.excerpt for row in evidence], len(sources)


def _promoted_without_text(external_id: str) -> None:
    signal = _signal(external_id, None)
    with Session(engine) as session:
        persist_signals(session, [signal])
        assert promote_signals(session, [signal], owner_account_id=OWNER) == 1


def test_a_stored_source_and_its_evidence_are_filled_when_the_text_arrives_later() -> None:
    _promoted_without_text("jira:fill-1")
    later = _signal("jira:fill-1", f"Renew the cert. {MARKER}")

    with Session(engine) as session:
        assert persist_signals(session, [later]) == 0
        # Promotion on the same pass must not add an item or an evidence row for it.
        assert promote_signals(session, [later], owner_account_id=OWNER) == 0

    assert _stored("jira:fill-1") == (f"Renew the cert. {MARKER}", [f"Renew the cert. {MARKER}"], 1)


def test_a_stored_excerpt_is_never_overwritten() -> None:
    first = _signal("jira:fill-2", "First text.")
    with Session(engine) as session:
        persist_signals(session, [first])
        promote_signals(session, [first], owner_account_id=OWNER)
        persist_signals(session, [_signal("jira:fill-2", "Edited text.")])

    assert _stored("jira:fill-2") == ("First text.", ["First text."], 1)


def test_an_empty_source_stays_empty_when_the_new_signal_has_no_text() -> None:
    _promoted_without_text("jira:fill-3")

    with Session(engine) as session:
        persist_signals(session, [_signal("jira:fill-3", None), _signal("jira:fill-3", "")])

    assert _stored("jira:fill-3") == (None, [None], 1)


def test_a_source_that_was_never_promoted_is_filled_too() -> None:
    with Session(engine) as session:
        persist_signals(session, [_signal("jira:fill-4", None)])
        persist_signals(session, [_signal("jira:fill-4", "Text for a rejected source.")])

    assert _stored("jira:fill-4") == ("Text for a rejected source.", [], 1)


def test_a_late_excerpt_is_sealed_in_both_columns() -> None:
    """The fill goes through the encrypted columns: the marker must not be in the raw rows."""
    _promoted_without_text("jira:fill-5")

    with Session(engine) as session:
        persist_signals(session, [_signal("jira:fill-5", f"Secret body. {MARKER}")])
        raw = [row[0] for row in session.connection().exec_driver_sql(
            "SELECT excerpt FROM sources WHERE external_id = 'jira:fill-5' "
            "UNION ALL SELECT excerpt FROM work_evidence WHERE external_id = 'jira:fill-5'")]

    assert len(raw) == 2 and all(value and MARKER not in value for value in raw)
    assert _stored("jira:fill-5")[0] == f"Secret body. {MARKER}"
