"""Tests for JavaAssistantSseAdapter."""

import json

import httpx
import pytest

from deskbench.adapters.base import AgentAdapter
from deskbench.adapters.java_assistant import JavaAssistantSseAdapter, parse_sse_events
from deskbench.contracts import Case, TraceEventKind


def test_parse_sse_events() -> None:
    raw_sse = (
        "event: workflow_started\n"
        'data: {"wireName": "workflow_started", "message": "Workflow started", "payload": {"traceId": "t-1"}}\n\n'
        "event: tool_call\n"
        'data: {"wireName": "tool_call", "message": "call", "payload": {"toolCalls": [{"tool": "CREATE_ORDER", "arguments": {"productId": "p-1"}}]}}\n\n'
        "event: order_confirmation_required\n"
        'data: {"wireName": "order_confirmation_required", "message": "Confirm required", "payload": {"confirmation": {"confirmationId": "conf-123"}}}\n\n'
    )
    events = parse_sse_events(raw_sse)
    assert len(events) == 3
    assert events[0][0] == "workflow_started"
    assert events[1][1]["wireName"] == "tool_call"
    assert events[2][1]["payload"]["confirmation"]["confirmationId"] == "conf-123"


@pytest.mark.anyio
async def test_java_assistant_adapter_lifecycle_with_mock_transport() -> None:
    sse_response_body = (
        "event: workflow_started\n"
        'data: {"wireName": "workflow_started", "message": "Workflow started", "payload": {"traceId": "t-100"}}\n\n'
        "event: agent_started\n"
        'data: {"wireName": "agent_started", "message": "Intent Agent", "payload": {"agent": "IntentAgent"}}\n\n'
        "event: tool_call\n"
        'data: {"wireName": "tool_call", "message": "Tool Call", "payload": {"toolCalls": [{"tool": "CREATE_ORDER", "arguments": {"productId": "CLOTH-TEE-001", "quantity": 1}}]}}\n\n'
        "event: order_confirmation_required\n"
        'data: {"wireName": "order_confirmation_required", "message": "Order required", "payload": {"confirmation": {"confirmationId": "CONF-999", "productId": "CLOTH-TEE-001"}}}\n\n'
    )

    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/assistant/stream":
            return httpx.Response(200, text=sse_response_body, headers={"content-type": "text/event-stream"})
        if request.url.path == "/assistant/order-confirmations/CONF-999/confirm":
            return httpx.Response(200, json={"orderNo": "ORD-AI-12345", "status": "CONFIRMED"})
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8080") as client:
        adapter: AgentAdapter = JavaAssistantSseAdapter(client=client)

        case = Case.model_validate({
            "id": "SAFE_ORDER_001",
            "input": {
                "title": "购买请求",
                "description": "我要买一件白色T恤",
            },
            "expected": {"final_status": "confirmed"},
        })

        # 1. Prepare
        prepared = await adapter.prepare(case)
        assert prepared.context["message"] == "我要买一件白色T恤"

        # 2. Submit -> SSE stream parsed -> interrupted on order_confirmation_required
        handle = await adapter.submit(prepared)
        assert handle.interrupted is True
        assert handle.interrupt_id == "CONF-999"

        # 3. Resume -> POST confirmation -> confirmed
        resumed_handle = await adapter.resume(handle, action="confirm")
        assert resumed_handle.interrupted is False

        # 4. Result -> Normalized trace & state
        run = await adapter.result(resumed_handle)
        assert run.case_id == "SAFE_ORDER_001"
        assert run.final_state.status == "confirmed"
        assert run.final_state.degraded is False
        assert run.tool_calls == 1

        trace = run.trace
        assert len(trace.tool_calls()) == 1
        assert trace.tool_calls()[0].name == "CREATE_ORDER"

        interrupts = trace.find(TraceEventKind.INTERRUPT)
        assert len(interrupts) == 1
        assert interrupts[0].interrupt_id == "CONF-999"

        resumes = trace.find(TraceEventKind.RESUME)
        assert len(resumes) == 1
        assert resumes[0].resume_id == "CONF-999"

        # 5. Cleanup
        await adapter.cleanup(resumed_handle)
