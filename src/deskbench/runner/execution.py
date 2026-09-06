"""Run cases through adapters with bounded cleanup and evidence."""

from time import monotonic

import anyio

from deskbench.adapters import adapter_supports_fault
from deskbench.adapters.base import AgentAdapter, RunHandle
from deskbench.contracts import (
    AgentRun,
    CanonicalState,
    CanonicalTrace,
    Case,
    TraceEvent,
    TraceEventKind,
)
from deskbench.runner.limits import ExecutionLimits


async def run_case(
    case: Case, adapter: AgentAdapter, limits: ExecutionLimits
) -> AgentRun:
    """Execute a case and preserve terminal failure evidence.

    Args:
        case: Case to execute.
        adapter: System-under-test boundary.
        limits: Time and work limits.

    Returns:
        A standardized run result, including an error result on failure.
    """
    started = monotonic()
    handle: RunHandle | None = None
    steps = 0
    adapter_name = type(adapter).__name__
    if not adapter_supports_fault(adapter, case.fault):
        return _skipped_result(case, adapter_name, started)
    try:
        with anyio.fail_after(limits.timeout_seconds):
            prepared = await adapter.prepare(case)
            handle = await adapter.submit(prepared)
            steps = 1
            if handle.interrupted:
                for interaction in case.interaction:
                    if interaction.action.value == "submit":
                        continue
                    if steps >= limits.max_steps or steps >= case.policy.max_steps:
                        raise RuntimeError("maximum execution steps exceeded")
                    handle = await adapter.resume(handle, interaction.action.value)
                    steps += 1
            result = await adapter.result(handle)
            step_limit = min(limits.max_steps, case.policy.max_steps)
            execution_steps = (
                len(
                    [
                        e
                        for e in result.trace.events
                        if e.kind
                        in {
                            TraceEventKind.AGENT_STEP,
                            TraceEventKind.TOOL_CALL,
                            TraceEventKind.MODEL_CALL,
                        }
                    ]
                )
                or steps
            )
            if execution_steps > step_limit:
                raise RuntimeError("maximum execution steps exceeded")
            tool_calls = max(len(result.trace.tool_calls()), result.tool_calls)
            result.tool_calls = tool_calls
            if tool_calls > limits.max_tool_calls:
                raise RuntimeError("maximum tool calls exceeded")
            result.duration_ms = (monotonic() - started) * 1000
            return result
    except TimeoutError:
        return _error_result(
            case,
            "execution timed out",
            "error",
            adapter_name,
            started,
        )
    except Exception as error:
        return _error_result(case, str(error), "error", adapter_name, started)
    except BaseException:
        raise
    finally:
        if handle is not None:
            await _cleanup_safely(adapter, handle, limits.cleanup_timeout_seconds)


async def _cleanup_safely(
    adapter: AgentAdapter, handle: RunHandle, timeout_seconds: float
) -> None:
    """Attempt shielded, bounded cleanup without hiding the run result."""
    try:
        with anyio.CancelScope(shield=True):
            with anyio.fail_after(timeout_seconds):
                await adapter.cleanup(handle)
    except (Exception, anyio.get_cancelled_exc_class()):
        return None


def _skipped_result(
    case: Case,
    adapter: str,
    started: float,
    reason: str | None = None,
) -> AgentRun:
    """Build a skipped run result when an adapter does not support the case fault."""
    if reason is None:
        reason = (
            f"adapter '{adapter}' does not support fault "
            f"'{case.fault.component.value}:{case.fault.mode.value}'"
        )
    return AgentRun(
        run_id=f"skipped-{case.id}",
        case_id=case.id,
        adapter=adapter,
        final_state=CanonicalState(status="skipped"),
        trace=CanonicalTrace(
            events=[
                TraceEvent(
                    kind=TraceEventKind.LIFECYCLE,
                    payload={"action": "skip", "reason": reason},
                )
            ]
        ),
        skipped=True,
        skip_reason=reason,
        duration_ms=(monotonic() - started) * 1000,
    )


def _error_result(
    case: Case,
    message: str,
    status: str,
    adapter: str,
    started: float,
) -> AgentRun:
    """Build an evidence-bearing result for an execution failure."""
    return AgentRun(
        run_id=f"failed-{case.id}",
        case_id=case.id,
        adapter=adapter,
        final_state=CanonicalState(status=status, degraded=True),
        trace=CanonicalTrace(
            events=[
                TraceEvent(
                    kind=TraceEventKind.ERROR,
                    error=message,
                    raw={"case_id": case.id, "adapter": adapter},
                )
            ]
        ),
        error=message,
        duration_ms=(monotonic() - started) * 1000,
    )
