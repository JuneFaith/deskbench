"""Canonical execution trace contracts."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TraceEventKind(str, Enum):
    """Kinds of evidence emitted during an agent run."""

    AGENT_STEP = "agent_step"
    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    STATE_CHANGE = "state_change"
    INTERRUPT = "interrupt"
    RESUME = "resume"
    ERROR = "error"
    DEGRADATION = "degradation"


class TraceEvent(BaseModel):
    """One normalized execution event."""

    model_config = ConfigDict(extra="forbid")

    kind: TraceEventKind
    timestamp: str | None = None
    name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    from_status: str | None = None
    to_status: str | None = None
    interrupt_id: str | None = None
    resume_id: str | None = None
    error: str | None = None
    reason: str | None = None
    tokens: int | None = Field(default=None, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)
    retries: int = Field(default=0, ge=0)
    ticket_id: str | None = None
    actor_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class CanonicalTrace(BaseModel):
    """Ordered normalized evidence from one agent execution."""

    model_config = ConfigDict(extra="forbid")

    events: list[TraceEvent] = Field(default_factory=list)

    def find(self, kind: TraceEventKind) -> list[TraceEvent]:
        """Return events with the requested kind in original order."""
        return [event for event in self.events if event.kind == kind]

    def tool_calls(self) -> list[TraceEvent]:
        """Return tool-call events in original order."""
        return self.find(TraceEventKind.TOOL_CALL)
