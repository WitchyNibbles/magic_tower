"""Ephemeral local-browser session endpoints; no Graph secrets are exposed."""

from fastapi import APIRouter, Depends, Response, status

from ..config import Settings, get_settings
from ..security import (SESSION_COOKIE, LocalAccess, clear_browser_session,
                        create_browser_session, require_local_access,
                        require_local_agent_token, require_local_write_access)

router = APIRouter(prefix="/api/session", tags=["local session"])


@router.post("", status_code=status.HTTP_201_CREATED)
def start_session(response: Response, settings: Settings = Depends(get_settings),
                  _: None = Depends(require_local_agent_token)) -> dict[str, str]:
    """Exchange the one-time typed local token for an HttpOnly browser cookie."""
    session_id, csrf_token = create_browser_session(settings)
    # The UI is served over loopback HTTP by default, so Secure cannot be set.
    # Do not expose this service beyond Docker Compose's loopback port binding.
    response.set_cookie(SESSION_COOKIE, session_id, max_age=settings.local_session_ttl_seconds,
                        httponly=True, samesite="strict", secure=False, path="/api")
    return {"csrf_token": csrf_token}


@router.get("")
def current_session(access: LocalAccess = Depends(require_local_access)) -> dict[str, str]:
    """Restore CSRF after a normal same-origin page reload."""
    return {"csrf_token": access.csrf_token or ""}


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def end_session(response: Response, access: LocalAccess = Depends(require_local_write_access)) -> Response:
    clear_browser_session(access.session_id)
    response.delete_cookie(SESSION_COOKIE, path="/api")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
