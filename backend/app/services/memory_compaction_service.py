from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.services.coordination_service import CoordinationService
from backend.app.services.event_ledger_service import EventLedgerService
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase6_utils import csv, csv_list, now_iso, stable_id


class MemoryCompactionService:
    """Archives low-value checkpoint trace while preserving graph lineage and durable outcomes."""

    RETAIN_LABELS = {"Finding", "Evidence", "Decision", "Handoff", "WorkBranch", "Action", "ActionAttempt", "Blocker"}

    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self.coordination = CoordinationService(client)
        self.events = EventLedgerService(client)

    def _execution_context(self, snapshot: GraphSnapshot, execution_id: str) -> dict[str, Any] | None:
        execution = snapshot.node(execution_id)
        if not execution or not has_label(execution, "Execution"):
            return None
        task_id = str(execution.get("task_id") or "")
        task = snapshot.node(task_id)
        checkpoints = [snapshot.node(edge.target) for edge in snapshot.edges_from(execution_id, {"HAS_CHECKPOINT"}) if has_label(snapshot.node(edge.target), "Checkpoint")]
        related: dict[str, dict[str, Any]] = {}
        for node_id, node in snapshot.nodes.items():
            labels = set(node.get("_labels") or [])
            if not labels & self.RETAIN_LABELS:
                continue
            connected = False
            if has_label(node, "Finding") or has_label(node, "Evidence"):
                connected = any(edge.target == task_id for edge in snapshot.edges_from(node_id, {"ABOUT"}))
            elif has_label(node, "Handoff"):
                connected = any(edge.target == task_id for edge in snapshot.edges_from(node_id, {"HANDOFF_FOR"}))
            elif has_label(node, "WorkBranch"):
                connected = str(node.get("task_id") or "") == task_id or any(edge.target == execution_id for edge in snapshot.edges_from(node_id, {"PART_OF"}))
            elif has_label(node, "Blocker"):
                connected = str(node.get("task_id") or "") == task_id
            elif has_label(node, "Action"):
                connected = any(edge.source == task_id for edge in snapshot.edges_to(node_id, {"PROPOSED_ACTION"}))
            elif has_label(node, "ActionAttempt"):
                connected = str(node.get("task_id") or "") == task_id
            elif has_label(node, "Decision"):
                connected = any(edge.target == node_id for edge in snapshot.edges_from(task_id, {"ADDRESSES", "ABOUT"}))
            if connected:
                related[node_id] = node
        return {"execution": execution, "task": task, "task_id": task_id, "checkpoints": [x for x in checkpoints if x], "retained": related}

    def compact_execution(self, execution_id: str, *, keep_latest: int = 1, actor_id: str | None = None, timestamp: str | None = None) -> dict[str, Any]:
        if keep_latest < 1:
            raise ValueError("keep_latest must be >= 1")
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        context = self._execution_context(snapshot, execution_id)
        if context is None:
            raise ValueError(f"Execution not found: {execution_id}")
        checkpoints = sorted(context["checkpoints"], key=lambda n: (int(n.get("step_index") or 0), str(n.get("created_at") or "")))
        active = [cp for cp in checkpoints if str(cp.get("status") or "ACTIVE").upper() != "ARCHIVED"]
        retained_checkpoints = active[-keep_latest:]
        archived_checkpoints = active[:-keep_latest]
        retained_ids = sorted([str(node.get("id")) for node in context["retained"].values()] + [str(cp.get("id")) for cp in retained_checkpoints])
        archived_ids = [str(cp.get("id")) for cp in archived_checkpoints]
        compaction_id = stable_id("COMPACT-P6-", execution_id, ",".join(archived_ids), str(keep_latest))
        manifest_parts = [
            f"task:{context['task_id']}",
            *[f"retained:{node_id}" for node_id in retained_ids],
            *[f"archived:{node_id}" for node_id in archived_ids],
        ]
        upsert_node(
            self.client,
            "CompactionRecord",
            compaction_id,
            {
                "name": f"Compaction for {execution_id}",
                "execution_id": execution_id,
                "task_id": context["task_id"],
                "summary": f"Archived {len(archived_ids)} old checkpoints; retained durable findings/evidence/outcomes and {len(retained_checkpoints)} latest checkpoints.",
                "retained_entities": csv(retained_ids),
                "archived_entities": csv(archived_ids),
                "dependency_manifest": "|".join(manifest_parts),
                "created_at": timestamp,
                "status": "COMPLETED",
            },
        )
        upsert_relationship(self.client, execution_id, "HAS_COMPACTION", compaction_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_relationship(self.client, compaction_id, "ABOUT", execution_id, {"valid_from": timestamp, "confidence": 1.0})
        for cp in archived_checkpoints:
            cp_id = str(cp.get("id"))
            upsert_node(self.client, "Checkpoint", cp_id, {"status": "ARCHIVED", "archived_at": timestamp, "compaction_id": compaction_id})
            upsert_relationship(self.client, compaction_id, "DERIVED_FROM", cp_id, {"valid_from": timestamp, "confidence": 1.0})
        for node_id in retained_ids:
            if snapshot.node(node_id):
                upsert_relationship(self.client, compaction_id, "DERIVED_FROM", node_id, {"valid_from": timestamp, "confidence": 1.0})
        self.events.record("MEMORY_COMPACTED", about_ids=[execution_id, context["task_id"], compaction_id], actor_id=actor_id, summary=f"Archived {len(archived_ids)} checkpoints", occurred_at=timestamp)
        validation = self.validate_compaction(compaction_id)
        return {"compaction": GraphSnapshot.load(self.client).node(compaction_id), "archived_checkpoint_ids": archived_ids, "retained_checkpoint_ids": [str(cp.get("id")) for cp in retained_checkpoints], "validation": validation}

    def validate_compaction(self, compaction_id: str) -> dict[str, Any]:
        snapshot = GraphSnapshot.load(self.client)
        record = snapshot.node(compaction_id)
        if not record or not has_label(record, "CompactionRecord"):
            return {"valid": False, "errors": ["COMPACTION_NOT_FOUND"]}
        execution_id = str(record.get("execution_id") or "")
        context = self._execution_context(snapshot, execution_id)
        errors: list[str] = []
        if context is None:
            errors.append("EXECUTION_NOT_REACHABLE")
            return {"valid": False, "errors": errors}
        task_id = context["task_id"]
        if not any(edge.target == execution_id for edge in snapshot.edges_from(task_id, {"HAS_EXECUTION"})):
            errors.append("TASK_EXECUTION_LINEAGE_BROKEN")
        # Validate the persisted compaction manifest, not merely artifacts that are still
        # discoverable through their current lineage.  Otherwise deleting Evidence-[:ABOUT]->Task
        # also removes that Evidence from _execution_context(), causing a broken lineage to
        # disappear from validation instead of failing it.  Older/unit-created records without
        # retained_entities fall back to the reconstructed context for compatibility.
        retained_ids = csv_list(record.get("retained_entities"))
        if not retained_ids:
            retained_ids = sorted(context["retained"].keys())

        for node_id in retained_ids:
            node = snapshot.node(node_id)
            if not node:
                errors.append(f"RETAINED_ENTITY_MISSING:{node_id}")
                continue
            if has_label(node, "Finding") or has_label(node, "Evidence"):
                if not any(edge.target == task_id for edge in snapshot.edges_from(node_id, {"ABOUT"})):
                    errors.append(f"ARTIFACT_TASK_LINEAGE_BROKEN:{node_id}")
            if has_label(node, "WorkBranch"):
                if not any(edge.target == execution_id for edge in snapshot.edges_from(node_id, {"PART_OF"})):
                    errors.append(f"BRANCH_EXECUTION_LINEAGE_BROKEN:{node_id}")
            if has_label(node, "ActionAttempt"):
                action_id = str(node.get("action_id") or "")
                if action_id and not any(edge.target == node_id for edge in snapshot.edges_from(action_id, {"HAS_ATTEMPT"})):
                    errors.append(f"ACTION_ATTEMPT_LINEAGE_BROKEN:{node_id}")
        return {
            "valid": not errors,
            "errors": errors,
            "execution_id": execution_id,
            "task_id": task_id,
            "invariants": {
                "decision_explainability_preserved": not any("Decision" in code for code in errors),
                "evidence_lineage_preserved": not any("ARTIFACT_TASK_LINEAGE" in code for code in errors),
                "branch_history_preserved": not any("BRANCH_EXECUTION" in code for code in errors),
                "action_outcome_preserved": not any("ACTION_ATTEMPT" in code for code in errors),
            },
        }
