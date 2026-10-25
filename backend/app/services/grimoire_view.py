"""What the grimoire client sees of the work queue: which items need analysing, and their text.

The fingerprint is the contract between reading and writing. It is the SHA-256 of the
canonical JSON of exactly the fields the context route returns (minus the fingerprint
itself and the ``untrusted_content`` marker), computed whenever it is needed and never
stored on the item. An analysis row keeps the fingerprint it was written against, so an
item is stale precisely when its text now hashes differently: an excerpt that fills in
late, a new comment, a changed title.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..models import GrimoireProjectSnapshot, Source, WorkEvidence, WorkItem, WorkItemAnalysis, WorkStatus
from ..schemas import AnalysisWrite, GrimoireItemRef, ProjectSnapshot, ProjectSnapshotRead, ProjectSnapshotWritten
from .http_errors import conflict, not_found
from .timeutil import as_utc

logger = logging.getLogger(__name__)

_Row = TypeVar("_Row", WorkItemAnalysis, GrimoireProjectSnapshot)


def _evidence_fields(rows: Sequence[WorkEvidence]) -> list[dict[str, Any]]:
    # The excerpt is the last key so rows tied on everything else still fingerprint the same
    # whatever order they were stored in.
    ordered = sorted(rows, key=lambda row: (as_utc(row.observed_at), row.external_id, row.source_kind.value,
                                            row.excerpt is not None, row.excerpt or ""))
    return [{"source_kind": row.source_kind.value, "external_id": row.external_id,
             "observed_at": as_utc(row.observed_at).isoformat(), "excerpt": row.excerpt} for row in ordered]


def _fields(item: WorkItem, source: Source | None) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "title": item.title,
        "summary": item.summary,
        "source_kind": item.source_kind.value,
        "source_url": item.source_url,
        "evidence": _evidence_fields(item.evidence),
        "source_subject": source.subject if source else None,
        "source_excerpt": source.excerpt if source else None,
    }


def _sources_by_external_id(db: Session, items: Sequence[WorkItem]) -> dict[str, Source]:
    external_ids = {item.source_external_id for item in items if item.source_external_id}
    if not external_ids:
        return {}
    return {source.external_id: source for source in db.scalars(select(Source).where(Source.external_id.in_(external_ids)))}


def context_fields(db: Session, item: WorkItem) -> dict[str, Any]:
    """The item's text as the context route returns it, without fingerprint or marker."""
    return _fields(item, _sources_by_external_id(db, [item]).get(item.source_external_id or ""))


def fingerprint(fields: dict[str, Any]) -> str:
    canonical = json.dumps(fields, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def staleness(db: Session, items: Sequence[WorkItem]) -> dict[UUID, bool]:
    """For each item that has an analysis: has its source text changed since it was written?

    One query for the sources of all those items, however many there are. Items without
    an analysis are absent from the result.
    """
    analysed = [item for item in items if item.analysis is not None]
    sources = _sources_by_external_id(db, analysed)
    return {item.id: item.analysis.source_fingerprint != fingerprint(_fields(item, sources.get(item.source_external_id or "")))
            for item in analysed}


def mark_stale_analyses(db: Session, items: Sequence[WorkItem]) -> None:
    """Record on each loaded analysis whether its item's text has changed since (see ``staleness``)."""
    flags = staleness(db, items)
    for item in items:
        if item.analysis is not None:
            item.analysis.stale = flags[item.id]


def _assign(row: object, values: dict[str, Any]) -> None:
    for key, value in values.items():
        setattr(row, key, value)


def _upsert(db: Session, model: type[_Row], key: object, key_columns: dict[str, object], values: dict[str, Any],
            *, missing: str) -> _Row:
    """Insert the row at ``key`` or update it, and commit. A row is one per key.

    Two writers can both find no row and both insert; the one that loses gets an
    ``IntegrityError`` and updates the winner's row instead. If that row is gone by
    then it was deleted in between, which is a 404 for ``missing``, not a crash.
    """
    row = db.get(model, key)
    if row is None:
        row = model(**key_columns, **values)
        db.add(row)
    else:
        _assign(row, values)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = db.get(model, key)
        if row is None:
            raise not_found(missing) from None
        _assign(row, values)
        db.commit()
    return row


def save_analysis(db: Session, item: WorkItem, data: AnalysisWrite) -> WorkItemAnalysis:
    """Store ``data`` as the item's analysis, replacing any earlier one.

    Refused with 409 when the item's text no longer hashes to ``data.source_fingerprint``:
    the analyst wrote about text that has since changed and must read it again. Only the
    analysis row is written; the item's status, dismissal and promotion are untouched.
    The row's key is the item id, so two racing writes cannot leave two rows: the one that
    loses the insert updates the winner's row instead.
    """
    if fingerprint(context_fields(db, item)) != data.source_fingerprint:
        raise conflict("source changed since it was read")
    values = {"summary": data.summary, "details": data.details.model_dump_json(),
              "source_fingerprint": data.source_fingerprint, "analyzer": data.analyzer, "analyzed_at": datetime.now(UTC)}
    analysis = _upsert(db, WorkItemAnalysis, item.id, {"work_item_id": item.id}, values, missing="Work item")
    logger.info("grimoire analysis written for work item %s by %s", item.id, data.analyzer)
    return analysis


def get_open_item(db: Session, item_id: UUID) -> WorkItem:
    """The item grimoire may read: any that exists and has not been dismissed (404 otherwise)."""
    item = db.scalar(select(WorkItem).options(selectinload(WorkItem.evidence), selectinload(WorkItem.analysis))
                     .where(WorkItem.id == item_id))
    if item is None or item.status is WorkStatus.dismissed:
        raise not_found("Work item")
    return item


def items_needing_analysis(db: Session, *, needs_analysis: bool, limit: int,
                           offset: int) -> tuple[list[GrimoireItemRef], int]:
    """A page of references, with the total before paging.

    ``needs_analysis=True`` is the open items (not done, not dismissed) that have no
    analysis or a stale one. ``False`` is the rest of the non-dismissed items. Staleness
    needs each analysed item's current text hashed, so the filter runs here and the
    page is cut afterwards; the queue is tens to hundreds of items.
    """
    excluded = [WorkStatus.dismissed, WorkStatus.done] if needs_analysis else [WorkStatus.dismissed]
    candidates = list(db.scalars(
        select(WorkItem).options(selectinload(WorkItem.evidence), selectinload(WorkItem.analysis))
        .where(WorkItem.status.not_in(excluded)).order_by(WorkItem.updated_at.desc(), WorkItem.id)))
    stale = staleness(db, candidates)
    wanted = [item for item in candidates
              if (item.status is not WorkStatus.done and (item.analysis is None or stale[item.id])) is needs_analysis]
    refs = [GrimoireItemRef(
        id=item.id, title=item.title, source_kind=item.source_kind, source_url=item.source_url, status=item.status,
        analyzed_at=as_utc(item.analysis.analyzed_at) if item.analysis else None,
        stale=stale.get(item.id, False)) for item in wanted[offset:offset + limit]]
    return refs, len(wanted)


def save_project_snapshot(db: Session, data: ProjectSnapshot) -> ProjectSnapshotWritten:
    """Replace the one snapshot of grimoire's projects. Only that row is written.

    The row's key is the constant 1, so two racing first writes cannot leave two rows:
    the one that loses the insert updates the winner's row instead.
    """
    values = {"snapshot": data.model_dump_json(), "updated_at": datetime.now(UTC)}
    row = _upsert(db, GrimoireProjectSnapshot, 1, {"id": 1}, values, missing="Project snapshot")
    logger.info("grimoire project snapshot written: %d projects", len(data.projects))
    return ProjectSnapshotWritten(updated_at=as_utc(row.updated_at))


def read_project_snapshot(db: Session) -> ProjectSnapshotRead:
    """The snapshot for the signed-in user; empty, with no timestamp, before grimoire has written one."""
    row = db.get(GrimoireProjectSnapshot, 1)
    if row is None:
        return ProjectSnapshotRead(projects=[], updated_at=None)
    stored = ProjectSnapshot.model_validate_json(row.snapshot)
    return ProjectSnapshotRead(projects=stored.projects, updated_at=as_utc(row.updated_at))
