"""Tests for deterministic retrieval metrics."""

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
