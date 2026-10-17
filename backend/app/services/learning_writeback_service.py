from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.services.event_ledger_service import EventLedgerService
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase6_utils import now_iso, stable_id


class LearningWritebackService:
    """Central Phase 7 writeback boundary for durable execution results."""

    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self.events = EventLedgerService(client)

    def write_evidence(
        self,
        *,
        source_ref: str,
        content: str,
        evidence_type: str,
        agent_id: str,
        task_id: str,
        execution_id: str,
        situation_id: str | None = None,
        source_id: str | None = None,
        concern_ids: list[str] | None = None,
        supports_claim_ids: list[str] | None = None,
        refutes_claim_ids: list[str] | None = None,
        confidence: float = 1.0,
        source_authority: float = 0.5,
        observed_at: str | None = None,
        ingested_at: str | None = None,
    ) -> dict[str, Any]:
        observed_at = observed_at or now_iso()
        ingested_at = ingested_at or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        required = {agent_id: "Agent", task_id: "Task", execution_id: "Execution"}
        missing = [f"{label}:{eid}" for eid, label in required.items() if not has_label(snapshot.node(eid), label)]
        if missing:
            raise ValueError("Missing writeback provenance entity: " + ", ".join(missing))
        if situation_id and snapshot.node(situation_id) is None:
            raise ValueError(f"Situation not found: {situation_id}")
        if source_id and snapshot.node(source_id) is None:
            raise ValueError(f"Source not found: {source_id}")
        evidence_id = stable_id("E-P7-", source_ref, evidence_type, content, situation_id or "")
        props = {
            "name": content[:120],
            "content": content,
            "evidence_type": evidence_type,
            "status": "VALIDATED",
            "confidence": confidence,
            "source_authority": source_authority,
            "source_ref_id": source_ref,
            "observed_at": observed_at,
            "ingested_at": ingested_at,
            "created_at": ingested_at,
            "producing_agent_id": agent_id,
            "producing_task_id": task_id,
            "producing_execution_id": execution_id,
            "phase": "7",
        }
        upsert_node(self.client, "Evidence", evidence_id, props)
        upsert_relationship(self.client, agent_id, "PRODUCED", evidence_id, {"valid_from": ingested_at, "confidence": 1.0})
        upsert_relationship(self.client, task_id, "PRODUCED", evidence_id, {"valid_from": ingested_at, "confidence": 1.0})
        upsert_relationship(self.client, execution_id, "PRODUCED", evidence_id, {"valid_from": ingested_at, "confidence": 1.0})
        if source_id:
            upsert_relationship(self.client, evidence_id, "DERIVED_FROM", source_id, {"valid_from": ingested_at, "confidence": 1.0})
        for target in dict.fromkeys(([situation_id] if situation_id else []) + list(concern_ids or [])):
            upsert_relationship(self.client, evidence_id, "ABOUT", target, {"valid_from": ingested_at, "confidence": 1.0})
        for claim_id in dict.fromkeys(supports_claim_ids or []):
            upsert_relationship(self.client, evidence_id, "SUPPORTS", claim_id, {"valid_from": ingested_at, "confidence": confidence})
        for claim_id in dict.fromkeys(refutes_claim_ids or []):
            upsert_relationship(self.client, evidence_id, "REFUTES", claim_id, {"valid_from": ingested_at, "confidence": confidence})
        self.events.record(
            "RESULT_WRITTEN_BACK",
            about_ids=[evidence_id, task_id, execution_id] + ([situation_id] if situation_id else []),
            actor_id=agent_id,
            summary=f"Evidence {evidence_id} written back",
            occurred_at=ingested_at,
            event_id=stable_id("EVT-P7-", "RESULT_WRITTEN_BACK", evidence_id),
            properties={"phase": "7", "artifact_type": "Evidence"},
        )
        return self.get_artifact(evidence_id) or {"id": evidence_id, **props}

    def write_claim_from_artifact(
        self,
        artifact_id: str,
        *,
        subject_ids: list[str],
        agent_id: str,
        task_id: str,
        statement: str | None = None,
        confidence: float | None = None,
        evidence_ids: list[str] | None = None,
        branch_id: str | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        source = snapshot.node(artifact_id)
        if source is None or not (has_label(source, "Finding") or has_label(source, "Hypothesis")):
            raise ValueError("Claims may be written back only from a Finding or Hypothesis")
        claim_id = stable_id("C-P7-", artifact_id, *sorted(subject_ids))
        text = statement or str(source.get("statement") or source.get("name") or artifact_id)
        conf = float(confidence if confidence is not None else source.get("confidence") or 0.5)
        upsert_node(self.client, "Claim", claim_id, {
            "statement": text,
            "name": text[:120],
            "status": "UNVERIFIED",
            "confidence": conf,
            "created_at": timestamp,
            "valid_from": timestamp,
            "source_artifact_id": artifact_id,
            "producing_task_id": task_id,
            "branch_id": branch_id,
            "phase": "7",
        })
        upsert_relationship(self.client, claim_id, "DERIVED_FROM", artifact_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_relationship(self.client, claim_id, "ASSERTED_BY", agent_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_relationship(self.client, task_id, "PRODUCED", claim_id, {"valid_from": timestamp, "confidence": 1.0})
        if branch_id:
            upsert_relationship(self.client, claim_id, "PART_OF", branch_id, {"valid_from": timestamp, "confidence": 1.0})
        for sid in dict.fromkeys(subject_ids):
            upsert_relationship(self.client, claim_id, "ABOUT", sid, {"valid_from": timestamp, "confidence": 1.0})
        for eid in dict.fromkeys(evidence_ids or []):
            upsert_relationship(self.client, eid, "SUPPORTS", claim_id, {"valid_from": timestamp, "confidence": 1.0})
        self.events.record(
            "RESULT_WRITTEN_BACK",
            about_ids=[claim_id, artifact_id, task_id],
            actor_id=agent_id,
            summary=f"Claim {claim_id} written back from {artifact_id}",
            occurred_at=timestamp,
            event_id=stable_id("EVT-P7-", "RESULT_WRITTEN_BACK", claim_id),
            properties={"phase": "7", "artifact_type": "Claim"},
        )
        return self.get_artifact(claim_id) or {"id": claim_id}


    def write_decision(
        self,
        decision_id: str,
        *,
        summary: str,
        actor_id: str,
        task_id: str,
        plan_id: str | None = None,
        claim_ids: list[str] | None = None,
        evidence_ids: list[str] | None = None,
        policy_ids: list[str] | None = None,
        action_ids: list[str] | None = None,
        outcome_ids: list[str] | None = None,
        decided_at: str | None = None,
    ) -> dict[str, Any]:
        decided_at = decided_at or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        if not has_label(snapshot.node(actor_id), "Agent") and not has_label(snapshot.node(actor_id), "Person"):
            raise ValueError(f"Decision actor not found: {actor_id}")
        if not has_label(snapshot.node(task_id), "Task"):
            raise ValueError(f"Task not found: {task_id}")
        upsert_node(self.client, "Decision", decision_id, {
            "name": summary[:120], "summary": summary, "status": "ACTIVE",
            "created_at": decided_at, "decided_at": decided_at, "phase": "7",
            "producing_task_id": task_id, "plan_id": plan_id,
        })
        upsert_relationship(self.client, decision_id, "PERFORMED_BY", actor_id, {"valid_from": decided_at, "confidence": 1.0})
        upsert_relationship(self.client, task_id, "PRODUCED", decision_id, {"valid_from": decided_at, "confidence": 1.0})
        if plan_id:
            upsert_relationship(self.client, decision_id, "PART_OF", plan_id, {"valid_from": decided_at, "confidence": 1.0})
        for ref in dict.fromkeys((claim_ids or []) + (evidence_ids or []) + (policy_ids or [])):
            upsert_relationship(self.client, decision_id, "BASED_ON", ref, {"valid_from": decided_at, "confidence": 1.0})
        for aid in dict.fromkeys(action_ids or []):
            upsert_relationship(self.client, decision_id, "PRODUCED", aid, {"valid_from": decided_at, "confidence": 1.0})
        for oid in dict.fromkeys(outcome_ids or []):
            upsert_relationship(self.client, decision_id, "BASED_ON", oid, {"valid_from": decided_at, "confidence": 1.0})
        self.events.record(
            "RESULT_WRITTEN_BACK", about_ids=[decision_id, task_id] + list(claim_ids or []) + list(evidence_ids or []),
            actor_id=actor_id, summary=f"Decision {decision_id} written back", occurred_at=decided_at,
            event_id=stable_id("EVT-P7-", "RESULT_WRITTEN_BACK", decision_id), properties={"phase": "7", "artifact_type": "Decision"},
        )
        return self.get_artifact(decision_id) or {"id": decision_id}

    def write_outcome(
        self,
        action_id: str,
        *,
        observed_effect: str,
        expected_effect: str | None = None,
        result: str,
        affected_ids: list[str] | None = None,
        measurements: dict[str, Any] | None = None,
        observed_at: str | None = None,
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        observed_at = observed_at or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        action = snapshot.node(action_id)
        if action is None or not has_label(action, "Action"):
            raise ValueError(f"Action not found: {action_id}")
        outcome_id = stable_id("OUT-P7-", action_id, observed_effect, result)
        upsert_node(self.client, "Outcome", outcome_id, {
            "name": observed_effect[:120],
            "observed_effect": observed_effect,
            "expected_effect": expected_effect,
            "result": result.upper(),
            "status": "OBSERVED",
            "measurements": str(measurements or {}),
            "observed_at": observed_at,
            "created_at": observed_at,
            "phase": "7",
        })
        upsert_relationship(self.client, action_id, "HAS_OUTCOME", outcome_id, {"valid_from": observed_at, "confidence": 1.0})
        upsert_relationship(self.client, action_id, "PRODUCED", outcome_id, {"valid_from": observed_at, "confidence": 1.0})
        for eid in dict.fromkeys(affected_ids or []):
            upsert_relationship(self.client, outcome_id, "ABOUT", eid, {"valid_from": observed_at, "confidence": 1.0})
        self.events.record(
            "OUTCOME_OBSERVED",
            about_ids=[action_id, outcome_id] + list(affected_ids or []),
            actor_id=actor_id,
            summary=observed_effect,
            occurred_at=observed_at,
            event_id=stable_id("EVT-P7-", "OUTCOME_OBSERVED", outcome_id),
            properties={"phase": "7", "result": result.upper()},
        )
        return self.get_artifact(outcome_id) or {"id": outcome_id}

    def persist_task_completion_history(self, task_id: str, *, execution_id: str, agent_id: str, completed_at: str | None = None) -> dict[str, Any]:
        completed_at = completed_at or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        task = snapshot.node(task_id)
        execution = snapshot.node(execution_id)
        if task is None or execution is None:
            raise ValueError("Task and Execution must exist")
        upsert_node(self.client, "Task", task_id, {"status": "COMPLETED", "completed_at": completed_at, "completed_by": agent_id})
        upsert_node(self.client, "Execution", execution_id, {"status": "COMPLETED", "completed_at": completed_at})
        self.events.record(
            "TASK_COMPLETED", about_ids=[task_id, execution_id], actor_id=agent_id,
            summary=f"Task {task_id} completed", occurred_at=completed_at,
            event_id=stable_id("EVT-P7-", "TASK_COMPLETED", task_id, execution_id),
            properties={"phase": "7"},
        )
        return {"task_id": task_id, "execution_id": execution_id, "completed_at": completed_at}

    def get_artifact(self, entity_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        node = snapshot.node(entity_id)
        if node is None:
            return None
        incoming = [edge.as_dict() for edge in snapshot.incoming.get(entity_id, [])]
        outgoing = [edge.as_dict() for edge in snapshot.outgoing.get(entity_id, [])]
        return {"entity": node, "incoming": incoming, "outgoing": outgoing}
