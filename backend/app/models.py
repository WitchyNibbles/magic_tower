import enum
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


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
    status: Mapped[WorkStatus] = mapped_column(Enum(WorkStatus), default=WorkStatus.pending)
    priority: Mapped[WorkPriority] = mapped_column(Enum(WorkPriority), default=WorkPriority.medium)
    source_kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind))
    source_external_id: Mapped[str | None] = mapped_column(String(512), unique=True, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    assigned_agent: Mapped[str | None] = mapped_column(String(128), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    evidence: Mapped[list["WorkEvidence"]] = relationship(back_populates="work_item", cascade="all, delete-orphan")
    dispatches: Mapped[list["AgentDispatch"]] = relationship(back_populates="work_item", cascade="all, delete-orphan")


class Source(Base):
    """Normalized message/source metadata. Content is deliberately not persisted."""

    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind))
    external_id: Mapped[str] = mapped_column(String(512), unique=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkEvidence(Base):
    """Provenance retained for agent-generated interpretation of a work item."""

    __tablename__ = "work_evidence"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    work_item_id: Mapped[UUID] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"))
    source_kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind))
    external_id: Mapped[str] = mapped_column(String(512))
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
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
