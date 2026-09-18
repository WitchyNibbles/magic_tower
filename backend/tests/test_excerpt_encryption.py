"""Guards that message content never reaches the database file in cleartext.

``Source.excerpt`` carries up to 2000 characters of real mail and Teams bodies, so
these tests work against a real on-disk SQLite file and read its raw bytes: an
assertion against the ORM would only prove the round trip, which is exactly the
part that still works when nothing is encrypted. The Alembic runs are subprocesses
with ``DATABASE_URL`` in the environment for the same reason ``test_migrations.py``
uses them -- ``alembic/env.py`` takes its URL no other way.
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base
from app.main import app
from app.models import Source, SourceKind
from app.services.crypto import generate_encryption_key

BACKEND_DIR = Path(__file__).resolve().parents[1]
TOKEN_HEADERS = {"Authorization": "Bearer test-local-agent-token"}

# Distinctive enough that finding it in a database file cannot be a coincidence.
MARKER = "quarterly-forecast-marker-8f3a1c"


@pytest.fixture
def encryption_key(monkeypatch) -> str:
    """Configure ``APP_ENCRYPTION_KEY`` for this test and for subprocesses it starts."""
    key = generate_encryption_key()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    return key


def _database_with_schema(path: Path):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine)
    return engine


def _run_alembic(database_path: Path, *argv: str) -> subprocess.CompletedProcess:
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database_path}"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *argv],
        cwd=BACKEND_DIR, env=environment, capture_output=True, text=True, timeout=25,
    )


def _write_plaintext_excerpt(database_path: Path, external_id: str, excerpt: str) -> None:
    """Leave behind exactly what a pre-encryption release wrote: a cleartext column."""
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("UPDATE sources SET excerpt = ? WHERE external_id = ?", (excerpt, external_id))
        connection.commit()
    finally:
        connection.close()


def _stored_excerpt(database_path: Path, external_id: str) -> str | None:
    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute("SELECT excerpt FROM sources WHERE external_id = ?", (external_id,)).fetchone()
    finally:
        connection.close()
    return None if row is None else row[0]


@pytest.mark.usefixtures("encryption_key")
def test_source_excerpt_is_encrypted_at_rest(tmp_path):
    """AC5: the marker a sync would persist must not be findable in the database file."""
    database_path = tmp_path / "at-rest.db"
    engine = _database_with_schema(database_path)
    try:
        with Session(engine) as session:
            session.add(Source(kind=SourceKind.outlook_email, external_id="outlook:at-rest", excerpt=MARKER))
            session.commit()
    finally:
        engine.dispose()

    assert MARKER.encode() not in database_path.read_bytes(), "message content is still on disk in cleartext"


@pytest.mark.usefixtures("encryption_key")
def test_a_source_excerpt_is_decrypted_on_read(tmp_path):
    database_path = tmp_path / "round-trip.db"
    engine = _database_with_schema(database_path)
    try:
        with Session(engine) as session:
            session.add(Source(kind=SourceKind.teams_message, external_id="teams:round-trip", excerpt=MARKER))
            session.commit()
        with Session(engine) as session:
            stored = session.query(Source).one()
            assert stored.excerpt == MARKER
    finally:
        engine.dispose()


@pytest.mark.usefixtures("encryption_key")
def test_the_sources_api_still_serves_excerpts_in_cleartext():
    """The evidence blockquote path: what the GUI reads must survive encryption."""
    with TestClient(app) as client:
        created = client.post(
            "/api/sources",
            json={"kind": "outlook_email", "external_id": "outlook:api", "excerpt": MARKER},
            headers=TOKEN_HEADERS,
        )
        assert created.status_code == 201, created.text
        assert created.json()["excerpt"] == MARKER
        listed = client.get("/api/sources", headers=TOKEN_HEADERS)
        assert listed.status_code == 200
        assert [source["excerpt"] for source in listed.json()["items"]] == [MARKER]


def test_storing_an_excerpt_without_an_encryption_key_fails_closed(monkeypatch):
    """No key must mean no write, not a cleartext write -- the 503 convention."""
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/sources",
            json={"kind": "outlook_email", "external_id": "outlook:keyless", "excerpt": MARKER},
            headers=TOKEN_HEADERS,
        )
    assert response.status_code == 503, response.text
    assert "APP_ENCRYPTION_KEY" in response.json()["detail"]


@pytest.mark.usefixtures("encryption_key")
def test_an_excerpt_that_cannot_be_decrypted_is_never_served(monkeypatch):
    """A restored backup paired with the wrong key must 503, not leak or invent content."""
    with TestClient(app) as client:
        created = client.post(
            "/api/sources",
            json={"kind": "outlook_email", "external_id": "outlook:wrong-key", "excerpt": MARKER},
            headers=TOKEN_HEADERS,
        )
        assert created.status_code == 201, created.text
        monkeypatch.setenv("APP_ENCRYPTION_KEY", generate_encryption_key())
        get_settings.cache_clear()
        response = client.get("/api/sources", headers=TOKEN_HEADERS)

    assert response.status_code == 503, response.text
    assert MARKER not in response.text


@pytest.mark.usefixtures("encryption_key")
def test_the_data_migration_encrypts_excerpts_written_before_the_change(tmp_path):
    database_path = tmp_path / "legacy.db"
    engine = _database_with_schema(database_path)
    try:
        with Session(engine) as session:
            session.add(Source(kind=SourceKind.outlook_email, external_id="outlook:legacy", excerpt=None))
            session.commit()
    finally:
        engine.dispose()
    _write_plaintext_excerpt(database_path, "outlook:legacy", MARKER)
    assert MARKER.encode() in database_path.read_bytes(), "the fixture failed to write cleartext"

    result = _run_alembic(database_path, "upgrade", "head")

    assert result.returncode == 0, result.stderr
    assert MARKER.encode() not in database_path.read_bytes(), "a pre-existing row was left in cleartext"
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with Session(engine) as session:
            assert session.query(Source).one().excerpt == MARKER
    finally:
        engine.dispose()


@pytest.mark.usefixtures("encryption_key")
def test_the_data_migration_leaves_an_already_encrypted_excerpt_alone_when_it_runs_again(tmp_path):
    """Re-running must not seal a ciphertext inside a second ciphertext.

    ``stamp 0001`` rewinds only the recorded revision, so the following ``upgrade``
    replays the data migration over rows it has already converted -- the situation
    an operator creates by restoring a database and re-running the chain.
    """
    database_path = tmp_path / "rerun.db"
    engine = _database_with_schema(database_path)
    try:
        with Session(engine) as session:
            session.add(Source(kind=SourceKind.outlook_email, external_id="outlook:rerun", excerpt=None))
            session.commit()
    finally:
        engine.dispose()
    _write_plaintext_excerpt(database_path, "outlook:rerun", MARKER)
    assert _run_alembic(database_path, "upgrade", "head").returncode == 0
    once = _stored_excerpt(database_path, "outlook:rerun")

    assert _run_alembic(database_path, "stamp", "0001").returncode == 0
    second = _run_alembic(database_path, "upgrade", "head")

    assert second.returncode == 0, second.stderr
    assert _stored_excerpt(database_path, "outlook:rerun") == once, "the migration re-encrypted a sealed excerpt"
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with Session(engine) as session:
            assert session.query(Source).one().excerpt == MARKER
    finally:
        engine.dispose()
