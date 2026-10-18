from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase6_utils import csv, csv_list, now_iso


DEFAULT_AGENT_SPECS: dict[str, dict[str, Any]] = {
    "AGENT-P6-INVESTIGATOR": {
        "name": "Investigator Worker",
        "agent_type": "INVESTIGATOR",
        "capabilities": ["RELATIONAL_INVESTIGATION", "EVIDENCE_COLLECTION", "FINDING_CREATION"],
        "supported_task_types": ["INVESTIGATE", "ACQUIRE_EVIDENCE"],
        "permissions": ["READ_GRAPH", "WRITE_FINDING", "LINK_EVIDENCE", "CHECKPOINT"],
        "supported_tools": ["TOOL-DEPLOY-LOOKUP", "TOOL-GIT-LOOKUP", "TOOL-LOG-LOOKUP", "TOOL-CATALOG-LOOKUP"],
        "evidence_types": ["INVESTIGATION_RESULT", "EVIDENCE"],
        "actions_may_propose": [],
        "actions_may_execute": [],
    },
    "AGENT-P6-VERIFIER": {
        "name": "Verifier Worker",
        "agent_type": "VERIFIER",
        "capabilities": ["EVIDENCE_VERIFICATION", "CLAIM_VERIFICATION", "POLICY_VALIDATION", "HANDOFF_VALIDATION"],
        "supported_task_types": ["VERIFY_CLAIM", "RESOLVE_CONFLICT", "VALIDATE_POLICY", "VALIDATE_OUTCOME", "REQUEST_APPROVAL"],
        "permissions": ["READ_GRAPH", "WRITE_FINDING", "VALIDATE_FINDING", "CHECKPOINT"],
        "supported_tools": [],
        "evidence_types": ["VALIDATION_RESULT", "CLAIM_STATUS", "APPROVAL"],
        "actions_may_propose": [],
        "actions_may_execute": [],
    },
    "AGENT-P6-DEPENDENCY": {
        "name": "Dependency Analyst Worker",
        "agent_type": "DEPENDENCY_ANALYST",
        "capabilities": ["BLAST_RADIUS", "DEPENDENCY_ANALYSIS", "TOPOLOGY_RISK"],
        "supported_task_types": ["INVESTIGATE"],
        "permissions": ["READ_GRAPH", "WRITE_FINDING", "CHECKPOINT"],
        "supported_tools": ["TOOL-CATALOG-LOOKUP"],
        "evidence_types": ["INVESTIGATION_RESULT"],
        "actions_may_propose": [],
        "actions_may_execute": [],
    },
    "AGENT-P6-REMEDIATION": {
        "name": "Remediation Worker",
        "agent_type": "REMEDIATION_WORKER",
        "capabilities": ["ACTION_PREPARATION", "GOVERNED_ACTION", "OUTCOME_VALIDATION"],
        "supported_task_types": ["PREPARE_ACTION", "VALIDATE_OUTCOME"],
        "permissions": ["READ_GRAPH", "WRITE_FINDING", "PROPOSE_ACTION", "EXECUTE_SANDBOX_ACTION", "CHECKPOINT"],
        "supported_tools": [],
        "evidence_types": ["ACTION_PROPOSAL", "VALIDATION_RESULT"],
        "actions_may_propose": ["rollback", "verification", "recovery", "service_restart"],
        "actions_may_execute": ["rollback", "verification", "recovery", "service_restart"],
    },
}


class AgentRegistryService:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    def ensure_default_agents(self, *, timestamp: str | None = None) -> list[dict[str, Any]]:
        """Ensure the four built-in worker definitions exist without resetting runtime state.

        Registry calls are intentionally idempotent. Mutable coordination fields such as
        ``status`` and ``availability`` belong to persisted execution state and must not be
        reset merely because another process reconstructs the registry.
        """
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        result = []
        for agent_id, spec in DEFAULT_AGENT_SPECS.items():
            existing = snapshot.node(agent_id)
            props = {
                "name": spec["name"],
                "agent_type": spec["agent_type"],
                "status": (existing or {}).get("status") or "ACTIVE",
                "availability": (existing or {}).get("availability") or "AVAILABLE",
                "created_at": (existing or {}).get("created_at") or timestamp,
                "capabilities": csv(spec["capabilities"]),
                "supported_task_types": csv(spec["supported_task_types"]),
                "permissions": csv(spec["permissions"]),
                "supported_tools": csv(spec["supported_tools"]),
                "evidence_types": csv(spec["evidence_types"]),
                "actions_may_propose": csv(spec["actions_may_propose"]),
                "actions_may_execute": csv(spec["actions_may_execute"]),
                "registry_version": "phase6-v1",
            }
            upsert_node(self.client, "Agent", agent_id, props)
            result.append({"id": agent_id, **props})
        return result

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        node = GraphSnapshot.load(self.client).node(agent_id)
        return node if node and has_label(node, "Agent") else None

    @staticmethod
    def _eligibility(agent: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
        supported = set(csv_list(agent.get("supported_task_types")))
        permissions = set(csv_list(agent.get("permissions")))
        task_type = str(task.get("task_type") or "")
        reasons: list[str] = []
        if str(agent.get("status") or "").upper() != "ACTIVE":
            reasons.append("AGENT_NOT_ACTIVE")
        if str(agent.get("availability") or "AVAILABLE").upper() not in {"AVAILABLE", "IDLE"}:
            reasons.append("AGENT_NOT_AVAILABLE")
        if task_type not in supported:
            reasons.append(f"TASK_TYPE_NOT_SUPPORTED:{task_type}")
        if "READ_GRAPH" not in permissions:
            reasons.append("READ_GRAPH_PERMISSION_REQUIRED")
        return {
            "eligible": not reasons,
            "reason_codes": reasons,
            "task_type": task_type,
            "supported_task_types": sorted(supported),
            "permissions": sorted(permissions),
        }

    def check_task_eligibility(self, task_id: str, agent_id: str) -> dict[str, Any]:
        snapshot = GraphSnapshot.load(self.client)
        task = snapshot.node(task_id)
        agent = snapshot.node(agent_id)
        if not task or not has_label(task, "Task"):
            return {"eligible": False, "reason_codes": ["TASK_NOT_FOUND"], "task": task, "agent": agent}
        if not agent or not has_label(agent, "Agent"):
            return {"eligible": False, "reason_codes": ["AGENT_NOT_FOUND"], "task": task, "agent": agent}
        result = self._eligibility(agent, task)
        # Phase 5 CANDIDATE_FOR is preferred evidence, but equivalent persisted capability is allowed.
        is_candidate = any(edge.source == agent_id for edge in snapshot.edges_to(task_id, {"CANDIDATE_FOR"}))
        return {**result, "task": task, "agent": agent, "phase5_candidate": is_candidate, "eligibility_basis": "CANDIDATE_FOR" if is_candidate else "PERSISTED_CAPABILITY"}
