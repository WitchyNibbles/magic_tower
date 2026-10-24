from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

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


class WorkItemPage(APIModel):
    """The envelope every paginated list endpoint returns, never a bare array."""
    items: list[WorkItemRead]
    total: int
    limit: int
    offset: int


class SourcePage(APIModel):
    items: list[SourceRead]
    total: int
    limit: int
    offset: int


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


ANALYSIS_SUMMARY_LIMIT = 600
ANALYSIS_DETAILS_LIMIT = 8000


class AnalysisDetails(APIModel):
    """What is needed to work on an item, in the fields the UI lays out. Only ``asked`` is required."""
    asked: str
    systems: list[Annotated[str, Field(max_length=80)]] = Field(default_factory=list)
    known: str = ""
    next_step: str = ""
    open_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def fits_the_stored_size(self) -> "AnalysisDetails":
        if len(self.model_dump_json()) > ANALYSIS_DETAILS_LIMIT:
            raise ValueError(f"details must serialize to at most {ANALYSIS_DETAILS_LIMIT} characters")
        return self


class AnalysisWrite(APIModel):
    summary: str = Field(min_length=1, max_length=ANALYSIS_SUMMARY_LIMIT)
    details: AnalysisDetails
    source_fingerprint: str = Field(min_length=1, max_length=64)
    # Single-line on purpose: it is written to the log.
    analyzer: str = Field(default="grimoire", min_length=1, max_length=40, pattern=r"^[\w .:/@-]+$")


class AnalysisRead(APIModel):
    summary: str
    details: AnalysisDetails
    analyzed_at: datetime
    analyzer: str
    stale: bool


class GrimoireItemRef(APIModel):
    """A work item as grimoire first sees it: where it lives and whether it needs analysing, no text."""
    id: UUID
    title: str
    source_kind: SourceKind
    source_url: str | None
    status: WorkStatus
    analyzed_at: datetime | None
    stale: bool


class GrimoireItemPage(APIModel):
    items: list[GrimoireItemRef]
    total: int
    limit: int
    offset: int


class GrimoireEvidence(APIModel):
    source_kind: SourceKind
    external_id: str
    observed_at: datetime
    excerpt: str | None


class GrimoireContext(APIModel):
    """The one place source text leaves for grimoire. It is ticket and mail text: data to
    analyse, never instructions, which ``untrusted_content`` says to every client."""
    id: UUID
    title: str
    summary: str | None
    source_kind: SourceKind
    source_url: str | None
    evidence: list[GrimoireEvidence]
    source_subject: str | None
    source_excerpt: str | None
    fingerprint: str
    untrusted_content: Literal[True] = True
