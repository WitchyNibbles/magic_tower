from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .models import SourceKind, WorkStatus


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "workboard-api"


class EvidenceInput(BaseModel):
    source_kind: SourceKind
    external_id: str = Field(min_length=1, max_length=512)
    excerpt: str | None = Field(default=None, max_length=10_000)
    observed_at: datetime | None = None


class WorkItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    summary: str | None = Field(default=None, max_length=20_000)
    source_kind: SourceKind
    source_external_id: str | None = Field(default=None, max_length=512)
    source_url: HttpUrl | None = None
    due_at: datetime | None = None
    evidence: list[EvidenceInput] = Field(default_factory=list)


class WorkItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    summary: str | None
    status: WorkStatus
    source_kind: SourceKind
    source_external_id: str | None
    source_url: str | None
    assigned_agent: str | None
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentDispatchRequest(BaseModel):
    work_item_id: UUID
    client: str = Field(pattern="^(codex|claude-code)$")
    instruction: str = Field(min_length=1, max_length=20_000)
