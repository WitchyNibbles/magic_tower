from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .models import DispatchStatus, SourceKind, WorkPriority, WorkStatus


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceInput(APIModel):
    source_kind: SourceKind
    external_id: str = Field(min_length=1, max_length=512)
    excerpt: str | None = Field(default=None, max_length=10_000)
    observed_at: datetime | None = None


class EvidenceRead(EvidenceInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    work_item_id: UUID
    observed_at: datetime


class WorkItemBase(APIModel):
    title: str = Field(min_length=1, max_length=500)
    summary: str | None = Field(default=None, max_length=20_000)
    priority: WorkPriority = WorkPriority.medium
    source_kind: SourceKind = SourceKind.manual
    source_external_id: str | None = Field(default=None, min_length=1, max_length=512)
    source_url: HttpUrl | None = None
    assigned_agent: str | None = Field(default=None, min_length=1, max_length=128)
    due_at: datetime | None = None


class WorkItemCreate(WorkItemBase):
    evidence: list[EvidenceInput] = Field(default_factory=list, max_length=100)


class WorkItemUpdate(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    summary: str | None = Field(default=None, max_length=20_000)
    status: WorkStatus | None = None
    priority: WorkPriority | None = None
    assigned_agent: str | None = Field(default=None, min_length=1, max_length=128)
    due_at: datetime | None = None


class WorkItemRead(WorkItemBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: WorkStatus
    source_url: str | None
    created_at: datetime
    updated_at: datetime
    evidence: list[EvidenceRead] = Field(default_factory=list)


class SourceBase(APIModel):
    kind: SourceKind
    external_id: str = Field(min_length=1, max_length=512)
    subject: str | None = Field(default=None, max_length=500)
    url: HttpUrl | None = None
    excerpt: str | None = Field(default=None, max_length=10_000)
    observed_at: datetime | None = None


class SourceCreate(SourceBase):
    pass


class SourceUpdate(APIModel):
    subject: str | None = Field(default=None, max_length=500)
    url: HttpUrl | None = None
    excerpt: str | None = Field(default=None, max_length=10_000)
    observed_at: datetime | None = None


class SourceRead(SourceBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    url: str | None
    observed_at: datetime
    created_at: datetime
    updated_at: datetime


class AgentDispatchRequest(APIModel):
    work_item_id: UUID
    client: str = Field(pattern=r"^(codex|claude-code)$")
    instruction: str = Field(min_length=1, max_length=20_000)


class AgentDispatchForItem(APIModel):
    client: str = Field(pattern=r"^(codex|claude-code)$")
    instruction: str = Field(min_length=1, max_length=20_000)


class AgentDispatchUpdate(APIModel):
    status: DispatchStatus
    result: str | None = Field(default=None, max_length=20_000)


class AgentDispatchRead(AgentDispatchRequest):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: DispatchStatus
    result: str | None
    created_at: datetime
    updated_at: datetime


class AgentContextRequest(APIModel):
    work_item_id: UUID
    client: str = Field(pattern=r"^(codex|claude-code)$")


class AgentContextRead(APIModel):
    work_item: WorkItemRead
    prompt: str


class AgentProposalCreate(WorkItemCreate):
    client: str = Field(pattern=r"^(codex|claude-code)$")
    confidence: float = Field(ge=0, le=1)


class AgentProposalRead(APIModel):
    client: str
    confidence: float
    work_item: WorkItemRead
