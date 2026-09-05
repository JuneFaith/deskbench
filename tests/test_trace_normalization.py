"""Tests for canonical trace normalization."""

import pytest

from deskbench.contracts import TraceEventKind
from deskbench.trace.normalize import TraceNormalizationError, normalize_trace


def test_normalize_trace_preserves_tool_and_state_evidence() -> None:
    trace = normalize_trace(
        [
            {
                "kind": "tool_call",
                "name": "assign_ticket",
                "arguments": {"ticket_id": "T1"},
            },
            {"kind": "state_change", "from": "classified", "to": "assigned"},
        ]
    )

    assert trace.tool_calls()[0].name == "assign_ticket"
    assert trace.find(TraceEventKind.STATE_CHANGE)[0].to_status == "assigned"


def test_normalize_trace_keeps_unknown_fields_as_raw_evidence() -> None:
    trace = normalize_trace([{"kind": "error", "error": "timeout", "vendor": "tix"}])

    assert trace.events[0].raw == {"vendor": "tix"}


def test_normalize_trace_reports_invalid_event_context() -> None:
    with pytest.raises(TraceNormalizationError, match="event 0"):
        normalize_trace([{"kind": "not-an-event"}])
