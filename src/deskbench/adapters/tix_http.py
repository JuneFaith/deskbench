"""HTTP boundary for the public Tix ticket API.

Tix is treated as an external system under test.  A ticket id is the business
handle; a thread id returned by ticket detail is the approval resume handle.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from time import monotonic
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import anyio
import httpx
from pydantic import BaseModel, ConfigDict, Field

from deskbench.adapters.base import AgentAdapter, PreparedRun, RunHandle
from deskbench.contracts import AgentRun, CanonicalState, Case
from deskbench.contracts.cases import FaultComponent, FaultMode, FaultPlan
from deskbench.trace import normalize_trace


class HttpAdapterError(RuntimeError):
    """An HTTP, transport, or response-schema error at the Tix boundary."""

    def __init__(
        self,
        status_code: int,
        endpoint: str,
        detail: str,
        *,
        code: str | None = None,
        classification: str = "http",
    ) -> None:
        message = f"HTTP {status_code} {endpoint}: {detail}"
        super().__init__(message)
        self.status_code = status_code
        self.endpoint = endpoint
        self.detail = detail
        self.code = code
        self.classification = classification


class HttpProbeResult(BaseModel):
    """Evidence from a deliberate business-rule probe."""

    model_config = ConfigDict(extra="forbid")

    accepted: bool
    status_code: int
    endpoint: str
    code: str | None = None
    detail: str | None = None
    response: dict[str, Any] = Field(default_factory=dict)


class TixHttpAdapter(AgentAdapter):
    """Adapt Tix's public ticket endpoints to canonical benchmark models.

    Args:
        base_url: Tix API root, normally ending in ``/api``.
        token: Existing bearer token.  A username/password pair may be used
            instead by passing them as keyword arguments and calling ``login``.
        username: Optional Tix login username.
        password: Optional Tix login password.  It is never persisted.
        client: Optional injected client for protocol tests.
        timeout: Per-request timeout in seconds.
        poll_interval: Delay between bounded status polls.
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        username: str | None = None,
        password: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
    ) -> None:
        normalized_url = base_url.rstrip("/")
        _validate_base_url(normalized_url)
        if not normalized_url.endswith("/api"):
            normalized_url = f"{normalized_url}/api"
        self._base_url = normalized_url
        self._token = token
        self._username = username
        self._password = password
        self._client = client
        self._owned_client: httpx.AsyncClient | None = None
        if poll_interval <= 0:
            raise ValueError("poll_interval must be greater than 0")
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._submit_timeout = timeout if timeout < 30.0 else max(timeout, 60.0)

    def supports_fault(self, fault: FaultPlan) -> bool:
        """TixHttpAdapter operates against a black-box HTTP deployment.

        It supports client-level interaction faults (such as duplicate_resume),
        but does not support server-side in-process component faults (such as
        LLM timeout or Embedding service unavailable).
        """
        if fault.component == FaultComponent.NONE or fault.mode == FaultMode.NONE:
            return True
        if fault.mode == FaultMode.DUPLICATE_RESUME:
            return True
        return False

    async def login(self) -> str:
        """Authenticate with Tix and retain the returned bearer token."""
        if not self._username or self._password is None:
            if self._token:
                return self._token
            raise ValueError("username and password are required when token is absent")
        payload = await self._request(
            "POST",
            "/auth/login",
            json={"username": self._username, "password": self._password},
            authenticate=False,
        )
        self._token = _required_string(payload, "access_token", "/auth/login")
        return self._token

    async def prepare(self, case: Case) -> PreparedRun:
        """Prepare the public Tix create-ticket payload without network I/O."""
        return PreparedRun(case=case, context={"request_id": str(uuid4())})

    async def submit(self, prepared: PreparedRun) -> RunHandle:
        """Create a Tix ticket and use its ``ticket_id`` as the run handle."""
        payload = dict(prepared.case.input)
        if prepared.case.title and "title" not in payload:
            payload["title"] = prepared.case.title
        response = await self._request("POST", "/tickets", json=payload)
        ticket_id = _required_string(response, "ticket_id", "/tickets")
        handle = RunHandle(run_id=ticket_id, case_id=prepared.case.id)
        return await self._discover_interrupt(handle, timeout=self._submit_timeout)

    async def result(self, handle: RunHandle) -> AgentRun:
        """Read ticket detail and normalize ticket/event evidence."""
        detail = await self._ticket_detail(handle.run_id)
        ticket = _mapping(detail.get("ticket"), "/tickets/{id} ticket")
        if ticket.get("id") != handle.run_id:
            raise HttpAdapterError(
                200,
                f"/tickets/{handle.run_id}",
                "response ticket id does not match requested ticket id",
                classification="schema",
            )
        events = detail.get("events", [])
        if not isinstance(events, list):
            raise HttpAdapterError(
                200,
                f"/tickets/{handle.run_id}",
                "events must be a list",
                classification="schema",
            )
        return AgentRun(
            run_id=handle.run_id,
            case_id=handle.case_id,
            adapter="tix_http",
            final_state=_canonical_state(ticket, events=events),
            trace=normalize_trace([_event_mapping(event) for event in events]),
            error=_optional_string(detail.get("error")),
        )

    async def resume(
        self,
        handle: RunHandle,
        action: str,
        *,
        actor: str = "system",
        comment: str | None = None,
    ) -> RunHandle:
        """Resume the ticket's pending graph using its thread id."""
        thread_id = handle.interrupt_id
        if not thread_id:
            detail = await self._ticket_detail(handle.run_id)
            ticket = _mapping(detail.get("ticket"), "/tickets/{id} ticket")
            thread_id = _optional_string(ticket.get("thread_id"))
        if not thread_id:
            raise HttpAdapterError(
                422,
                f"/tickets/{handle.run_id}/resume",
                "thread_id is required for resume",
                classification="schema",
            )
        deadline = monotonic() + self._submit_timeout
        while True:
            try:
                response = await self._request(
                    "POST",
                    f"/tickets/{handle.run_id}/resume",
                    json={
                        "thread_id": thread_id,
                        "action": action,
                        "actor": actor,
                        "comment": comment,
                    },
                )
                break
            except HttpAdapterError as error:
                if error.status_code == 409 and monotonic() < deadline:
                    await anyio.sleep(min(self._poll_interval, 0.2))
                    continue
                raise
        endpoint = f"/tickets/{handle.run_id}/resume"
        _validate_run_response(response, endpoint, expected_ticket_id=handle.run_id)
        result = _graph_result(response, endpoint, expected_ticket_id=handle.run_id)
        if result["error"]:
            if not handle.interrupted:
                # Out-of-band or duplicate resume was rejected by the server as expected.
                return handle.model_copy(update={"interrupted": False})
            raise HttpAdapterError(
                200,
                f"/tickets/{handle.run_id}/resume",
                result["error"],
                classification="business",
            )
        interruption = response.get("interrupted")
        if result["completed"] and interruption is not None:
            raise HttpAdapterError(
                200,
                endpoint,
                "completed run must not include an interrupted object",
                classification="schema",
            )
        if not result["completed"] and interruption is None:
            raise HttpAdapterError(
                200,
                endpoint,
                "incomplete run must include an interrupted object",
                classification="schema",
            )
        next_thread = _optional_string(response.get("thread_id")) or result["thread_id"]
        if interruption is not None:
            interrupt_thread = _optional_string(interruption.get("thread_id"))
            next_thread = interrupt_thread or next_thread
        if interruption is not None and not next_thread:
            raise HttpAdapterError(
                200,
                f"/tickets/{handle.run_id}/resume",
                "interrupted response is missing thread_id",
                classification="schema",
            )
        return handle.model_copy(
            update={
                "interrupted": interruption is not None,
                "interrupt_id": next_thread or handle.interrupt_id,
            }
        )

    async def probe_transition(
        self, handle: RunHandle, transition: str, **fields: Any
    ) -> HttpProbeResult:
        """Probe a normal transition and return business rejection evidence.

        A successful HTTP response is not interpreted as business success: the
        response is inspected for the returned ticket status and the caller can
        assert whether the requested transition actually took effect.
        """
        return await self._probe(
            "POST",
            f"/tickets/{handle.run_id}/transition",
            json={"transition": transition, **fields},
        )

    async def probe_patch(
        self, handle: RunHandle, fields: Mapping[str, Any]
    ) -> HttpProbeResult:
        """Probe a ticket mutation and preserve a rejection as structured evidence."""
        return await self._probe(
            "PATCH", f"/tickets/{handle.run_id}", json=dict(fields)
        )

    async def wait_for_status(
        self,
        handle: RunHandle,
        statuses: set[str] | frozenset[str],
        *,
        timeout: float = 60.0,
    ) -> AgentRun:
        """Poll ticket detail until a status is observed or the deadline expires."""
        deadline = monotonic() + timeout
        latest: AgentRun | None = None
        while True:
            latest = await self.result(handle)
            if latest.final_state.status in statuses:
                return latest
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise HttpAdapterError(
                    408,
                    f"/tickets/{handle.run_id}",
                    f"status did not reach {sorted(statuses)}; last={latest.final_state.status}",
                    classification="timeout",
                )
            await anyio.sleep(min(self._poll_interval, remaining))

    async def cleanup(self, handle: RunHandle) -> None:
        """Close an owned client; ticket cleanup belongs to the deployment.

        Tix exposes no public ``DELETE /runs`` or benchmark cleanup endpoint.
        Tests therefore use a dedicated deployment/database whose lifecycle
        performs isolation and cleanup outside this Adapter.
        """
        del handle
        await self._close_owned_client()

    async def _ticket_detail(self, ticket_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/tickets/{ticket_id}")

    async def _discover_interrupt(
        self, handle: RunHandle, *, timeout: float
    ) -> RunHandle:
        deadline = monotonic() + timeout
        while True:
            detail = await self._ticket_detail(handle.run_id)
            ticket = _mapping(detail.get("ticket"), f"/tickets/{handle.run_id}")
            if ticket.get("id") != handle.run_id:
                raise HttpAdapterError(
                    200,
                    f"/tickets/{handle.run_id}",
                    "response ticket id does not match requested ticket id",
                    classification="schema",
                )
            thread_id = _optional_string(ticket.get("thread_id"))
            status = _optional_string(ticket.get("status"))
            if status in {"pending_approval", "pending_review"}:
                if not thread_id:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise HttpAdapterError(
                            200,
                            f"/tickets/{handle.run_id}",
                            "approval state is missing thread_id",
                            classification="schema",
                        )
                    await anyio.sleep(min(self._poll_interval, remaining))
                    continue
                return handle.model_copy(
                    update={"interrupted": True, "interrupt_id": thread_id}
                )
            if status in {"closed", "escalated", "cancelled"}:
                return handle
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise HttpAdapterError(
                    408,
                    f"/tickets/{handle.run_id}",
                    f"ticket did not reach an actionable state; last={status}",
                    classification="timeout",
                )
            await anyio.sleep(min(self._poll_interval, remaining))

    async def _probe(self, method: str, path: str, **kwargs: Any) -> HttpProbeResult:
        try:
            status_code, payload = await self._request_with_status(
                method, path, **kwargs
            )
        except HttpAdapterError as error:
            return HttpProbeResult(
                accepted=False,
                status_code=error.status_code,
                endpoint=error.endpoint,
                code=error.code,
                detail=error.detail,
            )
        ticket = payload.get("ticket")
        accepted = _probe_mutation_applied(path, kwargs, ticket)
        return HttpProbeResult(
            accepted=accepted,
            status_code=status_code,
            endpoint=path,
            detail=(
                "business response did not confirm the requested mutation"
                if not accepted
                else None
            ),
            response=payload,
        )

    async def _close_owned_client(self) -> None:
        if self._owned_client is not None:
            await self._owned_client.aclose()
            self._owned_client = None

    async def _request_with_status(
        self, method: str, path: str, *, authenticate: bool = True, **kwargs: Any
    ) -> tuple[int, dict[str, Any]]:
        client = self._client
        if client is None:
            self._owned_client = self._owned_client or httpx.AsyncClient(
                trust_env=False
            )
            client = self._owned_client
        headers = dict(kwargs.pop("headers", {}))
        if (
            authenticate
            and self._token is None
            and self._username
            and self._password is not None
        ):
            await self.login()
        if authenticate and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            response = await client.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                timeout=self._timeout,
                **kwargs,
            )
        except httpx.HTTPError as error:
            raise HttpAdapterError(
                0, path, str(error), classification="transport"
            ) from error
        if response.is_error:
            code, detail = _error_fields(response)
            raise HttpAdapterError(
                response.status_code, path, detail, code=code, classification="http"
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise HttpAdapterError(
                response.status_code,
                path,
                "response is not JSON",
                classification="schema",
            ) from error
        if not isinstance(payload, dict):
            raise HttpAdapterError(
                response.status_code,
                path,
                "response must be an object",
                classification="schema",
            )
        return response.status_code, payload

    async def _request(
        self, method: str, path: str, *, authenticate: bool = True, **kwargs: Any
    ) -> dict[str, Any]:
        _status, payload = await self._request_with_status(
            method, path, authenticate=authenticate, **kwargs
        )
        return payload


def _validate_base_url(value: str) -> None:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Tix base URL must use HTTP(S) and include a host")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError(
            "Tix base URL must not include credentials, query, or fragment"
        )
    if parts.scheme == "http" and parts.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError("HTTPS is required for non-local Tix URLs")


def _validate_run_response(
    payload: Mapping[str, Any], endpoint: str, expected_ticket_id: str | None = None
) -> None:
    for key in ("run_duration_s", "degraded_count"):
        if (
            key not in payload
            or not isinstance(payload[key], (int, float))
            or isinstance(payload[key], bool)
        ):
            raise HttpAdapterError(
                200, endpoint, f"{key} must be numeric", classification="schema"
            )
    interruption = payload.get("interrupted")
    if interruption is not None:
        if not isinstance(interruption, Mapping):
            raise HttpAdapterError(
                200,
                endpoint,
                "interrupted must be an object or null",
                classification="schema",
            )
        for req_field in ("interrupt_type", "ticket_id", "thread_id"):
            val = interruption.get(req_field)
            if not isinstance(val, str) or not val.strip():
                raise HttpAdapterError(
                    200,
                    endpoint,
                    f"interrupted.{req_field} must be a non-empty string",
                    classification="schema",
                )
        if expected_ticket_id and interruption.get("ticket_id") != expected_ticket_id:
            raise HttpAdapterError(
                200,
                endpoint,
                "interrupted ticket_id does not match requested ticket id",
                classification="schema",
            )


def _graph_result(
    payload: Mapping[str, Any], endpoint: str, expected_ticket_id: str | None = None
) -> dict[str, Any]:
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise HttpAdapterError(
            200, endpoint, "result must be an object", classification="schema"
        )
    required = ("ticket_id", "thread_id", "completed", "last_node", "error")
    missing = [key for key in required if key not in result]
    if missing:
        raise HttpAdapterError(
            200,
            endpoint,
            f"result missing fields: {', '.join(missing)}",
            classification="schema",
        )
    ticket_id = _optional_string(result.get("ticket_id"))
    if not ticket_id or not isinstance(result.get("completed"), bool):
        raise HttpAdapterError(
            200, endpoint, "result has invalid fields", classification="schema"
        )
    if expected_ticket_id and ticket_id != expected_ticket_id:
        raise HttpAdapterError(
            200,
            endpoint,
            "result ticket_id does not match requested ticket id",
            classification="schema",
        )
    if result.get("error") is not None and not isinstance(result.get("error"), str):
        raise HttpAdapterError(
            200,
            endpoint,
            "result.error must be a string or null",
            classification="schema",
        )
    last_node = result.get("last_node")
    if last_node is not None and not isinstance(last_node, str):
        raise HttpAdapterError(
            200,
            endpoint,
            "result.last_node must be a string or null",
            classification="schema",
        )
    return {
        "ticket_id": ticket_id,
        "thread_id": _optional_string(result.get("thread_id")),
        "completed": result["completed"],
        "last_node": result["last_node"],
        "error": result.get("error"),
    }


def _probe_mutation_applied(path: str, kwargs: Mapping[str, Any], ticket: Any) -> bool:
    if not isinstance(ticket, Mapping):
        return False
    if path.endswith("/transition"):
        body = kwargs.get("json")
        if not isinstance(body, Mapping):
            return False
        transition = body.get("transition")
        if not isinstance(transition, str):
            return False
        expected_status = {
            "close": "closed",
            "cancel": "cancelled",
            "accept": "processing",
        }.get(transition)
        return expected_status is not None and ticket.get("status") == expected_status
    body = kwargs.get("json")
    return isinstance(body, Mapping) and all(
        ticket.get(key) == value for key, value in body.items()
    )


def _canonical_state(
    ticket: Mapping[str, Any], events: Sequence[Mapping[str, Any]] = ()
) -> CanonicalState:
    known = {
        "id",
        "title",
        "description",
        "status",
        "category",
        "priority",
        "urgency",
        "severity",
        "impact",
        "assignee",
        "resolution",
        "needs_review",
        "review_required",
        "thread_id",
    }
    raw = {key: value for key, value in ticket.items() if key not in known}
    status = _required_string(ticket, "status", "/tickets/{id}")
    is_escalated = status == "escalated"
    is_pending_review = status == "pending_review"
    canonical_needs_review = is_pending_review or (
        status not in {"closed", "cancelled", "escalated"}
        and bool(
            ticket.get("review_required", False) or ticket.get("needs_review", False)
        )
    )
    has_degraded = bool(ticket.get("degraded", False))
    if not has_degraded and events:
        has_degraded = any(
            isinstance(e.get("detail"), Mapping)
            and bool(e.get("detail", {}).get("degraded"))
            for e in events
        )
    return CanonicalState(
        status=status,
        category=_optional_string(ticket.get("category")),
        priority=_optional_string(ticket.get("priority")),
        urgency=_optional_string(ticket.get("urgency")),
        severity=_optional_string(ticket.get("severity")),
        impact=_optional_string(ticket.get("impact")),
        assignee=_optional_string(ticket.get("assignee")),
        assigned=ticket.get("assignee") is not None,
        resolution=_optional_string(ticket.get("resolution")),
        needs_review=canonical_needs_review,
        degraded=has_degraded,
        human_takeover=bool(ticket.get("human_takeover", False)) or is_escalated,
        thread_id=_optional_string(ticket.get("thread_id")),
        metadata={"ticket_id": ticket.get("id"), "raw": raw}
        if raw
        else {"ticket_id": ticket.get("id")},
    )


def _event_mapping(value: Any) -> dict[str, Any]:
    event = _mapping(value, "ticket event")
    event_type = _optional_string(event.get("event_type"))
    detail_raw = event.get("detail")
    detail_dict: Mapping[str, Any] = (
        detail_raw if isinstance(detail_raw, Mapping) else {}
    )
    if event_type == "transition":
        kind = "state_change"
    elif event_type == "system" and (
        detail_dict.get("error") or detail_dict.get("phase") == "orchestrator_failure"
    ):
        kind = "error"
    else:
        kind = {
            "agent_execution": "agent_step",
            "note": "agent_step",
            "system": "agent_step",
        }.get(event_type or "", "agent_step")
    known = {
        "id",
        "ticket_id",
        "event_type",
        "from_status",
        "to_status",
        "actor",
        "detail",
        "timestamp",
    }
    raw = {key: value for key, value in event.items() if key not in known}
    raw_payload = {
        "event_id": event.get("id"),
        "event_type": event_type,
        "detail": dict(detail_dict),
        **raw,
    }
    decision = _optional_string(detail_dict.get("approval_action"))
    if decision:
        raw_payload["decision"] = decision
    return {
        "kind": kind,
        "timestamp": event.get("timestamp"),
        "from": event.get("from_status"),
        "to": event.get("to_status"),
        "ticket_id": event.get("ticket_id"),
        "actor_id": event.get("actor"),
        "raw": raw_payload,
    }


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HttpAdapterError(
            200, label, "response must contain an object", classification="schema"
        )
    return value


def _error_fields(response: httpx.Response) -> tuple[str | None, str]:
    try:
        payload = response.json()
    except ValueError:
        return None, response.text
    if isinstance(payload, Mapping):
        code = payload.get("code")
        detail = payload.get("detail") or payload.get("message") or payload
        return _optional_string(code), str(detail)
    return None, str(payload)


def _required_string(payload: Mapping[str, Any], key: str, endpoint: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise HttpAdapterError(
            200, endpoint, f"missing non-empty {key}", classification="schema"
        )
    return value


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None
