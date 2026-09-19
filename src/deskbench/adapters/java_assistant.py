"""Adapter boundary for the Spring Boot Java Assistant (ai-ticket-assistant) via SSE."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from deskbench.adapters.base import AgentAdapter, PreparedRun, RunHandle
from deskbench.contracts import (
    AgentRun,
    CanonicalState,
    CanonicalTrace,
    Case,
    FaultComponent,
    FaultMode,
    FaultPlan,
    TraceEvent,
    TraceEventKind,
)


def parse_sse_events(raw_text: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse raw SSE payload into (event_type, payload_dict) tuples."""
    events: list[tuple[str, dict[str, Any]]] = []
    current_event = "message"
    current_data_lines: list[str] = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            if current_data_lines:
                data_str = "\n".join(current_data_lines)
                try:
                    payload = json.loads(data_str)
                except Exception:
                    payload = {"raw": data_str}
                events.append((current_event, payload))
                current_data_lines = []
                current_event = "message"
            continue
        if line.startswith("event:"):
            current_event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            current_data_lines.append(line[len("data:") :].strip())

    if current_data_lines:
        data_str = "\n".join(current_data_lines)
        try:
            payload = json.loads(data_str)
        except Exception:
            payload = {"raw": data_str}
        events.append((current_event, payload))

    return events


class JavaAssistantSseAdapter(AgentAdapter):
    """Adapt Spring Boot Multi-Agent Assistant via WebFlux SSE stream to canonical benchmark models."""

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._external_client = client
        self.timeout = timeout
        self._runs: dict[str, dict[str, Any]] = {}

    def supports_fault(self, fault: FaultPlan) -> bool:
        """Java assistant supports simulated LLM and network fault modes."""
        return fault.component in (FaultComponent.NONE, FaultComponent.LLM)

    async def prepare(self, case: Case) -> PreparedRun:
        input_data = case.input
        message = input_data.description or input_data.title or ""
        customer_id = getattr(input_data, "customer_id", None) or "CUST-1001"
        session_id = f"eval-sess-{uuid4().hex[:8]}"
        return PreparedRun(
            case=case,
            context={
                "message": message,
                "customer_id": customer_id,
                "session_id": session_id,
            },
        )

    async def submit(self, prepared: PreparedRun) -> RunHandle:
        run_id = f"run-java-{uuid4().hex[:8]}"
        ctx = prepared.context
        case = prepared.case

        stream_url = f"{self.base_url}/assistant/stream"
        params = {
            "message": ctx["message"],
            "customerId": ctx["customer_id"],
            "sessionId": ctx["session_id"],
        }

        trace_events: list[TraceEvent] = []
        confirmation_id: str | None = None
        final_answer: str = ""
        is_degraded = False

        client = self._external_client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.get(
                stream_url,
                params=params,
                headers={"Accept": "text/event-stream"},
            )
            response.raise_for_status()
            parsed_events = parse_sse_events(response.text)

            for event_type, payload in parsed_events:
                wire_name = payload.get("wireName", event_type)
                msg = payload.get("message", "")
                data = payload.get("payload", {})

                if wire_name == "workflow_started":
                    trace_events.append(
                        TraceEvent(
                            kind=TraceEventKind.LIFECYCLE,
                            name="workflow_started",
                            payload=data,
                        )
                    )
                elif wire_name in ("agent_started", "agent_completed"):
                    trace_events.append(
                        TraceEvent(
                            kind=TraceEventKind.AGENT_STEP,
                            name=data.get("agent", wire_name),
                            payload=data,
                        )
                    )
                elif wire_name == "tool_call":
                    calls = data.get("toolCalls", [])
                    for call in calls:
                        trace_events.append(
                            TraceEvent(
                                kind=TraceEventKind.TOOL_CALL,
                                name=call.get("tool", "unknown"),
                                arguments=call.get("arguments", {}),
                                payload=call,
                            )
                        )
                elif wire_name == "tool_result":
                    trace_events.append(
                        TraceEvent(
                            kind=TraceEventKind.TOOL_RESULT,
                            name="tool_result",
                            payload=data,
                        )
                    )
                elif wire_name == "order_confirmation_required":
                    conf = data.get("confirmation", {})
                    confirmation_id = str(conf.get("confirmationId") or conf.get("id") or "")
                    trace_events.append(
                        TraceEvent(
                            kind=TraceEventKind.INTERRUPT,
                            name="order_confirmation_required",
                            interrupt_id=confirmation_id or None,
                            payload=conf,
                        )
                    )
                elif wire_name == "final_answer":
                    final_answer = msg or str(data)
                elif wire_name == "error":
                    is_degraded = True
                    trace_events.append(
                        TraceEvent(
                            kind=TraceEventKind.ERROR,
                            name="error",
                            error=msg or str(data),
                            payload=data,
                        )
                    )

        finally:
            if self._external_client is None:
                await client.aclose()

        interrupted = bool(confirmation_id)
        self._runs[run_id] = {
            "case": case,
            "context": ctx,
            "trace_events": trace_events,
            "confirmation_id": confirmation_id,
            "interrupted": interrupted,
            "final_answer": final_answer,
            "is_degraded": is_degraded,
            "confirmed": False,
        }

        return RunHandle(
            run_id=run_id,
            case_id=case.id,
            interrupted=interrupted,
            interrupt_id=confirmation_id,
        )

    async def resume(self, handle: RunHandle, action: str) -> RunHandle:
        run_data = self._runs.get(handle.run_id)
        if not run_data or not handle.interrupt_id:
            return handle

        if action.lower() in ("confirm", "approve"):
            confirm_url = (
                f"{self.base_url}/assistant/order-confirmations/{handle.interrupt_id}/confirm"
            )
            body = {
                "customerId": run_data["context"]["customer_id"],
                "sessionId": run_data["context"]["session_id"],
            }
            client = self._external_client or httpx.AsyncClient(timeout=self.timeout)
            try:
                resp = await client.post(confirm_url, json=body)
                resp.raise_for_status()
                order_result = resp.json()
                run_data["confirmed"] = True
                run_data["order_result"] = order_result
                run_data["trace_events"].append(
                    TraceEvent(
                        kind=TraceEventKind.RESUME,
                        name="order_confirmed",
                        resume_id=handle.interrupt_id,
                        payload=order_result,
                    )
                )
            finally:
                if self._external_client is None:
                    await client.aclose()

        return handle.model_copy(update={"interrupted": False})

    async def result(self, handle: RunHandle) -> AgentRun:
        run_data = self._runs.get(handle.run_id)
        if not run_data:
            raise RuntimeError(f"Unknown run handle {handle.run_id}")

        trace = CanonicalTrace(events=run_data["trace_events"])
        tool_count = len(trace.tool_calls())

        status = "pending_confirmation" if run_data["interrupted"] else "completed"
        if run_data["confirmed"]:
            status = "confirmed"
        if run_data["is_degraded"]:
            status = "degraded"

        final_state = CanonicalState(
            status=status,
            degraded=run_data["is_degraded"],
            metadata={
                "confirmation_id": run_data["confirmation_id"],
                "confirmed": run_data["confirmed"],
                "final_answer": run_data["final_answer"],
                "total_events": len(trace.events),
            },
        )

        return AgentRun(
            run_id=handle.run_id,
            case_id=handle.case_id,
            adapter="java_assistant_sse",
            final_state=final_state,
            trace=trace,
            tool_calls=tool_count,
        )

    async def cleanup(self, handle: RunHandle) -> None:
        self._runs.pop(handle.run_id, None)
