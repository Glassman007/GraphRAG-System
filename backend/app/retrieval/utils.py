from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from backend.app.graph.temporal import to_epoch_us

TOKEN_RE = re.compile(r"[A-Za-z0-9_./:#-]+")

# Small deterministic normalization vocabulary. This is not a learned model; it only
# makes the default local embedding fixture-capable without an external dependency.
CONCEPTS = {
    "old": "legacy", "previous": "legacy", "legacy": "legacy",
    "worker": "client", "writer": "client", "client": "client",
    "rejected": "incompatible", "incompatibility": "incompatible", "compatibility": "compatible",
    "constraint": "schema", "schema": "schema", "migration": "migration",
    "database": "db", "db": "db", "rollout": "deployment", "deploy": "deployment", "deployment": "deployment",
    "failure": "error", "failed": "error", "error": "error",
    "null": "null", "missing": "null",
}


def tokenize(text: str) -> list[str]:
    values = []
    for raw in TOKEN_RE.findall((text or "").lower()):
        token = CONCEPTS.get(raw, raw)
        values.append(token)
    return values


def stable_hash(*parts: Any, prefix: str = "RET", length: int = 20) -> str:
    payload = "|".join(json.dumps(p, sort_keys=True, default=str) for p in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:length].upper()}"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def temporal_visible(observed_at: str | None, valid_from: str | None, valid_until: str | None, as_of: str | None) -> bool:
    if as_of is None:
        return valid_until is None
    point = to_epoch_us(as_of)
    if observed_at is not None and to_epoch_us(observed_at) > point:
        return False
    if valid_from is not None and to_epoch_us(valid_from) > point:
        return False
    if valid_until is not None and to_epoch_us(valid_until) <= point:
        return False
    return True


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(y*y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot/(na*nb)
