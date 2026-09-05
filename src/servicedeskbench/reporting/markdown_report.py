"""Markdown report rendering."""

from servicedeskbench.contracts import AgentRun


def render_markdown(runs: list[AgentRun], report_id: str) -> str:
    """Render run outcomes and trace evidence as Markdown."""
    lines = [f"# ServiceDeskBench report {report_id}", "", f"Cases: {len(runs)}", ""]
    for run in runs:
        lines.extend(
            [
                f"## {run.case_id} — {run.final_state.status}",
                f"- Adapter: `{run.adapter}`",
                f"- Trace events: {len(run.trace.events)}",
            ]
        )
        if run.error:
            lines.append(f"- Error: `{run.error}`")
        for score in run.scores:
            marker = "PASS" if score.passed else "FAIL"
            lines.append(f"- {score.scorer}: **{marker}** ({score.value:.3f})")
            for failure, evidence in zip(score.failures, score.evidence, strict=False):
                lines.append(f"  - `{failure}`: `{evidence}`")
        lines.append("")
    return "\n".join(lines)
