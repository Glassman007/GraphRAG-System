from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase8_utils import entities_with_label, node_visible, path_text


COVERAGE_RELATIONS = {
    "ownership": {"OWNS"},
    "responsibility": {"RESPONSIBLE_FOR"},
    "expertise": {"EXPERT_IN"},
}


class BusFactorService:
    MAX_RESOURCES = 300
    MAX_ACTORS = 300

    def __init__(self, client: FalkorGraphClient):
        self.client = client

    @staticmethod
    def _actors_for(snapshot: GraphSnapshot, resource_id: str, rels: set[str], *, as_of: str | None = None, unavailable: set[str] | None = None) -> list[dict[str, Any]]:
        unavailable = unavailable or set()
        out = []
        for edge in snapshot.edges_to(resource_id, rels, as_of=as_of):
            actor = snapshot.node(edge.source)
            if not actor or edge.source in unavailable or not node_visible(actor, as_of):
                continue
            if not (has_label(actor, "Person") or has_label(actor, "Team") or has_label(actor, "Agent")):
                continue
            out.append({"actor": actor, "relationship": edge.type, "confidence": float(edge.properties.get("confidence", 1.0)), "path": path_text(edge)})
        out.sort(key=lambda x: str(x["actor"].get("id")))
        return out

    @staticmethod
    def _approvers_for(snapshot: GraphSnapshot, resource_id: str, *, as_of: str | None = None, unavailable: set[str] | None = None) -> list[dict[str, Any]]:
        unavailable = unavailable or set()
        related = {resource_id}
        # Bounded one-hop operational objects about / affecting the resource.
        for edge in snapshot.edges_to(resource_id, {"ABOUT", "AFFECTS", "CHANGED"}, as_of=as_of):
            related.add(edge.source)
        for edge in snapshot.edges_from(resource_id, {"ABOUT", "AFFECTS", "CHANGED"}, as_of=as_of):
            related.add(edge.target)
        out = []
        seen = set()
        for rid in sorted(related):
            for edge in snapshot.edges_from(rid, {"APPROVED_BY"}, as_of=as_of):
                if edge.target in unavailable or edge.target in seen:
                    continue
                actor = snapshot.node(edge.target)
                if actor and node_visible(actor, as_of):
                    seen.add(edge.target)
                    out.append({"actor": actor, "relationship": "APPROVED_BY", "path": path_text(edge), "approved_entity": rid})
        return out

    @staticmethod
    def resource_coverage_from_snapshot(snapshot: GraphSnapshot, resource_id: str, *, as_of: str | None = None, unavailable: set[str] | None = None) -> dict[str, Any] | None:
        resource = snapshot.node(resource_id)
        if resource is None or not node_visible(resource, as_of):
            return None
        dimensions = {}
        for name, rels in COVERAGE_RELATIONS.items():
            actors = BusFactorService._actors_for(snapshot, resource_id, rels, as_of=as_of, unavailable=unavailable)
            dimensions[name] = {"count": len(actors), "actors": actors}
        approvers = BusFactorService._approvers_for(snapshot, resource_id, as_of=as_of, unavailable=unavailable)
        dimensions["approval"] = {"count": len(approvers), "actors": approvers}
        relevant_counts = []
        for name in ("ownership", "responsibility", "expertise", "approval"):
            count = dimensions[name]["count"]
            if count > 0:
                relevant_counts.append(count)
        bus_factor = min(relevant_counts) if relevant_counts else 0
        criticality = str(resource.get("criticality") or "MEDIUM").upper()
        gaps = [name for name, value in dimensions.items() if value["count"] == 0]
        if bus_factor <= 1 and criticality in {"HIGH", "CRITICAL", "SEV-0", "SEV-1"}:
            risk = "HIGH"
        elif bus_factor <= 1:
            risk = "MEDIUM"
        elif bus_factor == 2:
            risk = "MEDIUM"
        else:
            risk = "LOW"
        return {
            "resource": resource,
            "as_of": as_of,
            "coverage": dimensions,
            "bus_factor": bus_factor,
            "risk": risk,
            "coverage_gaps": gaps,
            "explanation": f"minimum non-zero independent coverage dimension is {bus_factor}; criticality={criticality}",
            "graph_required": True,
        }

    @staticmethod
    def _active_tasks_for_actor(snapshot: GraphSnapshot, actor_id: str, *, as_of: str | None = None) -> list[str]:
        active = {"OPEN", "PENDING", "READY", "CLAIMED", "IN_PROGRESS", "BLOCKED", "HANDOFF_PENDING", "STALE_INPUT"}
        ids = set()
        for edge in snapshot.edges_from(actor_id, {"CANDIDATE_FOR"}, as_of=as_of):
            task = snapshot.node(edge.target)
            if task and has_label(task, "Task") and str(task.get("status") or "").upper() in active:
                ids.add(edge.target)
        for edge in snapshot.edges_to(actor_id, {"CLAIMED_BY", "ASSIGNED_TO"}, as_of=as_of):
            task = snapshot.node(edge.source)
            if task and has_label(task, "Task") and str(task.get("status") or "").upper() in active:
                ids.add(edge.source)
        return sorted(ids)

    @staticmethod
    def simulate_loss_from_snapshot(snapshot: GraphSnapshot, actor_ids: list[str], *, as_of: str | None = None) -> dict[str, Any]:
        unavailable = set(actor_ids)
        resources = [n for n in snapshot.nodes.values() if (has_label(n, "System") or has_label(n, "Project")) and node_visible(n, as_of)]
        affected = []
        for resource in sorted(resources, key=lambda n: str(n.get("id")))[: BusFactorService.MAX_RESOURCES]:
            rid = str(resource["id"])
            before = BusFactorService.resource_coverage_from_snapshot(snapshot, rid, as_of=as_of, unavailable=set())
            after = BusFactorService.resource_coverage_from_snapshot(snapshot, rid, as_of=as_of, unavailable=unavailable)
            if not before or not after:
                continue
            newly_lost = []
            for dim in before["coverage"]:
                if before["coverage"][dim]["count"] > 0 and after["coverage"][dim]["count"] == 0:
                    newly_lost.append(dim)
            if newly_lost:
                affected.append({"resource": resource, "lost_dimensions": newly_lost, "before": before["coverage"], "after": after["coverage"]})

        unroutable = []
        active = {"OPEN", "PENDING", "READY", "CLAIMED", "IN_PROGRESS", "BLOCKED", "HANDOFF_PENDING", "STALE_INPUT"}
        for task in [n for n in snapshot.nodes.values() if has_label(n, "Task") and str(n.get("status") or "").upper() in active and node_visible(n, as_of)]:
            tid = str(task["id"])
            candidates = [e.source for e in snapshot.edges_to(tid, {"CANDIDATE_FOR"}, as_of=as_of)]
            if candidates and all(x in unavailable for x in candidates):
                unroutable.append({"task": task, "candidate_ids": sorted(candidates), "reason": "all graph-ranked candidates unavailable"})

        approval_gaps = []
        for action in [n for n in snapshot.nodes.values() if has_label(n, "Action") and node_visible(n, as_of)]:
            aid = str(action["id"])
            approvers = [e.target for e in snapshot.edges_from(aid, {"APPROVED_BY"}, as_of=as_of)]
            if approvers and all(a in unavailable for a in approvers):
                approval_gaps.append({"action": action, "approver_ids": sorted(approvers)})

        return {
            "unavailable_actor_ids": sorted(unavailable),
            "affected_resources": affected,
            "unroutable_tasks": unroutable,
            "approval_gaps": approval_gaps,
            "canonical_graph_mutated": False,
            "graph_required": True,
        }

    def simulate_loss(self, actor_ids: list[str], *, as_of: str | None = None) -> dict[str, Any]:
        snapshot = GraphSnapshot.load(self.client)
        return self.simulate_loss_from_snapshot(snapshot, actor_ids, as_of=as_of)

    def actor_impact(self, actor_id: str, *, as_of: str | None = None) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        actor = snapshot.node(actor_id)
        if actor is None or not (has_label(actor, "Person") or has_label(actor, "Team") or has_label(actor, "Agent")):
            return None
        sim = self.simulate_loss_from_snapshot(snapshot, [actor_id], as_of=as_of)
        unique = []
        for item in sim["affected_resources"]:
            unique.append({"resource": item["resource"], "unique_capabilities": item["lost_dimensions"]})
        high = any(str(x["resource"].get("criticality") or "").upper() in {"HIGH", "CRITICAL"} for x in unique)
        risk = "HIGH" if high or len(unique) >= 2 else "MEDIUM" if unique or sim["unroutable_tasks"] or sim["approval_gaps"] else "LOW"
        return {
            "actor": actor,
            "risk": risk,
            "unique_capabilities": unique,
            "systems_affected": [x["resource"] for x in unique if has_label(x["resource"], "System")],
            "approval_dependencies": sim["approval_gaps"],
            "unroutable_tasks": sim["unroutable_tasks"],
            "active_tasks": self._active_tasks_for_actor(snapshot, actor_id, as_of=as_of),
            "simulation": sim,
        }

    def organization_summary(self, *, as_of: str | None = None, limit: int = 100) -> dict[str, Any]:
        snapshot = GraphSnapshot.load(self.client)
        resources = entities_with_label(snapshot, "System", as_of=as_of)[: self.MAX_RESOURCES]
        results = [self.resource_coverage_from_snapshot(snapshot, str(r["id"]), as_of=as_of) for r in resources]
        results = [x for x in results if x]
        results.sort(key=lambda x: ({"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(x["risk"], 3), x["bus_factor"], str(x["resource"].get("id"))))
        return {"as_of": as_of, "resources": results[:limit], "bounds": {"max_resources": self.MAX_RESOURCES, "limit": limit}, "graph_required": True}
