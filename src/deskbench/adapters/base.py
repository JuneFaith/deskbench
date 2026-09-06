"""Adapter boundaries for systems under evaluation."""

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from deskbench.contracts import AgentRun, Case
from deskbench.contracts.cases import FaultComponent, FaultMode, FaultPlan


class PreparedRun(BaseModel):
    """Adapter-owned prepared input for one case."""

    model_config = ConfigDict(extra="forbid")

    case: Case
    context: dict[str, Any] = Field(default_factory=dict)


class RunHandle(BaseModel):
    """Opaque, serializable handle for an adapter execution."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    case_id: str
    interrupted: bool = False
    interrupt_id: str | None = None


class AgentAdapter(Protocol):
    """Protocol implemented by each system-under-test boundary."""

    def supports_fault(self, fault: FaultPlan) -> bool:
        """Return whether the adapter supports executing a fault plan."""
        ...

    async def prepare(self, case: Case) -> PreparedRun:
        """Prepare isolated state for a case."""
        ...

    async def submit(self, prepared: PreparedRun) -> RunHandle:
        """Submit a prepared case to the system under test."""
        ...

    async def resume(self, handle: RunHandle, action: str) -> RunHandle:
        """Continue an interrupted run with an operator action."""
        ...

    async def result(self, handle: RunHandle) -> AgentRun:
        """Read the standardized result and evidence."""
        ...

    async def cleanup(self, handle: RunHandle) -> None:
        """Remove isolated run data."""
        ...


def adapter_supports_fault(adapter: AgentAdapter, fault: FaultPlan) -> bool:
    """Check if an adapter supports the requested fault plan."""
    checker = getattr(adapter, "supports_fault", None)
    if callable(checker):
        return bool(checker(fault))
    return fault.component == FaultComponent.NONE or fault.mode == FaultMode.NONE
