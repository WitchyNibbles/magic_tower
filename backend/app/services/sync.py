"""Read-only sync orchestration and deliberately minimal local sync status."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from sqlalchemy.orm import Session

from ..config import Settings
from ..integrations.graph import GraphClient
from .crypto import EncryptedTokenStore, TokenStoreError
from .graph import fetch_signals, persist_signals
from .promotion import promote_signals
from .sync_registry import UnknownSourceKindError, get_sync_handler, register_sync_handler

GRAPH_SOURCE_KIND = "graph"


class SyncError(RuntimeError):
    pass


def token_store(settings: Settings) -> EncryptedTokenStore:
    key = settings.app_encryption_key
    if key is None:
        raise SyncError("APP_ENCRYPTION_KEY is not configured")
    return EncryptedTokenStore(settings.token_store_path, key.get_secret_value())


def status(settings: Settings) -> dict[str, Any]:
    configured = not settings.graph_configuration_errors()
    try:
        connected = token_store(settings).load() is not None
    except (SyncError, TokenStoreError):
        connected = False
    return {"configured": configured, "connected": connected, "mode": "read-only", "last_sync_at": None}


def _owner_addresses(profile: dict[str, Any]) -> tuple[str, ...]:
    """Both addresses Graph knows the signed-in user by; alias-domain tenants differ in the two."""
    return tuple(address for address in (profile.get("userPrincipalName"), profile.get("mail")) if isinstance(address, str))


def _sync_graph(settings: Settings, db: Session | None = None, limit: int = 50, client: GraphClient | None = None, **_: Any) -> dict[str, Any]:
    """The only handler that knows about Microsoft Graph; the identity assertion
    below is Graph-specific and must not apply to any other registered kind."""
    if settings.graph_configuration_errors():
        raise SyncError("Microsoft Graph is not configured")
    try:
        token = token_store(settings).load()
    except TokenStoreError as error:
        raise SyncError("Stored Graph credentials are unavailable") from error
    if not token or not isinstance(token.get("access_token"), str):
        raise SyncError("Microsoft Graph is not connected")
    graph = client or GraphClient(token["access_token"])
    profile = graph.me()
    if profile.get("id") != settings.microsoft_target_user_id:
        raise SyncError("connected Microsoft user does not match MICROSOFT_TARGET_USER_ID")
    signals = fetch_signals(graph, limit)
    created = persist_signals(db, signals) if db is not None else 0
    # Every signal is kept as a ``Source``; only the actionable ones reach the queue.
    promoted = promote_signals(db, signals, _owner_addresses(profile), settings.allowlisted_senders()) if db is not None else 0
    return {"mode": "read-only", "synced_at": datetime.now(UTC).isoformat(), "count": len(signals), "new_sources": created, "new_work_items": promoted}


register_sync_handler(GRAPH_SOURCE_KIND, _sync_graph)


def sync(settings: Settings, db: Session | None = None, client: GraphClient | None = None, limit: int = 50, kind: str = GRAPH_SOURCE_KIND) -> dict[str, Any]:
    """Dispatch to whatever handler is registered for ``kind``.

    Adding a new source kind (Jira, Freshservice, ...) means registering a
    handler for it elsewhere -- nothing here has to change.
    """
    try:
        handler = get_sync_handler(kind)
    except UnknownSourceKindError as error:
        raise SyncError(str(error)) from error
    return handler(settings, db=db, limit=limit, client=client)
