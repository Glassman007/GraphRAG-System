from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.knowledge_invalidation_service import KnowledgeInvalidationService
from backend.app.services.learning_writeback_service import LearningWritebackService
from backend.app.services.memory_promotion_service import MemoryPromotionService
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase7_utils import status


class ClosedLoopLearningService:
    """Orchestrates Phase 7 without collapsing writeback/promotion/invalidation into one policy blob."""

    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self.writeback = LearningWritebackService(client)
        self.promotion = MemoryPromotionService(client)
        self.invalidation = KnowledgeInvalidationService(client)

    def process_completed_execution(self, execution_id: str) -> dict[str, Any]:
        snapshot = GraphSnapshot.load(self.client)
        execution = snapshot.node(execution_id)
        if execution is None or not has_label(execution, "Execution"):
            raise ValueError(f"Execution not found: {execution_id}")
        if status(execution) != "COMPLETED":
            return {"execution_id": execution_id, "status": "NOT_READY", "reasons": ["EXECUTION_NOT_COMPLETED"]}
        task_id = str(execution.get("task_id") or "")
        task = snapshot.node(task_id)
        situation_ids = [e.target for e in snapshot.edges_from(task_id, {"ABOUT"}) if has_label(snapshot.node(e.target), "Incident")]
        findings = [snapshot.node(e.target) for e in snapshot.edges_from(task_id, {"PRODUCED"}) if has_label(snapshot.node(e.target), "Finding")]
        evidence = [snapshot.node(e.target) for e in snapshot.edges_from(task_id, {"PRODUCED"}) if has_label(snapshot.node(e.target), "Evidence")]
        actions = [snapshot.node(e.target) for e in snapshot.edges_from(task_id, {"PROPOSED_ACTION"}) if has_label(snapshot.node(e.target), "Action")]
        promoted = []
        not_promoted = []
        for finding in [x for x in findings if x]:
            result = self.promotion.promote_artifact(str(finding["id"]), subject_ids=situation_ids)
            (promoted if result.get("status") == "PROMOTED" else not_promoted).append(result)
        outcomes = []
        for action in [x for x in actions if x]:
            aid = str(action["id"])
            existing = [snapshot.node(e.target) for e in snapshot.edges_from(aid, {"HAS_OUTCOME"}) if has_label(snapshot.node(e.target), "Outcome")]
            outcomes.extend([x for x in existing if x])
        return {
            "execution_id": execution_id,
            "situation_id": situation_ids[0] if situation_ids else None,
            "status": "PROCESSED",
            "written_back": {"evidence": [x for x in evidence if x], "claims": [], "decisions": [], "actions": [x for x in actions if x], "outcomes": outcomes},
            "promoted": promoted,
            "not_promoted": not_promoted,
            "invalidated": [],
            "requires_revalidation": [],
            "affected_tasks": [],
            "affected_plans": [],
            "events_created": [],
            "task": task,
        }

    def close_situation(self, situation_id: str) -> dict[str, Any]:
        result = self.promotion.promote_incident_precedent(situation_id)
        return {"situation_id": situation_id, "precedent": result}

    def report(self, situation_id: str) -> dict[str, Any]:
        snapshot = GraphSnapshot.load(self.client)
        incident = snapshot.node(situation_id)
        if incident is None:
            raise ValueError(f"Situation not found: {situation_id}")
        tasks = [snapshot.node(e.source) for e in snapshot.edges_to(situation_id, {"ABOUT"}) if has_label(snapshot.node(e.source), "Task")]
        artifacts = []
        for task in [x for x in tasks if x]:
            tid = str(task["id"])
            for e in snapshot.edges_from(tid, {"PRODUCED", "PROPOSED_ACTION"}):
                node = snapshot.node(e.target)
                if node:
                    artifacts.append(node)
        return {"situation": incident, "tasks": [x for x in tasks if x], "artifacts": artifacts, "precedent": self.promotion.precedent_eligibility(situation_id)}
