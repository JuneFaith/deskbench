"""Convert adapter-specific events into canonical trace evidence."""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from servicedeskbench.contracts import CanonicalTrace, TraceEvent


class TraceNormalizationError(ValueError):
    """Raised when an adapter event cannot be normalized."""


def normalize_trace(events: Sequence[Mapping[str, Any]]) -> CanonicalTrace:
    """Normalize mappings while retaining fields unknown to the benchmark.

    Args:
        events: Ordered adapter events.

    Returns:
        A canonical trace containing one typed event for each input mapping.

    Raises:
        TraceNormalizationError: If an event kind or required event value is
            invalid.
    """
    normalized: list[TraceEvent] = []
    known_fields = set(TraceEvent.model_fields)
    for index, event in enumerate(events):
        try:
            source = dict(event)
            aliases = {"from": "from_status", "to": "to_status"}
            payload = {
                aliases.get(key, key): value
                for key, value in source.items()
                if key in known_fields or key in aliases
            }
            raw = {
                key: value
                for key, value in source.items()
                if key not in known_fields and key not in aliases
            }
            if raw:
                existing_raw = payload.get("raw", {})
                if not isinstance(existing_raw, dict):
                    raise TypeError("raw event evidence must be a mapping")
                payload["raw"] = {**existing_raw, **raw}
            normalized.append(TraceEvent.model_validate(payload))
        except (ValidationError, TypeError, ValueError) as error:
            kind = event.get("kind", "unknown")
            raise TraceNormalizationError(
                f"failed to normalize event {index} ({kind}): {error}"
            ) from error
    return CanonicalTrace(events=normalized)
