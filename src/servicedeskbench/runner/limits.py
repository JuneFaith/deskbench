"""Resource limits for one benchmark run."""

from pydantic import BaseModel, ConfigDict, Field


class ExecutionLimits(BaseModel):
    """Maximum wall time and execution work for a case."""

    model_config = ConfigDict(extra="forbid")

    timeout_seconds: float = Field(default=120.0, gt=0)
    cleanup_timeout_seconds: float = Field(default=5.0, gt=0)
    max_steps: int = Field(default=20, ge=1)
    max_tool_calls: int = Field(default=50, ge=1)
