"""Tests for the ServiceDeskBench execution runner."""

import anyio
import pytest

from servicedeskbench.adapters.base import AgentAdapter, PreparedRun, RunHandle
from servicedeskbench.contracts import (
    AgentRun,
    CanonicalState,
    CanonicalTrace,
    Case,
    CaseAction,
    Interaction,
    TraceEvent,
    TraceEventKind,
)
from servicedeskbench.runner.execution import run_case
from servicedeskbench.runner.limits import ExecutionLimits


class ScriptedAdapter(AgentAdapter):
    def __init__(self, *, fail: bool = False, interrupt: bool = True) -> None:
        self.fail = fail
        self.interrupt = interrupt
        self.actions: list[str] = []
        self.cleaned = False

    async def prepare(self, case: Case) -> PreparedRun:
        return PreparedRun(case=case)

    async def submit(self, prepared: PreparedRun) -> RunHandle:
        if self.fail:
            raise RuntimeError("submit failed")
        return RunHandle(
            run_id="run-1", case_id=prepared.case.id, interrupted=self.interrupt
        )

    async def resume(self, handle: RunHandle, action: str) -> RunHandle:
        self.actions.append(action)
        return handle.model_copy(update={"interrupted": False})

    async def result(self, handle: RunHandle) -> AgentRun:
        return AgentRun(
            run_id=handle.run_id,
            case_id=handle.case_id,
            adapter="scripted",
            final_state=CanonicalState(status="closed"),
            trace=CanonicalTrace(events=[TraceEvent(kind=TraceEventKind.RESUME)]),
        )

    async def cleanup(self, handle: RunHandle) -> None:
        self.cleaned = True


@pytest.fixture
def case() -> Case:
    return Case.model_validate(
        {
            "id": "case-1",
            "interaction": [{"action": "approve"}],
            "expected": {"final_status": "closed"},
        }
    )


@pytest.mark.anyio
async def test_runner_dispatches_interactions_and_always_cleans_up(case: Case) -> None:
    adapter = ScriptedAdapter()

    result = await run_case(case, adapter, ExecutionLimits(timeout_seconds=1))

    assert result.final_state.status == "closed"
    assert adapter.actions == ["approve"]
    assert adapter.cleaned is True


@pytest.mark.anyio
async def test_runner_records_adapter_failure_and_cleans_up(case: Case) -> None:
    adapter = ScriptedAdapter(fail=True)

    result = await run_case(case, adapter, ExecutionLimits(timeout_seconds=1))

    assert result.error == "submit failed"
    assert result.final_state.status == "error"
    assert result.trace.events[0].error == "submit failed"
    assert adapter.cleaned is False


@pytest.mark.anyio
async def test_runner_stops_a_run_that_exceeds_the_time_limit(case: Case) -> None:
    class SlowAdapter(ScriptedAdapter):
        async def submit(self, prepared: PreparedRun) -> RunHandle:
            await anyio.sleep(0.05)
            return await super().submit(prepared)

    result = await run_case(case, SlowAdapter(), ExecutionLimits(timeout_seconds=0.001))

    assert result.error == "execution timed out"


@pytest.mark.anyio
async def test_runner_enforces_max_steps_before_unbounded_resumes(case: Case) -> None:
    class NeverEndingAdapter(ScriptedAdapter):
        async def submit(self, prepared: PreparedRun) -> RunHandle:
            return RunHandle(
                run_id="run-steps", case_id=prepared.case.id, interrupted=True
            )

        async def resume(self, handle: RunHandle, action: str) -> RunHandle:
            self.actions.append(action)
            return handle

    case.interaction = [
        Interaction(action=CaseAction.APPROVE),
        Interaction(action=CaseAction.APPROVE),
        Interaction(action=CaseAction.APPROVE),
    ]
    adapter = NeverEndingAdapter()

    result = await run_case(case, adapter, ExecutionLimits(max_steps=2))

    assert result.error == "maximum execution steps exceeded"
    assert len(adapter.actions) == 1
    assert adapter.cleaned is True


@pytest.mark.anyio
@pytest.mark.anyio
async def test_runner_enforces_case_step_limit_on_completed_trace(case: Case) -> None:
    class LongTraceAdapter(ScriptedAdapter):
        async def result(self, handle: RunHandle) -> AgentRun:
            return AgentRun(
                run_id=handle.run_id,
                case_id=handle.case_id,
                adapter="long-trace",
                final_state=CanonicalState(status="closed"),
                trace=CanonicalTrace(
                    events=[
                        TraceEvent(kind=TraceEventKind.AGENT_STEP),
                        TraceEvent(kind=TraceEventKind.AGENT_STEP),
                    ]
                ),
            )

    case.policy.max_steps = 1
    result = await run_case(case, LongTraceAdapter(interrupt=False), ExecutionLimits())

    assert result.error == "maximum execution steps exceeded"


@pytest.mark.anyio
async def test_runner_persists_tool_count_from_trace(case: Case) -> None:
    class ToolTraceAdapter(ScriptedAdapter):
        async def result(self, handle: RunHandle) -> AgentRun:
            return AgentRun(
                run_id=handle.run_id,
                case_id=handle.case_id,
                adapter="tool-trace",
                final_state=CanonicalState(status="closed"),
                trace=CanonicalTrace(
                    events=[TraceEvent(kind=TraceEventKind.TOOL_CALL, name="lookup")]
                ),
            )

    result = await run_case(case, ToolTraceAdapter(interrupt=False), ExecutionLimits())

    assert result.tool_calls == 1


@pytest.mark.anyio
async def test_runner_propagates_external_cancellation(case: Case) -> None:
    class CancelAdapter(ScriptedAdapter):
        async def submit(self, prepared: PreparedRun) -> RunHandle:
            await anyio.sleep_forever()
            raise AssertionError("unreachable")

    results: list[AgentRun] = []
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(
            _run_and_store,
            results,
            case,
            CancelAdapter(),
        )
        await anyio.sleep(0)
        task_group.cancel_scope.cancel()

    assert results == []


async def _run_and_store(
    results: list[AgentRun], case: Case, adapter: AgentAdapter
) -> None:
    results.append(await run_case(case, adapter, ExecutionLimits(timeout_seconds=1)))
    return None


@pytest.mark.anyio
async def test_runner_bounds_hanging_cleanup(case: Case) -> None:
    class HangingCleanupAdapter(ScriptedAdapter):
        async def cleanup(self, handle: RunHandle) -> None:
            await anyio.sleep(1)

    result = await run_case(
        case,
        HangingCleanupAdapter(interrupt=False),
        ExecutionLimits(timeout_seconds=1, cleanup_timeout_seconds=0.001),
    )

    assert result.error is None


@pytest.mark.anyio
async def test_runner_preserves_adapter_and_elapsed_time_on_failure(case: Case) -> None:
    class SlowFailAdapter(ScriptedAdapter):
        async def submit(self, prepared: PreparedRun) -> RunHandle:
            await anyio.sleep(0.01)
            raise RuntimeError("submit failed")

    result = await run_case(case, SlowFailAdapter(), ExecutionLimits(timeout_seconds=1))

    assert result.adapter == "SlowFailAdapter"
    assert result.duration_ms is not None and result.duration_ms >= 10
