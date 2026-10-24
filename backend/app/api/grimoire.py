"""Routes for the grimoire client, guarded by ``GRIMOIRE_API_TOKEN`` and nothing else."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..schemas import AnalysisRead, AnalysisWrite, GrimoireContext, GrimoireItemPage, ProjectSnapshot, ProjectSnapshotWritten
from ..security import require_grimoire_token
from ..services.grimoire_view import context_fields, fingerprint, get_open_item, items_needing_analysis, save_analysis, save_project_snapshot
from ..services.sync_all import sync_ready_sources
from ..services.work_items import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT

router = APIRouter(prefix="/api/grimoire", tags=["grimoire"], dependencies=[Depends(require_grimoire_token)])


@router.get("/items", response_model=GrimoireItemPage)
def list_items(needs_analysis: bool = True, limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
               offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    """References only (id, title, link, status, analysis state): never any source text."""
    refs, total = items_needing_analysis(db, needs_analysis=needs_analysis, limit=limit, offset=offset)
    return GrimoireItemPage(items=refs, total=total, limit=limit, offset=offset)


@router.get("/items/{item_id}/context", response_model=GrimoireContext)
def item_context(item_id: UUID, db: Session = Depends(get_db)):
    """The only route that returns source text to grimoire. It is data, not instructions."""
    fields = context_fields(db, get_open_item(db, item_id))
    return GrimoireContext(**fields, fingerprint=fingerprint(fields))


@router.post("/sync")
def run_sync(db: Session = Depends(get_db)) -> dict[str, object]:
    """Sync every ready source, as Sync now does, so grimoire can analyse fresh data.

    A source failing is a result under its kind, not an HTTP error (``POST /api/sync/all``).
    """
    return {"results": sync_ready_sources(get_settings(), db)}


@router.put("/items/{item_id}/analysis", response_model=AnalysisRead)
def write_analysis(item_id: UUID, payload: AnalysisWrite, db: Session = Depends(get_db)):
    """Store an analysis of the text grimoire read; 409 if that text has changed since."""
    analysis = save_analysis(db, get_open_item(db, item_id), payload)
    return AnalysisRead.from_row(analysis, stale=False)  # just checked against the current text


@router.put("/projects", response_model=ProjectSnapshotWritten)
def write_projects(payload: ProjectSnapshot, db: Session = Depends(get_db)):
    """Replace the snapshot of grimoire's projects that the UI shows read-only."""
    return save_project_snapshot(db, payload)
