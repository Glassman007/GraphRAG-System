from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.services.coordination_service import CoordinationService
from backend.app.services.event_ledger_service import EventLedgerService
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase6_utils import now_iso, stable_id


class BranchMemoryService:
    """Isolated speculative memory with explicit validated promotion into shared state."""

    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self.coordination = CoordinationService(client)
        self.events = EventLedgerService(client)

    def create_branch(self, execution_id: str, agent_id: str, *, purpose: str, branch_kind: str = "HYPOTHESIS", timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        execution = snapshot.node(execution_id)
        if not execution or not has_label(execution, "Execution"):
            raise ValueError(f"Execution not found: {execution_id}")
        task_id = str(execution.get("task_id"))
        branch_id = stable_id("BRANCH-P6-", execution_id, agent_id, purpose, branch_kind)
        upsert_node(
            self.client,
            "WorkBranch",
            branch_id,
            {
                "name": purpose[:120],
                "purpose": purpose,
                "branch_kind": branch_kind.upper(),
                "status": "OPEN",
                "parent_execution": execution_id,
                "task_id": task_id,
                "created_by": agent_id,
                "created_at": timestamp,
            },
        )
        upsert_relationship(self.client, task_id, "HAS_BRANCH", branch_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_relationship(self.client, branch_id, "PART_OF", execution_id, {"valid_from": timestamp, "confidence": 1.0})
        self.events.record("BRANCH_CREATED", about_ids=[branch_id, execution_id, task_id], actor_id=agent_id, summary=purpose, occurred_at=timestamp)
        return self.get_branch(branch_id) or {"branch_id": branch_id}

    def get_branch(self, branch_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        branch = snapshot.node(branch_id)
        if not branch or not has_label(branch, "WorkBranch"):
            return None
        findings = [snapshot.node(edge.target) for edge in snapshot.edges_from(branch_id, {"CONTAINS"}) if has_label(snapshot.node(edge.target), "Finding")]
        parents = [snapshot.node(edge.target) for edge in snapshot.edges_from(branch_id, {"PART_OF"}) if snapshot.node(edge.target)]
        return {"branch": branch, "findings": [x for x in findings if x], "parents": [x for x in parents if x]}

    def add_branch_finding(self, branch_id: str, agent_id: str, *, statement: str, confidence: float, evidence_ids: list[str] | None = None, kind: str = "HYPOTHESIS") -> dict[str, Any]:
        detail = self.get_branch(branch_id)
        if detail is None:
            raise ValueError(f"Branch not found: {branch_id}")
        branch = detail["branch"]
        if str(branch.get("status") or "").upper() != "OPEN":
            raise ValueError("Findings can only be added to OPEN branches")
        return self.coordination.add_finding(
            str(branch.get("task_id")),
            agent_id,
            statement=statement,
            confidence=confidence,
            kind=kind,
            evidence_ids=evidence_ids,
            branch_id=branch_id,
        )

    def validate_branch(self, branch_id: str, *, min_confidence: float = 0.6, require_evidence: bool = True, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        detail = self.get_branch(branch_id)
        if detail is None:
            return {"valid": False, "errors": ["BRANCH_NOT_FOUND"], "findings": []}
        snapshot = GraphSnapshot.load(self.client)
        branch = detail["branch"]
        errors: list[str] = []
        parent_exec = [node for node in detail["parents"] if has_label(node, "Execution")]
        if not parent_exec:
            errors.append("MISSING_BRANCH_PROVENANCE")
        if not detail["findings"]:
            errors.append("NO_BRANCH_FINDINGS")
        finding_results = []
        for finding in detail["findings"]:
            fid = str(finding.get("id"))
            evidence = [snapshot.node(edge.target) for edge in snapshot.edges_from(fid, {"DERIVED_FROM"}) if has_label(snapshot.node(edge.target), "Evidence")]
            f_errors = []
            if float(finding.get("confidence") or 0.0) < min_confidence:
                f_errors.append("LOW_CONFIDENCE")
            if require_evidence and not evidence:
                f_errors.append("MISSING_EVIDENCE")
            if f_errors:
                errors.extend(f"{fid}:{code}" for code in f_errors)
            finding_results.append({"finding": finding, "evidence": [x for x in evidence if x], "errors": f_errors})
        valid = not errors
        if valid and str(branch.get("status") or "").upper() == "OPEN":
            upsert_node(self.client, "WorkBranch", branch_id, {"status": "VALIDATED", "validated_at": timestamp})
            self.events.record("BRANCH_VALIDATED", about_ids=[branch_id], actor_id=str(branch.get("created_by") or "" ) or None, summary=f"Validated {branch_id}", occurred_at=timestamp)
        return {"branch_id": branch_id, "valid": valid, "errors": errors, "findings": finding_results}

    def merge_branch(self, branch_id: str, agent_id: str, *, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        validation = self.validate_branch(branch_id, timestamp=timestamp)
        if not validation["valid"]:
            raise ValueError(f"Branch cannot merge: {', '.join(validation['errors'])}")
        detail = self.get_branch(branch_id)
        assert detail is not None
        branch = detail["branch"]
        task_id = str(branch.get("task_id"))
        promoted = []
        snapshot = GraphSnapshot.load(self.client)
        for source in detail["findings"]:
            source_id = str(source.get("id"))
            promoted_id = stable_id("FIND-P6-MERGED-", branch_id, source_id)
            upsert_node(
                self.client,
                "Finding",
                promoted_id,
                {
                    "name": str(source.get("name") or source.get("statement") or "Merged finding")[:120],
                    "statement": source.get("statement"),
                    "finding_kind": source.get("finding_kind"),
                    "status": source.get("status") or "OPEN",
                    "confidence": source.get("confidence"),
                    "scope": "SHARED",
                    "task_id": task_id,
                    "created_at": timestamp,
                    "created_by": agent_id,
                    "merged_from_branch": branch_id,
                },
            )
            upsert_relationship(self.client, agent_id, "PRODUCED", promoted_id, {"valid_from": timestamp, "confidence": 1.0})
            upsert_relationship(self.client, promoted_id, "ABOUT", task_id, {"valid_from": timestamp, "confidence": 1.0})
            upsert_relationship(self.client, promoted_id, "DERIVED_FROM", source_id, {"valid_from": timestamp, "confidence": 1.0})
            upsert_relationship(self.client, promoted_id, "DERIVED_FROM", branch_id, {"valid_from": timestamp, "confidence": 1.0})
            for edge in snapshot.edges_from(source_id, {"DERIVED_FROM"}):
                if has_label(snapshot.node(edge.target), "Evidence"):
                    upsert_relationship(self.client, promoted_id, "DERIVED_FROM", edge.target, {"valid_from": timestamp, "confidence": 1.0})
            promoted.append(promoted_id)
        upsert_node(self.client, "WorkBranch", branch_id, {"status": "MERGED", "merged_at": timestamp, "merged_by": agent_id})
        self.events.record("BRANCH_MERGED", about_ids=[branch_id, task_id, *promoted], actor_id=agent_id, summary=f"Merged {branch_id}", occurred_at=timestamp)
        return {"branch": GraphSnapshot.load(self.client).node(branch_id), "promoted_finding_ids": promoted, "validation": validation}

    def reject_branch(self, branch_id: str, agent_id: str, *, reason: str, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        detail = self.get_branch(branch_id)
        if detail is None:
            raise ValueError(f"Branch not found: {branch_id}")
        upsert_node(self.client, "WorkBranch", branch_id, {"status": "REJECTED", "closed_at": timestamp, "rejection_reason": reason, "rejected_by": agent_id})
        self.events.record("BRANCH_REJECTED", about_ids=[branch_id], actor_id=agent_id, summary=reason, occurred_at=timestamp)
        return self.get_branch(branch_id) or {}
