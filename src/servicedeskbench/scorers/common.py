"""Shared helpers for deterministic scorers."""

from typing import Any

from servicedeskbench.contracts import ScoreResult

Failure = tuple[str, dict[str, Any]]


def result_for(name: str, failures: list[Failure], total: int) -> ScoreResult:
    """Create a score while retaining every failure's evidence."""
    return ScoreResult(
        scorer=name,
        passed=not failures,
        value=1.0 if not failures else max(0.0, 1.0 - len(failures) / max(total, 1)),
        failures=[code for code, _ in failures],
        evidence=[evidence for _, evidence in failures],
    )


def add_check(
    failures: list[Failure],
    condition: bool,
    code: str,
    evidence: dict[str, Any],
) -> None:
    """Append an evidence-bearing failure when a condition is violated."""
    if condition:
        failures.append((code, evidence))
