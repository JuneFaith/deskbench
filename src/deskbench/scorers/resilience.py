"""Failure recovery scorer."""

from deskbench.contracts import AgentRun, ScoreResult, TraceEventKind
from deskbench.scorers.common import Failure, result_for


def score_resilience(case: object, run: AgentRun) -> ScoreResult:
    """Reject infrastructure failures that appear as successful completion."""
    del case
    failures: list[Failure] = []
    if run.final_state.degraded and run.final_state.status == "closed":
        failures.append(
            (
                "degraded_false_success",
                {"actual_state": run.final_state.model_dump()},
            )
        )
    if run.error and not run.final_state.degraded:
        failures.append(
            (
                "unmarked_failure",
                {"error": run.error, "actual_state": run.final_state.model_dump()},
            )
        )
    if run.error and not run.trace.find(TraceEventKind.ERROR):
        failures.append(("missing_error_evidence", {"error": run.error}))
    return result_for("resilience", failures, 3)
