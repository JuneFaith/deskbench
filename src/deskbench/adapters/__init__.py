"""Adapters for service-desk systems under evaluation."""

from deskbench.adapters.base import (
    AgentAdapter,
    PreparedRun,
    RunHandle,
    adapter_supports_fault,
)
from deskbench.adapters.java_assistant import JavaAssistantSseAdapter
from deskbench.adapters.tix_retrieval import (
    RetrievalResult,
    TixRetrievalAdapter,
)

__all__ = [
    "AgentAdapter",
    "JavaAssistantSseAdapter",
    "PreparedRun",
    "RetrievalResult",
    "RunHandle",
    "TixRetrievalAdapter",
    "adapter_supports_fault",
]
