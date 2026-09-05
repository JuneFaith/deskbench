"""Report persistence and regression gates."""

from deskbench.reporting.gate import (
    GatePolicy,
    GateResult,
    Summary,
    evaluate_gate,
)
from deskbench.reporting.json_report import (
    EvaluationReport,
    ReportPaths,
    read_report,
    write_report,
)
from deskbench.reporting.summary import read_summary

__all__ = [
    "EvaluationReport",
    "GatePolicy",
    "GateResult",
    "ReportPaths",
    "Summary",
    "evaluate_gate",
    "read_report",
    "read_summary",
    "write_report",
]
