"""Guards that the Alembic chain -- not application startup -- owns the schema.

``conftest`` still builds the test schema with ``Base.metadata.create_all`` (see the
note there), so nothing else in the suite would notice if the migrations stopped
matching ``app.models``. These tests close that gap. Every Alembic run here is a
subprocess with ``DATABASE_URL`` set, because that is the only way ``alembic/env.py``
takes its URL -- in-process the ``lru_cache``d settings are already pinned to the
conftest database -- and because it is the exact path the container CMD and an
operator use.
"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.database import Base

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_VERSIONS_DIR = BACKEND_DIR / "alembic" / "versions"
MODEL_TABLES = {"work_items", "sources", "work_evidence", "agent_dispatches"}
BASELINE_TABLES_IN_FK_ORDER = ("work_evidence", "agent_dispatches", "work_items", "sources")

# A bare interpreter is the only honest way to ask what startup does to an empty
# database: ``app.database`` binds its engine at import time, so the running suite
# is already pinned to the conftest database file.
STARTUP_AGAINST_AN_EMPTY_DATABASE = """
import json

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.database import engine
from app.main import app

with TestClient(app) as client:
    client.get("/api/health")

print(json.dumps(sorted(inspect(engine).get_table_names())))
"""


def _run_with_database(database_path: Path, *argv: str) -> subprocess.CompletedProcess:
    """Run ``python argv`` from ``backend/`` with ``DATABASE_URL`` pointed at ``database_path``."""
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database_path}"}
    return subprocess.run(
        [sys.executable, *argv],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=25,
    )


def _upgrade_to_head(database_path: Path) -> None:
    """Apply the whole migration chain to ``database_path`` through the CLI."""
    result = _run_with_database(database_path, "-m", "alembic", "upgrade", "head")
    assert result.returncode == 0, result.stderr


def _build_baseline_database(database_path: Path, *, keep_tables: frozenset[str] | None = None) -> None:
    """Build a pre-Alembic database shaped by revision ``0001``'s frozen schema
    alone -- never by ``app.models`` -- by running ``0001``'s own ``upgrade()``
    through the CLI and then stripping the ``alembic_version`` row it leaves
    behind (a real ``workboard.db`` predating Alembic never had one).

    Building from ``app.models`` instead, as these fixtures used to, ties every
    legacy-database test to today's schema: the moment a later revision adds a
    column to a baseline table, ``0001``'s drift check refuses these fixtures
    for a reason that has nothing to do with the behaviour under test. Building
    from ``0001`` directly keeps that possible.

    ``keep_tables``, when given, additionally drops every baseline table not
    named, to fabricate a database that only ever held part of the baseline.
    """
    result = _run_with_database(database_path, "-m", "alembic", "upgrade", "0001")
    assert result.returncode == 0, result.stderr
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("DROP TABLE alembic_version")
        if keep_tables is not None:
            for table in BASELINE_TABLES_IN_FK_ORDER:
                if table not in keep_tables:
                    connection.execute(f"DROP TABLE {table}")
        connection.commit()
    finally:
        connection.close()


def _insert_baseline_work_item(database_path: Path, *, title: str) -> None:
    """Insert a row using nothing but the ``work_items`` columns revision
    ``0001`` declares, through raw SQL rather than ``app.models`` -- so the
    fixture stays valid even once a later revision has added a column to this
    table that the frozen schema above does not have.
    """
    now = datetime.now(timezone.utc).isoformat()
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO work_items (id, title, status, priority, source_kind, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), title, "pending", "medium", "manual", now, now),
        )
        connection.commit()
    finally:
        connection.close()


def _schema_drift_from_models(database_path: Path) -> list:
    """Autogenerate's diff between the database on disk and ``Base.metadata``."""
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            return compare_metadata(MigrationContext.configure(connection), Base.metadata)
    finally:
        engine.dispose()


def _current_revision(database_path: Path) -> str | None:
    """The revision Alembic has recorded in ``database_path``, or ``None`` if unstamped."""
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def _declared_baseline_columns() -> dict[str, frozenset[str]]:
    """``BASELINE_COLUMNS`` as revision ``0001`` declares it, loaded through Alembic."""
    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    return script.get_revision("0001").module.BASELINE_COLUMNS


def _head_revision() -> str:
    """The chain's head as the CLI reports it, so a new revision cannot go unnoticed here."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.split()[0]


def test_an_empty_database_is_migrated_not_alembic_stamped_and_matches_the_models(tmp_path):
    database_path = tmp_path / "fresh.db"

    _upgrade_to_head(database_path)

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        # Named explicitly so the drift check below cannot pass by comparing an
        # empty database against an empty ``Base.metadata``.
        assert MODEL_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    drift = _schema_drift_from_models(database_path)
    assert drift == [], f"the migration chain has drifted from app.models: {drift}"


def test_application_startup_writes_no_schema_of_its_own(tmp_path):
    database_path = tmp_path / "startup.db"

    result = _run_with_database(database_path, "-c", STARTUP_AGAINST_AN_EMPTY_DATABASE)

    assert result.returncode == 0, result.stderr
    tables = json.loads(result.stdout.strip().splitlines()[-1])
    assert tables == [], "startup still creates schema; migrations must be the only source of DDL"


def test_a_database_predating_alembic_takes_the_alembic_stamp_with_its_rows_intact(tmp_path):
    """The operator path for a ``workboard.db`` left behind by the old ``create_all`` startup.

    Such a database already holds every table the baseline revision creates but has
    no ``alembic_version`` row, and the container CMD runs ``upgrade head`` against
    it unattended. The chain must therefore tolerate the tables being there.
    """
    database_path = tmp_path / "legacy.db"
    _build_baseline_database(database_path)
    _insert_baseline_work_item(database_path, title="predates alembic")

    _upgrade_to_head(database_path)

    assert _current_revision(database_path) == _head_revision()
    assert _schema_drift_from_models(database_path) == []
    connection = sqlite3.connect(database_path)
    try:
        titles = connection.execute("SELECT title FROM work_items").fetchall()
    finally:
        connection.close()
    assert titles == [("predates alembic",)]


def test_the_alembic_stamp_is_refused_when_only_some_baseline_tables_exist(tmp_path):
    """``create_all`` never left a partial schema behind, so one is a sign of damage."""
    database_path = tmp_path / "partial.db"
    _build_baseline_database(database_path, keep_tables=frozenset({"sources"}))

    result = _run_with_database(database_path, "-m", "alembic", "upgrade", "head")

    assert result.returncode != 0, "a partial pre-Alembic schema was silently migrated"
    assert "only ['sources'] of the baseline tables" in result.stderr
    assert _current_revision(database_path) is None


def test_the_alembic_stamp_is_refused_when_a_baseline_table_lost_a_column(tmp_path):
    """Table names alone cannot tell a ``create_all`` database from a damaged one.

    ``create_all`` always produced every baseline column, so a baseline table that is
    present but short of one was altered afterwards. Nothing later in the chain adds
    it back, so recording ``0001`` over it leaves the API querying a column that does
    not exist while ``alembic current`` reports the database is at head.
    """
    database_path = tmp_path / "dropped-column.db"
    _build_baseline_database(database_path)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("ALTER TABLE work_items DROP COLUMN priority")
        connection.commit()
    finally:
        connection.close()

    result = _run_with_database(database_path, "-m", "alembic", "upgrade", "head")

    assert result.returncode != 0, "a drifted pre-Alembic schema was silently stamped"
    assert "work_items is missing ['priority']" in result.stderr
    assert _current_revision(database_path) is None


def test_the_alembic_stamp_is_refused_when_a_baseline_table_gained_a_column(tmp_path):
    """The other half of the mismatch: an added column is equally a sign of damage.

    It also collides head-on with the chain's future -- the revision that adds this
    column for everyone else would fail here with a duplicate -- so the database is
    better stopped now, while the operator is already running ``upgrade``.
    """
    database_path = tmp_path / "added-column.db"
    _build_baseline_database(database_path)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("ALTER TABLE work_items ADD COLUMN nickname VARCHAR(8)")
        connection.commit()
    finally:
        connection.close()

    result = _run_with_database(database_path, "-m", "alembic", "upgrade", "head")

    assert result.returncode != 0, "a drifted pre-Alembic schema was silently stamped"
    assert "work_items has unexpected ['nickname']" in result.stderr
    assert _current_revision(database_path) is None


def test_the_alembic_stamp_check_trusts_exactly_the_columns_revision_0001_creates(tmp_path):
    """``0001`` declares the columns its skip check demands; the two must agree.

    The check reads a declared mapping rather than ``Base.metadata``, which later
    revisions are free to move on. Were that mapping to disagree with the
    ``create_table`` calls beside it, the check would wave through exactly the drift
    it exists to catch.
    """
    database_path = tmp_path / "baseline.db"
    result = _run_with_database(database_path, "-m", "alembic", "upgrade", "0001")
    assert result.returncode == 0, result.stderr

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        created = {
            table: {column["name"] for column in inspector.get_columns(table)}
            for table in MODEL_TABLES
        }
    finally:
        engine.dispose()

    declared = {table: set(columns) for table, columns in _declared_baseline_columns().items()}
    assert created == declared, "the declared baseline columns drifted from the revision's DDL"


_PROOF_REVISION_ID = "t15_proof_added_column"
_PROOF_REVISION_TEMPLATE = '''"""T15 proof: a later revision can add a column to a baseline table.

Written to disk by ``tests/test_migrations.py`` for the lifetime of a single
test and deleted again in its teardown -- never part of the real chain. Exists
to prove that stamping a legacy database no longer breaks the moment a
migration like this one is added for real, now that the fixtures above are
built from revision ``0001``'s frozen schema instead of from ``app.models``.

Revision ID: {revision}
Revises: {down_revision}
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "{revision}"
down_revision: str | None = "{down_revision}"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("nickname", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "nickname")
'''


def test_a_column_added_to_a_baseline_table_by_a_later_revision_still_stamps_a_legacy_database(tmp_path):
    """The proof this task exists for.

    A database built from revision ``0001`` alone -- and never told about a
    column a later revision adds to one of its baseline tables -- must still
    take the stamp and upgrade cleanly, exactly like the operator's real
    ``workboard.db`` would. Before this task, the fixtures above would have
    made this untestable: they were built from ``app.models``, which already
    has the new column the moment a revision adds it, so the frozen baseline
    check would never see a legacy database missing it.
    """
    revision_path = ALEMBIC_VERSIONS_DIR / "t15_proof_added_column.py"
    revision_path.write_text(
        _PROOF_REVISION_TEMPLATE.format(revision=_PROOF_REVISION_ID, down_revision=_head_revision())
    )
    try:
        database_path = tmp_path / "legacy-before-new-column.db"
        _build_baseline_database(database_path)
        connection = sqlite3.connect(database_path)
        try:
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "INSERT INTO sources (id, kind, external_id, observed_at, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid4()), "manual", "manual:predates-new-column", now, now, now),
            )
            connection.commit()
        finally:
            connection.close()

        result = _run_with_database(database_path, "-m", "alembic", "upgrade", "head")

        assert result.returncode == 0, result.stderr
        assert _current_revision(database_path) == _PROOF_REVISION_ID
        connection = sqlite3.connect(database_path)
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(sources)")}
            row = connection.execute("SELECT external_id, nickname FROM sources").fetchone()
        finally:
            connection.close()
        assert "nickname" in columns
        assert row == ("manual:predates-new-column", None)
    finally:
        revision_path.unlink(missing_ok=True)
