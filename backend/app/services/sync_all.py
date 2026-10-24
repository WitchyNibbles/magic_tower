"""Sync every ready source in turn and report each one's outcome.

Shared by ``POST /api/sync/all`` (the Sync now button) and the scheduler, so a
button press and a scheduled tick sync the same set and report the same way.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from ..config import Settings
from .sync import SyncError, sync
from .sync_registry import ready_kinds

logger = logging.getLogger(__name__)


def sync_ready_sources(settings: Settings, db: Session) -> dict[str, dict[str, Any]]:
    """One entry per ready kind: the handler's envelope, or ``{"error": message}``.

    One source failing must not stop the rest or fail the caller, so this never
    raises for a handler. A ``SyncError`` is the handler's own, owner-readable
    message and is passed through. Anything else is a bug or an outage nobody
    wrote a message for: it is logged with its traceback and the caller gets a
    fixed sentence, because an arbitrary exception's text (a URL, a header) is not
    something to hand to the browser.
    """
    results: dict[str, dict[str, Any]] = {}
    for kind in ready_kinds(settings):
        try:
            results[kind] = sync(settings, db, kind=kind)
        except SyncError as error:
            results[kind] = {"error": str(error)}
        except Exception:
            logger.exception("%s sync failed", kind)
            results[kind] = {"error": f"{kind} sync failed; see the API log"}
    return results
