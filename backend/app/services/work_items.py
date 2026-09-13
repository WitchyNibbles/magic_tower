from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..models import AgentDispatch, DispatchStatus, Source, WorkEvidence, WorkItem, WorkStatus
from ..schemas import (AgentDispatchRequest, AgentDispatchUpdate, EvidenceInput, SourceCreate, SourceUpdate,
                       WorkItemCreate, WorkItemUpdate)


def not_found(entity: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{entity} not found")


def conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def get_work_item(db: Session, item_id: UUID) -> WorkItem:
    item = db.scalar(select(WorkItem).options(selectinload(WorkItem.evidence)).where(WorkItem.id == item_id))
    if item is None:
        raise not_found("Work item")
    return item


def list_work_items(db: Session, status_filter: WorkStatus | None, source_kind: str | None, assigned_agent: str | None) -> list[WorkItem]:
    query = select(WorkItem).options(selectinload(WorkItem.evidence)).order_by(WorkItem.updated_at.desc())
    if status_filter:
        query = query.where(WorkItem.status == status_filter)
    if source_kind:
        query = query.where(WorkItem.source_kind == source_kind)
    if assigned_agent:
        query = query.where(WorkItem.assigned_agent == assigned_agent)
    return list(db.scalars(query))


def create_work_item(db: Session, payload: WorkItemCreate) -> WorkItem:
    data = payload.model_dump(exclude={"evidence"}, mode="json")
    data["source_url"] = str(data["source_url"]) if data.get("source_url") else None
    item = WorkItem(**data)
    for evidence in payload.evidence:
        item.evidence.append(WorkEvidence(**evidence.model_dump(exclude={"observed_at"}), observed_at=evidence.observed_at))
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("A work item with this source_external_id already exists")
    return get_work_item(db, item.id)


def update_work_item(db: Session, item_id: UUID, payload: WorkItemUpdate) -> WorkItem:
    item = get_work_item(db, item_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    return get_work_item(db, item.id)


def delete_work_item(db: Session, item_id: UUID) -> None:
    db.delete(get_work_item(db, item_id))
    db.commit()


def add_evidence(db: Session, item_id: UUID, payload: EvidenceInput) -> WorkEvidence:
    item = get_work_item(db, item_id)
    evidence = WorkEvidence(
        work_item_id=item.id,
        **payload.model_dump(exclude={"observed_at"}),
        observed_at=payload.observed_at,
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence


def delete_evidence(db: Session, item_id: UUID, evidence_id: UUID) -> None:
    get_work_item(db, item_id)
    evidence = db.get(WorkEvidence, evidence_id)
    if evidence is None or evidence.work_item_id != item_id:
        raise not_found("Evidence")
    db.delete(evidence)
    db.commit()


def get_source(db: Session, source_id: UUID) -> Source:
    source = db.get(Source, source_id)
    if source is None:
        raise not_found("Source")
    return source


def create_source(db: Session, payload: SourceCreate) -> Source:
    data = payload.model_dump(mode="json")
    data["url"] = str(data["url"]) if data.get("url") else None
    source = Source(**data)
    db.add(source)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("A source with this external_id already exists")
    return get_source(db, source.id)


def update_source(db: Session, source_id: UUID, payload: SourceUpdate) -> Source:
    source = get_source(db, source_id)
    data = payload.model_dump(exclude_unset=True, mode="json")
    if "url" in data:
        data["url"] = str(data["url"]) if data["url"] else None
    for key, value in data.items():
        setattr(source, key, value)
    db.commit()
    return get_source(db, source_id)


def delete_source(db: Session, source_id: UUID) -> None:
    db.delete(get_source(db, source_id))
    db.commit()


def create_dispatch(db: Session, payload: AgentDispatchRequest) -> AgentDispatch:
    get_work_item(db, payload.work_item_id)
    dispatch = AgentDispatch(**payload.model_dump())
    db.add(dispatch)
    db.commit()
    db.refresh(dispatch)
    return dispatch


def update_dispatch(db: Session, dispatch_id: UUID, payload: AgentDispatchUpdate) -> AgentDispatch:
    dispatch = db.get(AgentDispatch, dispatch_id)
    if dispatch is None:
        raise not_found("Agent dispatch")
    dispatch.status = payload.status
    if payload.result is not None:
        dispatch.result = payload.result
    db.commit()
    db.refresh(dispatch)
    return dispatch


def list_dispatches(db: Session, work_item_id: UUID | None = None) -> list[AgentDispatch]:
    query = select(AgentDispatch).order_by(AgentDispatch.created_at.desc())
    if work_item_id:
        query = query.where(AgentDispatch.work_item_id == work_item_id)
    return list(db.scalars(query))
