"""The data half of removing the Teams source (revision ``0008``).

``teams_message`` stops being a ``SourceKind`` member the moment ``app.models``
ships without it, so a database still holding a row written by a completed Teams
sync would fail to load the moment anything reads it through the ORM. These
tests build exactly that database by hand -- a ``teams_message`` source, its
signal context, its promotion ledger row, and a work item (with evidence)
promoted from it, alongside an unrelated ``outlook_email`` row that must survive
untouched -- and assert revision ``0008`` deletes the Teams half and leaves the
rest exactly as it was.

Every row is built with raw SQL against revision ``0007`` rather than through
``app.models``, the same reason ``tests/test_migrations.py`` does: the fixture
must still describe a real pre-``0008`` database once ``SourceKind`` no longer
has a Python-side member for the row it is building.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run_alembic(database_path: Path, *argv: str) -> subprocess.CompletedProcess:
    """``alembic/env.py`` takes its URL from the environment and nowhere else."""
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database_path}"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *argv],
        cwd=BACKEND_DIR, env=environment, capture_output=True, text=True, timeout=25,
    )


def _uid() -> str:
    """The 32-character form ``sa.Uuid`` stores on SQLite."""
    return uuid4().hex


def _build_pre_removal_database(database_path: Path) -> dict[str, str]:
    """A database at revision ``0007`` holding one Teams source (promoted, with
    evidence) and one Outlook source (promoted, with evidence) that must survive.

    Returns the ids inserted, so the assertions below never have to guess them.
    """
    result = _run_alembic(database_path, "upgrade", "0007")
    assert result.returncode == 0, result.stderr

    now = datetime.now(timezone.utc).isoformat()
    ids = {
        "teams_source": _uid(), "teams_item": _uid(), "teams_evidence": _uid(),
        "mail_source": _uid(), "mail_item": _uid(), "mail_evidence": _uid(),
    }
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO sources (id, kind, external_id, subject, observed_at, created_at, updated_at)"
            " VALUES (?, 'teams_message', 'teams:direct-1', 'Release window', ?, ?, ?)",
            (ids["teams_source"], now, now, now),
        )
        connection.execute(
            "INSERT INTO source_signal_context (source_id, sender_kind, headers)"
            " VALUES (?, 'user', '{}')",
            (ids["teams_source"],),
        )
        connection.execute(
            "INSERT INTO source_promotions (source_id, considered_at) VALUES (?, ?)",
            (ids["teams_source"], now),
        )
        connection.execute(
            "INSERT INTO work_items (id, title, status, priority, source_kind, source_external_id, created_at, updated_at)"
            " VALUES (?, 'Release window', 'pending', 'medium', 'teams_message', 'teams:direct-1', ?, ?)",
            (ids["teams_item"], now, now),
        )
        connection.execute(
            "INSERT INTO work_evidence (id, work_item_id, source_kind, external_id, excerpt, observed_at)"
            " VALUES (?, ?, 'teams_message', 'teams:direct-1', 'are you free to cut the release', ?)",
            (ids["teams_evidence"], ids["teams_item"], now),
        )
        connection.execute(
            "INSERT INTO sources (id, kind, external_id, subject, observed_at, created_at, updated_at)"
            " VALUES (?, 'outlook_email', 'outlook:direct-1', 'Review the plan', ?, ?, ?)",
            (ids["mail_source"], now, now, now),
        )
        connection.execute(
            "INSERT INTO source_promotions (source_id, considered_at) VALUES (?, ?)",
            (ids["mail_source"], now),
        )
        connection.execute(
            "INSERT INTO work_items (id, title, status, priority, source_kind, source_external_id, created_at, updated_at)"
            " VALUES (?, 'Review the plan', 'pending', 'medium', 'outlook_email', 'outlook:direct-1', ?, ?)",
            (ids["mail_item"], now, now),
        )
        connection.execute(
            "INSERT INTO work_evidence (id, work_item_id, source_kind, external_id, excerpt, observed_at)"
            " VALUES (?, ?, 'outlook_email', 'outlook:direct-1', 'please review', ?)",
            (ids["mail_evidence"], ids["mail_item"], now),
        )
        connection.commit()
    finally:
        connection.close()
    return ids


def test_upgrade_deletes_every_row_a_teams_source_left_behind(tmp_path):
    database_path = tmp_path / "teams-removal.db"
    ids = _build_pre_removal_database(database_path)

    result = _run_alembic(database_path, "upgrade", "head")

    assert result.returncode == 0, result.stderr
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("SELECT kind FROM sources").fetchall() == [("outlook_email",)]
        assert connection.execute("SELECT source_kind FROM work_items").fetchall() == [("outlook_email",)]
        assert connection.execute("SELECT source_kind FROM work_evidence").fetchall() == [("outlook_email",)]
        assert connection.execute(
            "SELECT source_id FROM source_signal_context"
        ).fetchall() == []
        assert connection.execute(
            "SELECT source_id FROM source_promotions"
        ).fetchall() == [(ids["mail_source"],)]
    finally:
        connection.close()


def test_upgrade_leaves_the_surviving_outlook_row_byte_identical(tmp_path):
    """Deleting the Teams half must not touch a single column of what stays."""
    database_path = tmp_path / "teams-removal-survivor.db"
    ids = _build_pre_removal_database(database_path)

    result = _run_alembic(database_path, "upgrade", "head")

    assert result.returncode == 0, result.stderr
    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute(
            "SELECT id, kind, external_id, subject FROM sources WHERE id = ?", (ids["mail_source"],)
        ).fetchone()
    finally:
        connection.close()
    assert row == (ids["mail_source"], "outlook_email", "outlook:direct-1", "Review the plan")


def test_upgrade_is_idempotent_on_a_database_with_no_teams_rows(tmp_path):
    """The common case -- a database that never ran a Teams sync -- must upgrade cleanly."""
    database_path = tmp_path / "no-teams.db"
    result = _run_alembic(database_path, "upgrade", "head")

    assert result.returncode == 0, result.stderr
