"""Persisted "last successful sync" marker per source kind (``SyncCursor``).

SQLite returns naive datetimes even for a ``timezone=True`` column, and writes an
aware one as its wall-clock fields with the offset dropped. Both ends are
pinned to UTC here -- a value is converted to UTC on the way in and a naive
value read back is taken as UTC -- so a caller never sees a cursor shifted by
the offset of whatever zone it was handed or the machine happens to run in.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import SyncCursor
from .timeutil import as_utc


def last_success(db: Session, kind: str) -> datetime | None:
    """The UTC start time of ``kind``'s last successful sync, or ``None`` if it never ran."""
    cursor = db.get(SyncCursor, kind)
    return None if cursor is None else as_utc(cursor.last_success_at)


def record_success(db: Session, kind: str, at: datetime) -> None:
    """Upsert ``kind``'s cursor to ``at`` and commit."""
    cursor = db.get(SyncCursor, kind)
    if cursor is None:
        db.add(SyncCursor(kind=kind, last_success_at=as_utc(at)))
    else:
        cursor.last_success_at = as_utc(at)
    db.commit()
