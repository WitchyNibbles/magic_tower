"""Delegated OAuth routes; responses intentionally exclude tokens and secrets."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from ..config import get_settings
from ..services.oauth import OAuthError, authorization_url, exchange_code, verify_state
from ..services.sync import SyncError, token_store
from ..integrations.graph import GraphClient
from ..security import require_local_access, require_local_write_access

router = APIRouter(prefix="/api/auth", tags=["Microsoft Graph authentication"])


@router.get("/microsoft/start", dependencies=[Depends(require_local_access)])
def microsoft_start() -> dict[str, str]:
    try:
        return {"authorization_url": authorization_url(get_settings())}
    except OAuthError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/callback", response_class=HTMLResponse, include_in_schema=False)
def microsoft_callback(code: str = Query(min_length=1), state: str = Query(min_length=1)) -> HTMLResponse:
    settings = get_settings()
    try:
        verifier = verify_state(settings, state)
        token = exchange_code(settings, code, verifier)
        identity = GraphClient(str(token["access_token"])).me()
        if identity.get("id") != settings.microsoft_target_user_id:
            raise OAuthError("connected Microsoft user does not match configured target")
        token_store(settings).save(token)
    except (OAuthError, SyncError) as error:
        raise HTTPException(status_code=400, detail="Microsoft connection could not be completed") from error
    return HTMLResponse("<html><body><p>Microsoft Graph connected. You may close this window.</p></body></html>")


@router.delete("/microsoft", dependencies=[Depends(require_local_write_access)])
def disconnect_microsoft() -> dict[str, bool]:
    try:
        token_store(get_settings()).clear()
    except SyncError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"disconnected": True}
