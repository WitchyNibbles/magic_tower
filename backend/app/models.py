import enum
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .services.field_crypto import EncryptedText


class WorkStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    blocked = "blocked"
    done = "done"


class WorkPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class SourceKind(str, enum.Enum):
    outlook_email = "outlook_email"
    teams_message = "teams_message"
    manual = "manual"


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
    assigned_agent: Mapped[str | None] = mapped_column(String(128), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

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
    # Real mail and Teams bodies land here, so the column -- and only the column --
    # holds ciphertext; readers still see cleartext. Stays ``TEXT`` on disk.
    excerpt: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

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
    considered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class WorkEvidence(Base):
    """Provenance retained for agent-generated interpretation of a work item."""

    __tablename__ = "work_evidence"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    work_item_id: Mapped[UUID] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"))
    source_kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind))
    external_id: Mapped[str] = mapped_column(String(512))
    # Promotion carries the source excerpt across into this column, so it holds the
    # same real mail and Teams bodies and is sealed the same way. Stays ``TEXT``.
    excerpt: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    work_item: Mapped[WorkItem] = relationship(back_populates="dispatches")
