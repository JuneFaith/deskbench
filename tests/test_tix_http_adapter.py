"""Contract tests for the real public Tix HTTP boundary."""

import json

import httpx
import pytest

from servicedeskbench.adapters.base import RunHandle
from servicedeskbench.adapters.tix_http import HttpAdapterError, TixHttpAdapter
from servicedeskbench.contracts import Case


@pytest.mark.anyio
async def test_ticket_adapter_uses_public_ticket_endpoints_and_maps_events() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"access_token": "token-1"})
        if request.url.path == "/api/tickets" and request.method == "POST":
            return httpx.Response(
                202, json={"ticket_id": "ticket-1", "run_status": "started"}
            )
        if request.url.path == "/api/tickets/ticket-1":
            return httpx.Response(
                200,
                json={
                    "ticket": {
                        "id": "ticket-1",
                        "status": "pending_approval",
                        "category": "security",
                        "priority": "P1",
                        "urgency": "high",
                        "severity": "major",
                        "impact": "high",
                        "assignee": "handler-1",
                        "resolution": None,
                        "needs_review": True,
                        "thread_id": "thread-1",
                        "private_field": "kept as raw evidence",
                    },
                    "events": [
                        {
                            "id": "event-1",
                            "ticket_id": "ticket-1",
                            "event_type": "transition",
                            "from_status": "awaiting_assignment",
                            "to_status": "pending_approval",
                            "actor": "system",
                            "detail": {"approval_type": "dispatch"},
                            "timestamp": "2026-09-03T00:00:00Z",
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TixHttpAdapter(
        "https://tix.test/api", username="submitter", password="password", client=client
    )
    case = Case.model_validate(
        {
            "id": "case-1",
            "input": {
                "title": "Account compromised",
                "description": "Suspicious login",
            },
            "expected": {"final_status": "closed"},
        }
    )

    await adapter.login()
    handle = await adapter.submit(await adapter.prepare(case))
    result = await adapter.result(handle)
    await adapter.cleanup(handle)
    await client.aclose()

    assert handle.run_id == "ticket-1"
    assert result.final_state.status == "pending_approval"
    assert result.final_state.category == "security"
    assert result.final_state.assignee == "handler-1"
    assert result.final_state.thread_id == "thread-1"
    assert result.trace.events[0].kind == "state_change"
    assert result.trace.events[0].from_status == "awaiting_assignment"
    assert result.trace.events[0].actor_id == "system"
    assert result.trace.events[0].raw["detail"] == {"approval_type": "dispatch"}
    assert requests[0].url.path == "/api/auth/login"
    assert requests[1].headers["authorization"] == "Bearer token-1"
    assert all("/runs" not in request.url.path for request in requests)
    assert json.loads(requests[1].content)["title"] == "Account compromised"


@pytest.mark.anyio
async def test_submit_discovers_initial_interrupt() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/tickets":
            return httpx.Response(
                202, json={"ticket_id": "ticket-1", "run_status": "started"}
            )
        if request.method == "GET" and request.url.path == "/api/tickets/ticket-1":
            return httpx.Response(
                200,
                json={
                    "ticket": {
                        "id": "ticket-1",
                        "status": "pending_approval",
                        "thread_id": "thread-1",
                    },
                    "events": [],
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TixHttpAdapter("https://tix.test/api", token="token-1", client=client)
    case = Case.model_validate({"id": "case-1", "expected": {"final_status": "closed"}})

    handle = await adapter.submit(await adapter.prepare(case))
    await client.aclose()

    assert handle.interrupted is True
    assert handle.interrupt_id == "thread-1"


@pytest.mark.anyio
async def test_resume_preserves_next_interrupt_from_complete_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tickets/ticket-1/resume"
        return httpx.Response(
            200,
            json={
                "result": {
                    "ticket_id": "ticket-1",
                    "thread_id": "thread-2",
                    "completed": False,
                    "last_node": "await_review",
                    "error": None,
                },
                "interrupted": {
                    "interrupt_type": "resolution_review",
                    "ticket_id": "ticket-1",
                    "thread_id": "thread-2",
                    "context": {},
                },
                "thread_id": "thread-2",
                "run_duration_s": 0.1,
                "degraded_count": 0,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TixHttpAdapter("https://tix.test/api", token="token-1", client=client)
    handle = RunHandle(
        run_id="ticket-1", case_id="case-1", interrupted=True, interrupt_id="thread-1"
    )

    resumed = await adapter.resume(handle, "approve")
    await client.aclose()

    assert resumed.interrupted is True
    assert resumed.interrupt_id == "thread-2"


@pytest.mark.anyio
async def test_resume_rejects_incomplete_run_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": {
                    "ticket_id": "ticket-1",
                    "thread_id": None,
                    "completed": True,
                    "last_node": "collect_feedback",
                    "error": None,
                },
                "interrupted": None,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TixHttpAdapter("https://tix.test/api", token="token-1", client=client)
    handle = RunHandle(
        run_id="ticket-1", case_id="case-1", interrupted=True, interrupt_id="thread-1"
    )

    with pytest.raises(HttpAdapterError, match="run_duration_s"):
        await adapter.resume(handle, "approve")
    await client.aclose()


@pytest.mark.anyio
async def test_resume_surfaces_structured_business_error_in_http_200() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": {
                    "ticket_id": "ticket-1",
                    "thread_id": None,
                    "completed": False,
                    "last_node": "resume",
                    "error": "thread_ticket_mismatch: wrong ticket",
                },
                "interrupted": None,
                "thread_id": None,
                "run_duration_s": 0.1,
                "degraded_count": 0,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TixHttpAdapter("https://tix.test/api", token="token-1", client=client)
    handle = RunHandle(
        run_id="ticket-1", case_id="case-1", interrupted=True, interrupt_id="thread-1"
    )

    with pytest.raises(HttpAdapterError, match="thread_ticket_mismatch") as error:
        await adapter.resume(handle, "approve")
    await client.aclose()

    assert error.value.status_code == 200
    assert error.value.classification == "business"


@pytest.mark.anyio
async def test_probe_does_not_accept_unchanged_ticket_from_http_200() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "ticket": {"id": "ticket-1", "status": "pending_approval"},
                    "events": [],
                },
            )
        return httpx.Response(
            200,
            json={
                "ticket": {"id": "ticket-1", "status": "pending_approval"},
                "events": [],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TixHttpAdapter("https://tix.test/api", token="token-1", client=client)
    probe = await adapter.probe_transition(
        RunHandle(run_id="ticket-1", case_id="case-1"), "close"
    )
    await client.aclose()

    assert probe.accepted is False
    assert [request.method for request in requests] == ["POST"]


@pytest.mark.anyio
async def test_resume_uses_ticket_and_thread_id() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/resume"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "ticket_id": "ticket-1",
                        "thread_id": None,
                        "completed": True,
                        "last_node": "collect_feedback",
                        "error": None,
                    },
                    "interrupted": None,
                    "thread_id": None,
                    "run_duration_s": 0.1,
                    "degraded_count": 0,
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TixHttpAdapter("https://tix.test/api", token="token-1", client=client)
    handle = RunHandle(
        run_id="ticket-1", case_id="case-1", interrupted=True, interrupt_id="thread-1"
    )

    resumed = await adapter.resume(
        handle, "approve", actor="supervisor", comment="approved"
    )
    await client.aclose()

    assert not resumed.interrupted
    assert requests[0].url.path == "/api/tickets/ticket-1/resume"
    assert json.loads(requests[0].content) == {
        "thread_id": "thread-1",
        "action": "approve",
        "actor": "supervisor",
        "comment": "approved",
    }


@pytest.mark.anyio
async def test_probe_returns_structured_business_rejection_without_calling_it_success() -> (
    None
):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={"code": "TICKET_LOCKED", "detail": "approval required"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TixHttpAdapter("https://tix.test/api", token="token-1", client=client)
    handle = RunHandle(run_id="ticket-1", case_id="case-1")

    probe = await adapter.probe_transition(handle, "close")
    await client.aclose()

    assert not probe.accepted
    assert probe.status_code == 409
    assert probe.code == "TICKET_LOCKED"
    assert probe.detail == "approval required"


def test_rejects_remote_cleartext_url() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        TixHttpAdapter("http://tix.example.test", token="token-1")


def test_allows_local_cleartext_url_for_development() -> None:
    adapter = TixHttpAdapter("http://127.0.0.1:8000", token="token-1")
    assert adapter._base_url == "http://127.0.0.1:8000/api"


@pytest.mark.parametrize(
    "url",
    [
        "https://tix.example.test/api?tenant=one",
        "https://user:password@tix.example.test",
        "https://tix.example.test/api#fragment",
    ],
)
def test_rejects_ambiguous_base_url(url: str) -> None:
    with pytest.raises(ValueError):
        TixHttpAdapter(url, token="token-1")


@pytest.mark.anyio
async def test_root_url_is_normalized_to_tix_api_prefix() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            409, json={"code": "TICKET_LOCKED", "detail": "approval required"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TixHttpAdapter("https://tix.test", token="token-1", client=client)
    await adapter.probe_transition(
        RunHandle(run_id="ticket-1", case_id="case-1"), "close"
    )
    await client.aclose()

    assert requests[0].url.path == "/api/tickets/ticket-1/transition"


@pytest.mark.anyio
async def test_patch_probe_uses_public_ticket_endpoint() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            409, json={"code": "TICKET_LOCKED", "detail": "approval required"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TixHttpAdapter("https://tix.test/api", token="token-1", client=client)
    probe = await adapter.probe_patch(
        RunHandle(run_id="ticket-1", case_id="case-1"), {"title": "mutated"}
    )
    await client.aclose()

    assert not probe.accepted
    assert requests[0].method == "PATCH"
    assert requests[0].url.path == "/api/tickets/ticket-1"
    assert "/runs" not in requests[0].url.path


@pytest.mark.anyio
async def test_structured_schema_errors_expose_classification_and_cleanup_is_noop() -> (
    None
):
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(202, json={"run_status": "started"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TixHttpAdapter("https://tix.test/api", token="token-1", client=client)
    case = Case.model_validate({"id": "case-1", "expected": {"final_status": "closed"}})

    with pytest.raises(HttpAdapterError) as error:
        await adapter.submit(await adapter.prepare(case))
    await adapter.cleanup(RunHandle(run_id="ticket-1", case_id="case-1"))
    await client.aclose()

    assert error.value.classification == "schema"
    assert error.value.endpoint == "/tickets"
    assert "/runs/ticket-1" not in requests


@pytest.mark.anyio
async def test_login_error_preserves_server_code() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"code": "INVALID_CREDENTIALS", "detail": "invalid"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TixHttpAdapter(
        "https://tix.test/api", username="u", password="p", client=client
    )

    with pytest.raises(HttpAdapterError) as error:
        await adapter.login()
    await client.aclose()

    assert error.value.classification == "http"
    assert error.value.status_code == 401
    assert error.value.code == "INVALID_CREDENTIALS"


@pytest.mark.anyio
async def test_discover_interrupt_rejects_mismatched_ticket_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/tickets":
            return httpx.Response(
                202, json={"ticket_id": "ticket-1", "run_status": "started"}
            )
        if request.method == "GET" and request.url.path == "/api/tickets/ticket-1":
            return httpx.Response(
                200,
                json={
                    "ticket": {
                        "id": "foreign-ticket",
                        "status": "pending_approval",
                        "thread_id": "thread-1",
                    },
                    "events": [],
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TixHttpAdapter(
        "https://tix.test/api", token="token-1", client=client, timeout=1.0
    )
    case = Case.model_validate({"id": "case-1", "expected": {"final_status": "closed"}})

    with pytest.raises(HttpAdapterError, match="response ticket id does not match"):
        await adapter.submit(await adapter.prepare(case))
    await client.aclose()


@pytest.mark.anyio
async def test_resume_rejects_mismatched_ticket_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": {
                    "ticket_id": "other-ticket",
                    "thread_id": "thread-2",
                    "completed": False,
                    "last_node": "await_review",
                    "error": None,
                },
                "interrupted": {
                    "interrupt_type": "resolution_review",
                    "ticket_id": "ticket-1",
                    "thread_id": "thread-2",
                    "context": {},
                },
                "thread_id": "thread-2",
                "run_duration_s": 0.1,
                "degraded_count": 0,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TixHttpAdapter("https://tix.test/api", token="token-1", client=client)
    handle = RunHandle(
        run_id="ticket-1", case_id="case-1", interrupted=True, interrupt_id="thread-1"
    )

    with pytest.raises(HttpAdapterError, match="result ticket_id does not match"):
        await adapter.resume(handle, "approve")
    await client.aclose()


@pytest.mark.anyio
async def test_resume_rejects_inconsistent_completed_without_interruption() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": {
                    "ticket_id": "ticket-1",
                    "thread_id": "thread-1",
                    "completed": False,
                    "last_node": "classify",
                    "error": None,
                },
                "interrupted": None,
                "thread_id": None,
                "run_duration_s": 0.1,
                "degraded_count": 0,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TixHttpAdapter("https://tix.test/api", token="token-1", client=client)
    handle = RunHandle(
        run_id="ticket-1", case_id="case-1", interrupted=True, interrupt_id="thread-1"
    )

    with pytest.raises(
        HttpAdapterError, match="incomplete run must include an interrupted object"
    ):
        await adapter.resume(handle, "approve")
    await client.aclose()


def test_rejects_non_positive_poll_interval() -> None:
    with pytest.raises(ValueError, match="poll_interval"):
        TixHttpAdapter("https://tix.test/api", token="token-1", poll_interval=0)
    with pytest.raises(ValueError, match="poll_interval"):
        TixHttpAdapter("https://tix.test/api", token="token-1", poll_interval=-1.0)
