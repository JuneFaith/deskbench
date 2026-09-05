"""Tests for the public AgentAdapter protocol."""

import pytest

from servicedeskbench.adapters.base import (
    AgentAdapter,
    PreparedRun,
    RunHandle,
)
from servicedeskbench.contracts import AgentRun, CanonicalState, CanonicalTrace, Case


class ContractAdapter:
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
