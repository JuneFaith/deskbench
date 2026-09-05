"""Adapters for service-desk systems under evaluation."""

from deskbench.adapters.base import AgentAdapter, PreparedRun, RunHandle
from deskbench.adapters.tix_retrieval import (
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
