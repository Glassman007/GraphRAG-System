from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.agent_registry_service import AgentRegistryService
from backend.app.services.coordination_service import CoordinationService
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase6_utils import csv_list, now_iso
from backend.app.services.routing_service import ResponsibilityRoutingService


class GovernanceService:
    """Deterministic action policy gate. Agent proposals never override this decision."""

    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self.registry = AgentRegistryService(client)
        self.coordination = CoordinationService(client)

    @staticmethod
    def _action_system_targets(snapshot: GraphSnapshot, action_id: str) -> list[str]:
        systems: set[str] = set()
        for edge in snapshot.edges_from(action_id, {"ABOUT"}):
            node = snapshot.node(edge.target)
            if has_label(node, "System"):
                systems.add(edge.target)
            elif has_label(node, "Change"):
                for change_edge in snapshot.edges_from(edge.target, {"CHANGED", "AFFECTS"}):
                    if has_label(snapshot.node(change_edge.target), "System"):
                        systems.add(change_edge.target)
        return sorted(systems)

    def evaluate_action(self, action_id: str, *, agent_id: str | None = None, as_of: str | None = None) -> dict[str, Any]:
        as_of = as_of or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        action = snapshot.node(action_id)
        if not action or not has_label(action, "Action"):
            return {"action_id": action_id, "decision": "DENY", "missing_requirements": ["ACTION_NOT_FOUND"], "policies_checked": [], "ownership_paths": [], "authority_paths": [], "approvals": [], "permissions": []}

        task_edges = snapshot.edges_to(action_id, {"PROPOSED_ACTION"}, as_of=as_of)
        task = snapshot.node(task_edges[0].source) if task_edges else None
        task_id = str((task or {}).get("id") or "")
        missing: list[str] = []
        permissions: list[str] = []
        authority_paths: list[Any] = []

        if not task or not has_label(task, "Task"):
            missing.append("ACTION_NOT_LINKED_TO_TASK")
        elif str(task.get("status") or "").upper() not in {"CLAIMED", "IN_PROGRESS"}:
            missing.append("TASK_NOT_IN_EXECUTION_STATE")
        if task_id and self.coordination.get_unresolved_blockers(task_id):
            missing.append("UNRESOLVED_TASK_BLOCKER")

        agent = snapshot.node(agent_id) if agent_id else None
        if agent_id:
            if not agent or not has_label(agent, "Agent"):
                missing.append("AGENT_NOT_FOUND")
            else:
                permissions = csv_list(agent.get("permissions"))
                if "EXECUTE_SANDBOX_ACTION" not in permissions:
                    missing.append("AGENT_EXECUTION_PERMISSION_MISSING")
                allowed_types = set(csv_list(agent.get("actions_may_execute")))
                if str(action.get("action_type") or "") not in allowed_types:
                    missing.append("ACTION_TYPE_NOT_PERMITTED_FOR_AGENT")
                if task_id:
                    owner = (self.coordination.get_task_owner(task_id, as_of=as_of) or {}).get("owner")
                    if not owner or str(owner.get("id")) != agent_id:
                        missing.append("AGENT_IS_NOT_TASK_OWNER")

        target_systems = self._action_system_targets(snapshot, action_id)
        ownership_paths = []
        for system_id in target_systems:
            owner_info = ResponsibilityRoutingService(self.client).find_owner(system_id, as_of=as_of)
            current = owner_info.get("owners") or []
            if not current:
                missing.append(f"MISSING_CURRENT_OWNER:{system_id}")
            else:
                ownership_paths.extend(item.get("path") for item in current)

        policies = []
        explicit_deny = False
        governed_scope = {action_id, *target_systems}
        # Include Change targets so a policy that governs the change is not missed.
        governed_scope.update(edge.target for edge in snapshot.edges_from(action_id, {"ABOUT"}, as_of=as_of))
        for target_id in sorted(governed_scope):
            for edge in snapshot.edges_to(target_id, {"GOVERNS"}, as_of=as_of):
                policy = snapshot.node(edge.source)
                if not policy or not has_label(policy, "Policy"):
                    continue
                item = {
                    "policy": policy,
                    "target_id": target_id,
                    "path": f"{edge.source}-[:GOVERNS]->{target_id}",
                    "authoritative": bool(edge.properties.get("authoritative") or policy.get("authoritative")),
                }
                policies.append(item)
                effect = str(policy.get("effect") or policy.get("decision") or "").upper()
                if effect in {"DENY", "PROHIBIT", "PROHIBITED"}:
                    explicit_deny = True

        approvals = []
        for edge in snapshot.edges_from(action_id, {"APPROVED_BY"}, as_of=as_of):
            actor = snapshot.node(edge.target)
            if actor:
                approvals.append({"actor": actor, "path": f"{action_id}-[:APPROVED_BY]->{edge.target}"})
                authority_paths.append([action_id, "APPROVED_BY", edge.target])

        approval_required = bool(action.get("approval_required"))
        required_evidence = []
        missing_evidence = []
        for edge in snapshot.edges_from(action_id, {"REQUIRES"}, as_of=as_of):
            target = snapshot.node(edge.target)
            if has_label(target, "Evidence"):
                required_evidence.append(target)
                if str(target.get("status") or "ACTIVE").upper() in {"MISSING", "REJECTED", "INVALID"}:
                    missing_evidence.append(edge.target)
            elif has_label(target, "Question") and str(target.get("status") or "OPEN").upper() not in {"RESOLVED", "CLOSED", "ANSWERED"}:
                missing_evidence.append(edge.target)

        if explicit_deny:
            decision = "DENY"
            missing.append("AUTHORITATIVE_POLICY_DENY")
        elif any(code in missing for code in ("AGENT_NOT_FOUND", "AGENT_EXECUTION_PERMISSION_MISSING", "ACTION_TYPE_NOT_PERMITTED_FOR_AGENT", "AGENT_IS_NOT_TASK_OWNER")):
            decision = "DENY"
        elif approval_required and not approvals:
            decision = "REQUIRES_APPROVAL"
            missing.append("APPROVAL_REQUIRED")
        elif missing_evidence:
            decision = "INSUFFICIENT_EVIDENCE"
            missing.extend(f"MISSING_EVIDENCE:{eid}" for eid in missing_evidence)
        elif any(code.startswith("MISSING_CURRENT_OWNER:") or code in {"ACTION_NOT_LINKED_TO_TASK", "TASK_NOT_IN_EXECUTION_STATE", "UNRESOLVED_TASK_BLOCKER"} for code in missing):
            decision = "DENY"
        else:
            decision = "ALLOW"

        return {
            "action": action,
            "action_id": action_id,
            "task": task,
            "agent": agent,
            "decision": decision,
            "policies_checked": policies,
            "ownership_paths": ownership_paths,
            "authority_paths": authority_paths,
            "approvals": approvals,
            "permissions": permissions,
            "required_evidence": required_evidence,
            "missing_requirements": list(dict.fromkeys(missing)),
            "graph_required": True,
        }
