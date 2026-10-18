from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.app.graph.temporal import public_properties, to_epoch_us


INACTIVE_STATUSES = {"DISSOLVED", "INACTIVE", "RETIRED", "DELETED", "DISABLED"}


def node_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return public_properties(value)
    if hasattr(value, "properties"):
        data = public_properties(value.properties)
        labels = getattr(value, "labels", None)
        if labels:
            data["_labels"] = list(labels) if not isinstance(labels, str) else [labels]
        return data
    return {"value": value}


def now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")


def is_active_node(node: dict[str, Any] | None, as_of: str) -> bool:
    if not node:
        return False
    status = str(node.get("status") or "").upper()
    valid_from = node.get("valid_from")
    valid_until = node.get("valid_until")
    as_of_us = to_epoch_us(as_of)
    valid_from_us = to_epoch_us(valid_from) if valid_from else None
    valid_until_us = to_epoch_us(valid_until) if valid_until else None
    # A current status such as DISSOLVED must not erase historical validity.
    # If the node has an explicit future valid_until relative to as_of, it was active then.
    if status in INACTIVE_STATUSES and not (valid_until_us is not None and as_of_us < valid_until_us):
        return False
    if valid_from_us is not None and valid_from_us > as_of_us:
        return False
    if valid_until_us is not None and valid_until_us <= as_of_us:
        return False
    return True


def is_interval_active(valid_from: str | None, valid_until: str | None, as_of: str) -> bool:
    as_of_us = to_epoch_us(as_of)
    if valid_from is not None and to_epoch_us(valid_from) > as_of_us:
        return False
    if valid_until is not None and to_epoch_us(valid_until) <= as_of_us:
        return False
    return True

def dedupe_nodes(nodes: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for node in nodes:
        if not node:
            continue
        key = str(node.get("id") or repr(sorted(node.items())))
        if key in seen:
            continue
        seen.add(key)
        out.append(node)
    return out
