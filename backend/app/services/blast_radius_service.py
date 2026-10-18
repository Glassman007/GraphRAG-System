from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot, has_label


class BlastRadiusService:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    @staticmethod
    def _observed_evidence(snapshot: GraphSnapshot, system_id: str) -> list[dict[str, Any]]:
        evidence_ids = {e.source for e in snapshot.edges_to(system_id, {"ABOUT"}) if has_label(snapshot.node(e.source), "Evidence")}
        out = []
        for eid in sorted(evidence_ids):
            evidence = snapshot.node(eid)
            incident_links = [e.target for e in snapshot.edges_from(eid, {"ABOUT"}) if has_label(snapshot.node(e.target), "Incident")]
            if incident_links:
                out.append({"evidence": evidence, "incidents": incident_links})
        return out

    def analyze(self, entity_id: str, *, max_depth: int = 6, as_of: str | None = None) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        entity = snapshot.node(entity_id)
        if entity is None:
            return None

        roots: list[dict[str, Any]] = []
        if has_label(entity, "Change"):
            for edge in snapshot.edges_from(entity_id, {"CHANGED", "AFFECTS"}, as_of=as_of):
                roots.append({"system_id": edge.target, "via_change_edge": edge.as_dict()})
        else:
            roots.append({"system_id": entity_id, "via_change_edge": None})

        impacted: dict[str, dict[str, Any]] = {}
        for root in roots:
            root_id = root["system_id"]
            for item in snapshot.dependency_reachability(root_id, reverse=True, max_depth=max_depth, as_of=as_of):
                system = snapshot.node(item["entity_id"])
                if not has_label(system, "System"):
                    continue
                observed = self._observed_evidence(snapshot, item["entity_id"])
                candidate = {
                    "system": system,
                    "depth": item["depth"],
                    "impact": "OBSERVED" if observed else "POTENTIAL",
                    "observed_evidence": observed,
                    "path": item,
                    "root_system_id": root_id,
                }
                prior = impacted.get(item["entity_id"])
                if prior is None or candidate["depth"] < prior["depth"] or (candidate["impact"] == "OBSERVED" and prior["impact"] != "OBSERVED"):
                    impacted[item["entity_id"]] = candidate

        upstream = []
        if has_label(entity, "System"):
            for item in snapshot.dependency_reachability(entity_id, reverse=False, max_depth=max_depth, as_of=as_of):
                node = snapshot.node(item["entity_id"])
                if has_label(node, "System"):
                    upstream.append({"system": node, "depth": item["depth"], "path": item})

        values = sorted(impacted.values(), key=lambda x: (x["depth"], str(x["system"].get("id"))))
        return {
            "entity": entity,
            "roots": roots,
            "downstream_dependents": values,
            "upstream_dependencies": upstream,
            "observed_count": sum(1 for x in values if x["impact"] == "OBSERVED"),
            "potential_count": sum(1 for x in values if x["impact"] == "POTENTIAL"),
            "cycle_protection": "simple-path visited-node guard",
            "graph_required": True,
        }
