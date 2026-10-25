"""Local bearer/session access and CSRF protections for Workboard.

The bearer token is a local-host trust boundary, not a defense against a
compromised host, browser profile, or Docker daemon. It is separate from and
must never be reused as a Microsoft Graph credential.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import get_db
from .models import BrowserSession

SESSION_COOKIE = "workboard_session"


@dataclass(frozen=True)
class LocalAccess:
    via_bearer: bool
    csrf_token: str | None = None
    session_id: str | None = None


def _configured_token(settings: Settings) -> str:
    configured = settings.local_api_token
    expected = configured.get_secret_value() if configured else ""
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LOCAL_API_TOKEN must be configured before accessing Workboard data",
        )
    return expected


def _same_secret(supplied: str, expected: str) -> bool:
    """Constant-time equality on UTF-8 bytes: ``compare_digest`` raises on a non-ASCII ``str``."""
    return hmac.compare_digest(supplied.encode(), expected.encode())


def _valid_bearer(authorization: str | None, expected: str) -> bool:
    scheme, _, supplied = (authorization or "").partition(" ")
    return scheme.lower() == "bearer" and bool(supplied) and _same_secret(supplied, expected)


def require_local_agent_token(authorization: Annotated[str | None, Header()] = None,
                              settings: Settings = Depends(get_settings)) -> None:
    """Authenticate an installed agent directly with the local bearer token."""
    if not _valid_bearer(authorization, _configured_token(settings)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="A valid local API bearer token is required",
                            headers={"WWW-Authenticate": "Bearer"})


def require_grimoire_token(authorization: Annotated[str | None, Header()] = None,
                           settings: Settings = Depends(get_settings)) -> None:
    """Authenticate the grimoire client on ``/api/grimoire/*`` with its own bearer token.

    Deliberately not ``LOCAL_API_TOKEN`` and not a browser session: whoever holds one of
    those cannot read source text or write analyses, and this token opens no other route.
    """
    configured = settings.grimoire_api_token
    expected = configured.get_secret_value() if configured else ""
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="grimoire API not configured")
    local = settings.local_api_token
    if local is not None and _same_secret(local.get_secret_value(), expected):
        # Refused here, not when the settings load: a shared value must not take the whole app down,
        # only open nothing -- otherwise the local bearer would be a grimoire credential.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="GRIMOIRE_API_TOKEN must differ from LOCAL_API_TOKEN")
    if not _valid_bearer(authorization, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="A valid grimoire API bearer token is required",
                            headers={"WWW-Authenticate": "Bearer"})


def _session_key(session_id: str) -> str:
    """The stored form of a session id: its SHA-256, so the database never holds the cookie value."""
    return hashlib.sha256(session_id.encode()).hexdigest()


def create_browser_session(db: Session, settings: Settings) -> tuple[str, str]:
    """Return an opaque session id and CSRF token, storing only the id's hash.

    Sessions that have already expired are deleted first, so the table holds no
    more than the browsers signed in during the last session lifetime.
    """
    session_id, csrf_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = time.time()
    db.execute(delete(BrowserSession).where(BrowserSession.expires_at <= now))
    db.add(BrowserSession(id_hash=_session_key(session_id), csrf_token=csrf_token,
                          expires_at=now + settings.local_session_ttl_seconds))
    db.commit()
    return session_id, csrf_token


def clear_browser_session(db: Session, session_id: str | None) -> None:
    if session_id:
        db.execute(delete(BrowserSession).where(BrowserSession.id_hash == _session_key(session_id)))
        db.commit()


def _session_csrf(db: Session, session_id: str | None) -> str | None:
    if not session_id:
        return None
    stored = db.get(BrowserSession, _session_key(session_id))
    if stored is None:
        return None
    if stored.expires_at <= time.time():
        db.delete(stored)
        db.commit()
        return None
    return stored.csrf_token


def require_local_access(authorization: Annotated[str | None, Header()] = None,
                         session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
                         settings: Settings = Depends(get_settings),
                         db: Session = Depends(get_db)) -> LocalAccess:
    """Allow either an installed-agent bearer token or an opaque browser session."""
    expected = _configured_token(settings)
    if authorization:
        if _valid_bearer(authorization, expected):
            return LocalAccess(via_bearer=True)
        raise HTTPException(status_code=401, detail="A valid local API bearer token is required",
                            headers={"WWW-Authenticate": "Bearer"})
    csrf_token = _session_csrf(db, session_id)
    if csrf_token:
        return LocalAccess(via_bearer=False, csrf_token=csrf_token, session_id=session_id)
    raise HTTPException(status_code=401, detail="A local browser session or bearer token is required",
                        headers={"WWW-Authenticate": "Bearer"})


def require_local_write_access(access: LocalAccess = Depends(require_local_access),
                               csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None) -> LocalAccess:
    """Cookie-authenticated writes require CSRF; direct bearer calls do not."""
    if not access.via_bearer and (not csrf_token or not _same_secret(csrf_token, access.csrf_token or "")):
        raise HTTPException(status_code=403, detail="A valid X-CSRF-Token header is required")
    return access
