"""Tests for the tix retrieval adapter boundary."""

from collections.abc import Sequence
from typing import Any

import pytest

from deskbench.adapters.tix_retrieval import TixRetrievalAdapter


class RetrievalClient:
    async def search(
        self,
        query: str,
        *,
        min_score: float,
        candidate_length: int,
        parameters: dict[str, Any],
    ) -> Sequence[dict[str, Any]]:
        assert query == "database timeout"
        assert min_score == 0.4
        assert candidate_length == 3
        assert parameters["rrf_weight"] == 0.7
        return [{"id": "kb-1", "score": 0.9, "source": "knowledge"}]


@pytest.mark.anyio
async def test_retrieval_adapter_preserves_experiment_parameters() -> None:
    adapter = TixRetrievalAdapter(
        RetrievalClient(),
        min_score=0.4,
        candidate_length=3,
        parameters={"rrf_weight": 0.7},
    )

    result = await adapter.search("q1", "database timeout")

    assert result.query_id == "q1"
    assert result.document_ids == ["kb-1"]
    assert result.scores == [0.9]
    assert result.parameters["candidate_length"] == 3
