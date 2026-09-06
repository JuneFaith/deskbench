"""Run and scoring result contracts."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from deskbench.contracts.state import CanonicalState
from deskbench.contracts.trace import CanonicalTrace


class ScoreResult(BaseModel):
    """Deterministic score with actionable failure evidence."""

    model_config = ConfigDict(extra="forbid")

    scorer: str
    passed: bool
    value: float = Field(ge=0, le=1)
    failures: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)


class ExperimentMetadata(BaseModel):
    """Version information needed to reproduce an evaluation run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    dataset_version: str
    tix_commit: str | None = None
    adapter: str
    agent_version: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    embedding_model: str | None = None
    retrieval_parameters: dict[str, Any] = Field(default_factory=dict)
    scorer_version: str = "1"
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None


class AgentRun(BaseModel):
    """Standardized result of one Adapter execution."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    case_id: str
    adapter: str
    dataset_version: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    agent_version: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    embedding_model: str | None = None
    final_state: CanonicalState
    trace: CanonicalTrace
    scores: list[ScoreResult] = Field(default_factory=list)
    error: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    tokens: int | None = Field(default=None, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    retries: int = Field(default=0, ge=0)
    skipped: bool = False
    skip_reason: str | None = None
