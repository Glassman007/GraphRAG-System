from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase3_utils import now_iso


class CompanyBrainExpertiseService:
    """Bounded company-wide expertise coverage derived from canonical graph relationships.

    This is a read-only facade over existing EXPERT_IN / CANDIDATE_EXPERT semantics.
    It does not score employees or promote candidate expertise.
    """

    def __init__(self, client: FalkorGraphClient):
        self.client = client

    def list(self, *, as_of: str | None = None, limit: int = 200) -> dict[str, Any]:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        snapshot = GraphSnapshot.load(self.client)
        point = as_of or now_iso()
        items: list[dict[str, Any]] = []
        for edge in snapshot.edges:
            if edge.type not in {"EXPERT_IN", "CANDIDATE_EXPERT"}:
                continue
            if not snapshot._edge_active(edge, point):
                continue
            actor = snapshot.node(edge.source)
            domain = snapshot.node(edge.target)
            if not actor or not domain:
                continue
            if not (has_label(actor, "Person") or has_label(actor, "Team")):
                continue
            source_ref_id = edge.properties.get("source_ref_id")
            evidence = snapshot.node(str(source_ref_id)) if source_ref_id else None
            items.append(
                {
                    "actor": actor,
                    "domain": domain,
                    "relationship": edge.type,
                    "status": "CANONICAL" if edge.type == "EXPERT_IN" else "CANDIDATE",
                    "confidence": float(edge.properties.get("confidence") or 0.0),
                    "valid_from": edge.properties.get("valid_from"),
                    "valid_until": edge.properties.get("valid_until"),
                    "source_ref_id": source_ref_id,
                    "evidence": evidence if evidence and has_label(evidence, "ExpertiseEvidence") else None,
                    "path": [edge.source, edge.type, edge.target],
                }
            )
        items.sort(
            key=lambda item: (
                0 if item["status"] == "CANONICAL" else 1,
                -float(item["confidence"]),
                str((item["domain"] or {}).get("id") or ""),
                str((item["actor"] or {}).get("id") or ""),
            )
        )
        total = len(items)
        return {
            "as_of": as_of,
            "items": items[:limit],
            "count": min(total, limit),
            "total_available": total,
            "limit": limit,
            "graph_required": True,
            "note": "Organizational capability coverage; not an employee ranking.",
        }
