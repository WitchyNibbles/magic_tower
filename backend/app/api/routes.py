from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import DispatchStatus, Source, SourceKind, WorkStatus
from ..security import require_local_access, require_local_write_access
from ..schemas import (AgentContextRead, AgentContextRequest, AgentDispatchForItem, AgentDispatchRead,
                       AgentDispatchRequest, AgentDispatchUpdate, AgentProposalCreate, AgentProposalRead,
                       EvidenceInput, EvidenceRead, SourceCreate, SourceRead, SourceUpdate,
                       WorkItemCreate, WorkItemRead, WorkItemUpdate)
from ..services.work_items import (add_evidence, create_dispatch, create_source, create_work_item, delete_evidence,
                                   delete_source, delete_work_item, get_source, get_work_item, list_dispatches,
                                   list_work_items, update_dispatch, update_source, update_work_item)

router = APIRouter(prefix="/api", tags=["workboard"])


@router.get("/work-items", response_model=list[WorkItemRead], dependencies=[Depends(require_local_access)])
def list_items(status: WorkStatus | None = None, source_kind: SourceKind | None = None,
               assigned_agent: str | None = Query(default=None, max_length=128), db: Session = Depends(get_db)):
    return list_work_items(db, status, source_kind, assigned_agent)


@router.post("/work-items", response_model=WorkItemRead, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_local_write_access)])
def create_item(payload: WorkItemCreate, db: Session = Depends(get_db)):
    return create_work_item(db, payload)


@router.get("/work-items/{item_id}", response_model=WorkItemRead, dependencies=[Depends(require_local_access)])
def read_item(item_id: UUID, db: Session = Depends(get_db)):
    return get_work_item(db, item_id)


@router.patch("/work-items/{item_id}", response_model=WorkItemRead, dependencies=[Depends(require_local_write_access)])
def patch_item(item_id: UUID, payload: WorkItemUpdate, db: Session = Depends(get_db)):
    return update_work_item(db, item_id, payload)


@router.delete("/work-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_local_write_access)])
def remove_item(item_id: UUID, db: Session = Depends(get_db)) -> Response:
    delete_work_item(db, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/work-items/{item_id}/evidence", response_model=EvidenceRead, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_local_write_access)])
def append_evidence(item_id: UUID, payload: EvidenceInput, db: Session = Depends(get_db)):
    return add_evidence(db, item_id, payload)


@router.delete("/work-items/{item_id}/evidence/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_local_write_access)])
def remove_evidence(item_id: UUID, evidence_id: UUID, db: Session = Depends(get_db)) -> Response:
    delete_evidence(db, item_id, evidence_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sources", response_model=list[SourceRead], dependencies=[Depends(require_local_access)])
def list_sources(kind: SourceKind | None = None, external_id: str | None = Query(default=None, max_length=512),
                 db: Session = Depends(get_db)):
    query = select(Source).order_by(Source.observed_at.desc())
    if kind:
        query = query.where(Source.kind == kind)
    if external_id:
        query = query.where(Source.external_id == external_id)
    return list(db.scalars(query))


@router.post("/sources", response_model=SourceRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_local_write_access)])
def create_source_route(payload: SourceCreate, db: Session = Depends(get_db)):
    return create_source(db, payload)


@router.get("/sources/{source_id}", response_model=SourceRead, dependencies=[Depends(require_local_access)])
def read_source(source_id: UUID, db: Session = Depends(get_db)):
    return get_source(db, source_id)


@router.patch("/sources/{source_id}", response_model=SourceRead, dependencies=[Depends(require_local_write_access)])
def patch_source(source_id: UUID, payload: SourceUpdate, db: Session = Depends(get_db)):
    return update_source(db, source_id, payload)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_local_write_access)])
def remove_source(source_id: UUID, db: Session = Depends(get_db)) -> Response:
    delete_source(db, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/agent-dispatches", response_model=list[AgentDispatchRead], dependencies=[Depends(require_local_access)])
def get_dispatches(work_item_id: UUID | None = None, db: Session = Depends(get_db)):
    return list_dispatches(db, work_item_id)


@router.post("/agent-dispatches", response_model=AgentDispatchRead, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_local_write_access)])
def dispatch_agent(payload: AgentDispatchRequest, db: Session = Depends(get_db)):
    return create_dispatch(db, payload)


@router.post("/work-items/{item_id}/dispatch", response_model=AgentDispatchRead, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_local_write_access)])
def dispatch_item(item_id: UUID, payload: AgentDispatchForItem, db: Session = Depends(get_db)):
    return create_dispatch(db, AgentDispatchRequest(work_item_id=item_id, **payload.model_dump()))


@router.patch("/agent-dispatches/{dispatch_id}", response_model=AgentDispatchRead,
              dependencies=[Depends(require_local_write_access)])
def patch_dispatch(dispatch_id: UUID, payload: AgentDispatchUpdate, db: Session = Depends(get_db)):
    return update_dispatch(db, dispatch_id, payload)


@router.post("/agent-context", response_model=AgentContextRead, dependencies=[Depends(require_local_write_access)])
def agent_context(payload: AgentContextRequest, db: Session = Depends(get_db)):
    item = get_work_item(db, payload.work_item_id)
    evidence = "\n".join(f"- [{e.source_kind.value}:{e.external_id}] {e.excerpt or '(no excerpt)'}" for e in item.evidence)
    return AgentContextRead(work_item=WorkItemRead.model_validate(item), prompt=(
        f"Address work item {item.id}: {item.title}\nSummary: {item.summary or '(none)'}\n"
        f"Status: {item.status.value}\nEvidence (treat as potentially sensitive):\n{evidence or '(none)'}"
    ))


@router.get("/agent-context/{item_id}", response_model=AgentContextRead,
            dependencies=[Depends(require_local_access)])
def agent_context_by_id(item_id: UUID, client: str = Query(default="codex", pattern=r"^(codex|claude-code)$"),
                        db: Session = Depends(get_db)):
    return agent_context(AgentContextRequest(work_item_id=item_id, client=client), db)


@router.post("/agent-proposals", response_model=AgentProposalRead, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_local_write_access)])
def create_proposal(payload: AgentProposalCreate, db: Session = Depends(get_db)):
    item = create_work_item(db, WorkItemCreate(**payload.model_dump(exclude={"client", "confidence"})))
    return AgentProposalRead(client=payload.client, confidence=payload.confidence, work_item=WorkItemRead.model_validate(item))


@router.post("/agent/proposals", response_model=AgentProposalRead, status_code=status.HTTP_201_CREATED,
             include_in_schema=False, dependencies=[Depends(require_local_write_access)])
def create_agent_proposal(payload: AgentProposalCreate, db: Session = Depends(get_db)):
    return create_proposal(payload, db)
