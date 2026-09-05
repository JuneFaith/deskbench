"""Agent trajectory scorer."""

from servicedeskbench.contracts import AgentRun, Case, ScoreResult, TraceEventKind
from servicedeskbench.scorers.common import Failure, result_for


def score_trajectory(case: Case, run: AgentRun) -> ScoreResult:
    """Check tool policy and step limits against canonical evidence."""
    failures: list[Failure] = []
    tool_calls = run.trace.find(TraceEventKind.TOOL_CALL)
    for trace_index, event in enumerate(run.trace.events):
        if event.kind != TraceEventKind.TOOL_CALL:
            continue
        if event.name in case.policy.forbidden_tools:
            failures.append(
                (
                    "forbidden_tool",
                    {"trace_index": trace_index, "tool": event.name},
                )
            )
        if case.policy.allowed_tools and event.name not in case.policy.allowed_tools:
            failures.append(
                (
                    "unexpected_tool",
                    {"trace_index": trace_index, "tool": event.name},
                )
            )
    execution_steps = len(
        [
            e
            for e in run.trace.events
            if e.kind
            in {
                TraceEventKind.AGENT_STEP,
                TraceEventKind.TOOL_CALL,
                TraceEventKind.MODEL_CALL,
            }
        ]
    ) or len(run.trace.events)
    if execution_steps > case.policy.max_steps:
        failures.append(
            (
                "max_steps_exceeded",
                {"actual": execution_steps, "limit": case.policy.max_steps},
            )
        )
    return result_for("trajectory", failures, len(tool_calls) + 1)
