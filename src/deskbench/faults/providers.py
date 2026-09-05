"""Inject controlled failures around evaluation-side dependencies."""

from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

from deskbench.contracts import FaultMode, FaultPlan

T = TypeVar("T")


class FaultInjected(RuntimeError):
    """A planned dependency failure."""


class FaultProvider(Generic[T]):
    """Wrap one async operation with a one-shot fault plan."""

    def __init__(self, plan: FaultPlan, operation: Callable[[], Awaitable[T]]) -> None:
        self._plan = plan
        self._operation = operation
        self._injected = False

    async def run(self) -> T:
        """Inject the configured failure, then call the dependency."""
        if self._plan.mode != FaultMode.NONE and not self._injected:
            self._injected = True
            if self._plan.mode == FaultMode.TIMEOUT:
                raise TimeoutError(f"planned {self._plan.component.value} timeout")
            raise FaultInjected(
                f"planned {self._plan.component.value} {self._plan.mode.value}"
            )
        return await self._operation()
