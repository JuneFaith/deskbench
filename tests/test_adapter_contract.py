"""Tests for the public AgentAdapter protocol."""

from typing import cast

import pytest

from deskbench.adapters.base import (
    AgentAdapter,
    PreparedRun,
    RunHandle,
    adapter_supports_fault,
)
from deskbench.contracts import (
    AgentRun,
    CanonicalState,
    CanonicalTrace,
    Case,
    FaultComponent,
    FaultMode,
    FaultPlan,
)


class ContractAdapter:
    def supports_fault(self, fault: FaultPlan) -> bool:
        return fault.component == FaultComponent.NONE

    async def prepare(self, case: Case) -> PreparedRun:
        return PreparedRun(case=case, context={})

    async def submit(self, prepared: PreparedRun) -> RunHandle:
        return RunHandle(run_id="run-1", case_id=prepared.case.id, interrupted=False)

    async def resume(self, handle: RunHandle, action: str) -> RunHandle:
        return handle.model_copy(update={"interrupted": False})

    async def result(self, handle: RunHandle) -> AgentRun:
        return AgentRun(
            run_id=handle.run_id,
            case_id=handle.case_id,
            adapter="contract",
            final_state=CanonicalState(status="closed"),
            trace=CanonicalTrace(),
        )

    async def cleanup(self, handle: RunHandle) -> None:
        return None


@pytest.fixture
def case() -> Case:
    return Case.model_validate({"id": "case-1", "expected": {"final_status": "closed"}})


@pytest.mark.anyio
async def test_adapter_contract_requires_lifecycle_methods(case: Case) -> None:
    adapter: AgentAdapter = ContractAdapter()
    prepared = await adapter.prepare(case)
    handle = await adapter.submit(prepared)
    result = await adapter.result(handle)
    await adapter.cleanup(handle)

    assert result.run_id == handle.run_id
    assert handle.case_id == case.id
    assert adapter.supports_fault(FaultPlan())
    assert not adapter.supports_fault(FaultPlan(component=FaultComponent.LLM))
    assert adapter_supports_fault(adapter, FaultPlan())
    assert not adapter_supports_fault(adapter, FaultPlan(component=FaultComponent.LLM))


def test_adapter_supports_fault_fallback_without_attribute() -> None:
    class BareAdapter:
        pass

    bare = BareAdapter()
    assert adapter_supports_fault(cast(AgentAdapter, bare), FaultPlan())
    assert not adapter_supports_fault(
        cast(AgentAdapter, bare),
        FaultPlan(component=FaultComponent.LLM, mode=FaultMode.TIMEOUT),
    )
