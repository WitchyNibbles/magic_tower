"""Routes for the grimoire client, guarded by ``GRIMOIRE_API_TOKEN`` and nothing else."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import GrimoireContext, GrimoireItemPage
from ..security import require_grimoire_token
from ..services.grimoire_view import context_fields, fingerprint, get_open_item, items_needing_analysis
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
