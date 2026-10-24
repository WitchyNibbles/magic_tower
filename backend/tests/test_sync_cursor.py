"""``app/services/sync_cursor.py``: the per-source "last successful sync" marker a
Jira sync derives its window from. Uses the per-run temp SQLite database from
``conftest``; nothing here reaches the network.

SQLite hands back naive datetimes even for a ``timezone=True`` column, so the
timezone cases below are the point of this file: a cursor read back as local or
naive time would shift every later window by the machine's UTC offset.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.database import engine
from app.services.sync_cursor import last_success, record_success


def test_a_kind_that_never_synced_has_no_cursor() -> None:
    with Session(engine) as db:
        assert last_success(db, "jira") is None


def test_a_recorded_cursor_reads_back_as_the_same_utc_instant() -> None:
    at = datetime(2026, 10, 20, 9, 30, 15, tzinfo=UTC)

    with Session(engine) as db:
        record_success(db, "jira", at)

    with Session(engine) as fresh:
        stored = last_success(fresh, "jira")

    assert stored == at
    assert stored is not None and stored.utcoffset() == timedelta(0)


def test_a_cursor_given_in_another_timezone_is_stored_as_the_same_instant() -> None:
    plus_two = timezone(timedelta(hours=2))

    with Session(engine) as db:
        record_success(db, "jira", datetime(2026, 10, 20, 11, 30, tzinfo=plus_two))

    with Session(engine) as fresh:
        assert last_success(fresh, "jira") == datetime(2026, 10, 20, 9, 30, tzinfo=UTC)


def test_recording_again_replaces_the_cursor_instead_of_adding_a_second_row() -> None:
    with Session(engine) as db:
        record_success(db, "jira", datetime(2026, 10, 20, 9, 0, tzinfo=UTC))
        record_success(db, "jira", datetime(2026, 10, 21, 9, 0, tzinfo=UTC))

    with Session(engine) as fresh:
        assert last_success(fresh, "jira") == datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


def test_each_kind_keeps_its_own_cursor() -> None:
    jira_at = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    graph_at = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)

    with Session(engine) as db:
        record_success(db, "jira", jira_at)
        record_success(db, "graph", graph_at)

    with Session(engine) as fresh:
        assert last_success(fresh, "jira") == jira_at
        assert last_success(fresh, "graph") == graph_at
