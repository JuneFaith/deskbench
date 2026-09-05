"""Tests for reproducible benchmark reports."""

import json
from pathlib import Path

from servicedeskbench.contracts import (
    AgentRun,
    CanonicalState,
    CanonicalTrace,
    ExperimentMetadata,
    ScoreResult,
)
from servicedeskbench.reporting.json_report import (
    EvaluationReport,
    read_report,
    write_report,
)


def test_write_report_creates_timestamped_jsonl_and_markdown(tmp_path: Path) -> None:
    run = AgentRun(
        run_id="run-1",
        case_id="case-1",
        adapter="test",
        final_state=CanonicalState(status="closed"),
        trace=CanonicalTrace(),
    )

    paths = write_report([run], tmp_path, metadata={"dataset_version": "v1"})

    assert paths.summary.exists()
    assert paths.cases.exists()
    assert paths.markdown.exists()
    assert json.loads(paths.summary.read_text())["case_count"] == 1
    assert len(paths.cases.read_text().splitlines()) == 1


def test_report_round_trip_preserves_experiment_metadata(tmp_path: Path) -> None:
    metadata = ExperimentMetadata(
        run_id="experiment-1",
        dataset_version="v1",
        adapter="deterministic",
        model="model-a",
        prompt_version="prompt-1",
        retrieval_parameters={"candidate_length": 5},
    )
    run = AgentRun(
        run_id="run-1",
        case_id="case-1",
        adapter="deterministic",
        final_state=CanonicalState(status="closed"),
        trace=CanonicalTrace(),
    )

    paths = write_report(EvaluationReport(metadata=metadata, runs=[run]), tmp_path)
    loaded = read_report(paths.root)

    assert loaded.metadata.model == "model-a"
    assert loaded.metadata.retrieval_parameters == {"candidate_length": 5}
    assert loaded.runs[0].case_id == "case-1"


def test_summary_derives_retrieval_metrics_from_persisted_scores(
    tmp_path: Path,
) -> None:
    run = AgentRun(
        run_id="run-1",
        case_id="case-1",
        adapter="deterministic",
        final_state=CanonicalState(status="closed"),
        trace=CanonicalTrace(),
        scores=[
            ScoreResult(
                scorer="retrieval",
                passed=True,
                value=0.75,
                metrics={"recall_at_5": 0.75, "mrr": 0.5},
            )
        ],
    )

    paths = write_report([run], tmp_path)

    from servicedeskbench.reporting.summary import read_summary

    summary = read_summary(paths.summary)

    assert summary.recall_at_5 == 0.75
    assert summary.mrr == 0.5


def test_unscored_run_is_not_counted_as_passed(tmp_path: Path) -> None:
    run = AgentRun(
        run_id="run-1",
        case_id="case-1",
        adapter="deterministic",
        final_state=CanonicalState(status="closed"),
        trace=CanonicalTrace(),
    )

    paths = write_report([run], tmp_path)
    payload = json.loads(paths.summary.read_text())

    assert payload["passed_count"] == 0


def test_summary_accepts_complete_summary_without_optional_explanation(
    tmp_path: Path,
) -> None:
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "approval_bypass_rate": 0,
                "cross_ticket_resume_rate": 0,
                "degraded_false_success_rate": 0,
                "illegal_transition_rate": 0,
                "forbidden_tool_rate": 0,
                "recall_at_5": 0.8,
                "mrr": 0.7,
                "completion_rate": 0.6,
                "p95_latency_ms": 12,
                "mean_tool_calls": 3,
            }
        )
    )

    from servicedeskbench.reporting.summary import read_summary

    loaded = read_summary(summary)

    assert loaded.recall_at_5 == 0.8
    assert loaded.completion_rate == 0.6


def test_summary_accepts_report_directory(tmp_path: Path) -> None:
    run = AgentRun(
        run_id="run-1",
        case_id="case-1",
        adapter="deterministic",
        final_state=CanonicalState(status="closed"),
        trace=CanonicalTrace(),
        scores=[ScoreResult(scorer="outcome", passed=True, value=1.0)],
    )

    paths = write_report([run], tmp_path)

    from servicedeskbench.reporting.summary import read_summary

    summary = read_summary(paths.root)

    assert summary.completion_rate == 1.0
