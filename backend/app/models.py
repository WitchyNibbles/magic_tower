import enum
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .services.field_crypto import EncryptedText


def _utc_now() -> datetime:
    """Timezone-aware UTC now; ``_utc_now()`` is deprecated and returns a naive value."""
    return datetime.now(UTC)


class WorkStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    blocked = "blocked"
    done = "done"
    # A hand correction (T08): the heuristic promoted this in error, but the row
    # -- and its evidence -- stays, unlike ``DELETE /api/work-items/{id}``. Kept
    # distinct from a hard delete on purpose: ``promote_signals`` and the T06
    # backfill both key their idempotency off the row existing at all, so this
    # status only has to sit there, not be read anywhere, to stop either from
    # promoting the same source again.
    dismissed = "dismissed"


class WorkPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class SourceKind(str, enum.Enum):
    outlook_email = "outlook_email"
    manual = "manual"
    # No Alembic revision needed: ``sources.kind``/``work_items.source_kind`` are
    # ``VARCHAR(13)`` with no CHECK (``alembic/versions/0001_initial_schema.py``);
    # ``freshservice`` is 12 characters. Spelled identically here, in
    # ``app/services/jira_sync.py``, ``app/services/freshservice_sync.py`` and in
    # docs, or ``scripts/deaddocs_check.py`` reads it as a retired connector.
    jira = "jira"
    freshservice = "freshservice"


class WorkItem(Base):
    """Durable work item, sourced from Graph or created by a user/agent."""

    __tablename__ = "work_items"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[WorkStatus] = mapped_column(Enum(WorkStatus), default=WorkStatus.pending, index=True)
    priority: Mapped[WorkPriority] = mapped_column(Enum(WorkPriority), default=WorkPriority.medium)
    source_kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind), index=True)
    source_external_id: Mapped[str | None] = mapped_column(String(512), unique=True, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # Indexed: ``GET /api/work-items?assigned_agent=`` filters on it (AC9's carried
    # gap -- ``0006`` indexed status/source_kind/updated_at but missed this column).
    assigned_agent: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, index=True)

    evidence: Mapped[list["WorkEvidence"]] = relationship(back_populates="work_item", cascade="all, delete-orphan")
    dispatches: Mapped[list["AgentDispatch"]] = relationship(back_populates="work_item", cascade="all, delete-orphan")


class Source(Base):
    """Normalized message/source metadata; the message body is stored encrypted."""

    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind), index=True)
    external_id: Mapped[str] = mapped_column(String(512), unique=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # Real mail bodies land here, so the column -- and only the column -- holds
    # ciphertext; readers still see cleartext. Stays ``TEXT`` on disk.
    excerpt: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)

    signal_context: Mapped["SourceSignalContext | None"] = relationship(back_populates="source", uselist=False, cascade="all, delete-orphan")


class SourceSignalContext(Base):
    """The rest of the signal ``should_promote`` decides from, kept for later replay.

    ``sender``, ``sender_kind``, ``to_recipients`` and ``headers`` are not part of
    ``sources`` -- a legacy pre-Alembic database is recognised by that table's exact
    column set (``alembic/versions/0001_initial_schema.py``), so a field the queue
    itself never renders belongs in its own table instead of growing that one.
    Without this, a labeled-sample export built from the database alone could only
    ever replay the heuristic's last rule: every other rule reads one of these.
    ``headers`` holds only the names a rule reads (``promotion.HEURISTIC_HEADERS``):
    ``persist_signals`` drops the rest of Graph's ``internetMessageHeaders`` block
    rather than storing routing chains and authentication results for nobody.

    Not encrypted: a sender address and a bulk-mail header are metadata, the same
    tier ``Source.subject`` already sits at, not message content.
    """

    __tablename__ = "source_signal_context"

    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True)
    sender: Mapped[str | None] = mapped_column(String(320), nullable=True)
    sender_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_recipients: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    headers: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)

    source: Mapped[Source] = relationship(back_populates="signal_context")


class SourcePromotion(Base):
    """One row per ``Source`` the promotion heuristic has already judged, either verdict.

    ``work_items`` alone cannot tell a ``Source`` promotion rejected from one it was
    never shown -- both leave no matching work item. The backfill in
    ``app/services/backfill.py`` selects on the absence of a row here, because that
    absence is the one fact that means "promotion has never decided about this
    source". ``promote_signals`` writes a row the first time it judges a source,
    whether or not the signal is promoted; it never records a verdict, only that
    one was reached, because the verdict is already recoverable from
    ``work_items.source_external_id`` when it matters.
    """

    __tablename__ = "source_promotions"

    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True)
    considered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class WorkItemIssueKey(Base):
    """The Jira issue one work item is about, named by its issue key (AC9).

    A Jira issue reaches the queue by two doors -- its notification mail, which
    ``promotion.TICKET_SENDER_MARKERS`` lets through, and the participation query
    -- and the two carry different ``external_id``s (``outlook:{id}`` and
    ``jira:{id}``), so nothing in ``work_items`` alone can tell that they are the
    same ticket. The issue key is the one name both doors can produce: the API
    reports it on the issue, and ``app/services/jira_dedupe.py`` extracts it from
    notification mail.

    Its own table rather than a ``work_items`` column, following
    ``source_promotions``: only Jira-derived items have a key, and the queue never
    renders it. ``issue_key`` is unique, so "one issue, one work item" is a
    constraint the database holds and not only a query the promoter remembers to
    run.
    """

    __tablename__ = "work_item_issue_keys"

    work_item_id: Mapped[UUID] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"), primary_key=True)
    issue_key: Mapped[str] = mapped_column(String(255), unique=True)


class WorkEvidence(Base):
    """Provenance retained for agent-generated interpretation of a work item."""

    __tablename__ = "work_evidence"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    work_item_id: Mapped[UUID] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"))
    source_kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind))
    external_id: Mapped[str] = mapped_column(String(512))
    # Promotion carries the source excerpt across into this column, so it holds the
    # same real mail bodies and is sealed the same way. Stays ``TEXT``.
    excerpt: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    work_item: Mapped[WorkItem] = relationship(back_populates="evidence")


class DispatchStatus(str, enum.Enum):
    queued = "queued"
    delivered = "delivered"
    completed = "completed"
    failed = "failed"


class AgentDispatch(Base):
    """An auditable hand-off to an installed local coding-agent integration."""

    __tablename__ = "agent_dispatches"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    work_item_id: Mapped[UUID] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"))
    client: Mapped[str] = mapped_column(String(32))
    instruction: Mapped[str] = mapped_column(Text)
    status: Mapped[DispatchStatus] = mapped_column(Enum(DispatchStatus), default=DispatchStatus.queued)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)

    work_item: Mapped[WorkItem] = relationship(back_populates="dispatches")


class BrowserSession(Base):
    """A signed-in browser, kept in the database so an API restart does not end it.

    ``id_hash`` is the SHA-256 of the cookie value, never the value itself, so a
    copy of the database cannot be replayed as a session. The CSRF token is stored
    as issued: ``GET /api/session`` has to hand it back after a page reload, and
    it is worthless without the cookie. ``expires_at`` is Unix time, not
    ``time.monotonic()``, which restarts with the process.
    """

    __tablename__ = "browser_sessions"

    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[float] = mapped_column(Float, index=True)


class SyncCursor(Base):
    """When a source kind last synced successfully, so the next sync can ask its
    upstream only for what changed since.

    One row per kind that keeps a cursor; today only ``"jira"`` does. Graph syncs
    without one (it reads the latest inbox messages up to a limit), so it has no row.
    ``last_success_at`` is the moment that sync *started*, not when it finished:
    anything updated while it ran then falls inside the next window instead of in
    a gap between two.
    """

    __tablename__ = "sync_cursors"

    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_success_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
