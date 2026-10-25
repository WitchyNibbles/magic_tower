"""Delegated Microsoft OAuth helpers. No credentials are logged or returned."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
import json

from .crypto import EncryptedTokenStore, TokenStoreError

from ..config import Settings

LOGIN_ROOT = "https://login.microsoftonline.com"
GRAPH_SCOPES = ("offline_access", "User.Read", "Mail.Read")


class OAuthError(RuntimeError):
    pass


class _RefuseRedirects(HTTPRedirectHandler):
    """``urlopen`` follows a 3xx, copying the request's headers to wherever it points
    and, for a POST answered with 301/302/303, re-issuing it as a GET. The token
    request carries the client secret, authorization code and refresh token, so a
    redirect is an error, not a hop."""

    def redirect_request(self, *_: object, **__: object) -> None:
        raise OAuthError("Microsoft token exchange was redirected")


_opener = build_opener(_RefuseRedirects)


def _state_key(settings: Settings) -> bytes:
    secret = settings.microsoft_client_secret
    if secret is None:
        raise OAuthError("Microsoft Graph is not configured")
    return secret.get_secret_value().encode()


def make_state(settings: Settings, now: datetime | None = None) -> str:
    issued = int((now or datetime.now(UTC)).timestamp())
    nonce = secrets.token_urlsafe(24)
    payload = f"{issued}.{nonce}"
    signature = hmac.new(_state_key(settings), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def _state_store(settings: Settings) -> EncryptedTokenStore:
    key = settings.app_encryption_key
    if key is None:
        raise OAuthError("APP_ENCRYPTION_KEY is not configured")
    return EncryptedTokenStore(settings.oauth_state_store_path, key.get_secret_value())


def verify_state(settings: Settings, state: str, now: datetime | None = None) -> str:
    try:
        issued_text, nonce, provided = state.split(".")
        issued = int(issued_text)
        if len(nonce) < 20:
            raise ValueError
        payload = f"{issued_text}.{nonce}"
        expected = hmac.new(_state_key(settings), payload.encode(), hashlib.sha256).digest()
        padded = provided + "=" * (-len(provided) % 4)
        valid = hmac.compare_digest(expected, base64.urlsafe_b64decode(padded))
    except (ValueError, UnicodeError, TypeError, binascii.Error):
        raise OAuthError("invalid OAuth state") from None
    current = int((now or datetime.now(UTC)).timestamp())
    if not valid or issued > current or current - issued > timedelta(minutes=10).total_seconds():
        raise OAuthError("expired or invalid OAuth state")
    try:
        stored = _state_store(settings).load()
    except TokenStoreError as error:
        raise OAuthError("invalid OAuth state") from error
    if not stored or not hmac.compare_digest(str(stored.get("state", "")), state):
        raise OAuthError("expired or invalid OAuth state")
    _state_store(settings).clear()  # one-time use, including failed code exchanges
    verifier = stored.get("verifier")
    if not isinstance(verifier, str):
        raise OAuthError("invalid OAuth state")
    return verifier


def authorization_url(settings: Settings) -> str:
    errors = settings.graph_configuration_errors()
    if errors:
        raise OAuthError("Graph configuration is incomplete: " + ", ".join(errors))
    verifier = secrets.token_urlsafe(64)
    state = make_state(settings)
    _state_store(settings).save({"state": state, "verifier": verifier})
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = {
        "client_id": settings.microsoft_client_id,
        "response_type": "code",
        "redirect_uri": settings.microsoft_redirect_uri,
        "response_mode": "query",
        "scope": " ".join(GRAPH_SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    tenant = settings.microsoft_tenant_id
    return f"{LOGIN_ROOT}/{tenant}/oauth2/v2.0/authorize?{urlencode(params)}"


def _request_token(settings: Settings, grant: dict[str, str]) -> dict[str, object]:
    """POST one grant to the token endpoint and stamp the result with ``expires_at``.

    ``expires_in`` is relative to the response, so it is converted to an absolute
    Unix time here, before the token is stored and the moment is lost.
    """
    errors = settings.graph_configuration_errors()
    if errors:
        raise OAuthError("Graph configuration is incomplete: " + ", ".join(errors))
    body = urlencode({
        "client_id": settings.microsoft_client_id,
        "client_secret": settings.microsoft_client_secret.get_secret_value() if settings.microsoft_client_secret else "",
        "scope": " ".join(GRAPH_SCOPES),
        **grant,
    }).encode()
    request = Request(
        f"{LOGIN_ROOT}/{settings.microsoft_tenant_id}/oauth2/v2.0/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    requested_at = time.time()
    try:
        with _opener.open(request, timeout=15) as response:
            token = json.loads(response.read())
    except OAuthError:
        raise
    except Exception as error:
        raise OAuthError("Microsoft token exchange failed") from error
    if not isinstance(token, dict) or not token.get("access_token"):
        raise OAuthError("Microsoft token exchange returned no access token")
    if isinstance(token.get("expires_in"), (int, float)):
        token["expires_at"] = requested_at + token["expires_in"]
    return token


def exchange_code(settings: Settings, code: str, verifier: str) -> dict[str, object]:
    """Exchange an authorization code. Token data stays inside the backend."""
    return _request_token(settings, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.microsoft_redirect_uri,
        "code_verifier": verifier,
    })


def refresh_access_token(settings: Settings, refresh_token: str) -> dict[str, object]:
    """Redeem a refresh token for a new access token.

    Microsoft usually rotates the refresh token, but the response may omit it; the
    old one then stays valid and is carried forward so the next refresh still works.
    """
    token = _request_token(settings, {"grant_type": "refresh_token", "refresh_token": refresh_token})
    token.setdefault("refresh_token", refresh_token)
    return token
