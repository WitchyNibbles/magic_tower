"""Two writers racing to insert the same grimoire row: the loser updates the winner's row.

The race is simulated: the session's first lookup answers "no row" although another
session has already committed one, so its insert hits the primary key. Fixture text is invented.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import GrimoireProjectSnapshot, SourceKind, WorkItem, WorkItemAnalysis
from app.schemas import AnalysisDetails, AnalysisWrite, ProjectSnapshot
from app.services.grimoire_view import context_fields, fingerprint, save_analysis, save_project_snapshot


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def _blind_to(monkeypatch, db: Session, model: type, *, times: int) -> None:
    """Make the next ``times`` lookups of ``model`` by key answer None, as a stale read would."""
    real_get, remaining = db.get, [times]

    def get(entity, ident, *args, **kwargs):
        if entity is model and remaining[0] > 0:
            remaining[0] -= 1
            return None
        return real_get(entity, ident, *args, **kwargs)

    monkeypatch.setattr(db, "get", get)


def _item(db: Session) -> WorkItem:
    item = WorkItem(title="Renew the widget", source_kind=SourceKind.manual)
    db.add(item)
    db.commit()
    return item


def _winning_analysis(item: WorkItem) -> None:
    with SessionLocal() as other:
        other.add(WorkItemAnalysis(work_item_id=item.id, summary="winner", details='{"asked":"winner"}',
                                   source_fingerprint="0" * 64, analyzer="winner"))
        other.commit()


def _write(db: Session, item: WorkItem) -> AnalysisWrite:
    return AnalysisWrite(summary="loser, written last", details=AnalysisDetails(asked="Renew it"),
                         source_fingerprint=fingerprint(context_fields(db, item)))


def test_losing_the_analysis_insert_race_updates_the_winners_row(db, monkeypatch):
    item = _item(db)
    data = _write(db, item)
    _winning_analysis(item)
    _blind_to(monkeypatch, db, WorkItemAnalysis, times=1)

    saved = save_analysis(db, item, data)

    assert saved.summary == "loser, written last"
    assert db.scalar(select(func.count()).select_from(WorkItemAnalysis)) == 1
    assert db.get(WorkItemAnalysis, item.id).analyzer == "grimoire"


def test_a_vanished_winner_row_is_not_found_not_a_server_error_for_the_analysis(db, monkeypatch):
    item = _item(db)
    data = _write(db, item)
    _winning_analysis(item)
    _blind_to(monkeypatch, db, WorkItemAnalysis, times=2)

    with pytest.raises(HTTPException) as refused:
        save_analysis(db, item, data)

    assert refused.value.status_code == 404
    assert db.scalar(select(func.count()).select_from(WorkItemAnalysis)) == 1, "the session is still usable"


def _winning_snapshot() -> None:
    with SessionLocal() as other:
        other.add(GrimoireProjectSnapshot(id=1, snapshot=ProjectSnapshot(projects=[]).model_dump_json()))
        other.commit()


def _snapshot() -> ProjectSnapshot:
    return ProjectSnapshot(projects=[{"code": "PRJ-A", "name": "Invented project", "status": "active", "tasks": [],
                                      "open_questions": 0, "pending_prod_steps": []}])


def test_losing_the_snapshot_insert_race_updates_the_winners_row(db, monkeypatch):
    _winning_snapshot()
    _blind_to(monkeypatch, db, GrimoireProjectSnapshot, times=1)

    written = save_project_snapshot(db, _snapshot())

    assert written.updated_at is not None
    assert db.scalar(select(func.count()).select_from(GrimoireProjectSnapshot)) == 1
    assert "PRJ-A" in db.get(GrimoireProjectSnapshot, 1).snapshot


def test_a_vanished_winner_row_is_not_found_not_a_server_error_for_the_snapshot(db, monkeypatch):
    _winning_snapshot()
    _blind_to(monkeypatch, db, GrimoireProjectSnapshot, times=2)

    with pytest.raises(HTTPException) as refused:
        save_project_snapshot(db, _snapshot())

    assert refused.value.status_code == 404
    assert db.scalar(select(func.count()).select_from(GrimoireProjectSnapshot)) == 1, "the session is still usable"
