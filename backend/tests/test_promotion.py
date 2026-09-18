"""The heuristic that turns normalized signals into triage work items.

``persist_signals`` only ever wrote ``Source`` rows, so a sync left the queue the
GUI renders empty. Promotion closes that gap, and these tests pin the two halves
of it: ``should_promote`` as a pure decision over a signal dict, and
``promote_signals`` as the idempotent writer that carries the message excerpt into
``WorkEvidence``.

Every clause of every rule has a test that fails when that clause alone is deleted.
The fixtures that exercise the header rule therefore use a sender the sender rule
would let through -- otherwise the sender rule would shadow the header rule and a
deleted header clause would never redden anything.

Every fixture here is synthetic. The labeled sample of the owner's real mail that
the heuristic is ultimately measured against stays out of this repository, so
nothing below is evidence of accuracy -- only of the rules being the rules.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import Base, engine
from app.integrations.graph import GraphClient
from app.models import SourceKind, WorkItem, WorkStatus
from app.services.crypto import EncryptedTokenStore, generate_encryption_key
from app.services.promotion import EXCERPT_LIMIT, TITLE_LIMIT, promote_signals, should_promote
from app.services.sync import sync

BACKEND_DIR = Path(__file__).resolve().parents[1]
MAILBOX = "owner@contoso.com"
# The signed-in account's ``userPrincipalName``; tenants with alias domains hand out
# a different address for mail, so the owner is known by both.
PRINCIPAL = "owner@contoso.onmicrosoft.com"
OWNER = (PRINCIPAL, MAILBOX)
# An address a real person also writes from; only the header rule can reject mail from it.
HUMAN_LOOKING_SENDER = "updates@vendor.example"

# Distinctive enough that finding it in a database file cannot be a coincidence.
MARKER = "promoted-excerpt-marker-5d0b74"


@pytest.fixture
def encryption_key(monkeypatch) -> str:
    """Configure ``APP_ENCRYPTION_KEY`` for this test and for subprocesses it starts."""
    key = generate_encryption_key()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    return key


def _run_alembic(database_path: Path, *argv: str) -> subprocess.CompletedProcess:
    """``alembic/env.py`` takes its URL from the environment and nowhere else."""
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database_path}"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *argv],
        cwd=BACKEND_DIR, env=environment, capture_output=True, text=True, timeout=25,
    )


def _stored_evidence_excerpt(database_path: Path) -> str | None:
    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute("SELECT excerpt FROM work_evidence").fetchone()
    finally:
        connection.close()
    return None if row is None else row[0]


def _write_plaintext_evidence_excerpt(database_path: Path, excerpt: str) -> None:
    """Leave behind exactly what a pre-encryption release wrote: a cleartext column."""
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("UPDATE work_evidence SET excerpt = ?", (excerpt,))
        connection.commit()
    finally:
        connection.close()


def _email(**overrides: Any) -> dict[str, Any]:
    """A normalized inbox message a colleague sent to the owner, by default."""
    return {
        "external_id": "outlook:direct-1",
        "source_kind": "outlook_email",
        "title": "Can you review the migration plan?",
        "excerpt": MARKER,
        "source_url": "https://outlook.office.com/mail/direct-1",
        "observed_at": "2026-09-18T08:30:00Z",
        "sender": "colleague@contoso.com",
        "sender_kind": "user",
        "to_recipients": [MAILBOX],
        "headers": {},
        **overrides,
    }


def _newsletter(**overrides: Any) -> dict[str, Any]:
    """Bulk mail that must never reach triage, recognizable by its sender alone."""
    return _email(external_id="outlook:newsletter-1", title="Your weekly product digest",
                  sender="newsletter@vendor.example", **overrides)


def _bulk_mailing(**overrides: Any) -> dict[str, Any]:
    """Bulk mail recognizable only by its headers; the sender could be a person."""
    return _email(external_id="outlook:bulk-1", title="Your weekly product digest",
                  sender=HUMAN_LOOKING_SENDER, **overrides)


def _teams(**overrides: Any) -> dict[str, Any]:
    return {
        "external_id": "teams:direct-1",
        "source_kind": "teams_message",
        "title": "Release window",
        "excerpt": "are you free to cut the release today?",
        "source_url": "https://teams.microsoft.com/l/message/1",
        "observed_at": "2026-09-18T09:00:00Z",
        "sender": None,
        "sender_kind": "user",
        "to_recipients": [],
        "headers": {},
        **overrides,
    }


def test_promotion_accepts_mail_addressed_directly_to_the_owner() -> None:
    assert should_promote(_email(), OWNER) is True


def test_promotion_skips_a_newsletter_sender_that_carries_no_list_headers() -> None:
    assert should_promote(_newsletter(), OWNER) is False


@pytest.mark.parametrize("sender", [
    "no-reply@service.example", "Do-Not-Reply@service.example", "auto_reply@service.example",
    "MAILER-DAEMON@service.example", "postmaster@service.example", "bounce+abc123@service.example",
    "marketing@vendor.example", "campaign@vendor.example", "mailing-list@vendor.example",
    "noreply-github@service.example",
])
def test_promotion_skips_each_automated_sender_marker_however_it_is_punctuated(sender: str) -> None:
    assert should_promote(_email(sender=sender), OWNER) is False


def test_promotion_ignores_automation_markers_in_the_sender_domain() -> None:
    """A person at a marketing agency is still a person."""
    assert should_promote(_email(sender="alice@marketing-agency.example"), OWNER) is True


@pytest.mark.parametrize("header", ["List-Unsubscribe", "List-Id", "List-Post", "X-Campaign-Id"])
def test_promotion_skips_a_human_looking_sender_whose_only_marker_is_a_list_header(header: str) -> None:
    assert should_promote(_bulk_mailing(headers={header: "<https://vendor.example/u>"}), OWNER) is False


@pytest.mark.parametrize("precedence", ["Bulk", "list", "junk"])
def test_promotion_skips_a_human_looking_sender_whose_only_marker_is_a_precedence_header(precedence: str) -> None:
    assert should_promote(_bulk_mailing(headers={"Precedence": precedence}), OWNER) is False


def test_promotion_accepts_mail_whose_precedence_is_not_a_bulk_value() -> None:
    assert should_promote(_email(headers={"Precedence": "first-class"}), OWNER) is True


@pytest.mark.parametrize("auto_submitted", ["auto-generated", "Auto-Replied"])
def test_promotion_skips_a_human_looking_sender_whose_only_marker_is_auto_submitted(auto_submitted: str) -> None:
    assert should_promote(_bulk_mailing(headers={"Auto-Submitted": auto_submitted}), OWNER) is False


def test_promotion_accepts_mail_that_declares_auto_submitted_no() -> None:
    """``Auto-Submitted: no`` is the RFC 3834 way of saying a person sent it."""
    assert should_promote(_email(headers={"Auto-Submitted": "no"}), OWNER) is True


def test_promotion_skips_mail_the_owner_was_only_copied_on() -> None:
    """Cc is an FYI; the queue is for what was addressed to the owner."""
    assert should_promote(_email(to_recipients=["someone-else@contoso.com"]), OWNER) is False


def test_promotion_accepts_mail_addressed_to_the_owner_in_any_letter_case() -> None:
    """Neither side of the comparison is trusted to arrive in a canonical case."""
    assert should_promote(_email(to_recipients=["Owner@Contoso.COM"]), OWNER) is True
    assert should_promote(_email(), ("Owner@Contoso.COM",)) is True


def test_promotion_accepts_mail_addressed_to_the_owners_principal_name() -> None:
    """Either of the owner's addresses counts; alias-domain tenants use both."""
    assert should_promote(_email(to_recipients=[PRINCIPAL]), OWNER) is True


def test_promotion_does_not_reject_on_recipients_when_the_owner_address_is_unknown() -> None:
    """A missing profile costs the rule, not the queue: nothing is silently dropped."""
    assert should_promote(_email(to_recipients=["someone-else@contoso.com"]), ()) is True


def test_promotion_accepts_a_teams_message_from_a_person() -> None:
    """Teams carries no To list, so the recipient rule must not quietly reject it."""
    assert should_promote(_teams(), OWNER) is True


def test_promotion_skips_a_teams_message_posted_by_an_application() -> None:
    assert should_promote(_teams(sender_kind="application"), OWNER) is False


@pytest.mark.usefixtures("encryption_key")
def test_promotion_writes_one_pending_work_item_per_actionable_signal() -> None:
    with Session(engine) as session:
        created = promote_signals(session, [_email(), _newsletter(), _bulk_mailing(headers={"List-Id": "x"}), _teams()], OWNER)

        assert created == 2
        items = session.query(WorkItem).order_by(WorkItem.source_external_id).all()
        assert [item.source_external_id for item in items] == ["outlook:direct-1", "teams:direct-1"]
        assert {item.status for item in items} == {WorkStatus.pending}
        assert {item.source_kind for item in items} == {SourceKind.outlook_email, SourceKind.teams_message}


@pytest.mark.usefixtures("encryption_key")
def test_promotion_carries_the_excerpt_across_into_work_evidence() -> None:
    with Session(engine) as session:
        promote_signals(session, [_email()], OWNER)

        evidence = session.query(WorkItem).one().evidence
        assert [row.excerpt for row in evidence] == [MARKER]
        assert [row.external_id for row in evidence] == ["outlook:direct-1"]
        assert evidence[0].observed_at.isoformat().startswith("2026-09-18T08:30:00")


@pytest.mark.usefixtures("encryption_key")
def test_promotion_is_idempotent() -> None:
    """``work_items.source_external_id`` is unique, so a second sync must not raise.

    Re-running is the normal path, not an edge case: every sync re-reads the same
    inbox window and hands the same signals to promotion again.
    """
    with Session(engine) as session:
        first = promote_signals(session, [_email()], OWNER)
        second = promote_signals(session, [_email()], OWNER)

        assert (first, second) == (1, 0)
        assert session.query(WorkItem).count() == 1
        assert len(session.query(WorkItem).one().evidence) == 1


@pytest.mark.usefixtures("encryption_key")
@pytest.mark.parametrize("source_url", ["javascript:alert(1)", "ftp://files.example/report", "https://x.example/" + "a" * 2100, None])
def test_promotion_drops_a_source_url_that_is_not_a_usable_http_link(source_url: str | None) -> None:
    """``WorkItemCreate`` would reject these outright and abort the whole sync."""
    with Session(engine) as session:
        assert promote_signals(session, [_email(source_url=source_url)], OWNER) == 1
        assert session.query(WorkItem).one().source_url is None


@pytest.mark.usefixtures("encryption_key")
def test_promotion_falls_back_to_a_placeholder_title_for_a_blank_subject() -> None:
    with Session(engine) as session:
        assert promote_signals(session, [_email(title="   ")], OWNER) == 1
        assert session.query(WorkItem).one().title == "(no subject)"


@pytest.mark.usefixtures("encryption_key")
def test_promotion_bounds_the_title_and_excerpt_it_stores() -> None:
    """A Teams body can run to any length; the schema would reject it, not truncate it."""
    with Session(engine) as session:
        assert promote_signals(session, [_teams(title="t" * (TITLE_LIMIT + 1), excerpt="x" * 10_001)], OWNER) == 1
        item = session.query(WorkItem).one()
        assert len(item.title) == TITLE_LIMIT
        assert len(item.evidence[0].excerpt) == EXCERPT_LIMIT


@pytest.mark.usefixtures("encryption_key")
def test_promotion_does_not_leave_the_carried_excerpt_on_disk_in_cleartext(tmp_path) -> None:
    """The excerpt moves into a second column, so it must be sealed in that one too.

    Asserting through the ORM would only prove the round trip -- the part that keeps
    working when nothing is encrypted -- so this reads the raw database file.
    """
    database_path = tmp_path / "promoted.db"
    file_engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(bind=file_engine)
    try:
        with Session(file_engine) as session:
            assert promote_signals(session, [_email()], OWNER) == 1
        with Session(file_engine) as session:
            assert session.query(WorkItem).one().evidence[0].excerpt == MARKER
    finally:
        file_engine.dispose()

    assert MARKER.encode() not in database_path.read_bytes(), "the carried excerpt is still cleartext"


@pytest.fixture
def evidence_database(encryption_key, tmp_path) -> Path:
    """A database holding one evidence excerpt written the way a past release wrote it.

    Evidence excerpts predate this encryption, and ``POST /api/work-items/{id}/evidence``
    has been writing them in cleartext all along, so the migration -- not just the
    column type -- is what gets an existing installation out of cleartext.
    """
    database_path = tmp_path / "legacy-evidence.db"
    file_engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(bind=file_engine)
    try:
        with Session(file_engine) as session:
            promote_signals(session, [_email()], OWNER)
    finally:
        file_engine.dispose()
    _write_plaintext_evidence_excerpt(database_path, MARKER)
    assert MARKER.encode() in database_path.read_bytes(), "the fixture failed to write cleartext"
    return database_path


def test_promotion_migration_encrypts_evidence_excerpts_written_before_the_change(evidence_database) -> None:
    result = _run_alembic(evidence_database, "upgrade", "head")

    assert result.returncode == 0, result.stderr
    assert MARKER.encode() not in evidence_database.read_bytes(), "a pre-existing row was left in cleartext"
    file_engine = create_engine(f"sqlite:///{evidence_database}")
    try:
        with Session(file_engine) as session:
            assert session.query(WorkItem).one().evidence[0].excerpt == MARKER
    finally:
        file_engine.dispose()


def test_promotion_migration_leaves_an_already_encrypted_evidence_excerpt_alone(evidence_database) -> None:
    """Re-running must not seal a ciphertext inside a second ciphertext.

    ``stamp 0002`` rewinds only the recorded revision, so the following ``upgrade``
    replays the data migration over a row it has already converted -- the situation
    an operator creates by restoring a database and re-running the chain.
    """
    assert _run_alembic(evidence_database, "upgrade", "head").returncode == 0
    once = _stored_evidence_excerpt(evidence_database)

    assert _run_alembic(evidence_database, "stamp", "0002").returncode == 0
    second = _run_alembic(evidence_database, "upgrade", "head")

    assert second.returncode == 0, second.stderr
    assert _stored_evidence_excerpt(evidence_database) == once, "the migration re-encrypted a sealed excerpt"


def _selected(url: str, row: dict[str, Any]) -> dict[str, Any]:
    """Only the ``$select``ed fields, as Graph answers; what the client forgets to ask for, it never sees."""
    fields = parse_qs(urlparse(url).query)["$select"][0].split(",")
    return {field: row[field] for field in fields if field in row}


PROFILE = {"id": "expected-oid", "userPrincipalName": PRINCIPAL, "mail": MAILBOX}
INBOX = [
    {
        "id": "direct", "subject": "Please approve the change", "bodyPreview": MARKER,
        "webLink": "https://outlook.office.com/mail/direct", "receivedDateTime": "2026-09-18T08:30:00Z",
        "from": {"emailAddress": {"address": "colleague@contoso.com"}},
        "toRecipients": [{"emailAddress": {"address": MAILBOX}}],
        "internetMessageHeaders": [],
    },
    {
        "id": "bulk", "subject": "Weekly digest", "bodyPreview": "unsubscribe below",
        "from": {"emailAddress": {"address": HUMAN_LOOKING_SENDER}},
        "toRecipients": [{"emailAddress": {"address": MAILBOX}}],
        "internetMessageHeaders": [{"name": "List-Unsubscribe", "value": "<https://vendor.example/u>"}],
    },
]


def test_promotion_fills_the_queue_during_a_graph_sync(encryption_key, tmp_path) -> None:
    """The missing link end to end: a sync leaves triage populated, not empty.

    The owner is addressed by ``mail``, not ``userPrincipalName``, and the bulk
    message is only recognizable by a header -- so the sync has to ask Graph for
    both, or the direct message is dropped and the digest is promoted.
    """
    settings = Settings(
        microsoft_tenant_id="tenant", microsoft_client_id="client", microsoft_client_secret="secret",
        microsoft_target_user_id="expected-oid", app_encryption_key=encryption_key,
        token_store_path=tmp_path / "tokens",
    )
    EncryptedTokenStore(settings.token_store_path, encryption_key).save({"access_token": "token"})

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        if "/me?$select=" in url:
            return _selected(url, PROFILE)
        if "/me/mailFolders/" in url:
            return {"value": [_selected(url, row) for row in INBOX]}
        if "/me/chats" in url:
            return {"value": []}
        raise AssertionError(url)

    with Session(engine) as session:
        result = sync(settings, session, client=GraphClient("token", transport))

        assert result["new_sources"] == 2, "both signals must still be stored as sources"
        assert result["new_work_items"] == 1
        item = session.query(WorkItem).one()
        assert item.source_external_id == "outlook:direct"
        assert item.evidence[0].excerpt == MARKER
