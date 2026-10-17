from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.temporal import to_epoch_us
from backend.app.services.coordination_service import CoordinationService
from backend.app.services.event_ledger_service import EventLedgerService
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase6_utils import now_iso
from backend.app.services.work_planning_service import WorkPlanningService


class CoordinationRiskService:
    """Explainable deadlock, contention, abandoned-lock and starvation detection."""

    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self.events = EventLedgerService(client)
        self.coordination = CoordinationService(client)

    @staticmethod
    def _cycles(adjacency: dict[str, set[str]]) -> list[list[str]]:
        cycles: set[tuple[str, ...]] = set()
        visiting: list[str] = []
        on_stack: set[str] = set()

        def canonical(cycle: list[str]) -> tuple[str, ...]:
            core = cycle[:-1]
            if not core:
                return tuple(cycle)
            rotations = [tuple(core[i:] + core[:i]) for i in range(len(core))]
            best = min(rotations)
            return best + (best[0],)

        def dfs(node: str) -> None:
            visiting.append(node)
            on_stack.add(node)
            for nxt in sorted(adjacency.get(node, set())):
                if nxt in on_stack:
                    idx = visiting.index(nxt)
                    cycles.add(canonical(visiting[idx:] + [nxt]))
                elif nxt not in visited:
                    dfs(nxt)
            on_stack.remove(node)
            visiting.pop()
            visited.add(node)

        visited: set[str] = set()
        for node in sorted(adjacency):
            if node not in visited:
                dfs(node)
        return [list(cycle) for cycle in sorted(cycles)]

    def detect_deadlocks(self, *, record_events: bool = False) -> dict[str, Any]:
        snapshot = GraphSnapshot.load(self.client)
        adjacency: dict[str, set[str]] = defaultdict(set)
        edge_map: dict[tuple[str, str], list[str]] = defaultdict(list)
        for edge in snapshot.edges:
            if edge.type not in {"BLOCKED_BY", "REQUIRES"}:
                continue
            if not (has_label(snapshot.node(edge.source), "Task") and has_label(snapshot.node(edge.target), "Task")):
                continue
            target = snapshot.node(edge.target) or {}
            if edge.type == "REQUIRES" and str(target.get("status") or "").upper() in {"COMPLETED", "DONE", "RESOLVED", "CLOSED"}:
                continue
            adjacency[edge.source].add(edge.target)
            edge_map[(edge.source, edge.target)].append(edge.type)
        cycles = self._cycles(adjacency)
        findings = []
        for cycle in cycles:
            tasks = cycle[:-1]
            agents = []
            blocking_edges = []
            for idx in range(len(tasks)):
                src = cycle[idx]
                dst = cycle[idx + 1]
                blocking_edges.append({"source": src, "target": dst, "types": edge_map.get((src, dst), [])})
                owner = (self.coordination.get_task_owner(src) or {}).get("owner")
                if owner:
                    agents.append(str(owner.get("id")))
            item = {
                "cycle": cycle,
                "tasks": tasks,
                "agents": sorted(set(agents)),
                "blocking_edges": blocking_edges,
                "recommended_recovery": "Review one blocking dependency/ownership edge and explicitly release, resolve, or re-plan; no automatic resolution applied.",
            }
            findings.append(item)
            if record_events:
                self.events.record("DEADLOCK_DETECTED", about_ids=tasks, summary=" -> ".join(cycle))
        return {"deadlocks": findings, "count": len(findings), "graph_required": True}

    def detect_contention(self, *, as_of: str | None = None, starvation_age_seconds: int = 1800, min_claim_attempts: int = 3) -> dict[str, Any]:
        as_of = as_of or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        conflicting_ownership = []
        for node_id, node in snapshot.nodes.items():
            if not has_label(node, "Task"):
                continue
            claims = CoordinationService._active_claims(snapshot, node_id, as_of=as_of)
            if len(claims) > 1:
                conflicting_ownership.append({"task_id": node_id, "owners": [c["agent"] for c in claims]})

        locks_by_resource: dict[str, list[dict[str, Any]]] = defaultdict(list)
        abandoned_locks = []
        for lock_id, lock in snapshot.nodes.items():
            if not has_label(lock, "Lock"):
                continue
            status = str(lock.get("status") or "ACTIVE").upper()
            resources = [edge.target for edge in snapshot.edges_from(lock_id, {"LOCKS"})]
            lease_until = lock.get("lease_until")
            expired = bool(lease_until and to_epoch_us(str(lease_until)) <= to_epoch_us(as_of))
            if status == "ACTIVE" and expired:
                abandoned_locks.append({"lock": lock, "resources": resources, "reason": "LEASE_EXPIRED"})
            if status == "ACTIVE" and not expired:
                for resource in resources:
                    locks_by_resource[resource].append(lock)
        resource_contention = [
            {"resource_id": resource, "locks": locks}
            for resource, locks in sorted(locks_by_resource.items())
            if len(locks) > 1
        ]

        starvation = []
        planner = WorkPlanningService(self.client)
        as_of_us = to_epoch_us(as_of)
        for task_id, task in snapshot.nodes.items():
            if not has_label(task, "Task"):
                continue
            if CoordinationService._active_claims(snapshot, task_id, as_of=as_of):
                continue
            readiness = planner._task_readiness(snapshot, task_id)
            if not readiness["ready"]:
                continue
            ready_since = task.get("ready_since") or task.get("created_at")
            if not ready_since:
                continue
            age_seconds = max(0.0, (as_of_us - to_epoch_us(str(ready_since))) / 1_000_000)
            attempts = int(task.get("claim_attempts") or 0)
            priority = str(task.get("priority") or "P2").upper()
            age_threshold = starvation_age_seconds / (2 if priority in {"P0", "HIGH"} else 1)
            if age_seconds >= age_threshold and attempts >= min_claim_attempts:
                starvation.append({
                    "task": task,
                    "ready_age_seconds": round(age_seconds, 2),
                    "claim_attempts": attempts,
                    "priority": priority,
                    "reason": "READY task exceeded age threshold with repeated claim attempts and no active owner",
                })
        return {
            "as_of": as_of,
            "conflicting_ownership": conflicting_ownership,
            "resource_contention": resource_contention,
            "abandoned_locks": abandoned_locks,
            "starvation": starvation,
            "graph_required": True,
        }
