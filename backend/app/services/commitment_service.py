from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.temporal import to_epoch_us
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase8_utils import entities_with_label, node_timestamp_us, node_visible, path_text


TERMINAL = {"FULFILLED", "BREACHED", "CANCELLED", "SUPERSEDED"}


class CommitmentTrackingService:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    @staticmethod
    def _point(as_of: str | None) -> str:
        return as_of or datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")

    @staticmethod
    def _evidence_visible(snapshot: GraphSnapshot, entity_id: str, as_of: str | None) -> dict[str, Any] | None:
        node = snapshot.node(entity_id)
        return node if node_visible(node, as_of) else None

    @staticmethod
    def inspect_from_snapshot(snapshot: GraphSnapshot, commitment_id: str, *, as_of: str | None = None, at_risk_window_hours: int = 24) -> dict[str, Any] | None:
        commitment = snapshot.node(commitment_id)
        if commitment is None or not has_label(commitment, "Commitment") or not node_visible(commitment, as_of):
            return None
        point = CommitmentTrackingService._point(as_of)
        cid = str(commitment["id"])
        promisor_edges = snapshot.edges_from(cid, {"PROMISED_BY", "MADE_BY"}, as_of=as_of)
        promisee_edges = snapshot.edges_from(cid, {"OWED_TO"}, as_of=as_of)
        subject_edges = snapshot.edges_from(cid, {"COMMITTED_TO", "ABOUT"}, as_of=as_of)
        dep_edges = snapshot.edges_from(cid, {"DEPENDS_ON", "REQUIRES"}, as_of=as_of)
        satisfy_edges = snapshot.edges_from(cid, {"SATISFIED_BY"}, as_of=as_of)
        breach_edges = snapshot.edges_from(cid, {"BREACHED_BY"}, as_of=as_of)
        satisfaction = [CommitmentTrackingService._evidence_visible(snapshot, e.target, as_of) for e in satisfy_edges]
        satisfaction = [x for x in satisfaction if x]
        breach = [CommitmentTrackingService._evidence_visible(snapshot, e.target, as_of) for e in breach_edges]
        breach = [x for x in breach if x]
        raw_status = str(commitment.get("status") or "OPEN").upper()
        due = commitment.get("due_at")
        status = raw_status if raw_status in TERMINAL else "OPEN"
        reason = "node lifecycle state"
        if breach:
            status, reason = "BREACHED", "explicit BREACHED_BY graph evidence"
        elif satisfaction:
            status, reason = "FULFILLED", "explicit SATISFIED_BY graph evidence"
        elif due:
            now_us, due_us = to_epoch_us(point), to_epoch_us(str(due))
            if now_us > due_us:
                status, reason = "OVERDUE", "deadline passed without fulfillment/breach evidence"
            elif due_us - now_us <= at_risk_window_hours * 3600 * 1_000_000:
                status, reason = "AT_RISK", "deadline is within configured risk window"
        # Incoming dependencies represent work that relies on the commitment.
        consequences = []
        for edge in snapshot.edges_to(cid, {"DEPENDS_ON", "REQUIRES"}, as_of=as_of):
            source = snapshot.node(edge.source)
            if source and node_visible(source, as_of):
                consequences.append({"entity": source, "relationship": edge.type, "path": path_text(edge)})
        # Explicit AFFECTS from the commitment is also a consequence.
        for edge in snapshot.edges_from(cid, {"AFFECTS"}, as_of=as_of):
            target = snapshot.node(edge.target)
            if target and node_visible(target, as_of):
                consequences.append({"entity": target, "relationship": edge.type, "path": path_text(edge)})
        return {
            "commitment": commitment,
            "as_of": point,
            "status": status,
            "status_reason": reason,
            "promisors": [{"entity": snapshot.node(e.target), "path": path_text(e)} for e in promisor_edges if snapshot.node(e.target)],
            "promisees": [{"entity": snapshot.node(e.target), "path": path_text(e)} for e in promisee_edges if snapshot.node(e.target)],
            "subjects": [{"entity": snapshot.node(e.target), "path": path_text(e)} for e in subject_edges if snapshot.node(e.target)],
            "dependencies": [{"entity": snapshot.node(e.target), "path": path_text(e)} for e in dep_edges if snapshot.node(e.target)],
            "fulfillment_evidence": satisfaction,
            "breach_evidence": breach,
            "downstream_consequences": sorted(consequences, key=lambda x: str(x["entity"].get("id"))),
            "due_at": due,
            "source": commitment.get("source_ref_id") or commitment.get("source") or "graph commitment record",
            "provenance_paths": sorted({path_text(e) for e in promisor_edges + promisee_edges + subject_edges + dep_edges + satisfy_edges + breach_edges}),
            "graph_required": True,
        }

    def get(self, commitment_id: str, *, as_of: str | None = None) -> dict[str, Any] | None:
        return self.inspect_from_snapshot(GraphSnapshot.load(self.client), commitment_id, as_of=as_of)

    def list(self, *, as_of: str | None = None, status: str | None = None, entity_id: str | None = None) -> list[dict[str, Any]]:
        snapshot = GraphSnapshot.load(self.client)
        out = []
        for node in entities_with_label(snapshot, "Commitment", as_of=as_of):
            value = self.inspect_from_snapshot(snapshot, str(node["id"]), as_of=as_of)
            if not value:
                continue
            if status and value["status"] != status.upper():
                continue
            if entity_id:
                involved = {x["entity"].get("id") for key in ("promisors", "promisees", "subjects", "dependencies", "downstream_consequences") for x in value[key] if x.get("entity")}
                if entity_id not in involved:
                    continue
            out.append(value)
        return out
