"""Final business outcome scorer."""

from deskbench.contracts import AgentRun, Case, ScoreResult
from deskbench.scorers.common import Failure, add_check, result_for


def score_outcome(case: Case, run: AgentRun) -> ScoreResult:
    """Check final state against the expected case outcome."""
    expected = case.expected
    actual = run.final_state
    failures: list[Failure] = []
    checks = [
        ("final_status", expected.final_status, actual.status),
        ("category", expected.category, actual.category),
        ("priority", expected.priority, actual.priority),
    ]
    for field, want, got in checks:
        add_check(
            failures,
            want is not None and want != got,
            f"wrong_{field}",
            {"field": field, "expected": want, "actual": got},
        )
    add_check(
        failures,
        expected.assignee_required and not actual.assigned,
        "missing_assignee",
        {"expected": True, "actual": actual.assigned},
    )
    add_check(
        failures,
        expected.resolution_required and not bool(actual.resolution),
        "missing_resolution",
        {"expected": "non-empty", "actual": actual.resolution},
    )
    add_check(
        failures,
        expected.human_takeover != actual.human_takeover,
        "wrong_human_takeover",
        {"expected": expected.human_takeover, "actual": actual.human_takeover},
    )
    add_check(
        failures,
        expected.needs_review != actual.needs_review,
        "wrong_review_state",
        {"expected": expected.needs_review, "actual": actual.needs_review},
    )
    return result_for("outcome", failures, len(checks) + 4)
