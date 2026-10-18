from __future__ import annotations

import hashlib
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase3_utils import now_iso


class EvidenceAcquisitionService:
    """Deterministic graph routing. External execution is deliberately a mock in Phase 4."""

    def __init__(self, client: FalkorGraphClient, retrieval_service: Any | None = None):
        self.client = client
        self.retrieval_service = retrieval_service

    def route_question(self, question_id: str, *, as_of: str | None = None) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        question = snapshot.node(question_id)
        if question is None or not has_label(question, "Question"):
            return None

        routes: list[dict[str, Any]] = []
        for req in snapshot.edges_from(question_id, {"REQUIRES"}, as_of=as_of):
            target = snapshot.node(req.target)
            if has_label(target, "DataSource"):
                routes.append({
                    "tool": None,
                    "data_source": target,
                    "authoritative": bool(target.get("authoritative")),
                    "capability": req.properties.get("capability"),
                    "path": [f"{question_id}-[:REQUIRES]->{req.target}"],
                })
            elif has_label(target, "Tool"):
                for query_edge in snapshot.edges_from(req.target, {"QUERIES"}, as_of=as_of):
                    source = snapshot.node(query_edge.target)
                    if not has_label(source, "DataSource"):
                        continue
                    routes.append({
                        "tool": target,
                        "data_source": source,
                        "authoritative": bool(source.get("authoritative")),
                        "capability": query_edge.properties.get("capability") or target.get("capability"),
                        "path": [
                            f"{question_id}-[:REQUIRES]->{req.target}",
                            f"{req.target}-[:QUERIES]->{query_edge.target}",
                        ],
                    })
        routes.sort(key=lambda r: (not r["authoritative"], str((r["tool"] or {}).get("id", "")), str((r["data_source"] or {}).get("id", ""))))
        subjects = [snapshot.node(e.target) for e in snapshot.edges_from(question_id, {"ABOUT"}, as_of=as_of)]
        return {
            "question": question,
            "relevant_entities": [s for s in subjects if s],
            "routes": routes,
            "selected_route": routes[0] if routes else None,
            "status": "ROUTABLE" if routes else "NO_GRAPH_ROUTE",
            "graph_required": True,
        }

    def acquire_mock(
        self,
        question_id: str,
        *,
        evidence_name: str,
        evidence_type: str,
        observed_at: str | None = None,
        confidence: float = 1.0,
        evidence_id: str | None = None,
    ) -> dict[str, Any]:
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        routing = self.route_question(question_id)
        if routing is None:
            raise ValueError("Question not found")
        selected = routing.get("selected_route")
        if selected is None:
            raise ValueError("No graph-backed Tool/DataSource route exists for this question")
        timestamp = observed_at or now_iso()
        source = selected["data_source"]
        tool = selected.get("tool")
        if evidence_id is None:
            digest = hashlib.sha256(f"{question_id}|{source['id']}|{evidence_name}|{timestamp}".encode()).hexdigest()[:12].upper()
            evidence_id = f"E-ACQ-{digest}"
        props = {
            "name": evidence_name,
            "evidence_type": evidence_type,
            "observed_at": timestamp,
            "created_at": timestamp,
            "source_ref_id": source["id"],
            "confidence": confidence,
            "acquisition_mode": "MOCK",
            "acquired_by_tool_id": tool.get("id") if tool else None,
        }
        upsert_node(self.client, "Evidence", evidence_id, props)
        upsert_relationship(self.client, evidence_id, "DERIVED_FROM", source["id"], {"valid_from": timestamp, "confidence": 1.0, "source_ref_id": source["id"]})
        upsert_relationship(self.client, question_id, "RESOLVED_BY", evidence_id, {"valid_from": timestamp, "confidence": confidence, "source_ref_id": source["id"]})
        upsert_relationship(self.client, evidence_id, "ABOUT", question_id, {"valid_from": timestamp, "confidence": 1.0})
        for entity in routing.get("relevant_entities", []):
            eid = entity.get("id")
            if eid and eid != question_id:
                upsert_relationship(self.client, evidence_id, "ABOUT", str(eid), {"valid_from": timestamp, "confidence": confidence})
        upsert_node(self.client, "Question", question_id, {"status": "RESOLVED", "resolved_at": timestamp})
        return {
            "question_id": question_id,
            "tool_request": {
                "tool_id": tool.get("id") if tool else None,
                "data_source_id": source["id"],
                "capability": selected.get("capability"),
                "execution": "MOCK",
            },
            "evidence_id": evidence_id,
            "provenance_paths": [
                f"{question_id}-[:RESOLVED_BY]->{evidence_id}",
                f"{evidence_id}-[:DERIVED_FROM]->{source['id']}",
            ],
        }

    def retrieve_question(self, question_id: str, *, max_results: int = 10, as_of: str | None = None, writeback: bool = True) -> dict[str, Any]:
        """Phase 10 bridge: use existing Phase 4 routing context to launch graph-first retrieval."""
        routing = self.route_question(question_id, as_of=as_of)
        if routing is None:
            raise ValueError("Question not found")
        from backend.app.retrieval.models import RetrievalRequest
        from backend.app.retrieval.service import RetrievalService

        seed_ids = [str(x.get("id")) for x in routing.get("relevant_entities", []) if x and x.get("id")]
        source_types = []
        for route in routing.get("routes", []):
            source = route.get("data_source") or {}
            source_type = source.get("source_type") or source.get("source_kind")
            if source_type and source_type not in source_types:
                source_types.append(str(source_type))
        question = routing["question"]
        request = RetrievalRequest(
            query=str(question.get("text") or question.get("name") or question_id),
            tenant_id=self.client.settings.tenant_id,
            investigation_id=question_id,
            seed_entity_ids=seed_ids or [question_id],
            as_of=as_of,
            allowed_source_types=source_types,
            max_results=max_results,
            writeback=writeback,
        )
        response = (self.retrieval_service or RetrievalService(self.client)).search(request)
        return {
            "question_id": question_id,
            "phase4_routing": routing,
            "phase10_retrieval": response.model_dump(mode="json"),
            "graph_required": True,
        }
