"""Retrieval boundary for tix experiments."""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field


class RetrievalClient(Protocol):
    """Minimal retrieval client expected from tix."""

    async def search(
        self,
        query: str,
        *,
        min_score: float,
        candidate_length: int,
        parameters: dict[str, Any],
    ) -> Sequence[Mapping[str, Any]]: ...


class RetrievalResult(BaseModel):
    """Normalized ranked retrieval output."""

    model_config = ConfigDict(extra="forbid")

    query_id: str
    document_ids: list[str] = Field(default_factory=list)
    scores: list[float] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class TixRetrievalAdapter:
    """Adapt tix retrieval responses without exporting tix objects."""

    def __init__(
        self,
        client: RetrievalClient,
        *,
        min_score: float = 0.0,
        candidate_length: int = 5,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        self._client = client
        self._min_score = min_score
        self._candidate_length = candidate_length
        self._parameters = parameters or {}

    async def search(self, query_id: str, query: str) -> RetrievalResult:
        """Run a retrieval query and preserve its experiment parameters."""
        rows = await self._client.search(
            query,
            min_score=self._min_score,
            candidate_length=self._candidate_length,
            parameters=self._parameters,
        )
        ids: list[str] = []
        scores: list[float] = []
        sources: list[str] = []
        for row in rows:
            document_id = row.get("id")
            if not isinstance(document_id, str):
                raise ValueError("tix retrieval result is missing string id")
            ids.append(document_id)
            scores.append(float(row.get("score", 0.0)))
            sources.append(str(row.get("source", "unknown")))
        return RetrievalResult(
            query_id=query_id,
            document_ids=ids,
            scores=scores,
            sources=sources,
            parameters={
                **self._parameters,
                "min_score": self._min_score,
                "candidate_length": self._candidate_length,
            },
        )


class TixHttpRetrievalClient:
    """HTTP client for Tix search endpoints implementing RetrievalClient protocol."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        source: str = "ticket",
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        normalized_url = base_url.rstrip("/")
        if not normalized_url.endswith("/api"):
            normalized_url = f"{normalized_url}/api"
        self._base_url = normalized_url
        self._token = token
        self._source = source
        self._client = client
        self._owned_client: httpx.AsyncClient | None = None
        self._timeout = timeout

    async def search(
        self,
        query: str,
        *,
        min_score: float,
        candidate_length: int,
        parameters: dict[str, Any],
    ) -> Sequence[Mapping[str, Any]]:
        client = self._client
        if client is None:
            self._owned_client = self._owned_client or httpx.AsyncClient(
                trust_env=False
            )
            client = self._owned_client
        endpoint = "/kb/search" if self._source == "kb" else "/tickets/search"
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        resp = await client.post(
            f"{self._base_url}{endpoint}",
            headers=headers,
            json={
                "query": query,
                "top_k": candidate_length,
                "min_score": min_score,
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", [])
        return cast(Sequence[Mapping[str, Any]], hits)

    async def close(self) -> None:
        if self._owned_client is not None:
            await self._owned_client.aclose()
            self._owned_client = None
