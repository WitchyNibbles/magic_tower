"""The one place a datetime is pinned to UTC.

SQLite returns naive datetimes even for a ``timezone=True`` column, and writes an aware
one as its wall-clock fields with the offset dropped. Everything stored here was written
as UTC, so a naive value read back is taken as UTC and an aware one is converted to it.
"""

from __future__ import annotations

from datetime import UTC, datetime


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
