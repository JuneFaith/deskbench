"""Opt-in real retrieval integration checks against Tix hybrid search."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from deskbench.adapters.base import RunHandle
from deskbench.adapters.tix_http import TixHttpAdapter
from deskbench.adapters.tix_retrieval import (
    TixHttpRetrievalClient,
    TixLocalHybridRetrievalClient,
    TixRetrievalAdapter,
)
from deskbench.scorers.retrieval import (
    RetrievalExample,
    RetrievalResult,
    score_retrieval,
)


@pytest.mark.integration
@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_tix_hybrid_retrieval_real_integration() -> None:
    """Evaluate real Tix hybrid retrieval against the labeled queries dataset."""
    config_path = os.environ.get("DESKBENCH_TIX_CONFIG") or os.environ.get(
        "SERVICEDESKBENCH_TIX_CONFIG"
    )
    tix_url = os.environ.get("DESKBENCH_TIX_URL") or os.environ.get(
        "SERVICEDESKBENCH_TIX_URL"
    )
    if not tix_url and (not config_path or not Path(config_path).is_file()):
        pytest.skip(
            "DESKBENCH_TIX_URL/SERVICEDESKBENCH_TIX_URL or "
            "DESKBENCH_TIX_CONFIG/SERVICEDESKBENCH_TIX_CONFIG required for retrieval integration"
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
        token = os.environ.get("DESKBENCH_TIX_TOKEN") or os.environ.get(
            "SERVICEDESKBENCH_TIX_TOKEN"
        )
        username = os.environ.get("DESKBENCH_TIX_USERNAME") or os.environ.get(
            "SERVICEDESKBENCH_TIX_USERNAME"
        )
        password = os.environ.get("DESKBENCH_TIX_PASSWORD") or os.environ.get(
            "SERVICEDESKBENCH_TIX_PASSWORD"
        )
        if not token and username:
            http_adapter = TixHttpAdapter(
                tix_url,
                username=username,
                password=password,
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


@pytest.mark.integration
@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_tix_kb_retrieval_real_integration() -> None:
    """Evaluate real Tix KB retrieval against the labeled queries dataset."""
    config_path = os.environ.get("DESKBENCH_TIX_CONFIG") or os.environ.get(
        "SERVICEDESKBENCH_TIX_CONFIG"
    )
    tix_url = os.environ.get("DESKBENCH_TIX_URL") or os.environ.get(
        "SERVICEDESKBENCH_TIX_URL"
    )
    if not tix_url and (not config_path or not Path(config_path).is_file()):
        pytest.skip(
            "DESKBENCH_TIX_URL/SERVICEDESKBENCH_TIX_URL or "
            "DESKBENCH_TIX_CONFIG/SERVICEDESKBENCH_TIX_CONFIG required for retrieval integration"
        )

    queries_path = (
        Path(__file__).parents[1] / "datasets" / "servicedesk_v1" / "rag_queries.yaml"
    )
    if not queries_path.is_file():
        pytest.skip("rag_queries.yaml not found")

    raw_data = yaml.safe_load(queries_path.read_text(encoding="utf-8"))
    queries = raw_data.get("queries", [])[:10]  # 取前 10 条真实 query 进行集成验收

    kb_client: Any
    if tix_url:
        token = os.environ.get("DESKBENCH_TIX_TOKEN") or os.environ.get(
            "SERVICEDESKBENCH_TIX_TOKEN"
        )
        username = os.environ.get("DESKBENCH_TIX_USERNAME") or os.environ.get(
            "SERVICEDESKBENCH_TIX_USERNAME"
        )
        password = os.environ.get("DESKBENCH_TIX_PASSWORD") or os.environ.get(
            "SERVICEDESKBENCH_TIX_PASSWORD"
        )
        if not token and username:
            http_adapter = TixHttpAdapter(
                tix_url,
                username=username,
                password=password,
            )
            token = await http_adapter.login()
            await http_adapter.cleanup(RunHandle(run_id="init", case_id="init"))
        kb_client = TixHttpRetrievalClient(tix_url, token=token, source="kb")
    else:
        assert config_path is not None
        kb_client = TixLocalHybridRetrievalClient(config_path, source="kb")
    adapter = TixRetrievalAdapter(kb_client, min_score=0.0, candidate_length=5)

    examples: list[RetrievalExample] = []
    results: list[RetrievalResult] = []

    try:
        for q in queries:
            qid = q["id"]
            expected = set(q.get("expected_kb_articles", []))
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
        await kb_client.close()
