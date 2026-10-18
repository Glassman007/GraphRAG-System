from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase3_utils import is_active_node


class KnowledgeGapService:
    """Detect only absences justified by explicit graph/domain rules."""

    def __init__(self, client: FalkorGraphClient):
        self.client = client

    @staticmethod
    def _claim_available(snapshot: GraphSnapshot, claim_id: str, *, as_of: str | None) -> bool:
        claim = snapshot.node(claim_id) or {}
        status = str(claim.get("status") or "OPEN").upper()
        if status == "REJECTED":
            return False
        # SUPERSEDES is the temporal source of truth. A claim whose current materialized
        # status is SUPERSEDED can still be historically valid before that edge becomes active.
        if snapshot.edges_to(claim_id, {"SUPERSEDES"}, as_of=as_of):
            return False
        if as_of is None and status == "SUPERSEDED":
            return False
        return True

    def detect_for_incident(self, incident_id: str, *, as_of: str | None = None) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        incident = snapshot.node(incident_id)
        if incident is None or not has_label(incident, "Incident"):
            return None

        gaps: list[dict[str, Any]] = []
        question_ids = {
            e.source for e in snapshot.edges_to(incident_id, {"ABOUT"}, as_of=as_of)
            if has_label(snapshot.node(e.source), "Question")
        }
        for qid in sorted(question_ids):
            question = snapshot.node(qid) or {}
            resolutions = [e for e in snapshot.edges_from(qid, {"RESOLVED_BY"}, as_of=as_of)]
            question_status = str(question.get("status") or "OPEN").upper()
            if as_of is None:
                if question_status not in {"OPEN", "UNRESOLVED", "BLOCKED"}:
                    continue
            else:
                # A current RESOLVED/CLOSED materialized status must not erase the earlier
                # unresolved state when its RESOLVED_BY evidence is not yet visible at as_of.
                if question_status in {"CANCELLED", "REJECTED"} or resolutions:
                    continue
            blockers = []
            for edge in snapshot.edges_to(qid, {"REQUIRES", "BLOCKED_BY"}, as_of=as_of):
                blockers.append({"entity": snapshot.node(edge.source), "relation": edge.type, "path": f"{edge.source}-[:{edge.type}]->{qid}"})
            explicit_requirements = [e for e in snapshot.edges_from(qid, {"REQUIRES"}, as_of=as_of)]
            relevant = [
                snapshot.node(e.target) for e in snapshot.edges_from(qid, {"ABOUT"}, as_of=as_of)
                if e.target != incident_id
            ]
            reason_codes = ["UNANSWERED_QUESTION"]
            if explicit_requirements and not resolutions:
                reason_codes.append("EXPECTED_EVIDENCE_MISSING")

            missing_owners = []
            for node in relevant:
                if not has_label(node, "System"):
                    continue
                if as_of and not is_active_node(node, as_of):
                    continue
                owners = [e for e in snapshot.edges_to(str(node["id"]), {"OWNS"}, as_of=as_of)]
                if not owners:
                    missing_owners.append(node)
            if missing_owners:
                reason_codes.append("MISSING_OWNER")

            gaps.append({
                "kind": "QUESTION_GAP",
                "question": question,
                "reason_codes": reason_codes,
                "blocking_entities": blockers,
                "expected_requirements": [
                    {"relation": e.type, "entity": snapshot.node(e.target), "path": f"{qid}-[:{e.type}]->{e.target}"}
                    for e in explicit_requirements
                ],
                "resolved_by": [snapshot.node(e.target) for e in resolutions],
                "relevant_entities": [x for x in relevant if x],
                "missing_owner_entities": missing_owners,
                "blocking_value": len(blockers) * 10 + (5 if "EXPECTED_EVIDENCE_MISSING" in reason_codes else 0) + (5 if missing_owners else 0),
            })

        claim_ids = {
            e.source for e in snapshot.edges_to(incident_id, {"ABOUT"}, as_of=as_of)
            if has_label(snapshot.node(e.source), "Claim")
        }
        for cid in sorted(claim_ids):
            claim = snapshot.node(cid) or {}
            if not self._claim_available(snapshot, cid, as_of=as_of):
                continue
            supports = [
                e for e in snapshot.edges_to(cid, {"SUPPORTS"}, as_of=as_of)
                if has_label(snapshot.node(e.source), "Evidence")
                and (as_of is None or is_active_node(snapshot.node(e.source), as_of))
            ]
            if not supports:
                gaps.append({
                    "kind": "UNSUPPORTED_CLAIM",
                    "claim": claim,
                    "reason_codes": ["EXPECTED_SUPPORTING_EVIDENCE_MISSING"],
                    "blocking_entities": [],
                    "blocking_value": 5,
                })

        # Defined relation rule: an object explicitly marked approval_required must have APPROVED_BY.
        incident_artifacts = {
            e.source for e in snapshot.edges_to(incident_id, {"ABOUT"}, as_of=as_of)
            if has_label(snapshot.node(e.source), "Action") or has_label(snapshot.node(e.source), "Decision")
        }
        for aid in sorted(incident_artifacts):
            node = snapshot.node(aid) or {}
            if not node.get("approval_required"):
                continue
            approvals = snapshot.edges_from(aid, {"APPROVED_BY"}, as_of=as_of)
            if not approvals:
                gaps.append({
                    "kind": "REQUIRED_RELATION_ABSENT",
                    "entity": node,
                    "expected_relation": "APPROVED_BY",
                    "rule": "approval_required=true",
                    "reason_codes": ["MISSING_REQUIRED_APPROVAL"],
                    "blocking_entities": [],
                    "blocking_value": 10,
                })

        gaps.sort(key=lambda g: (-int(g.get("blocking_value", 0)), str((g.get("question") or g.get("claim") or g.get("entity") or {}).get("id", ""))))
        return {"incident": incident, "gaps": gaps, "gap_count": len(gaps), "graph_required": True}
