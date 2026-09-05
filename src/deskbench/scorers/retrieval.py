"""Deterministic retrieval quality metrics."""

from collections.abc import Sequence
from math import log2

from pydantic import BaseModel, ConfigDict, Field


class RetrievalExample(BaseModel):
    """One labeled retrieval query."""

    model_config = ConfigDict(extra="forbid")

    query_id: str
    relevant_ids: set[str] = Field(default_factory=set)
    negative_ids: set[str] = Field(default_factory=set)
    authoritative_ids: set[str] = Field(default_factory=set)
    topic: str = "unknown"


class RetrievalResult(BaseModel):
    """Ranked document IDs returned for one query."""

    model_config = ConfigDict(extra="forbid")

    query_id: str
    document_ids: list[str] = Field(default_factory=list)


class RetrievalScore(BaseModel):
    """Aggregate retrieval metrics and leakage evidence."""

    model_config = ConfigDict(extra="forbid")

    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    precision_at_5: float
    mrr: float
    ndcg_at_5: float
    negative_leakage: float
    topic_breakdown: dict[str, dict[str, float]]
    passed: bool


def score_retrieval(
    examples: Sequence[RetrievalExample],
    results: Sequence[RetrievalResult],
) -> RetrievalScore:
    """Compute rank metrics and reject negative-document leakage."""
    by_id = {result.query_id: result for result in results}
    metrics = [_metrics(example, by_id.get(example.query_id)) for example in examples]
    count = max(len(metrics), 1)
    topic_breakdown: dict[str, dict[str, float]] = {}
    for example, metric in zip(examples, metrics, strict=False):
        bucket = topic_breakdown.setdefault(
            example.topic, {"count": 0.0, "recall_at_3": 0.0}
        )
        bucket["count"] += 1
        bucket["recall_at_3"] += metric["recall_at_3"]
    for bucket in topic_breakdown.values():
        bucket["recall_at_3"] /= bucket["count"]
    return RetrievalScore(
        recall_at_1=sum(m["recall_at_1"] for m in metrics) / count,
        recall_at_3=sum(m["recall_at_3"] for m in metrics) / count,
        recall_at_5=sum(m["recall_at_5"] for m in metrics) / count,
        precision_at_5=sum(m["precision_at_5"] for m in metrics) / count,
        mrr=sum(m["mrr"] for m in metrics) / count,
        ndcg_at_5=sum(m["ndcg_at_5"] for m in metrics) / count,
        negative_leakage=sum(m["negative_leakage"] for m in metrics) / count,
        topic_breakdown=topic_breakdown,
        passed=not any(m["negative_leakage"] for m in metrics),
    )


def _metrics(
    example: RetrievalExample, result: RetrievalResult | None
) -> dict[str, float]:
    ids = result.document_ids if result else []
    relevant = example.relevant_ids
    reciprocal_rank = 0.0
    for rank, document_id in enumerate(ids, start=1):
        if document_id in relevant:
            reciprocal_rank = 1 / rank
            break
    top_five = ids[:5]
    gains = [1 if document_id in relevant else 0 for document_id in top_five]
    ideal = sorted(gains, reverse=True)
    dcg = sum(gain / log2(rank + 1) for rank, gain in enumerate(gains, start=1))
    ideal_dcg = sum(gain / log2(rank + 1) for rank, gain in enumerate(ideal, start=1))
    return {
        "recall_at_1": float(bool(set(ids[:1]) & relevant)),
        "recall_at_3": float(bool(set(ids[:3]) & relevant)),
        "recall_at_5": float(bool(set(ids[:5]) & relevant)),
        "precision_at_5": sum(gains) / 5,
        "mrr": reciprocal_rank,
        "ndcg_at_5": dcg / ideal_dcg if ideal_dcg else 0.0,
        "negative_leakage": float(bool(set(ids[:5]) & example.negative_ids)),
    }
