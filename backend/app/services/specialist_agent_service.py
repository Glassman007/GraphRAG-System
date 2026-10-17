from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.agent_registry_service import AgentRegistryService
from backend.app.services.blast_radius_service import BlastRadiusService
from backend.app.services.coordination_service import CoordinationService
from backend.app.services.investigation_service import RelationalInvestigationService
from backend.app.services.phase4_graph import GraphSnapshot, has_label


class SpecialistAgentService:
    """Bounded deterministic worker behavior. No LLM loop and no free-form autonomous actions."""

    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self.registry = AgentRegistryService(client)
        self.coordination = CoordinationService(client)

    def _owned_task(self, task_id: str, agent_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        snapshot = GraphSnapshot.load(self.client)
        task = snapshot.node(task_id)
        agent = snapshot.node(agent_id)
        if not task or not has_label(task, "Task"):
            raise ValueError(f"Task not found: {task_id}")
        if not agent or not has_label(agent, "Agent"):
            raise ValueError(f"Agent not found: {agent_id}")
        owner = (self.coordination.get_task_owner(task_id) or {}).get("owner")
        if not owner or str(owner.get("id")) != agent_id:
            raise ValueError("Agent must own the task before running bounded work")
        return task, agent

    def run_investigator_step(self, task_id: str, agent_id: str) -> dict[str, Any]:
        task, agent = self._owned_task(task_id, agent_id)
        if str(agent.get("agent_type")) != "INVESTIGATOR":
            raise ValueError("Only INVESTIGATOR may run investigator behavior")
        if str(task.get("task_type")) not in {"INVESTIGATE", "ACQUIRE_EVIDENCE"}:
            raise ValueError("INVESTIGATOR does not support this task type")
        snapshot = GraphSnapshot.load(self.client)
        incident_ids = [edge.target for edge in snapshot.edges_from(task_id, {"ABOUT"}) if has_label(snapshot.node(edge.target), "Incident")]
        if not incident_ids:
            incident_ids = [str(task.get("situation_id"))] if has_label(snapshot.node(str(task.get("situation_id"))), "Incident") else []
        result = RelationalInvestigationService(self.client).investigate_incident(incident_ids[0]) if incident_ids else None
        path_count = len((result or {}).get("candidate_paths") or [])
        finding = self.coordination.add_finding(task_id, agent_id, statement=f"Deterministic investigation produced {path_count} connected candidate path(s).", confidence=0.8 if path_count else 0.4, kind="INVESTIGATION_RESULT")
        return {"agent_type": "INVESTIGATOR", "investigation": result, "finding": finding}

    def run_dependency_step(self, task_id: str, agent_id: str) -> dict[str, Any]:
        task, agent = self._owned_task(task_id, agent_id)
        if str(agent.get("agent_type")) != "DEPENDENCY_ANALYST":
            raise ValueError("Only DEPENDENCY_ANALYST may run dependency behavior")
        if str(task.get("task_type")) != "INVESTIGATE":
            raise ValueError("DEPENDENCY_ANALYST only accepts INVESTIGATE tasks")
        snapshot = GraphSnapshot.load(self.client)
        systems = [edge.target for edge in snapshot.edges_from(task_id, {"ABOUT"}) if has_label(snapshot.node(edge.target), "System")]
        if not systems:
            raise ValueError("Dependency task has no graph-linked System target")
        analysis = BlastRadiusService(self.client).analyze(systems[0])
        downstream = len((analysis or {}).get("downstream_dependents") or [])
        finding = self.coordination.add_finding(task_id, agent_id, statement=f"Dependency analysis for {systems[0]} found {downstream} downstream dependent(s).", confidence=0.9, kind="DEPENDENCY_ANALYSIS")
        return {"agent_type": "DEPENDENCY_ANALYST", "analysis": analysis, "finding": finding}

    def verify_finding(self, finding_id: str, agent_id: str, *, result: str, rationale: str = "") -> dict[str, Any]:
        agent = self.registry.get_agent(agent_id)
        if not agent or str(agent.get("agent_type")) != "VERIFIER":
            raise ValueError("Only VERIFIER may verify findings")
        return self.coordination.verify_finding(finding_id, agent_id, result=result, rationale=rationale)

    def remediation_capability(self, task_id: str, agent_id: str) -> dict[str, Any]:
        task, agent = self._owned_task(task_id, agent_id)
        if str(agent.get("agent_type")) != "REMEDIATION_WORKER":
            raise ValueError("Only REMEDIATION_WORKER may prepare remediation actions")
        if str(task.get("task_type")) not in {"PREPARE_ACTION", "VALIDATE_OUTCOME"}:
            raise ValueError("REMEDIATION_WORKER does not support this task type")
        return {"allowed": True, "task": task, "agent": agent, "note": "Action execution still requires GovernanceService ALLOW."}
