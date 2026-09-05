"""Graph-path Adapter for the tix system under test."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, cast
from uuid import uuid4

from deskbench.adapters.base import AgentAdapter, PreparedRun, RunHandle
from deskbench.contracts import AgentRun, CanonicalState, Case
from deskbench.trace import normalize_trace


class GraphExecutor(Protocol):
    """Minimal graph boundary required by the Adapter."""

    def submit(self, case: Mapping[str, Any], run_id: str) -> Awaitable[Any]: ...

    def resume(self, run_id: str, action: str) -> Awaitable[Any]: ...

    def result(self, run_id: str) -> Awaitable[Any]: ...

    def cleanup(self, run_id: str) -> Awaitable[Any]: ...


async def _await(value: Any) -> Any:
    """Await an async callback result while accepting synchronous test clients."""
    if isinstance(value, Awaitable):
        return await value
    return value


class TixGraphAdapter(AgentAdapter):
    """Adapt tix's local graph execution to canonical Deskbench models."""

    def __init__(
        self,
        graph_factory: Callable[[Case, str], GraphExecutor],
        *,
        adapter_name: str = "tix_graph",
    ) -> None:
        self._graph_factory = graph_factory
        self._adapter_name = adapter_name
        self._executors: dict[str, GraphExecutor] = {}

    async def prepare(self, case: Case) -> PreparedRun:
        """Create an isolated graph executor for a case."""
        run_id = str(uuid4())
        executor = self._graph_factory(case, run_id)
        self._executors[run_id] = executor
        return PreparedRun(case=case, context={"run_id": run_id})

    async def submit(self, prepared: PreparedRun) -> RunHandle:
        """Submit the case and capture an interrupt if one occurs."""
        run_id = cast(str, prepared.context["run_id"])
        response = await _await(
            self._executors[run_id].submit(prepared.case.model_dump(), run_id)
        )
        return self._handle_from_response(run_id, prepared.case.id, response)

    async def resume(self, handle: RunHandle, action: str) -> RunHandle:
        """Resume an interrupted graph with an operator action."""
        response = await _await(
            self._executors[handle.run_id].resume(handle.run_id, action)
        )
        return self._handle_from_response(handle.run_id, handle.case_id, response)

    async def result(self, handle: RunHandle) -> AgentRun:
        """Read and normalize the graph result."""
        response = await _await(self._executors[handle.run_id].result(handle.run_id))
        return self._run_from_response(handle, response)

    async def cleanup(self, handle: RunHandle) -> None:
        """Clean up graph state and release the executor."""
        executor = self._executors.pop(handle.run_id, None)
        if executor is not None:
            await _await(executor.cleanup(handle.run_id))

    @staticmethod
    def _handle_from_response(run_id: str, case_id: str, response: Any) -> RunHandle:
        payload = _mapping(response)
        interrupt = payload.get("interrupt")
        if isinstance(interrupt, Mapping):
            raw_id = interrupt.get("thread_id") or interrupt.get("id") or ""
            return RunHandle(
                run_id=run_id,
                case_id=case_id,
                interrupted=True,
                interrupt_id=str(raw_id) or None,
            )
        return RunHandle(run_id=run_id, case_id=case_id, interrupted=False)

    def _run_from_response(self, handle: RunHandle, response: Any) -> AgentRun:
        payload = _mapping(response)
        state = payload.get("final_state", payload.get("state", {}))
        trace = payload.get("trace", payload.get("events", []))
        return AgentRun(
            run_id=handle.run_id,
            case_id=handle.case_id,
            adapter=self._adapter_name,
            final_state=CanonicalState.model_validate(state),
            trace=normalize_trace(trace),
            error=_optional_string(payload.get("error")),
            duration_ms=_optional_float(payload.get("duration_ms")),
            tokens=_optional_int(payload.get("tokens")),
            tool_calls=int(payload.get("tool_calls", 0)),
            retries=int(payload.get("retries", 0)),
        )


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(
            f"tix graph response must be a mapping, got {type(value).__name__}"
        )
    return value


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _optional_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _optional_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int) else None
