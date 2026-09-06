"""Retrieval boundary for tix experiments."""

import asyncio
import importlib
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
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
        for attempt in range(8):
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
            if resp.status_code == 429 and attempt < 7:
                retry_after = resp.headers.get("Retry-After")
                wait_time = (
                    float(retry_after)
                    if retry_after and float(retry_after) > 0
                    else 0.6 * (attempt + 1)
                )
                await asyncio.sleep(wait_time)
                continue
            resp.raise_for_status()
            data = resp.json()
            hits = data.get("hits", [])
            return cast(Sequence[Mapping[str, Any]], hits)
        return []

    async def close(self) -> None:
        if self._owned_client is not None:
            await self._owned_client.aclose()
            self._owned_client = None


class TixLocalHybridRetrievalClient:
    """Connect Tix's local hybrid search to the deskbench retrieval adapter protocol."""

    def __init__(self, config_path: str | Path, source: str = "ticket") -> None:
        self._config_path = Path(config_path)
        self._source = source
        self._uow: Any = None
        self._engine: Any = None
        self._embedding_mgr: Any = None

    async def _ensure_initialized(self) -> None:
        if self._uow is not None:
            return
        tix_backend = self._config_path.resolve().parents[2] / "backend"
        if str(tix_backend) not in sys.path:
            sys.path.insert(0, str(tix_backend))
        for sp in (tix_backend / ".venv" / "lib").glob("python*/site-packages"):
            if str(sp) not in sys.path:
                sys.path.insert(0, str(sp))

        create_async_engine = importlib.import_module(
            "sqlalchemy.ext.asyncio"
        ).create_async_engine
        runtime_config_mod = importlib.import_module("src.core.runtime_config")
        load_runtime_config = runtime_config_mod.load_runtime_config
        set_current_runtime = runtime_config_mod.set_current_runtime
        embeddings_mod = importlib.import_module("src.llm.embeddings")
        get_embedding = embeddings_mod.get_embedding
        embedding_mgr_mod = importlib.import_module("src.services.embedding_manager")
        EmbeddingManager = embedding_mgr_mod.EmbeddingManager
        storage_impl_mod = importlib.import_module("src.storage.impl")
        PostgresUoW = storage_impl_mod.PostgresUoW

        runtime = load_runtime_config(self._config_path)
        set_current_runtime(runtime)
        self._embedding_mgr = EmbeddingManager(get_embedding(runtime))
        dsn = runtime.secret("postgres_dsn", "dsn").replace("+asyncpg", "")
        dsn = dsn.replace("postgresql://", "postgresql+asyncpg://")
        self._engine = create_async_engine(dsn)
        self._uow = PostgresUoW(self._engine)

    async def search(
        self,
        query: str,
        *,
        min_score: float,
        candidate_length: int,
        parameters: dict[str, Any],
    ) -> Sequence[Mapping[str, Any]]:
        await self._ensure_initialized()
        hybrid_search_mod = importlib.import_module("src.services.hybrid_search")
        hybrid_kb_search = hybrid_search_mod.hybrid_kb_search
        hybrid_ticket_search = hybrid_search_mod.hybrid_ticket_search

        emb = self._embedding_mgr.embed_query(query)
        if self._source == "kb":
            hits = await hybrid_kb_search(
                self._uow,
                query,
                emb,
                top_k=candidate_length,
                min_score=min_score,
            )
        else:
            hits = await hybrid_ticket_search(
                self._uow,
                query,
                emb,
                top_k=candidate_length,
                min_score=min_score,
            )
        return [
            {"id": doc_id, "score": float(score), "source": self._source}
            for doc_id, score in hits
        ]

    async def close(self) -> None:
        if self._uow is not None:
            await self._uow.close()
            self._uow = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
