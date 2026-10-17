from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot, edge_path_text, has_label


_ALLOWED = {"ABOUT", "DEPENDS_ON", "CHANGED", "AFFECTS", "SUPPORTS", "REFUTES", "DERIVED_FROM", "CONTAINS"}
_EDGE_WEIGHT = {"CHANGED": 2.5, "AFFECTS": 2.0, "DEPENDS_ON": 1.7, "SUPPORTS": 1.3, "REFUTES": 1.0, "ABOUT": 0.8, "CONTAINS": 0.7, "DERIVED_FROM": 0.4}


class RelationalInvestigationService:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    @staticmethod
    def _score(snapshot: GraphSnapshot, path: dict[str, Any]) -> float:
        score = sum(_EDGE_WEIGHT.get(e["type"], 0.2) for e in path["edges"])
        labels = [snapshot.node(i) or {} for i in path["node_ids"]]
        if any(has_label(n, "Evidence") for n in labels):
            score += 1.5
        if any(has_label(n, "Change") for n in labels):
            score += 2.0
        if any(e["type"] == "DEPENDS_ON" for e in path["edges"]):
            score += 1.0
        score -= max(0, len(path["edges"]) - 5) * 0.35
        return round(score, 4)

    def investigate_incident(self, incident_id: str, *, max_depth: int = 7, limit: int = 20) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        incident = snapshot.node(incident_id)
        if incident is None or not has_label(incident, "Incident"):
            return None
        # Candidate causes are changes structurally tied to this incident through shared evidence.
        incident_evidence = {e.source for e in snapshot.edges_to(incident_id, {"ABOUT"}) if has_label(snapshot.node(e.source), "Evidence")}
        change_ids = set()
        for evidence_id in incident_evidence:
            for edge in snapshot.edges_from(evidence_id, {"ABOUT"}):
                if has_label(snapshot.node(edge.target), "Change"):
                    change_ids.add(edge.target)
        if not change_ids:
            change_ids = {i for i, node in snapshot.nodes.items() if has_label(node, "Change")}
        # Phase 5/6/10/11 add many Task/Investigation/Retrieval nodes that can
        # point at an Incident or Change with ABOUT.  Those operational links are
        # not causal-investigation evidence and can generate hundreds of shortcut
        # paths, crowding the canonical evidence/dependency path out of the bounded
        # result set.  Keep ABOUT traversal only when it originates from Evidence;
        # all other allowed relationship types retain their existing semantics.
        path_snapshot=snapshot.clone()
        path_snapshot.remove_edges(
            lambda edge: edge.type=="ABOUT" and not has_label(snapshot.node(edge.source),"Evidence")
        )
        raw = path_snapshot.bounded_paths(
            incident_id,
            targets=change_ids,
            rel_types=_ALLOWED,
            max_depth=max_depth,
            direction="both",
            max_paths=max(limit * 8, 40),
        )
        candidates = []
        for path in raw:
            types = {e["type"] for e in path["edges"]}
            node_values = [snapshot.node(i) or {} for i in path["node_ids"]]
            # Require connected-data evidence, a dependency hop, and a change relation.
            if "DEPENDS_ON" not in types or not ({"CHANGED", "AFFECTS"} & types):
                continue
            if not any(has_label(n, "Evidence") for n in node_values):
                continue
            evidence = [n for n in node_values if has_label(n, "Evidence")]
            systems = [n for n in node_values if has_label(n, "System")]
            changes = [n for n in node_values if has_label(n, "Change")]
            candidates.append({
                "score": self._score(snapshot, path),
                "node_ids": path["node_ids"],
                "edges": path["edges"],
                "evidence": evidence,
                "systems": systems,
                "changes": changes,
                "explanation_path": edge_path_text(snapshot, path),
            })
        candidates.sort(key=lambda x: (-x["score"], len(x["edges"]), x["node_ids"][-1]))
        return {
            "incident": incident,
            "max_depth": max_depth,
            "relationship_filter": sorted(_ALLOWED),
            "candidate_paths": candidates[:limit],
            "graph_required": True,
        }
