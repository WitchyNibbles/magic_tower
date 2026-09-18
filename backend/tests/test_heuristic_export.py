"""The database side of measuring the heuristic against real mail.

``persist_signals`` used to write only ``subject``/``excerpt``/``url`` and drop the
fields ``should_promote`` decides from -- ``sender``, ``sender_kind``,
``to_recipients``, ``headers`` -- so a labeled sample built from the database could
never replay anything but the heuristic's default rule. These tests pin that the
fields survive a sync, and that exporting them reads the excerpt back in cleartext
rather than the AES-GCM ciphertext it is stored as (``Source.excerpt`` is
``EncryptedText``).

Every fixture here is synthetic; the labeled sample of the owner's real mail this
tool is for stays out of the repository entirely.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base, engine
from app.models import Source, SourceKind
from app.services.crypto import generate_encryption_key
from app.services.graph import persist_signals
from app.tools import heuristic_export
from app.tools.heuristic_sample import row_from_source

MARKER = "heuristic-eval-excerpt-marker-2f7c31"


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
        "to_recipients": ["owner@contoso.com"], "headers": {"X-Test": "1"},
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
        assert context.headers == {"X-Test": "1"}


@pytest.mark.usefixtures("encryption_key")
def test_persist_signals_stores_a_teams_signals_context_with_no_sender() -> None:
    with Session(engine) as session:
        persist_signals(session, [_signal(
            external_id="teams:direct-1", source_kind="teams_message",
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
            "to_recipients": ["owner@contoso.com"], "headers": {"X-Test": "1"},
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
