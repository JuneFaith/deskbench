"""Canonical service-desk state and trace contracts."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CanonicalState(BaseModel):
    """Business facts needed by Deskbench scorers."""

    model_config = ConfigDict(extra="forbid")

    status: str
    category: str | None = None
    priority: str | None = None
    urgency: str | None = None
    severity: str | None = None
    impact: str | None = None
    assigned: bool = False
    assignee: str | None = None
    resolution: str | None = None
    needs_review: bool = False
    auto_resolved: bool = False
    degraded: bool = False
    human_takeover: bool = False
    thread_id: str | None = None
    audit_summary: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
