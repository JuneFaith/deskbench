"""Case definitions and evaluation policy contracts."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CaseAction(str, Enum):
    """Operator action used to continue an interrupted run."""

    SUBMIT = "submit"
    APPROVE = "approve"
    REJECT = "reject"
    RESUME = "resume"


class FaultComponent(str, Enum):
    """External component that can be failed by a case."""

    NONE = "none"
    LLM = "llm"
    EMBEDDING = "embedding"
    RETRIEVAL = "retrieval"
    CHECKPOINT = "checkpoint"
    OUTBOX = "outbox"
    THREAD = "thread"


class FaultMode(str, Enum):
    """Failure behavior requested by a case."""

    NONE = "none"
    TIMEOUT = "timeout"
    INVALID_JSON = "invalid_json"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    WRITE_FAILURE = "write_failure"
    READ_FAILURE = "read_failure"
    DUPLICATE_RESUME = "duplicate_resume"
    CROSS_TICKET_THREAD = "cross_ticket_thread"


class Interaction(BaseModel):
    """One expected operator interaction in a case."""

    model_config = ConfigDict(extra="forbid")

    action: CaseAction
    expect_interrupt: str | None = None


class ExpectedOutcome(BaseModel):
    """Business facts expected after the case completes."""

    model_config = ConfigDict(extra="forbid")

    category: str | None = None
    priority: str | None = None
    final_status: str
    assignee_required: bool = False
    resolution_required: bool = False
    human_takeover: bool = False
    needs_review: bool = False
    auto_resolved: bool | None = None


class Policy(BaseModel):
    """Rules that must hold throughout a run."""

    model_config = ConfigDict(extra="forbid")

    forbidden_transitions: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    max_steps: int = Field(default=20, ge=1)
    max_rejections: int = Field(default=2, ge=0)


class FaultPlan(BaseModel):
    """Evaluation-side fault injection request."""

    model_config = ConfigDict(extra="forbid")

    component: FaultComponent = FaultComponent.NONE
    mode: FaultMode = FaultMode.NONE
    once: bool = True


class DatasetManifest(BaseModel):
    """Metadata and file inventory for one versioned dataset."""

    model_config = ConfigDict(extra="forbid")

    dataset_version: str
    source: str | None = None
    annotation_notes: str | None = None
    status: dict[str, str] = Field(default_factory=dict)
    source_assets: dict[str, str] = Field(default_factory=dict)
    label_semantics: str | None = None
    files: list[str] = Field(default_factory=list)
    layers: dict[str, list[str]] = Field(default_factory=dict)


class Case(BaseModel):
    """A versioned service-desk evaluation case."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    interaction: list[Interaction] = Field(default_factory=list)
    expected: ExpectedOutcome
    policy: Policy = Field(default_factory=Policy)
    fault: FaultPlan = Field(default_factory=FaultPlan)
    dataset_version: str = "servicedesk_v1"
    source: str | None = None
    annotation_notes: str | None = None

    @field_validator("id")
    @classmethod
    def id_must_not_be_empty(cls, value: str) -> str:
        """Reject blank case identifiers."""
        if not value.strip():
            raise ValueError("case id must not be empty")
        return value
