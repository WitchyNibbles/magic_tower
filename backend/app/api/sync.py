"""Read-only source ingestion endpoints for local UI and installed agent clients."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..services.backfill import backfill_promoted_sources
from ..services.sync import GRAPH_SOURCE_KIND, SyncError, status, sync
from ..security import require_local_write_access

router = APIRouter(prefix="/api/sync", tags=["source sync"])


@router.get("/status")
def sync_status() -> dict[str, object]:
    return status(get_settings())


@router.post("", dependencies=[Depends(require_local_write_access)])
def run_sync(
    limit: int = Query(default=50, ge=1, le=100),
    kind: str = Query(default=GRAPH_SOURCE_KIND),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Dispatch a sync for ``kind``, defaulting to Microsoft Graph so an omitted
    parameter behaves exactly as this route did before it accepted one.

    ``kind`` reaches ``sync()`` unchecked; an unregistered one comes back as
    ``UnknownSourceKindError`` wrapped in ``SyncError`` (``app/services/sync.py``),
    so *that* path answers 409 rather than 500. Only ``SyncError`` is caught here:
    a handler raising anything else -- ``GraphError``, say -- still escapes as a
    500, which is pre-existing behaviour this route does not change.
    """
    try:
        return sync(get_settings(), db, limit=limit, kind=kind)
    except SyncError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/backfill", dependencies=[Depends(require_local_write_access)])
def run_backfill(db: Session = Depends(get_db)) -> dict[str, object]:
    """Promote the sources stored before promotion existed, once.

    Explicit rather than automatic on startup: it writes work items, so it belongs
    behind the same guard as a sync, and boot must stay free of database work. It
    reaches no network and needs no Graph connection -- everything it reads is
    already on disk -- so it cannot fail the way ``POST /api/sync`` can.

    The envelope never collapses to one number: see
    ``app.services.backfill.backfill_promoted_sources`` for what ``considered``,
    ``new_work_items``, ``judged_without_context`` and
    ``promoted_without_owner_check`` each distinguish. The last two report the two
    ways a backfilled judgement is weaker than the one a live sync reaches.
    """
    return backfill_promoted_sources(db)
