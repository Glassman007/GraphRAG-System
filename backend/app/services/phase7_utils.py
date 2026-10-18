from __future__ import annotations

from typing import Any

from backend.app.services.phase4_graph import GraphSnapshot, has_label

INVALID_STATES = {"INVALIDATED", "RETRACTED", "SUPERSEDED", "REJECTED"}
VALIDATED_STATES = {"VALIDATED", "VERIFIED", "PROMOTED"}


def status(node: dict[str, Any] | None) -> str:
    return str((node or {}).get("status") or "").upper()


def active_evidence(snapshot: GraphSnapshot, claim_id: str) -> list[dict[str, Any]]:
    out = []
    for edge in snapshot.edges_to(claim_id, {"SUPPORTS"}):
        node = snapshot.node(edge.source)
        if has_label(node, "Evidence") and status(node) not in INVALID_STATES:
            out.append(node)
    return out


def evidence_for_artifact(snapshot: GraphSnapshot, artifact_id: str) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for edge in snapshot.edges_from(artifact_id, {"DERIVED_FROM", "REQUIRES"}):
        node = snapshot.node(edge.target)
        if has_label(node, "Evidence"):
            seen[str(node["id"])] = node
    for edge in snapshot.edges_to(artifact_id, {"SUPPORTS", "REFUTES"}):
        node = snapshot.node(edge.source)
        if has_label(node, "Evidence"):
            seen[str(node["id"])] = node
    return list(seen.values())


def validators_for(snapshot: GraphSnapshot, artifact_id: str) -> list[dict[str, Any]]:
    return [snapshot.node(e.target) for e in snapshot.edges_from(artifact_id, {"VALIDATED_BY"}) if snapshot.node(e.target)]
