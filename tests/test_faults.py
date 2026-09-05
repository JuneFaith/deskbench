"""Tests for evaluation-side fault plans."""

import pytest

from servicedeskbench.contracts import FaultComponent, FaultMode, FaultPlan
from servicedeskbench.faults.providers import FaultInjected, FaultProvider


def test_fault_plan_is_explicit_and_validated() -> None:
    plan = FaultPlan(component=FaultComponent.LLM, mode=FaultMode.TIMEOUT)

    assert plan.component == FaultComponent.LLM
    assert plan.once is True


@pytest.mark.anyio
async def test_fault_provider_injects_once_and_then_passes_through() -> None:
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    provider = FaultProvider(
        FaultPlan(component=FaultComponent.LLM, mode=FaultMode.ERROR), operation
    )

    with pytest.raises(FaultInjected, match="llm"):
        await provider.run()
    assert await provider.run() == "ok"
    assert calls == 1
