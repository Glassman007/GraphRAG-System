from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot, has_label


_DONE = {"COMPLETED", "EXECUTED", "SUCCESS", "SUCCEEDED", "VERIFIED", "RESOLVED", "CLOSED"}
_BAD = {"REJECTED", "CANCELLED", "FAILED", "PROHIBITED"}


class ConstraintPlanningService:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    @staticmethod
    def _prereq_satisfied(node: dict[str, Any] | None) -> bool:
        if not node:
            return False
        if has_label(node, "Evidence") or has_label(node, "Tool") or has_label(node, "DataSource"):
            return True
        return str(node.get("status") or "").upper() in _DONE

    @staticmethod
    def _action_constraints(
        snapshot: GraphSnapshot,
        action_id: str,
        included: set[str],
        *,
        as_of: str | None = None,
    ) -> list[dict[str, Any]]:
        action = snapshot.node(action_id) or {}
        violations: list[dict[str, Any]] = []
        if str(action.get("status") or "").upper() in _BAD:
            violations.append({"code": "PROHIBITED_STATE", "detail": f"action status is {action.get('status')}"})
        if action.get("approval_required") and not snapshot.edges_from(action_id, {"APPROVED_BY"}, as_of=as_of):
            violations.append({"code": "MISSING_APPROVAL", "detail": "approval_required=true but APPROVED_BY is absent"})
        prohibited = action.get("prohibited_subject_statuses") or []
        if isinstance(prohibited, str):
            prohibited = [prohibited]
        if prohibited:
            for edge in snapshot.edges_from(action_id, {"ABOUT"}, as_of=as_of):
                subject = snapshot.node(edge.target) or {}
                if str(subject.get("status") or "").upper() in {str(x).upper() for x in prohibited}:
                    violations.append({"code": "PROHIBITED_SUBJECT_STATE", "detail": f"{edge.target} status={subject.get('status')}"})
        for req in snapshot.edges_from(action_id, {"REQUIRES"}, as_of=as_of):
            prerequisite = snapshot.node(req.target)
            if has_label(prerequisite, "Action") and req.target in included:
                continue
            if not ConstraintPlanningService._prereq_satisfied(prerequisite):
                violations.append({
                    "code": "UNSATISFIED_REQUIREMENT",
                    "detail": f"{action_id}-[:REQUIRES]->{req.target}",
                    "prerequisite": prerequisite,
                })
        return violations

    def plan_for_incident(self, incident_id: str, *, as_of: str | None = None) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        incident = snapshot.node(incident_id)
        if incident is None or not has_label(incident, "Incident"):
            return None
        action_ids = {
            e.source for e in snapshot.edges_to(incident_id, {"ABOUT"}, as_of=as_of)
            if has_label(snapshot.node(e.source), "Action")
        }
        preferred = {
            aid for aid in action_ids
            if str((snapshot.node(aid) or {}).get("decision_role") or "").upper() != "ALTERNATIVE"
            and bool((snapshot.node(aid) or {}).get("plan_candidate", True))
        }
        rejected = []
        for aid in sorted(action_ids - preferred):
            rejected.append({"action": snapshot.node(aid), "reason_codes": ["ALTERNATIVE_OR_NOT_SELECTED"]})

        # Policy constraints can add required actions when a policy governs a selected action.
        policy_paths = []
        expanded = set(preferred)
        for aid in list(preferred):
            for gov in snapshot.edges_to(aid, {"GOVERNS"}, as_of=as_of):
                if not has_label(snapshot.node(gov.source), "Policy"):
                    continue
                policy = snapshot.node(gov.source) or {}
                for req in snapshot.edges_from(gov.source, {"REQUIRES"}, as_of=as_of):
                    if has_label(snapshot.node(req.target), "Action"):
                        expanded.add(req.target)
                        policy_paths.append(f"{gov.source}-[:GOVERNS]->{aid}; {gov.source}-[:REQUIRES]->{req.target}")

        # Build action prerequisite DAG.
        indegree = {aid: 0 for aid in expanded}
        outgoing: dict[str, list[str]] = defaultdict(list)
        requirement_paths = []
        for aid in expanded:
            for req in snapshot.edges_from(aid, {"REQUIRES"}, as_of=as_of):
                if req.target in expanded and has_label(snapshot.node(req.target), "Action"):
                    # prerequisite -> dependent for topological sorting
                    outgoing[req.target].append(aid)
                    indegree[aid] += 1
                    requirement_paths.append(f"{aid}-[:REQUIRES]->{req.target}")
        queue = deque(sorted([aid for aid, deg in indegree.items() if deg == 0]))
        ordered: list[str] = []
        while queue:
            item = queue.popleft()
            ordered.append(item)
            for nxt in sorted(outgoing.get(item, [])):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
        cycle = len(ordered) != len(expanded)

        violations = []
        for aid in sorted(expanded):
            for violation in self._action_constraints(snapshot, aid, expanded, as_of=as_of):
                violations.append({"action_id": aid, **violation})
        if cycle:
            violations.append({"action_id": None, "code": "ORDERING_CYCLE", "detail": "Action REQUIRES graph is cyclic"})

        # Active task blockers are reported, not silently treated as false facts.
        blockers = []
        for edge in snapshot.edges_to(incident_id, {"ABOUT"}, as_of=as_of):
            if not has_label(snapshot.node(edge.source), "Task"):
                continue
            for block in snapshot.edges_from(edge.source, {"BLOCKED_BY"}, as_of=as_of):
                target = snapshot.node(block.target) or {}
                if not self._prereq_satisfied(target):
                    blockers.append({"task": snapshot.node(edge.source), "blocker": target, "path": f"{edge.source}-[:BLOCKED_BY]->{block.target}"})

        steps = []
        for index, aid in enumerate(ordered, start=1):
            action = snapshot.node(aid) or {}
            steps.append({
                "order": index,
                "action": action,
                "requires": [snapshot.node(e.target) for e in snapshot.edges_from(aid, {"REQUIRES"}, as_of=as_of)],
                "approvals": [snapshot.node(e.target) for e in snapshot.edges_from(aid, {"APPROVED_BY"}, as_of=as_of)],
            })
        return {
            "target": incident,
            "status": "VALID" if not violations else "BLOCKED_OR_INVALID",
            "steps": steps,
            "violations": violations,
            "task_blockers": blockers,
            "rejected_candidates": rejected,
            "constraint_paths": sorted(set(requirement_paths + policy_paths + [b["path"] for b in blockers])),
            "graph_required": True,
        }
