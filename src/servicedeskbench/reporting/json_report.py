"""Persistent JSON and Markdown report writing."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from servicedeskbench.contracts import AgentRun, ExperimentMetadata
from servicedeskbench.reporting.markdown_report import render_markdown


class EvaluationReport(BaseModel):
    """Complete persisted evaluation report."""

    model_config = ConfigDict(extra="forbid")

    metadata: ExperimentMetadata
    runs: list[AgentRun] = Field(default_factory=list)


class ReportPaths:
    """Paths written for one report."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.summary = root / "summary.json"
        self.cases = root / "cases.jsonl"
        self.markdown = root / "markdown.md"


def write_report(
    report_or_runs: EvaluationReport | list[AgentRun],
    output_root: str | Path,
    *,
    metadata: dict[str, Any] | None = None,
) -> ReportPaths:
    """Write one non-overwriting timestamped report directory.

    ``list[AgentRun]`` remains accepted for the small programmatic API used by
    earlier releases; new callers should pass an explicit ``EvaluationReport``.
    """
    root = Path(output_root)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%S.%fZ")
    report_root = root / timestamp
    report_root.mkdir(parents=True, exist_ok=False)
    if isinstance(report_or_runs, EvaluationReport):
        report = report_or_runs
    else:
        report = EvaluationReport(
            metadata=ExperimentMetadata(
                run_id=timestamp,
                dataset_version=(metadata or {}).get("dataset_version", "unknown"),
                adapter=(metadata or {}).get("adapter", "unknown"),
                **{
                    key: value
                    for key, value in (metadata or {}).items()
                    if key not in {"run_id", "dataset_version", "adapter"}
                },
            ),
            runs=report_or_runs,
        )
    paths = ReportPaths(report_root)
    runs = report.runs
    summary = {
        **report.metadata.model_dump(mode="json"),
        "case_count": len(runs),
        "passed_count": sum(
            not run.error
            and bool(run.scores)
            and all(score.passed for score in run.scores)
            for run in runs
        ),
        "runs": [run.model_dump(mode="json") for run in runs],
    }
    paths.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    paths.cases.write_text(
        "".join(
            json.dumps(run.model_dump(mode="json"), sort_keys=True) + "\n"
            for run in runs
        )
    )
    paths.markdown.write_text(render_markdown(runs, report.metadata.run_id))
    return paths


def read_report(path: str | Path) -> EvaluationReport:
    """Read a report directory or its ``summary.json`` file."""
    source = Path(path)
    summary_path = source / "summary.json" if source.is_dir() else source
    payload: Any = json.loads(summary_path.read_text())
    metadata_fields = set(ExperimentMetadata.model_fields)
    metadata = {key: payload[key] for key in metadata_fields if key in payload}
    metadata.setdefault("run_id", summary_path.parent.name)
    metadata.setdefault("dataset_version", "unknown")
    metadata.setdefault("adapter", "unknown")
    runs_payload = payload.get("runs")
    if not isinstance(runs_payload, list):
        cases_path = summary_path.parent / "cases.jsonl"
        runs_payload = [
            json.loads(line) for line in cases_path.read_text().splitlines() if line
        ]
    return EvaluationReport(
        metadata=ExperimentMetadata.model_validate(metadata),
        runs=[AgentRun.model_validate(run) for run in runs_payload],
    )
