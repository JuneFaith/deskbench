"""End-to-end tests for the local evaluation pipeline."""

import json
from pathlib import Path

import pytest

from servicedeskbench.adapters.base import AgentAdapter, PreparedRun, RunHandle
from servicedeskbench.contracts import (
    AgentRun,
    CanonicalState,
    CanonicalTrace,
    Case,
)
from servicedeskbench.evaluation import run_dataset


class DeterministicAdapter(AgentAdapter):
    async def prepare(self, case: Case) -> PreparedRun:
        return PreparedRun(case=case)

    async def submit(self, prepared: PreparedRun) -> RunHandle:
        return RunHandle(run_id=f"run-{prepared.case.id}", case_id=prepared.case.id)

    async def resume(self, handle: RunHandle, action: str) -> RunHandle:
        return handle

    async def result(self, handle: RunHandle) -> AgentRun:
        return AgentRun(
            run_id=handle.run_id,
            case_id=handle.case_id,
            adapter="deterministic",
            final_state=CanonicalState(status="closed"),
            trace=CanonicalTrace(),
        )

    async def cleanup(self, handle: RunHandle) -> None:
        return None


@pytest.mark.anyio
async def test_run_dataset_executes_cases_and_writes_report(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.yaml"
    dataset.write_text("- id: case-1\n  expected:\n    final_status: closed\n")

    paths = await run_dataset(dataset, DeterministicAdapter(), tmp_path / "reports")

    assert paths.summary.exists()
    records = [json.loads(line) for line in paths.cases.read_text().splitlines()]
    assert [record["case_id"] for record in records] == ["case-1"]
