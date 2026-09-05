"""Adapters for service-desk systems under evaluation."""

from servicedeskbench.adapters.base import AgentAdapter, PreparedRun, RunHandle
from servicedeskbench.adapters.tix_retrieval import (
    RetrievalResult,
    TixRetrievalAdapter,
)

__all__ = [
    "AgentAdapter",
    "PreparedRun",
    "RetrievalResult",
    "RunHandle",
    "TixRetrievalAdapter",
]
