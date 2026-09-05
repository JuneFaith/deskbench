"""Tests for the Deskbench command line interface."""

import json
from pathlib import Path

import pytest
from pytest import CaptureFixture

from deskbench.cli import build_parser, main


def test_cli_exposes_run_score_and_gate_commands() -> None:
    parser = build_parser()

    assert parser.parse_args(["run", "--dataset", "cases.yaml"]).command == "run"
    assert parser.parse_args(["score", "--report", "summary.json"]).command == "score"
    assert parser.parse_args(["gate", "--report", "summary.json"]).command == "gate"


def test_cli_run_loads_dataset_and_reports_a_structured_error_without_adapter(
    tmp_path: Path, capsys: object
) -> None:
    dataset = tmp_path / "cases.yaml"
    dataset.write_text("- id: case-1\n  expected:\n    final_status: closed\n")

    exit_code = main(["run", "--dataset", str(dataset), "--adapter", "http", "--json"])

    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert output["error"]["code"] == "missing_tix_url"


def test_cli_score_reads_a_report_summary(tmp_path: Path, capsys: object) -> None:
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"case_count": 2, "passed_count": 1}))

    exit_code = main(["score", "--report", str(summary)])

    assert exit_code == 0
    assert "1/2" in capsys.readouterr().out  # type: ignore[attr-defined]


def test_cli_score_accepts_report_directory(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    report = tmp_path / "report"
    report.mkdir()
    (report / "summary.json").write_text(
        json.dumps({"case_count": 2, "passed_count": 2})
    )

    assert main(["score", "--report", str(report)]) == 0
    assert "2/2" in capsys.readouterr().out


def test_cli_gate_returns_structured_error_for_missing_report(
    capsys: CaptureFixture[str],
) -> None:
    exit_code = main(["gate", "--report", "/missing/report"])

    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["error"]["code"] == "evaluation_error"


def test_cli_invalid_arguments_return_structured_error(
    capsys: CaptureFixture[str],
) -> None:
    exit_code = main(["gate"])

    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["error"]["code"] == "evaluation_error"


def test_cli_gate_emits_json_when_requested(
    tmp_path: Path, capsys: CaptureFixture[str]
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
                "recall_at_5": 1,
                "mrr": 1,
                "completion_rate": 1,
                "p95_latency_ms": 1,
                "mean_tool_calls": 1,
            }
        )
    )

    assert main(["gate", "--report", str(summary), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True


def test_cli_gate_with_baseline_passes_when_within_tolerance(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "approval_bypass_rate": 0,
                "cross_ticket_resume_rate": 0,
                "degraded_false_success_rate": 0,
                "illegal_transition_rate": 0,
                "forbidden_tool_rate": 0,
                "recall_at_5": 0.8,
                "mrr": 0.8,
                "completion_rate": 1.0,
                "p95_latency_ms": 1000.0,
                "mean_tool_calls": 2.0,
            }
        )
    )
    current = tmp_path / "current.json"
    current.write_text(
        json.dumps(
            {
                "approval_bypass_rate": 0,
                "cross_ticket_resume_rate": 0,
                "degraded_false_success_rate": 0,
                "illegal_transition_rate": 0,
                "forbidden_tool_rate": 0,
                "recall_at_5": 0.8,
                "mrr": 0.8,
                "completion_rate": 1.0,
                "p95_latency_ms": 1100.0,
                "mean_tool_calls": 2.2,
            }
        )
    )

    exit_code = main(
        [
            "gate",
            "--report",
            str(current),
            "--baseline",
            str(baseline),
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["passed"] is True
    assert output["failures"] == []


def test_cli_gate_with_baseline_fails_on_regression(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "approval_bypass_rate": 0,
                "cross_ticket_resume_rate": 0,
                "degraded_false_success_rate": 0,
                "illegal_transition_rate": 0,
                "forbidden_tool_rate": 0,
                "recall_at_5": 0.8,
                "mrr": 0.8,
                "completion_rate": 1.0,
                "p95_latency_ms": 1000.0,
                "mean_tool_calls": 2.0,
            }
        )
    )
    current = tmp_path / "current.json"
    current.write_text(
        json.dumps(
            {
                "approval_bypass_rate": 0,
                "cross_ticket_resume_rate": 0,
                "degraded_false_success_rate": 0,
                "illegal_transition_rate": 0,
                "forbidden_tool_rate": 0,
                "recall_at_5": 0.8,
                "mrr": 0.8,
                "completion_rate": 0.5,
                "p95_latency_ms": 1500.0,
                "mean_tool_calls": 4.0,
            }
        )
    )

    exit_code = main(
        [
            "gate",
            "--report",
            str(current),
            "--baseline",
            str(baseline),
            "--json",
        ]
    )

    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["passed"] is False
    assert "completion_regression" in output["failures"]
    assert "p95_latency_regression" in output["failures"]
    assert "unexplained_tool_call_growth" in output["failures"]


def test_cli_graph_factory_env_var_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    dataset = tmp_path / "cases.yaml"
    dataset.write_text("- id: case-1\n  expected:\n    final_status: closed\n")

    monkeypatch.delenv("DESKBENCH_GRAPH_FACTORY", raising=False)
    monkeypatch.delenv("SERVICEDESKBENCH_GRAPH_FACTORY", raising=False)

    exit_code = main(["run", "--dataset", str(dataset), "--adapter", "graph", "--json"])
    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)
    assert "DESKBENCH_GRAPH_FACTORY" in output["error"]["detail"]

    monkeypatch.setenv("SERVICEDESKBENCH_GRAPH_FACTORY", "invalid_format")
    exit_code = main(["run", "--dataset", str(dataset), "--adapter", "graph", "--json"])
    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)
    assert "module:attribute syntax" in output["error"]["detail"]

    monkeypatch.setenv("DESKBENCH_GRAPH_FACTORY", "invalid_format")
    exit_code = main(["run", "--dataset", str(dataset), "--adapter", "graph", "--json"])
    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)
    assert "module:attribute syntax" in output["error"]["detail"]
