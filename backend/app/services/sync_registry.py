"""Registry of sync handlers, keyed by source kind.

``sync()`` in :mod:`app.services.sync` used to be hardwired to Microsoft Graph.
Adding a second connector (Jira, Freshservice, ...) meant editing its body. This
registry lets a connector register a handler for its own kind instead -- so a new
kind shows up by calling :func:`register_sync_handler` once, from wherever that
connector lives, without touching ``sync()``.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..config import Settings

# A handler receives the same shape ``sync()`` always did (settings, an optional
# db session, and a limit) plus any connector-specific extras as keyword-only
# args (e.g. Graph's ``client``), and returns the same result envelope ``sync()``
# has always returned.
SyncHandler = Callable[..., dict[str, Any]]
# Whether a kind is set up well enough to sync without being asked for by name.
ReadyCheck = Callable[["Settings"], bool]

_handlers: dict[str, SyncHandler] = {}
_ready_checks: dict[str, ReadyCheck] = {}
# One lock per kind, created at registration and never dropped: a sync that is
# holding it must not lose it to an ``unregister`` or a re-registration.
_locks: dict[str, threading.Lock] = {}


class UnknownSourceKindError(RuntimeError):
    """Raised when nothing is registered for the requested source kind."""


def register_sync_handler(kind: str, handler: SyncHandler, ready: ReadyCheck | None = None) -> None:
    """Register ``handler`` for ``kind``.

    ``ready(settings)`` says whether the kind is configured; only kinds with a
    ``ready`` check are ever synced unprompted (:func:`ready_kinds`), so a handler
    that cannot say when it is usable is reachable by name alone.
    """
    _handlers[kind] = handler
    _locks.setdefault(kind, threading.Lock())
    if ready is None:
        _ready_checks.pop(kind, None)
    else:
        _ready_checks[kind] = ready


def unregister_sync_handler(kind: str) -> None:
    _handlers.pop(kind, None)
    _ready_checks.pop(kind, None)


def get_sync_handler(kind: str) -> SyncHandler:
    try:
        return _handlers[kind]
    except KeyError as error:
        raise UnknownSourceKindError(f"no sync handler registered for source kind {kind!r}") from error


def registered_kinds() -> tuple[str, ...]:
    return tuple(_handlers)


def ready_kinds(settings: "Settings") -> tuple[str, ...]:
    """The registered kinds whose ``ready`` check passes for ``settings``, in registration order."""
    return tuple(kind for kind in _handlers if kind in _ready_checks and _ready_checks[kind](settings))


def sync_lock(kind: str) -> threading.Lock:
    """The lock that serialises syncs of ``kind``; ``sync()`` holds it around the handler call."""
    try:
        return _locks[kind]
    except KeyError as error:
        raise UnknownSourceKindError(f"no sync handler registered for source kind {kind!r}") from error
