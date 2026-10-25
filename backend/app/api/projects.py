"""The user-side view of grimoire's project snapshot, read-only."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import ProjectSnapshotRead
from ..security import require_local_access
from ..services.grimoire_view import read_project_snapshot

router = APIRouter(prefix="/api", tags=["projects"], dependencies=[Depends(require_local_access)])


@router.get("/projects", response_model=ProjectSnapshotRead)
def list_projects(db: Session = Depends(get_db)):
    """What grimoire last wrote with ``PUT /api/grimoire/projects``; nothing here can edit it."""
    return read_project_snapshot(db)
