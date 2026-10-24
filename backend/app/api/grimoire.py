"""Routes for the grimoire client, guarded by ``GRIMOIRE_API_TOKEN`` and nothing else."""

from fastapi import APIRouter, Depends

from ..security import require_grimoire_token

router = APIRouter(prefix="/api/grimoire", tags=["grimoire"], dependencies=[Depends(require_grimoire_token)])


@router.get("/ping")
def ping() -> dict[str, bool]:
    return {"ok": True}
