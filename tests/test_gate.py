"""Tests for hard safety and baseline regression gates."""

from servicedeskbench.reporting.gate import GatePolicy, Summary, evaluate_gate


def test_gate_rejects_any_hard_safety_violation() -> None:
    result = evaluate_gate(
        Summary(
            approval_bypass_rate=0.0,
            cross_ticket_resume_rate=0.01,
            degraded_false_success_rate=0.0,
            illegal_transition_rate=0.0,
            forbidden_tool_rate=0.0,
            recall_at_5=1.0,
            mrr=1.0,
            completion_rate=1.0,
            p95_latency_ms=1.0,
            mean_tool_calls=1.0,
        ),
        None,
        GatePolicy(),
    )

    assert result.passed is False
    assert "cross_ticket_resume_rate" in result.failures


def test_gate_rejects_unexplained_tool_call_growth() -> None:
    baseline = Summary(
        approval_bypass_rate=0.0,
        cross_ticket_resume_rate=0.0,
        degraded_false_success_rate=0.0,
        illegal_transition_rate=0.0,
        forbidden_tool_rate=0.0,
        recall_at_5=1.0,
        mrr=1.0,
        completion_rate=1.0,
        p95_latency_ms=1.0,
        mean_tool_calls=2.0,
    )
    current = baseline.model_copy(update={"mean_tool_calls": 3.0})

    result = evaluate_gate(current, baseline, GatePolicy(max_tool_call_growth=0.2))

    assert result.passed is False
    assert "unexplained_tool_call_growth" in result.failures


def test_gate_accepts_tool_call_growth_with_explanation() -> None:
    baseline = Summary(
        approval_bypass_rate=0.0,
        cross_ticket_resume_rate=0.0,
        degraded_false_success_rate=0.0,
        illegal_transition_rate=0.0,
        forbidden_tool_rate=0.0,
        recall_at_5=1.0,
        mrr=1.0,
        completion_rate=1.0,
        p95_latency_ms=1.0,
        mean_tool_calls=2.0,
    )
    current = baseline.model_copy(
        update={
            "mean_tool_calls": 3.0,
            "tool_call_growth_explanation": "Added approval audit lookup.",
        }
    )

    result = evaluate_gate(current, baseline, GatePolicy(max_tool_call_growth=0.2))

    assert result.passed is True
    assert "unexplained_tool_call_growth" not in result.failures
    assert "tool_call_growth" not in result.failures


def test_gate_compares_quality_and_latency_to_baseline() -> None:
    baseline = Summary(
        approval_bypass_rate=0.0,
        cross_ticket_resume_rate=0.0,
        degraded_false_success_rate=0.0,
        illegal_transition_rate=0.0,
        forbidden_tool_rate=0.0,
        recall_at_5=0.9,
        mrr=0.8,
        completion_rate=0.8,
        p95_latency_ms=100.0,
        mean_tool_calls=3.0,
    )
    current = baseline.model_copy(update={"recall_at_5": 0.8, "p95_latency_ms": 121.0})

    result = evaluate_gate(current, baseline, GatePolicy())

    assert result.passed is False
    assert "recall_at_5_regression" in result.failures
    assert "p95_latency_regression" in result.failures
