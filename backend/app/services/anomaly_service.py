from __future__ import annotations

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot, has_label


class GraphAnomalyService:
    """Explainable rule/motif deviations only; this is not general-purpose ML anomaly detection."""

    def __init__(self, client: FalkorGraphClient):
        self.client = client

    def detect(self) -> dict:
        snapshot = GraphSnapshot.load(self.client)
        anomalies = []

        # Motif rule: frontend -> service/API -> database is allowed; direct frontend -> database bypass is abnormal.
        for edge in snapshot.edges:
            if edge.type != "DEPENDS_ON":
                continue
            source, target = snapshot.node(edge.source) or {}, snapshot.node(edge.target) or {}
            if source.get("system_type") == "frontend" and target.get("system_type") == "database":
                mediated = []
                for first in snapshot.edges_from(edge.source, {"DEPENDS_ON"}):
                    middle = snapshot.node(first.target) or {}
                    if first.target == edge.target or middle.get("system_type") not in {"service", "api"}:
                        continue
                    for second in snapshot.edges_from(first.target, {"DEPENDS_ON"}):
                        if second.target == edge.target:
                            mediated.append([first.as_dict(), second.as_dict()])
                anomalies.append({
                    "rule": "FRONTEND_DIRECT_DATABASE",
                    "kind": "UNEXPECTED_DEPENDENCY",
                    "severity": "HIGH",
                    "abnormal_edge": edge.as_dict(),
                    "expected_motif": "frontend -> service/api -> database",
                    "normal_paths_present": mediated,
                    "rationale": "Frontend bypasses the normal API/service stage and depends directly on a database.",
                })

        # Required-edge rules for supported node types.
        for entity_id, node in snapshot.nodes.items():
            if has_label(node, "Decision") and str(node.get("status") or "").upper() not in {"DRAFT", "CANCELLED"}:
                if not snapshot.edges_from(entity_id, {"BASED_ON"}):
                    anomalies.append({
                        "rule": "DECISION_REQUIRES_BASIS",
                        "kind": "MISSING_REQUIRED_EDGE",
                        "severity": "HIGH",
                        "entity": node,
                        "missing": "BASED_ON",
                    })
            if has_label(node, "Change") and str(node.get("status") or "").upper() in {"DEPLOYED", "ROLLED_BACK"}:
                if not snapshot.edges_from(entity_id, {"CHANGED", "AFFECTS"}):
                    anomalies.append({
                        "rule": "CHANGE_REQUIRES_TARGET",
                        "kind": "MISSING_REQUIRED_EDGE",
                        "severity": "MEDIUM",
                        "entity": node,
                        "missing": "CHANGED|AFFECTS",
                    })

        # Dependency cycles are unusual topology for the supported service graph.
        for system_id, node in snapshot.nodes.items():
            if not has_label(node, "System"):
                continue
            paths = snapshot.dependency_reachability(system_id, reverse=False, max_depth=8)
            # dependency_reachability protects against cycles, so inspect direct return-to-source via one more edge.
            for item in paths:
                if any(e.target == system_id for e in snapshot.edges_from(item["entity_id"], {"DEPENDS_ON"})):
                    cycle_nodes = item["node_ids"] + [system_id]
                    canonical = min(cycle_nodes)
                    if system_id == canonical:
                        anomalies.append({
                            "rule": "DEPENDENCY_CYCLE",
                            "kind": "UNUSUAL_TOPOLOGY",
                            "severity": "MEDIUM",
                            "entity": node,
                            "cycle": cycle_nodes,
                        })
        anomalies.sort(key=lambda x: (x["rule"], str((x.get("entity") or {}).get("id", "")), str((x.get("abnormal_edge") or {}).get("source", ""))))
        return {"anomalies": anomalies, "count": len(anomalies), "method": "deterministic motif/rule comparison", "graph_required": True}
