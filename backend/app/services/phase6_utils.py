from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from backend.app.graph.temporal import to_epoch_us


def stable_id(prefix: str, *parts: str, length: int = 16) -> str:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:length].upper()
    return f"{prefix}{digest}"


def csv(values: Iterable[str] | None) -> str:
    return ",".join(sorted({str(value) for value in (values or []) if str(value).strip()}))


def csv_list(value: Any) -> list[str]:
    return [item for item in str(value or "").split(",") if item]


def now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")


def add_seconds(value: str, seconds: int) -> str:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (dt + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def is_expired(value: str | None, *, as_of: str) -> bool:
    return bool(value and to_epoch_us(value) <= to_epoch_us(as_of))


def json_safe_list(values: Iterable[Any] | None) -> list[Any]:
    return list(values or [])
