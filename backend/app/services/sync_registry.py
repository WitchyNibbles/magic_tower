"""Registry of sync handlers, keyed by source kind.

``sync()`` in :mod:`app.services.sync` used to be hardwired to Microsoft Graph.
Adding a second connector (Jira, Freshservice, ...) meant editing its body. This
registry lets a connector register a handler for its own kind instead -- so a new
kind shows up by calling :func:`register_sync_handler` once, from wherever that
connector lives, without touching ``sync()``.
"""

from __future__ import annotations

from typing import Any, Callable

# A handler receives the same shape ``sync()`` always did (settings, an optional
# db session, and a limit) plus any connector-specific extras as keyword-only
# args (e.g. Graph's ``client``), and returns the same result envelope ``sync()``
# has always returned.
SyncHandler = Callable[..., dict[str, Any]]

_handlers: dict[str, SyncHandler] = {}


class UnknownSourceKindError(RuntimeError):
    """Raised when nothing is registered for the requested source kind."""


def register_sync_handler(kind: str, handler: SyncHandler) -> None:
    _handlers[kind] = handler


def unregister_sync_handler(kind: str) -> None:
    _handlers.pop(kind, None)


def get_sync_handler(kind: str) -> SyncHandler:
    try:
        return _handlers[kind]
    except KeyError as error:
        raise UnknownSourceKindError(f"no sync handler registered for source kind {kind!r}") from error


def registered_kinds() -> tuple[str, ...]:
    return tuple(_handlers)
