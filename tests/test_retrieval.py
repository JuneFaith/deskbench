"""Tests for deterministic retrieval metrics."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from deskbench.reporting.summary import read_summary
from deskbench.retrieval import run_retrieval_evaluation
from deskbench.scorers.retrieval import (
    RetrievalExample,
    RetrievalResult,
    score_retrieval,
)


def test_retrieval_score_computes_rank_metrics_and_topic_breakdown() -> None:
    examples = [
        RetrievalExample(
            query_id="q1",
            relevant_ids={"kb-1"},
            topic="access",
            authoritative_ids={"kb-1"},
        ),
        RetrievalExample(
            query_id="q2",
            relevant_ids={"ticket-2"},
            topic="database",
            authoritative_ids=set(),
        ),
    ]
    results = [
        RetrievalResult(query_id="q1", document_ids=["kb-2", "kb-1"]),
        RetrievalResult(query_id="q2", document_ids=["ticket-2"]),
    ]

    score = score_retrieval(examples, results)

    assert score.recall_at_1 == 0.5
    assert score.recall_at_3 == 1.0
    assert score.mrr == 0.75
    assert score.topic_breakdown["access"]["recall_at_3"] == 1.0


def test_retrieval_score_detects_negative_source_leakage() -> None:
    examples = [
        RetrievalExample(
            query_id="q1",
            relevant_ids={"kb-1"},
            negative_ids={"ticket-wrong"},
            topic="security",
        )
    ]
    results = [RetrievalResult(query_id="q1", document_ids=["ticket-wrong", "kb-1"])]

    score = score_retrieval(examples, results)

    assert score.negative_leakage == 1.0
    assert score.passed is False


class MockRetrievalClient:
    """Mock retrieval client for unit tests."""

    def __init__(self, responses: dict[str, list[str]]) -> None:
        self.responses = responses
        self.searches: list[str] = []
        self.closed = False

    async def search(
        self,
        query: str,
        *,
        min_score: float,
        candidate_length: int,
        parameters: dict[str, Any],
    ) -> Sequence[Mapping[str, Any]]:
        self.searches.append(query)
        doc_ids = self.responses.get(query, [])[:candidate_length]
        return [
            {"id": doc_id, "score": 1.0 / (i + 1), "source": "mock"}
            for i, doc_id in enumerate(doc_ids)
        ]

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def sample_queries_yaml(tmp_path: Path) -> Path:
    data = {
        "queries": [
            {
                "id": "q-db-001",
                "text": "database auth error",
                "theme": "database",
                "expected_tickets": ["tkt-db-1"],
                "expected_kb_articles": ["kb-db-1"],
            },
            {
                "id": "q-sec-001",
                "text": "ssh brute force",
                "theme": "security",
                "expected_tickets": ["tkt-sec-1"],
                "expected_kb_articles": ["kb-sec-1"],
            },
            {
                "id": "q-neg-001",
                "text": "afternoon tea reimbursement",
                "theme": "unrelated",
                "expected_tickets": [],
                "expected_kb_articles": [],
            },
        ]
    }
    path = tmp_path / "queries.yaml"
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return path


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_run_retrieval_evaluation_both_sources(
    sample_queries_yaml: Path, tmp_path: Path
) -> None:
    kb_client = MockRetrievalClient(
        {
            "database auth error": ["kb-db-1", "kb-db-2"],
            "ssh brute force": ["kb-sec-1"],
            "afternoon tea reimbursement": ["kb-other"],
        }
    )
    ticket_client = MockRetrievalClient(
        {
            "database auth error": ["tkt-db-1"],
            "ssh brute force": ["tkt-sec-1"],
            "afternoon tea reimbursement": ["tkt-other"],
        }
    )

    output_dir = tmp_path / "reports"
    paths = await run_retrieval_evaluation(
        sample_queries_yaml,
        output_dir,
        source="both",
        kb_client=kb_client,
        ticket_client=ticket_client,
    )

    assert paths.summary.is_file()
    assert paths.cases.is_file()
    assert paths.markdown.is_file()

    summary = read_summary(paths.summary)
    assert summary.completion_rate == 1.0
    assert summary.recall_at_5 == 1.0
    assert summary.mrr == 1.0
    assert summary.approval_bypass_rate == 0.0

    raw_summary = yaml.safe_load(paths.summary.read_text(encoding="utf-8"))
    assert raw_summary["case_count"] == 3
    assert raw_summary["passed_count"] == 3
    assert raw_summary["kb_metrics"] is not None
    assert raw_summary["ticket_metrics"] is not None
    assert raw_summary["p95_latency_ms"] >= 0.0

    cases_text = paths.cases.read_text(encoding="utf-8")
    lines = [line for line in cases_text.splitlines() if line]
    assert len(lines) == 3

    md_text = paths.markdown.read_text(encoding="utf-8")
    assert "# Deskbench Retrieval Evaluation Report" in md_text
    assert "| Recall@5 |" in md_text
    assert "### Knowledge Base (KB)" in md_text
    assert "### Tickets" in md_text


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_run_retrieval_evaluation_single_source(
    sample_queries_yaml: Path, tmp_path: Path
) -> None:
    kb_client = MockRetrievalClient({"database auth error": ["kb-db-1"]})
    output_dir = tmp_path / "reports_kb"

    paths = await run_retrieval_evaluation(
        sample_queries_yaml,
        output_dir,
        source="kb",
        kb_client=kb_client,
    )

    raw_summary = yaml.safe_load(paths.summary.read_text(encoding="utf-8"))
    assert raw_summary["source"] == "kb"
    assert raw_summary["kb_metrics"] is not None
    assert raw_summary["ticket_metrics"] is None


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_run_retrieval_evaluation_raises_without_config(
    sample_queries_yaml: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DESKBENCH_TIX_URL", raising=False)
    monkeypatch.delenv("SERVICEDESKBENCH_TIX_URL", raising=False)
    monkeypatch.delenv("DESKBENCH_TIX_CONFIG", raising=False)
    monkeypatch.delenv("SERVICEDESKBENCH_TIX_CONFIG", raising=False)

    with pytest.raises(ValueError, match="tix URL or config is required"):
        await run_retrieval_evaluation(sample_queries_yaml, tmp_path / "reports")


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_run_retrieval_evaluation_with_mock_http_transport(
    sample_queries_yaml: Path, tmp_path: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url_path = request.url.path
        if url_path.endswith("/kb/search"):
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {"id": "kb-db-1", "score": 0.05, "source": "kb"},
                    ]
                },
            )
        if url_path.endswith("/tickets/search"):
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {"id": "tkt-db-1", "score": 0.05, "source": "ticket"},
                    ]
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        paths = await run_retrieval_evaluation(
            sample_queries_yaml,
            tmp_path / "reports_http",
            source="both",
            base_url="http://mock.tix/api",
            token="test-token",
            http_client=http_client,
        )

        raw_summary = yaml.safe_load(paths.summary.read_text(encoding="utf-8"))
        assert raw_summary["case_count"] == 3
        assert raw_summary["kb_metrics"]["recall_at_5"] >= 0.5
