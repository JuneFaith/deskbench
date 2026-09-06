"""Tests for the tix Graph Adapter boundary."""

from collections.abc import Mapping
from typing import Any

import pytest

from deskbench.adapters.tix_graph import TixGraphAdapter
from deskbench.contracts import Case, FaultComponent, FaultMode, FaultPlan


class Graph:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def submit(self, case: Mapping[str, Any], run_id: str) -> dict[str, Any]:
        self.calls.append("submit")
        return {"interrupt": {"id": "approval-1"}}

    async def resume(self, run_id: str, action: str) -> dict[str, Any]:
        self.calls.append(f"resume:{action}")
        return {}

    async def result(self, run_id: str) -> dict[str, Any]:
        self.calls.append("result")
        return {
            "state": {
                "status": "closed",
                "category": "security",
                "assigned": True,
                "resolution": "Account secured",
            },
            "events": [
                {"kind": "interrupt", "interrupt_id": "approval-1"},
                {"kind": "resume", "resume_id": "resume-1"},
                {"kind": "state_change", "from": "pending_approval", "to": "closed"},
            ],
        }

    async def cleanup(self, run_id: str) -> None:
        self.calls.append("cleanup")


@pytest.mark.anyio
async def test_graph_adapter_normalizes_interrupt_resume_and_result() -> None:
    graph = Graph()
    adapter = TixGraphAdapter(lambda case, run_id: graph)
    case = Case.model_validate(
        {
            "id": "security-1",
            "expected": {"final_status": "closed"},
        }
    )

    prepared = await adapter.prepare(case)
    handle = await adapter.submit(prepared)
    assert handle.interrupted is True
    assert handle.interrupt_id == "approval-1"

    resumed = await adapter.resume(handle, "approve")
    result = await adapter.result(resumed)
    await adapter.cleanup(resumed)

    assert result.adapter == "tix_graph"
    assert result.final_state.status == "closed"
    assert result.trace.events[2].to_status == "closed"
    assert graph.calls == ["submit", "resume:approve", "result", "cleanup"]


def test_tix_graph_adapter_supports_all_faults() -> None:
    adapter = TixGraphAdapter(lambda case, run_id: Graph())
    assert adapter.supports_fault(FaultPlan())
    assert adapter.supports_fault(
        FaultPlan(component=FaultComponent.LLM, mode=FaultMode.TIMEOUT)
    )
