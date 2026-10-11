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

import importlib.machinery
import importlib.util
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

BACKEND_DIR = Path(__file__).resolve().parents[1]
REVISION_PATH = BACKEND_DIR / "alembic" / "versions" / "0008_remove_teams_source.py"
# Every table the schema has, so a count comparison notices a statement that
# reaches a table these tests never thought to name.
TABLES = ("sources", "work_items", "work_evidence", "agent_dispatches", "source_signal_context", "source_promotions")


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


def _table_counts(database_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(database_path)
    try:
        return {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in TABLES}
    finally:
        connection.close()


def _replay_revision_statements(database_path: Path) -> None:
    """Run ``0008``'s statement set outside alembic, which will not repeat a
    revision it has already stamped."""
    loader = importlib.machinery.SourceFileLoader("remove_teams_revision", str(REVISION_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    revision = importlib.util.module_from_spec(spec)
    loader.exec_module(revision)
    connection = sqlite3.connect(database_path)
    try:
        for statement in revision._STATEMENTS:
            connection.execute(statement, {"kind": revision.REMOVED_KIND})
        connection.commit()
    finally:
        connection.close()


def _build_pre_removal_database(database_path: Path, include_teams: bool = True) -> dict[str, str]:
    """A database at revision ``0007`` holding one Teams source (promoted, with
    evidence and a queued dispatch) and one Outlook source (same shape) that must
    survive.

    ``include_teams=False`` builds the Outlook half alone -- an installation that
    never ran a Teams sync, which is the common case ``0008`` meets in the field.

    Returns the ids inserted, so the assertions below never have to guess them.
    """
    result = _run_alembic(database_path, "upgrade", "0007")
    assert result.returncode == 0, result.stderr

    now = datetime.now(timezone.utc).isoformat()
    ids = {
        "teams_source": _uid(), "teams_item": _uid(), "teams_evidence": _uid(), "teams_dispatch": _uid(),
        "mail_source": _uid(), "mail_item": _uid(), "mail_evidence": _uid(), "mail_dispatch": _uid(),
    }
    connection = sqlite3.connect(database_path)
    try:
        if include_teams:
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
                "INSERT INTO agent_dispatches (id, work_item_id, client, instruction, status, created_at, updated_at)"
                " VALUES (?, ?, 'codex', 'Draft a reply in the chat.', 'queued', ?, ?)",
                (ids["teams_dispatch"], ids["teams_item"], now, now),
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
        connection.execute(
            "INSERT INTO agent_dispatches (id, work_item_id, client, instruction, status, created_at, updated_at)"
            " VALUES (?, ?, 'codex', 'Draft a reply to the mail.', 'queued', ?, ?)",
            (ids["mail_dispatch"], ids["mail_item"], now, now),
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


def test_upgrade_leaves_no_dispatch_pointing_at_a_deleted_teams_work_item(tmp_path):
    """``agent_dispatches`` cascades from ``work_items`` -- but only if the pragma is on.

    Nothing in this repo sets ``PRAGMA foreign_keys``, the same reason the
    revision hand-deletes ``source_signal_context`` and ``source_promotions``,
    so deleting the Teams work item leaves its dispatch behind unless the
    revision deletes that too. ``GET /api/agent-dispatches`` does not join
    ``work_items``, so an orphan would be served with a ``work_item_id`` that
    404s.
    """
    database_path = tmp_path / "teams-removal-dispatches.db"
    ids = _build_pre_removal_database(database_path)

    result = _run_alembic(database_path, "upgrade", "head")

    assert result.returncode == 0, result.stderr
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT id FROM agent_dispatches WHERE id = ?", (ids["teams_dispatch"],)
        ).fetchall() == []
        assert connection.execute(
            "SELECT id, work_item_id, instruction FROM agent_dispatches"
        ).fetchall() == [(ids["mail_dispatch"], ids["mail_item"], "Draft a reply to the mail.")]
        assert connection.execute(
            "SELECT count(*) FROM agent_dispatches d"
            " LEFT JOIN work_items w ON w.id = d.work_item_id WHERE w.id IS NULL"
        ).fetchone() == (0,)
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
    """The common case -- a database that never ran a Teams sync -- must upgrade
    cleanly and stay unchanged when the statement set runs again.

    Alembic refuses to replay a revision it has already stamped, so a second
    ``upgrade head`` cannot show this on its own; the statements are replayed
    directly instead, against rows they must not touch.
    """
    database_path = tmp_path / "no-teams.db"
    ids = _build_pre_removal_database(database_path, include_teams=False)

    result = _run_alembic(database_path, "upgrade", "head")
    assert result.returncode == 0, result.stderr

    survivors = _table_counts(database_path)
    assert survivors == {
        "sources": 1, "work_items": 1, "work_evidence": 1,
        "agent_dispatches": 1, "source_signal_context": 0, "source_promotions": 1,
    }
    _replay_revision_statements(database_path)
    _replay_revision_statements(database_path)

    assert _table_counts(database_path) == survivors
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("SELECT id FROM sources").fetchone() == (ids["mail_source"],)
    finally:
        connection.close()
