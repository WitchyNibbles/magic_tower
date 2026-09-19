"""The database side of measuring the heuristic against real mail.

``persist_signals`` used to write only ``subject``/``excerpt``/``url`` and drop the
fields ``should_promote`` decides from -- ``sender``, ``sender_kind``,
``to_recipients``, ``headers`` -- so a labeled sample built from the database could
never replay anything but the heuristic's default rule. These tests pin that the
fields survive a sync, and that exporting them reads the excerpt back in cleartext
rather than the AES-GCM ciphertext it is stored as (``Source.excerpt`` is
``EncryptedText``).

Of ``headers`` only the names the heuristic reads survive: Graph returns the whole
``internetMessageHeaders`` block, and the rest of it -- routing chains, auth results,
the subject line again -- is not a heuristic input and has no business on disk. The
default fixture therefore carries one header of each kind.

Every fixture here is synthetic; the labeled sample of the owner's real mail this
tool is for stays out of the repository entirely.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, engine
from app.models import Source, SourceKind
from app.services.crypto import generate_encryption_key
from app.services.graph import persist_signals
from app.services.promotion import should_promote
from app.tools import heuristic_export
from app.tools.heuristic_sample import row_from_source, signal_from_row

MARKER = "heuristic-eval-excerpt-marker-2f7c31"
OWNER = "owner@contoso.com"

# What a real ``internetMessageHeaders`` block is mostly made of: routing chains, auth
# results, the subject line again, tenant bookkeeping. No rule reads any of it.
NOISE_HEADERS = {
    "Received": "from mail.vendor.example ([10.0.0.1]) by mail.contoso.com; Fri, 18 Sep 2026 08:30:00 +0000",
    "Authentication-Results": "spf=pass smtp.mailfrom=vendor.example; dkim=pass",
    "Thread-Topic": "Can you review the migration plan?",
    "X-MS-Exchange-Organization-Network-Message-Id": "4f1c0e2a-0000-4a11-9b6e-2b9d0f3c5a71",
}


@pytest.fixture
def permissive_umask():
    """Drop the process umask, so a mode assertion below measures the tool, not the shell."""
    previous = os.umask(0o000)
    yield
    os.umask(previous)


@pytest.fixture
def encryption_key(monkeypatch) -> str:
    from app.config import get_settings

    key = generate_encryption_key()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    return key


def _signal(**overrides: Any) -> dict[str, Any]:
    return {
        "external_id": "outlook:direct-1", "source_kind": "outlook_email",
        "title": "Can you review the migration plan?", "excerpt": MARKER,
        "source_url": "https://outlook.office.com/mail/direct-1",
        "observed_at": "2026-09-18T08:30:00Z",
        "sender": "colleague@contoso.com", "sender_kind": "user",
        "to_recipients": ["owner@contoso.com"], "headers": {"Auto-Submitted": "no", "X-Test": "1"},
        **overrides,
    }


@pytest.mark.usefixtures("encryption_key")
def test_persist_signals_carries_the_heuristic_fields_across() -> None:
    with Session(engine) as session:
        persist_signals(session, [_signal()])

        source = session.query(Source).one()
        context = source.signal_context
        assert context.sender == "colleague@contoso.com"
        assert context.sender_kind == "user"
        assert context.to_recipients == ["owner@contoso.com"]
        assert context.headers == {"Auto-Submitted": "no"}


@pytest.mark.usefixtures("encryption_key")
def test_persist_signals_stores_a_signal_context_with_no_sender() -> None:
    with Session(engine) as session:
        persist_signals(session, [_signal(
            external_id="outlook:no-sender-1",
            sender=None, sender_kind="application", to_recipients=[], headers={},
        )])

        context = session.query(Source).one().signal_context
        assert context.sender is None
        assert context.sender_kind == "application"
        assert context.to_recipients is None
        assert context.headers is None


@pytest.mark.usefixtures("encryption_key")
def test_row_from_source_reads_the_decrypted_excerpt_and_the_full_signal_shape() -> None:
    with Session(engine) as session:
        persist_signals(session, [_signal()])
        source = session.query(Source).one()

        row = row_from_source(source)

        assert row == {
            "id": "outlook:direct-1", "source_kind": "outlook_email",
            "subject": "Can you review the migration plan?", "excerpt": MARKER,
            "sender": "colleague@contoso.com", "sender_kind": "user",
            "to_recipients": ["owner@contoso.com"], "headers": {"Auto-Submitted": "no"},
            "url": "https://outlook.office.com/mail/direct-1",
            "observed_at": row["observed_at"], "label": None,
        }


def test_row_from_source_falls_back_to_empty_heuristic_fields_with_no_signal_context() -> None:
    """A ``Source`` a sync wrote before this feature shipped has no context row yet."""
    source = Source(kind=SourceKind.manual, external_id="manual:1", subject="hand-entered")

    row = row_from_source(source)

    assert row["sender"] is None
    assert row["sender_kind"] is None
    assert row["to_recipients"] == []
    assert row["headers"] == {}
    assert row["label"] is None


@pytest.mark.usefixtures("encryption_key")
def test_export_rows_reads_the_excerpt_in_cleartext_from_a_database_file(tmp_path) -> None:
    """Read through the ORM, not the raw file, so ``EncryptedText`` decrypts it -- and
    prove the file itself never holds the excerpt in cleartext, so this is really
    exercising the decrypt path and not a coincidence of an in-memory database."""
    database_path = tmp_path / "sample-source.db"
    file_engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(bind=file_engine)
    try:
        with Session(file_engine) as session:
            persist_signals(session, [_signal()])
        assert MARKER.encode() not in database_path.read_bytes(), "the fixture failed to encrypt the excerpt"

        with Session(file_engine) as session:
            rows = heuristic_export.export_rows(session)
    finally:
        file_engine.dispose()

    assert len(rows) == 1
    assert rows[0]["excerpt"] == MARKER
    assert rows[0]["label"] is None


@pytest.mark.usefixtures("encryption_key")
def test_main_writes_one_unlabeled_row_per_source_to_the_given_path(tmp_path) -> None:
    output_path = tmp_path / "nested" / "labeled-sample.json"
    with Session(engine) as session:
        persist_signals(session, [_signal(), _signal(external_id="outlook:direct-2", title="second")])

    exit_code = heuristic_export.main(["--output", str(output_path)])

    assert exit_code == 0
    written = json.loads(output_path.read_text())
    assert len(written) == 2
    assert {row["label"] for row in written} == {None}
    assert {row["id"] for row in written} == {"outlook:direct-1", "outlook:direct-2"}


def test_default_sample_path_is_under_the_owners_home_directory_and_gitignored() -> None:
    from app.tools.heuristic_sample import DEFAULT_SAMPLE_PATH

    assert DEFAULT_SAMPLE_PATH == Path.home() / ".magic-tower" / "labeled-sample.json"


# --- what lands on disk ------------------------------------------------------


@pytest.mark.usefixtures("encryption_key")
def test_persist_signals_stores_only_the_headers_the_heuristic_reads() -> None:
    with Session(engine) as session:
        persist_signals(session, [_signal(headers={**NOISE_HEADERS, "List-Id": "<digest.vendor.example>"})])

        assert session.query(Source).one().signal_context.headers == {"List-Id": "<digest.vendor.example>"}


@pytest.mark.usefixtures("encryption_key")
def test_persist_signals_stores_no_headers_at_all_when_none_of_them_is_read() -> None:
    """A direct message from a person carries no bulk marker, so none of its header block is kept."""
    with Session(engine) as session:
        persist_signals(session, [_signal(headers=NOISE_HEADERS)])

        assert session.query(Source).one().signal_context.headers is None


@pytest.mark.usefixtures("encryption_key")
def test_an_exported_row_still_decides_the_way_the_sync_did() -> None:
    """The allowlist has to keep every name the heuristic reads: a digest the live sync
    skipped must be skipped again when its exported row is replayed."""
    digest = _signal(external_id="outlook:digest-1", sender="updates@vendor.example",
                     headers={**NOISE_HEADERS, "List-Unsubscribe": "<https://vendor.example/u>"})
    assert should_promote(digest, [OWNER]) is False, "the fixture is not a message the sync would skip"

    with Session(engine) as session:
        persist_signals(session, [digest])
        row = row_from_source(session.query(Source).one())

    assert should_promote(signal_from_row(row), [OWNER]) is False


# --- main(): a database it cannot read, and a file only its owner can --------


def _bound_to(monkeypatch, database_path: Path) -> None:
    """Point the tool at ``database_path``, the way ``DATABASE_URL`` points it at one."""
    session_factory = sessionmaker(bind=create_engine(f"sqlite:///{database_path}"))
    monkeypatch.setattr(heuristic_export, "SessionLocal", session_factory)


def test_main_names_the_remedy_when_the_database_cannot_be_opened(tmp_path, monkeypatch, capsys) -> None:
    """Run without ``DATABASE_URL``, the tool opens the Docker path ``/data/workboard.db``,
    which a checkout cannot open. The owner needs the remedy, not a SQLAlchemy traceback."""
    _bound_to(monkeypatch, tmp_path / "no-such-directory" / "workboard.db")
    output_path = tmp_path / "labeled-sample.json"

    exit_code = heuristic_export.main(["--output", str(output_path)])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "DATABASE_URL" in err
    assert "alembic upgrade head" in err
    assert "Traceback" not in err
    assert not output_path.exists(), "a failed export must not leave a half-written sample behind"


def test_main_names_the_remedy_when_the_database_has_no_tables_yet(tmp_path, monkeypatch, capsys) -> None:
    """A database file that exists but was never migrated fails the same way, not differently."""
    _bound_to(monkeypatch, tmp_path / "unmigrated.db")
    output_path = tmp_path / "labeled-sample.json"

    exit_code = heuristic_export.main(["--output", str(output_path)])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "alembic upgrade head" in err
    assert "Traceback" not in err


def test_main_names_the_remedy_for_a_non_sqlite_database_error_too(tmp_path, monkeypatch, capsys) -> None:
    """The remedy is owed to every database the tool can be pointed at, not only SQLite.

    An unmigrated Postgres raises ``ProgrammingError`` ("relation ... does not
    exist") where SQLite raises ``OperationalError``, and ``DATABASE_URL`` is the
    owner's to set. Catching only the SQLite spelling hands them a traceback in the
    one case the message was written for.
    """
    _bound_to(monkeypatch, tmp_path / "workboard.db")

    def _unmigrated_postgres(db: Session) -> list[dict]:
        raise ProgrammingError("SELECT sources.id FROM sources", {},
                               Exception('relation "sources" does not exist'))

    monkeypatch.setattr(heuristic_export, "export_rows", _unmigrated_postgres)
    output_path = tmp_path / "labeled-sample.json"

    exit_code = heuristic_export.main(["--output", str(output_path)])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "DATABASE_URL" in err
    assert "alembic upgrade head" in err
    assert "Traceback" not in err


@pytest.mark.usefixtures("encryption_key", "permissive_umask")
def test_main_writes_a_sample_only_its_owner_can_read(tmp_path) -> None:
    """The file is the owner's real mail; on a shared or managed PC it must not be world-readable."""
    output_path = tmp_path / "nested" / "labeled-sample.json"
    with Session(engine) as session:
        persist_signals(session, [_signal()])

    assert heuristic_export.main(["--output", str(output_path)]) == 0

    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(output_path.parent.stat().st_mode) == 0o700


@pytest.mark.usefixtures("encryption_key", "permissive_umask")
def test_main_tightens_a_sample_an_earlier_run_left_world_readable(tmp_path) -> None:
    output_path = tmp_path / "labeled-sample.json"
    output_path.write_text("[]")
    os.chmod(output_path, 0o644)

    assert heuristic_export.main(["--output", str(output_path)]) == 0

    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
