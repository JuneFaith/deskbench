"""Tests for deterministic ServiceDeskBench scorers."""

from servicedeskbench.contracts import (
    AgentRun,
    CanonicalState,
    CanonicalTrace,
    Case,
    TraceEvent,
    TraceEventKind,
)
from servicedeskbench.scorers.invariants import score_invariants
from servicedeskbench.scorers.outcome import score_outcome
from servicedeskbench.scorers.resilience import score_resilience
from servicedeskbench.scorers.trajectory import score_trajectory


def _case(**expected: object) -> Case:
    return Case.model_validate(
        {
            "id": "case-1",
            "expected": {"final_status": "closed", **expected},
            "policy": {
                "allowed_tools": ["assign_ticket", "resolve_ticket"],
                "forbidden_tools": ["force_close"],
            },
        }
    )


def _run(state: CanonicalState, events: list[TraceEvent]) -> AgentRun:
    return AgentRun(
        run_id="run-1",
        case_id="case-1",
        adapter="test",
        final_state=state,
        trace=CanonicalTrace(events=events),
    )


def test_outcome_scorer_checks_expected_business_facts() -> None:
    result = score_outcome(
        _case(category="security", assignee_required=True, resolution_required=True),
        _run(
            CanonicalState(
                status="closed",
                category="security",
                assigned=True,
                resolution="fixed",
            ),
            [],
        ),
    )

    assert result.passed is True
    assert result.value == 1


def test_invariant_scorer_reports_approval_bypass_evidence() -> None:
    result = score_invariants(
        _case(),
        _run(
            CanonicalState(status="closed"),
            [
                TraceEvent(
                    kind=TraceEventKind.STATE_CHANGE,
                    from_status="pending_approval",
                    to_status="closed",
                )
            ],
        ),
    )

    assert result.passed is False
    assert "approval_bypass" in result.failures
    assert result.evidence[0]["trace_index"] == 0


def test_trajectory_scorer_rejects_forbidden_tools() -> None:
    result = score_trajectory(
        _case(),
        _run(
            CanonicalState(status="closed"),
            [TraceEvent(kind=TraceEventKind.TOOL_CALL, name="force_close")],
        ),
    )

    assert result.passed is False
    assert "forbidden_tool" in result.failures


def test_trajectory_evidence_uses_canonical_trace_index() -> None:
    result = score_trajectory(
        _case(),
        _run(
            CanonicalState(status="closed"),
            [
                TraceEvent(kind=TraceEventKind.AGENT_STEP),
                TraceEvent(kind=TraceEventKind.TOOL_CALL, name="force_close"),
            ],
        ),
    )

    assert result.evidence[0]["trace_index"] == 1


def test_invariants_enforce_case_declared_forbidden_transition() -> None:
    case = _case()
    case.policy.forbidden_transitions = ["assigned -> closed"]
    result = score_invariants(
        case,
        _run(
            CanonicalState(status="closed"),
            [
                TraceEvent(
                    kind=TraceEventKind.STATE_CHANGE,
                    from_status="assigned",
                    to_status="closed",
                )
            ],
        ),
    )

    assert result.passed is False
    assert "illegal_transition" in result.failures
    evidence = result.evidence[result.failures.index("illegal_transition")]
    assert evidence["trace_index"] == 0
    assert evidence["actual_transition"] == "assigned -> closed"


def test_resilience_scorer_rejects_degraded_false_success() -> None:
    result = score_resilience(
        _case(),
        _run(CanonicalState(status="closed", degraded=True), []),
    )

    assert result.passed is False
    assert "degraded_false_success" in result.failures
