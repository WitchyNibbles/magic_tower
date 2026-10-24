"""Read-only sync orchestration and deliberately minimal local sync status."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from sqlalchemy.orm import Session

from ..config import Settings
from ..integrations.graph import GraphAuthError, GraphClient, GraphThrottledError
from .crypto import EncryptedTokenStore, TokenStoreError
from .graph import fetch_signals, persist_signals
from .oauth import OAuthError, refresh_access_token
from .promotion import promote_signals
from .sync_registry import UnknownSourceKindError, get_sync_handler, register_sync_handler, sync_lock

GRAPH_SOURCE_KIND = "graph"
# Refresh this long before ``expires_at`` so a token cannot lapse mid-sync.
REFRESH_MARGIN_SECONDS = 300
RECONNECT_MESSAGE = "Microsoft Graph session has expired; reconnect Microsoft Graph"


class SyncError(RuntimeError):
    pass


def token_store(settings: Settings) -> EncryptedTokenStore:
    key = settings.app_encryption_key
    if key is None:
        raise SyncError("APP_ENCRYPTION_KEY is not configured")
    return EncryptedTokenStore(settings.token_store_path, key.get_secret_value())


def _graph_connected(settings: Settings) -> bool:
    """True when a Graph token is stored; an unusable store counts as not connected."""
    try:
        return token_store(settings).load() is not None
    except (SyncError, TokenStoreError):
        return False


def _graph_ready(settings: Settings) -> bool:
    """Graph is worth syncing unprompted only when it is configured *and* connected.

    A configured-but-unconnected Graph can only answer "not connected", so
    scheduling it would turn every tick (and every empty-handed button press) into
    a standing error for an owner who simply has not signed in. Reading the token
    store is a local file read, cheap enough to do on every readiness check.
    """
    return not settings.graph_configuration_errors() and _graph_connected(settings)


def status(settings: Settings) -> dict[str, Any]:
    configured = not settings.graph_configuration_errors()
    connected = _graph_connected(settings)
    return {"configured": configured, "connected": connected, "mode": "read-only", "last_sync_at": None}


def _owner_addresses(profile: dict[str, Any]) -> tuple[str, ...]:
    """Both addresses Graph knows the signed-in user by; alias-domain tenants differ in the two."""
    return tuple(address for address in (profile.get("userPrincipalName"), profile.get("mail")) if isinstance(address, str))


def _expires_soon(token: dict[str, Any]) -> bool:
    """True when the stored ``expires_at`` is within the refresh margin.

    Tokens saved before expiry was tracked carry no ``expires_at``; they are used
    as they are and refreshed only if Graph answers 401.
    """
    expires_at = token.get("expires_at")
    return isinstance(expires_at, (int, float)) and expires_at - REFRESH_MARGIN_SECONDS <= time.time()


def _refresh(settings: Settings, store: EncryptedTokenStore, token: dict[str, Any]) -> dict[str, Any]:
    """Redeem the stored refresh token and persist the result, encrypted, in its place."""
    refresh_token = token.get("refresh_token")
    if not isinstance(refresh_token, str):
        raise SyncError(RECONNECT_MESSAGE)
    try:
        refreshed = refresh_access_token(settings, refresh_token)
    except OAuthError as error:
        raise SyncError(RECONNECT_MESSAGE) from error
    store.save(refreshed)
    return refreshed


def _read_graph(settings: Settings, graph: GraphClient, limit: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Every Graph read a sync makes, before anything is written, so it can be retried."""
    profile = graph.me()
    if profile.get("id") != settings.microsoft_target_user_id:
        raise SyncError("connected Microsoft user does not match MICROSOFT_TARGET_USER_ID")
    return profile, fetch_signals(graph, limit)


def _read_graph_with_refresh(settings: Settings, store: EncryptedTokenStore, token: dict[str, Any], limit: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Refresh an expiring token up front, and once more if Graph still answers 401.

    A token that was refreshed during this sync and is then rejected is not refreshed
    again: a second new token would not fare better, and the owner has to reconnect.
    """
    refreshed = _expires_soon(token)
    if refreshed:
        token = _refresh(settings, store, token)
    try:
        return _read_graph(settings, GraphClient(str(token["access_token"])), limit)
    except GraphAuthError as error:
        if refreshed:
            raise SyncError(RECONNECT_MESSAGE) from error
    token = _refresh(settings, store, token)
    try:
        return _read_graph(settings, GraphClient(str(token["access_token"])), limit)
    except GraphAuthError as error:
        raise SyncError(RECONNECT_MESSAGE) from error


def _sync_graph(settings: Settings, db: Session | None = None, limit: int = 50, client: GraphClient | None = None, **_: Any) -> dict[str, Any]:
    """The only handler that knows about Microsoft Graph; the identity assertion
    below is Graph-specific and must not apply to any other registered kind.

    An injected ``client`` already carries its own token, so it is used as given
    and never refreshed.
    """
    if settings.graph_configuration_errors():
        raise SyncError("Microsoft Graph is not configured")
    store = token_store(settings)
    try:
        token = store.load()
    except TokenStoreError as error:
        raise SyncError("Stored Graph credentials are unavailable") from error
    if not token or not isinstance(token.get("access_token"), str):
        raise SyncError("Microsoft Graph is not connected")
    try:
        if client is not None:
            profile, signals = _read_graph(settings, client, limit)
        else:
            profile, signals = _read_graph_with_refresh(settings, store, token, limit)
    except GraphThrottledError as error:
        # ``GraphClient`` has already waited and retried; this is throttling that outlasted it.
        raise SyncError("Microsoft Graph is throttling requests; try the sync again in a few minutes") from error
    created = persist_signals(db, signals) if db is not None else 0
    # Every signal is kept as a ``Source``; only the actionable ones reach the queue.
    promoted = promote_signals(db, signals, _owner_addresses(profile), settings.allowlisted_senders()) if db is not None else 0
    return {"mode": "read-only", "synced_at": datetime.now(UTC).isoformat(), "count": len(signals), "new_sources": created, "new_work_items": promoted}


register_sync_handler(GRAPH_SOURCE_KIND, _sync_graph, ready=_graph_ready)


def sync(settings: Settings, db: Session | None = None, client: GraphClient | None = None, limit: int = 50, kind: str = GRAPH_SOURCE_KIND) -> dict[str, Any]:
    """Dispatch to whatever handler is registered for ``kind``.

    Adding a new source kind (Jira, Freshservice, ...) means registering a
    handler for it elsewhere -- nothing here has to change.

    The kind's lock is held for the whole handler call, so a scheduled run and a
    button press never sync one source at the same time: the later one waits its
    turn and then sees the cursor the first one recorded.
    """
    try:
        handler = get_sync_handler(kind)
        lock = sync_lock(kind)
    except UnknownSourceKindError as error:
        raise SyncError(str(error)) from error
    with lock:
        return handler(settings, db=db, limit=limit, client=client)
