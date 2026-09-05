"""Opt-in real retrieval integration checks against Tix hybrid search."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from servicedeskbench.adapters.base import RunHandle
from servicedeskbench.adapters.tix_http import TixHttpAdapter
from servicedeskbench.adapters.tix_retrieval import (
    TixHttpRetrievalClient,
    TixRetrievalAdapter,
)
from servicedeskbench.scorers.retrieval import (
    RetrievalExample,
    RetrievalResult,
    score_retrieval,
)


class TixLocalHybridRetrievalClient:
    """Connect Tix's hybrid search to the ServiceDeskBench retrieval adapter protocol."""

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
    ) -> list[dict[str, Any]]:
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


@pytest.mark.integration
@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_tix_hybrid_retrieval_real_integration() -> None:
    """Evaluate real Tix hybrid retrieval against the labeled queries dataset."""
    config_path = os.environ.get("SERVICEDESKBENCH_TIX_CONFIG")
    tix_url = os.environ.get("SERVICEDESKBENCH_TIX_URL")
    if not tix_url and (not config_path or not Path(config_path).is_file()):
        pytest.skip(
            "SERVICEDESKBENCH_TIX_URL or SERVICEDESKBENCH_TIX_CONFIG required for retrieval integration"
        )

    queries_path = (
        Path(__file__).parents[1] / "datasets" / "servicedesk_v1" / "rag_queries.yaml"
    )
    if not queries_path.is_file():
        pytest.skip("rag_queries.yaml not found")

    raw_data = yaml.safe_load(queries_path.read_text(encoding="utf-8"))
    queries = raw_data.get("queries", [])[:10]  # 取前 10 条真实 query 进行集成验收

    ticket_client: Any
    if tix_url:
        token = os.environ.get("SERVICEDESKBENCH_TIX_TOKEN")
        if not token and os.environ.get("SERVICEDESKBENCH_TIX_USERNAME"):
            http_adapter = TixHttpAdapter(
                tix_url,
                username=os.environ.get("SERVICEDESKBENCH_TIX_USERNAME"),
                password=os.environ.get("SERVICEDESKBENCH_TIX_PASSWORD"),
            )
            token = await http_adapter.login()
            await http_adapter.cleanup(RunHandle(run_id="init", case_id="init"))
        ticket_client = TixHttpRetrievalClient(tix_url, token=token, source="ticket")
    else:
        assert config_path is not None
        ticket_client = TixLocalHybridRetrievalClient(config_path, source="ticket")
    adapter = TixRetrievalAdapter(ticket_client, min_score=0.4, candidate_length=5)

    examples: list[RetrievalExample] = []
    results: list[RetrievalResult] = []

    try:
        for q in queries:
            qid = q["id"]
            expected = set(q.get("expected_tickets", []))
            if not expected:
                continue
            examples.append(
                RetrievalExample(
                    query_id=qid,
                    relevant_ids=expected,
                    topic=q.get("theme", "general"),
                )
            )
            res = await adapter.search(qid, q["text"])
            results.append(
                RetrievalResult(
                    query_id=qid,
                    document_ids=res.document_ids,
                )
            )

        score = score_retrieval(examples, results)
        assert score.recall_at_5 >= 0.8, (
            f"Recall@5 should be >= 0.8, got {score.recall_at_5}"
        )
        assert score.mrr >= 0.7, f"MRR should be >= 0.7, got {score.mrr}"
        assert score.passed is True
    finally:
        await ticket_client.close()
