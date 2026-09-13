"""Local bearer/session access and CSRF protections for Workboard.

The bearer token is a local-host trust boundary, not a defense against a
compromised host, browser profile, or Docker daemon. It is separate from and
must never be reused as a Microsoft Graph credential.
"""

from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass
from threading import Lock
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status

from .config import Settings, get_settings

SESSION_COOKIE = "workboard_session"


@dataclass(frozen=True)
class LocalAccess:
    via_bearer: bool
    csrf_token: str | None = None
    session_id: str | None = None


_sessions: dict[str, tuple[str, float]] = {}
_sessions_lock = Lock()


def _configured_token(settings: Settings) -> str:
    configured = settings.local_api_token
    expected = configured.get_secret_value() if configured else ""
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LOCAL_API_TOKEN must be configured before accessing Workboard data",
        )
    return expected


def _valid_bearer(authorization: str | None, expected: str) -> bool:
    scheme, _, supplied = (authorization or "").partition(" ")
    return scheme.lower() == "bearer" and bool(supplied) and hmac.compare_digest(supplied, expected)


def require_local_agent_token(authorization: Annotated[str | None, Header()] = None,
                              settings: Settings = Depends(get_settings)) -> None:
    """Authenticate an installed agent directly with the local bearer token."""
    if not _valid_bearer(authorization, _configured_token(settings)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="A valid local API bearer token is required",
                            headers={"WWW-Authenticate": "Bearer"})


def create_browser_session(settings: Settings) -> tuple[str, str]:
    """Return an opaque session id and CSRF token; neither is persisted to disk."""
    session_id, csrf_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with _sessions_lock:
        _sessions[session_id] = (csrf_token, time.monotonic() + settings.local_session_ttl_seconds)
    return session_id, csrf_token


def clear_browser_session(session_id: str | None) -> None:
    if session_id:
        with _sessions_lock:
            _sessions.pop(session_id, None)


def _session_csrf(session_id: str | None) -> str | None:
    if not session_id:
        return None
    with _sessions_lock:
        stored = _sessions.get(session_id)
        if not stored:
            return None
        csrf_token, expires_at = stored
        if expires_at <= time.monotonic():
            _sessions.pop(session_id, None)
            return None
        return csrf_token


def require_local_access(authorization: Annotated[str | None, Header()] = None,
                         session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
                         settings: Settings = Depends(get_settings)) -> LocalAccess:
    """Allow either an installed-agent bearer token or an opaque browser session."""
    expected = _configured_token(settings)
    if authorization:
        if _valid_bearer(authorization, expected):
            return LocalAccess(via_bearer=True)
        raise HTTPException(status_code=401, detail="A valid local API bearer token is required",
                            headers={"WWW-Authenticate": "Bearer"})
    csrf_token = _session_csrf(session_id)
    if csrf_token:
        return LocalAccess(via_bearer=False, csrf_token=csrf_token, session_id=session_id)
    raise HTTPException(status_code=401, detail="A local browser session or bearer token is required",
                        headers={"WWW-Authenticate": "Bearer"})


def require_local_write_access(access: LocalAccess = Depends(require_local_access),
                               csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None) -> LocalAccess:
    """Cookie-authenticated writes require CSRF; direct bearer calls do not."""
    if not access.via_bearer and (not csrf_token or not hmac.compare_digest(csrf_token, access.csrf_token or "")):
        raise HTTPException(status_code=403, detail="A valid X-CSRF-Token header is required")
    return access
