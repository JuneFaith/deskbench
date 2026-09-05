"""Dataset execution orchestration for Deskbench."""

from datetime import UTC, datetime
from pathlib import Path

from deskbench.adapters.base import AgentAdapter
from deskbench.contracts import AgentRun, Case, ExperimentMetadata
from deskbench.reporting.json_report import (
    EvaluationReport,
    ReportPaths,
    write_report,
)
from deskbench.runner.execution import run_case
from deskbench.runner.lifecycle import load_cases_async
from deskbench.runner.limits import ExecutionLimits
from deskbench.scorers import (
    score_invariants,
    score_outcome,
    score_resilience,
    score_trajectory,
)


async def evaluate_cases(
    dataset_path: str | Path,
    adapter: AgentAdapter,
    *,
    limits: ExecutionLimits | None = None,
) -> list[AgentRun]:
    """Execute and score all cases in a dataset."""
    cases = await load_cases_async(dataset_path)
    return await _evaluate_loaded_cases(cases, adapter, limits)


async def _evaluate_loaded_cases(
    cases: list[Case],
    adapter: AgentAdapter,
    limits: ExecutionLimits | None,
) -> list[AgentRun]:
    """Execute one already-loaded dataset snapshot."""
    run_limits = limits or ExecutionLimits()
    runs: list[AgentRun] = []
    for case in cases:
        started_at = datetime.now(UTC)
        run = await run_case(case, adapter, run_limits)
        run.dataset_version = case.dataset_version
        run.started_at = started_at
        run.ended_at = datetime.now(UTC)
        run.scores = [
            score_outcome(case, run),
            score_invariants(case, run),
            score_trajectory(case, run),
            score_resilience(case, run),
        ]
        runs.append(run)
    return runs


async def run_dataset(
    dataset_path: str | Path,
    adapter: AgentAdapter,
    output_path: str | Path,
    *,
    limits: ExecutionLimits | None = None,
) -> ReportPaths:
    """Execute, score, and persist one dataset evaluation."""
    started_at = datetime.now(UTC)
    cases = await load_cases_async(dataset_path)
    runs = await _evaluate_loaded_cases(cases, adapter, limits)
    dataset_version = cases[0].dataset_version if cases else "servicedesk_v1"
    report = EvaluationReport(
        metadata=ExperimentMetadata(
            run_id=started_at.strftime("%Y-%m-%dT%H%M%S.%fZ"),
            dataset_version=dataset_version,
            adapter=type(adapter).__name__,
            started_at=started_at,
            ended_at=datetime.now(UTC),
        ),
        runs=runs,
    )
    return write_report(report, output_path)
