from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphEdge, GraphSnapshot, has_label


class CounterfactualSimulationService:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    @staticmethod
    def _blast(snapshot: GraphSnapshot, entity_id: str, max_depth: int = 6) -> dict[str, Any]:
        entity = snapshot.node(entity_id) or {}
        roots = []
        if has_label(entity, "Change"):
            roots = [e.target for e in snapshot.edges_from(entity_id, {"CHANGED", "AFFECTS"})]
        elif has_label(entity, "System"):
            roots = [entity_id]
        elif has_label(entity, "Incident"):
            # Incidents are valid simulation entry points in the guided UI.
            # Start from systems explicitly affected by the incident, not arbitrary neighbors.
            roots = [e.target for e in snapshot.edges_from(entity_id, {"AFFECTS"})
                     if has_label(snapshot.node(e.target), "System")]
        impacted: dict[str, dict[str, Any]] = {}
        for root in roots:
            for item in snapshot.dependency_reachability(root, reverse=True, max_depth=max_depth):
                if has_label(snapshot.node(item["entity_id"]), "System"):
                    prior = impacted.get(item["entity_id"])
                    if prior is None or item["depth"] < prior["depth"]:
                        impacted[item["entity_id"]] = item
        return {"roots": sorted(set(roots)), "impacted": sorted(impacted), "paths": list(impacted.values())}

    @staticmethod
    def _constraint_summary(snapshot: GraphSnapshot) -> dict[str, Any]:
        missing_approvals = []
        unsatisfied_requirements = []
        for entity_id, node in snapshot.nodes.items():
            if not has_label(node, "Action"):
                continue
            if node.get("approval_required") and not snapshot.edges_from(entity_id, {"APPROVED_BY"}):
                missing_approvals.append(entity_id)
            for req in snapshot.edges_from(entity_id, {"REQUIRES"}):
                target = snapshot.node(req.target) or {}
                if has_label(target, "Question") and str(target.get("status") or "OPEN").upper() not in {"RESOLVED", "CLOSED"}:
                    unsatisfied_requirements.append(f"{entity_id}->{req.target}")
        return {"missing_approvals": sorted(missing_approvals), "unsatisfied_requirements": sorted(unsatisfied_requirements)}

    @staticmethod
    def _apply(snapshot: GraphSnapshot, operation: dict[str, Any]) -> dict[str, Any]:
        kind = str(operation.get("op") or "").lower()
        if kind == "remove_dependency":
            source, target = operation.get("source_id"), operation.get("target_id")
            removed = snapshot.remove_edges(lambda e: e.type == "DEPENDS_ON" and e.source == source and e.target == target)
            return {"op": kind, "removed_edges": removed}
        if kind == "rollback_change":
            change_id = str(operation.get("change_id") or "")
            if change_id not in snapshot.nodes:
                raise ValueError(f"Unknown change: {change_id}")
            snapshot.nodes[change_id] = {**snapshot.nodes[change_id], "status": "ROLLED_BACK", "hypothetical": True}
            removed = snapshot.remove_edges(lambda e: e.source == change_id and e.type in {"CHANGED", "AFFECTS"})
            return {"op": kind, "change_id": change_id, "removed_effect_edges": removed}
        if kind == "add_compatibility_layer":
            source = str(operation.get("source_id") or "")
            target = str(operation.get("target_id") or "")
            layer = str(operation.get("layer_id") or "SIM-COMPAT-LAYER")
            snapshot.nodes[layer] = {"id": layer, "name": operation.get("name") or "Hypothetical compatibility layer", "system_type": "compatibility_layer", "status": "HYPOTHETICAL", "_labels": ["Entity", "System"], "hypothetical": True}
            snapshot.remove_edges(lambda e: e.type == "DEPENDS_ON" and e.source == source and e.target == target)
            snapshot.add_edge(source, "DEPENDS_ON", layer, {"hypothetical": True})
            snapshot.add_edge(layer, "DEPENDS_ON", target, {"hypothetical": True})
            return {"op": kind, "layer_id": layer}
        if kind == "replace_relationship":
            source = str(operation.get("source_id") or "")
            target = str(operation.get("target_id") or "")
            rel_type = str(operation.get("relationship_type") or "")
            new_target = str(operation.get("new_target_id") or "")
            removed = snapshot.remove_edges(lambda e: e.type == rel_type and e.source == source and e.target == target)
            snapshot.add_edge(source, rel_type, new_target, {"hypothetical": True})
            return {"op": kind, "removed_edges": removed, "added": f"{source}-[:{rel_type}]->{new_target}"}
        raise ValueError(f"Unsupported simulation operation: {kind}")

    def simulate(self, entity_id: str, operations: list[dict[str, Any]], *, max_depth: int = 6) -> dict[str, Any] | None:
        canonical = GraphSnapshot.load(self.client)
        if canonical.node(entity_id) is None:
            return None
        hypothetical = canonical.clone()
        baseline = self._blast(canonical, entity_id, max_depth=max_depth)
        baseline_constraints = self._constraint_summary(canonical)
        applied = [self._apply(hypothetical, op) for op in operations]
        counterfactual = self._blast(hypothetical, entity_id, max_depth=max_depth)
        counterfactual_constraints = self._constraint_summary(hypothetical)
        baseline_set = set(baseline["impacted"])
        counter_set = set(counterfactual["impacted"])
        return {
            "entity": canonical.node(entity_id),
            "operations": applied,
            "canonical_result": {"blast_radius": baseline, "constraints": baseline_constraints},
            "counterfactual_result": {"blast_radius": counterfactual, "constraints": counterfactual_constraints},
            "delta": {
                "systems_no_longer_exposed": sorted(baseline_set - counter_set),
                "newly_exposed_systems": sorted(counter_set - baseline_set),
                "paths_removed_count": max(0, len(baseline["paths"]) - len(counterfactual["paths"])),
            },
            "canonical_mutated": False,
            "hypothetical_only": True,
            "graph_required": True,
        }
