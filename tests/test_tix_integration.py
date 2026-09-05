"""Opt-in black-box checks against a deployed Tix service."""

import os
from pathlib import Path

import pytest
import yaml

from deskbench.adapters.tix_http import TixHttpAdapter
from deskbench.contracts import Case


@pytest.mark.integration
@pytest.mark.anyio
async def test_tix_http_approval_black_box_requires_deployment() -> None:
    """Run the approval workflow only when a complete deployment is configured."""
    tix_url = os.environ.get("DESKBENCH_TIX_URL") or os.environ.get(
        "SERVICEDESKBENCH_TIX_URL"
    )
    username = os.environ.get("DESKBENCH_TIX_USERNAME") or os.environ.get(
        "SERVICEDESKBENCH_TIX_USERNAME"
    )
    password = os.environ.get("DESKBENCH_TIX_PASSWORD") or os.environ.get(
        "SERVICEDESKBENCH_TIX_PASSWORD"
    )
    missing = [
        name
        for name, val in [
            ("TIX_URL", tix_url),
            ("TIX_USERNAME", username),
            ("TIX_PASSWORD", password),
        ]
        if not val
    ]
    if missing:
        pytest.skip(
            "deployment required; missing "
            + ", ".join(f"DESKBENCH_{k}/SERVICEDESKBENCH_{k}" for k in missing)
        )

    assert tix_url and username and password
    adapter = TixHttpAdapter(
        tix_url,
        username=username,
        password=password,
        poll_interval=0.5,
    )
    fixture = (
        Path(__file__).parents[1] / "datasets" / "servicedesk_v1" / "approval.yaml"
    )
    case = Case.model_validate(yaml.safe_load(fixture.read_text(encoding="utf-8"))[0])
    await adapter.login()
    handle = await adapter.submit(await adapter.prepare(case))
    try:
        pending = await adapter.wait_for_status(
            handle,
            {"pending_approval", "pending_review", "closed", "escalated", "cancelled"},
        )
        assert pending.final_state.status == "pending_approval", (
            "approval case must enter dispatch approval; "
            f"observed {pending.final_state.status}"
        )
        assert any(
            event.raw.get("detail", {}).get("approval_type") == "dispatch"
            or event.raw.get("detail", {}).get("event") == "request_dispatch_approval"
            for event in pending.trace.events
        )

        approval_windows = 0
        current = pending
        while current.final_state.status in {"pending_approval", "pending_review"}:
            approval_windows += 1
            probe = await adapter.probe_transition(handle, "close")
            assert not probe.accepted
            assert probe.status_code in {409, 422}
            patch_probe = await adapter.probe_patch(
                handle, {"title": "must remain locked"}
            )
            assert not patch_probe.accepted
            assert patch_probe.status_code in {409, 422}
            handle = await adapter.resume(
                handle,
                "approve",
                actor=username,
                comment="deskbench approval MVP",
            )
            current = await adapter.wait_for_status(
                handle,
                {
                    "closed",
                    "escalated",
                    "pending_review",
                    "pending_approval",
                    "cancelled",
                },
            )
            if approval_windows == 1:
                assert current.final_state.status == "pending_review"
                assert any(
                    event.raw.get("detail", {}).get("approval_type") == "resolution"
                    or event.raw.get("detail", {}).get("event")
                    == "request_resolution_review"
                    for event in current.trace.events
                )

        assert approval_windows == 2
        assert current.final_state.status == "closed"
        assert current.final_state.assigned is True
        assert current.final_state.resolution
        assert current.trace.events
    finally:
        await adapter.cleanup(handle)
