"""Read-only Graph ingestion endpoints for local UI and installed agent clients."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..services.backfill import backfill_promoted_sources
from ..services.sync import SyncError, status, sync
from ..security import require_local_write_access

router = APIRouter(prefix="/api/sync", tags=["Microsoft Graph sync"])


@router.get("/status")
def sync_status() -> dict[str, object]:
    return status(get_settings())


@router.post("", dependencies=[Depends(require_local_write_access)])
def run_sync(limit: int = Query(default=50, ge=1, le=100), db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        return sync(get_settings(), db, limit=limit)
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
    ``new_work_items`` and ``judged_without_context`` each distinguish.
    """
    return backfill_promoted_sources(db)
