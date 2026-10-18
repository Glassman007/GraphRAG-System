from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

TEMPORAL_FIELDS = ("created_at", "observed_at", "occurred_at", "valid_from", "valid_until")
_INTERNAL_PREFIX = "_ts_"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def epoch_property(field: str) -> str:
    if field not in TEMPORAL_FIELDS:
        raise ValueError(f"Unsupported temporal field: {field}")
    return f"{_INTERNAL_PREFIX}{field}_us"


def parse_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"Invalid ISO-8601 timestamp: {value!r}") from exc
    else:
        raise TypeError(f"Timestamp must be an ISO-8601 string or datetime, got {type(value).__name__}")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Timestamp must include a timezone offset: {value!r}")
    return parsed


def to_epoch_us(value: str | datetime) -> int:
    normalized = parse_timestamp(value).astimezone(timezone.utc)
    delta = normalized - _EPOCH
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def with_temporal_epochs(properties: Mapping[str, Any]) -> dict[str, Any]:
    """Copy properties and derive integer microsecond fields for every known timestamp.

    The original ISO-8601 property is preserved for public/API output and provenance.
    Internal `_ts_*_us` properties are the only representation used for ordering/filtering.
    """
    result = dict(properties)
    for field in TEMPORAL_FIELDS:
        internal = epoch_property(field)
        if field not in result:
            continue
        value = result[field]
        if value is None:
            result[internal] = None
        else:
            result[internal] = to_epoch_us(value)
    return result


def public_properties(properties: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(properties or {}).items()
        if not key.startswith(_INTERNAL_PREFIX)
    }


def temporal_sort_key(value: str | datetime | None, *, missing: int = -1) -> int:
    return missing if value is None else to_epoch_us(value)
