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
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.database import Base
from app.models import SourceKind, WorkItem

BACKEND_DIR = Path(__file__).resolve().parents[1]
MODEL_TABLES = {"work_items", "sources", "work_evidence", "agent_dispatches"}

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
    legacy_engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(bind=legacy_engine)
    with Session(legacy_engine) as session:
        session.add(WorkItem(title="predates alembic", source_kind=SourceKind.manual))
        session.commit()
    legacy_engine.dispose()

    _upgrade_to_head(database_path)

    assert _current_revision(database_path) == _head_revision()
    assert _schema_drift_from_models(database_path) == []
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with Session(engine) as session:
            surviving = session.query(WorkItem).one()
    finally:
        engine.dispose()
    assert surviving.title == "predates alembic"


def test_the_alembic_stamp_is_refused_when_only_some_baseline_tables_exist(tmp_path):
    """``create_all`` never left a partial schema behind, so one is a sign of damage."""
    database_path = tmp_path / "partial.db"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.tables["sources"].create(engine)
    engine.dispose()

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
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
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
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
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
