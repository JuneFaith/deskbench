"""Convert persisted run reports into regression summaries."""

import json
from math import ceil
from pathlib import Path
from statistics import mean
from typing import Any

from deskbench.reporting.gate import Summary


def read_summary(path: str | Path) -> Summary:
    """Read a summary JSON file and derive gate metrics from its runs."""
    source = Path(path)
    summary_path = source / "summary.json" if source.is_dir() else source
    payload: Any = json.loads(summary_path.read_text())
    required_fields = set(Summary.model_fields) - {"tool_call_growth_explanation"}
    if all(name in payload for name in required_fields):
        return Summary.model_validate(payload)
    runs = payload.get("runs", [])
    executed_runs = [run for run in runs if not run.get("skipped", False)]
    count = max(len(executed_runs), 1)
    failure_counts = {
        "approval_bypass_rate": 0,
        "cross_ticket_resume_rate": 0,
        "degraded_false_success_rate": 0,
        "illegal_transition_rate": 0,
        "forbidden_tool_rate": 0,
    }
    completion = 0
    durations: list[float] = []
    tool_calls: list[float] = []
    retrieval_recalls: list[float] = []
    retrieval_mrrs: list[float] = []
    for run in executed_runs:
        scores = run.get("scores", [])
        failures = {
            failure for score in scores for failure in score.get("failures", [])
        }
        failure_aliases = {
            "approval_bypass_rate": {"approval_bypass"},
            "cross_ticket_resume_rate": {"cross_ticket_resume"},
            "degraded_false_success_rate": {"degraded_false_success"},
            "illegal_transition_rate": {"illegal_transition"},
            "forbidden_tool_rate": {"forbidden_tool"},
        }
        for name, aliases in failure_aliases.items():
            if failures.intersection(aliases):
                failure_counts[name] += 1
        if (
            not run.get("error")
            and bool(scores)
            and all(score.get("passed", False) for score in scores)
        ):
            completion += 1
        if isinstance(run.get("duration_ms"), (int, float)):
            durations.append(float(run["duration_ms"]))
        tool_calls.append(float(run.get("tool_calls", 0)))
        for score in scores:
            if score.get("scorer") != "retrieval":
                continue
            metrics = score.get("metrics", {})
            if isinstance(metrics.get("recall_at_5"), (int, float)):
                retrieval_recalls.append(float(metrics["recall_at_5"]))
            if isinstance(metrics.get("mrr"), (int, float)):
                retrieval_mrrs.append(float(metrics["mrr"]))
    durations.sort()
    p95 = durations[max(0, ceil(len(durations) * 0.95) - 1)] if durations else 0.0
    return Summary(
        approval_bypass_rate=failure_counts["approval_bypass_rate"] / count,
        cross_ticket_resume_rate=failure_counts["cross_ticket_resume_rate"] / count,
        degraded_false_success_rate=(
            failure_counts["degraded_false_success_rate"] / count
        ),
        illegal_transition_rate=failure_counts["illegal_transition_rate"] / count,
        forbidden_tool_rate=failure_counts["forbidden_tool_rate"] / count,
        recall_at_5=mean(retrieval_recalls) if retrieval_recalls else 0.0,
        mrr=mean(retrieval_mrrs) if retrieval_mrrs else 0.0,
        completion_rate=completion / count,
        p95_latency_ms=p95,
        mean_tool_calls=mean(tool_calls) if tool_calls else 0.0,
    )
