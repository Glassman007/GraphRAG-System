from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node
from backend.app.services.event_ledger_service import EventLedgerService
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase6_utils import now_iso, stable_id
from backend.app.services.phase7_utils import INVALID_STATES, active_evidence, status


class KnowledgeInvalidationService:
    """Bounded, explainable invalidation/revalidation over defined dependency semantics only."""

    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self.events = EventLedgerService(client)

    @staticmethod
    def impact_from_snapshot(snapshot: GraphSnapshot, entity_id: str, *, max_depth: int = 4) -> dict[str, Any]:
        if entity_id not in snapshot.nodes:
            return {"trigger": entity_id, "affected": [], "paths": [], "actions": []}
        # Only semantically load-bearing edges propagate staleness.
        allowed = {
            ("Evidence", "SUPPORTS", "Claim"),
            ("Claim", "BASED_ON", "Decision"),  # reverse direction handled below
            ("Decision", "ADDRESSES", "Task"),
            ("Claim", "ADDRESSES", "Task"),
            ("Question", "ADDRESSES", "Task"),
            ("Task", "PLAN_HAS_TASK", "Plan"),  # reverse direction handled below
            ("Policy", "GOVERNS", "Action"),
        }
        queue = [(entity_id, [entity_id], 0)]
        seen = {entity_id}
        affected: list[dict[str, Any]] = []
        paths: list[list[str]] = []
        while queue:
            current, path, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            current_node = snapshot.node(current)
            current_labels = set((current_node or {}).get("_labels") or [])
            candidates = []
            # canonical directions
            candidates += [(e.target, e.type, "out") for e in snapshot.edges_from(current, {"SUPPORTS", "GOVERNS", "CANDIDATE_FOR"})]
            # dependents point to inputs for BASED_ON/ADDRESSES and plan points to task
            candidates += [(e.source, e.type, "in") for e in snapshot.edges_to(current, {"BASED_ON", "ADDRESSES", "PLAN_HAS_TASK"})]
            for nxt, rel, direction in candidates:
                if nxt in seen:
                    continue
                next_node = snapshot.node(nxt)
                if not next_node:
                    continue
                next_labels = set(next_node.get("_labels") or [])
                valid = False
                if rel == "SUPPORTS" and "Evidence" in current_labels and "Claim" in next_labels:
                    valid = True
                elif rel == "BASED_ON" and "Claim" in current_labels and "Decision" in next_labels:
                    valid = True
                elif rel == "ADDRESSES" and ("Claim" in current_labels or "Decision" in current_labels or "Question" in current_labels) and "Task" in next_labels:
                    valid = True
                elif rel == "PLAN_HAS_TASK" and "Task" in current_labels and "Plan" in next_labels:
                    valid = True
                elif rel == "GOVERNS" and "Policy" in current_labels and "Action" in next_labels:
                    valid = True
                elif rel == "CANDIDATE_FOR" and ("Person" in current_labels or "Team" in current_labels or "Agent" in current_labels) and "Task" in next_labels:
                    valid = True
                if not valid:
                    continue
                seen.add(nxt)
                new_path = path + [rel, nxt]
                affected.append({"entity": next_node, "via": rel, "depth": depth + 1})
                paths.append(new_path)
                queue.append((nxt, new_path, depth + 1))
        actions = []
        for item in affected:
            labels = set(item["entity"].get("_labels") or [])
            if "Claim" in labels:
                action = "REVALIDATE_CLAIM"
            elif "Decision" in labels:
                action = "REVIEW_DECISION"
            elif "Task" in labels:
                action = "REPLAN_TASK"
            elif "Plan" in labels:
                action = "RECOMPUTE_PLAN"
            elif "Action" in labels:
                action = "RECHECK_GOVERNANCE"
            else:
                action = "REVIEW"
            actions.append({"entity_id": item["entity"].get("id"), "action": action})
        return {"trigger": entity_id, "affected": affected, "paths": paths, "actions": actions}

    def get_impact(self, entity_id: str) -> dict[str, Any]:
        return self.impact_from_snapshot(GraphSnapshot.load(self.client), entity_id)

    def invalidate_evidence(self, evidence_id: str, *, reason: str, actor_id: str | None = None, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        evidence = snapshot.node(evidence_id)
        if evidence is None or not has_label(evidence, "Evidence"):
            raise ValueError(f"Evidence not found: {evidence_id}")
        if status(evidence) == "INVALIDATED" and evidence.get("invalidation_reason") == reason:
            return {"trigger": evidence_id, "already_invalidated": True, **self.get_impact(evidence_id)}
        upsert_node(self.client, "Evidence", evidence_id, {"status": "INVALIDATED", "invalidated_at": timestamp, "invalidation_reason": reason})
        impacted_claim_ids = [e.target for e in snapshot.edges_from(evidence_id, {"SUPPORTS"}) if has_label(snapshot.node(e.target), "Claim")]
        status_changes: list[dict[str, Any]] = []
        paths: list[list[str]] = []
        for claim_id in impacted_claim_ids:
            # Re-load semantics logically excluding the just-invalidated evidence.
            remaining = [x for x in active_evidence(snapshot, claim_id) if str(x.get("id")) != evidence_id and status(x) not in INVALID_STATES]
            new_status = "REQUIRES_REVALIDATION" if remaining else "INVALIDATED"
            upsert_node(self.client, "Claim", claim_id, {"status": new_status, "invalidated_at": timestamp if new_status == "INVALIDATED" else None, "stale_since": timestamp})
            status_changes.append({"entity_id": claim_id, "status": new_status, "reason": f"supporting evidence {evidence_id} invalidated"})
            paths.append([evidence_id, "SUPPORTS", claim_id])
            for edge in snapshot.edges_to(claim_id, {"BASED_ON"}):
                decision = snapshot.node(edge.source)
                if not has_label(decision, "Decision"):
                    continue
                did = str(decision["id"])
                upsert_node(self.client, "Decision", did, {"applicability_status": "REQUIRES_REVIEW", "stale_since": timestamp})
                status_changes.append({"entity_id": did, "status": "REQUIRES_REVIEW", "reason": f"based on {claim_id}"})
                paths.append([evidence_id, "SUPPORTS", claim_id, "BASED_ON", did])
                self._mark_dependent_tasks(snapshot, did, timestamp, status_changes, paths, prefix=[evidence_id, "SUPPORTS", claim_id, "BASED_ON", did])
            self._mark_dependent_tasks(snapshot, claim_id, timestamp, status_changes, paths, prefix=[evidence_id, "SUPPORTS", claim_id])
        self.events.record("KNOWLEDGE_INVALIDATED", about_ids=[evidence_id] + [x["entity_id"] for x in status_changes], actor_id=actor_id,
                           summary=f"Evidence {evidence_id} invalidated: {reason}", occurred_at=timestamp,
                           event_id=stable_id("EVT-P7-", "KNOWLEDGE_INVALIDATED", evidence_id, reason), properties={"phase": "7", "reason": reason})
        return {"trigger": evidence_id, "trigger_change": "EVIDENCE_INVALIDATED", "affected": status_changes, "paths": paths, "actions": self.get_impact(evidence_id).get("actions", [])}

    def _mark_dependent_tasks(self, snapshot: GraphSnapshot, source_id: str, timestamp: str, changes: list[dict[str, Any]], paths: list[list[str]], *, prefix: list[str]) -> None:
        for edge in snapshot.edges_to(source_id, {"ADDRESSES", "DERIVED_FROM"}):
            task = snapshot.node(edge.source)
            if not has_label(task, "Task"):
                continue
            tid = str(task["id"])
            if status(task) in {"COMPLETED", "CANCELLED"}:
                continue
            upsert_node(self.client, "Task", tid, {"input_status": "STALE_INPUT", "stale_since": timestamp})
            changes.append({"entity_id": tid, "status": "STALE_INPUT", "reason": f"depends on {source_id}"})
            paths.append(prefix + [edge.type, tid])
            for p_edge in snapshot.edges_to(tid, {"PLAN_HAS_TASK"}):
                plan = snapshot.node(p_edge.source)
                if not has_label(plan, "Plan"):
                    continue
                pid = str(plan["id"])
                upsert_node(self.client, "Plan", pid, {"planning_status": "REPLAN_REQUIRED", "stale_since": timestamp})
                changes.append({"entity_id": pid, "status": "REPLAN_REQUIRED", "reason": f"contains stale task {tid}"})
                paths.append(prefix + [edge.type, tid, "PLAN_HAS_TASK", pid])


    def supersede_claim(self, old_claim_id: str, new_claim_id: str, *, timestamp: str | None = None, actor_id: str | None = None) -> dict[str, Any]:
        from backend.app.graph.mutations import upsert_relationship
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        old_claim, new_claim = snapshot.node(old_claim_id), snapshot.node(new_claim_id)
        if not has_label(old_claim, "Claim") or not has_label(new_claim, "Claim"):
            raise ValueError("Both claims must exist")
        upsert_node(self.client, "Claim", old_claim_id, {"status": "SUPERSEDED", "valid_until": timestamp, "invalidated_at": timestamp})
        upsert_relationship(self.client, new_claim_id, "SUPERSEDES", old_claim_id, {"valid_from": timestamp, "confidence": 1.0})
        impact = self.get_impact(old_claim_id)
        affected = []
        for item in impact.get("affected", []):
            node = item["entity"]
            if has_label(node, "Decision"):
                upsert_node(self.client, "Decision", str(node["id"]), {"applicability_status": "REQUIRES_REVIEW", "stale_since": timestamp})
                affected.append({"entity_id": node["id"], "status": "REQUIRES_REVIEW"})
            elif has_label(node, "Task") and status(node) not in {"COMPLETED", "CANCELLED"}:
                upsert_node(self.client, "Task", str(node["id"]), {"input_status": "STALE_INPUT", "stale_since": timestamp})
                affected.append({"entity_id": node["id"], "status": "STALE_INPUT"})
            elif has_label(node, "Plan"):
                upsert_node(self.client, "Plan", str(node["id"]), {"planning_status": "REPLAN_REQUIRED", "stale_since": timestamp})
                affected.append({"entity_id": node["id"], "status": "REPLAN_REQUIRED"})
        self.events.record("KNOWLEDGE_SUPERSEDED", about_ids=[old_claim_id, new_claim_id] + [a["entity_id"] for a in affected], actor_id=actor_id,
                           summary=f"{old_claim_id} superseded by {new_claim_id}", occurred_at=timestamp,
                           event_id=stable_id("EVT-P7-", "KNOWLEDGE_SUPERSEDED", old_claim_id, new_claim_id, timestamp), properties={"phase": "7"})
        return {"trigger": old_claim_id, "replacement": new_claim_id, "affected": affected, "paths": impact.get("paths", [])}

    def source_authority_changed(self, source_id: str, *, authoritative: bool, authority_score: float | None = None, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        source = snapshot.node(source_id)
        if source is None or not (has_label(source, "DataSource") or has_label(source, "Document") or has_label(source, "SourceRecord")):
            raise ValueError(f"Source not found: {source_id}")
        label = next(label for label in ("DataSource", "Document", "SourceRecord") if has_label(source, label))
        props = {"authoritative": authoritative, "authority_changed_at": timestamp}
        if authority_score is not None:
            props["authority_score"] = authority_score
        upsert_node(self.client, label, source_id, props)
        affected = []
        if not authoritative:
            for edge in snapshot.edges_to(source_id, {"DERIVED_FROM"}):
                evidence = snapshot.node(edge.source)
                if not has_label(evidence, "Evidence"):
                    continue
                for c_edge in snapshot.edges_from(str(evidence["id"]), {"SUPPORTS"}):
                    claim = snapshot.node(c_edge.target)
                    if has_label(claim, "Claim") and status(claim) not in {"INVALIDATED", "SUPERSEDED"}:
                        upsert_node(self.client, "Claim", str(claim["id"]), {"status": "REQUIRES_REVALIDATION", "stale_since": timestamp})
                        affected.append({"entity_id": claim["id"], "status": "REQUIRES_REVALIDATION", "via_evidence": evidence["id"]})
        return {"source_id": source_id, "authoritative": authoritative, "affected": affected, "timestamp": timestamp}

    def _mark_tasks_about_entities(self, snapshot: GraphSnapshot, entity_ids: list[str], timestamp: str, reason: str) -> dict[str, list[str]]:
        tasks: set[str] = set()
        plans: set[str] = set()
        for entity_id in entity_ids:
            for edge in snapshot.edges_to(entity_id, {"ABOUT", "ADDRESSES"}):
                task = snapshot.node(edge.source)
                if not has_label(task, "Task") or status(task) in {"COMPLETED", "CANCELLED"}:
                    continue
                tid = str(task["id"])
                upsert_node(self.client, "Task", tid, {"input_status": "STALE_INPUT", "stale_since": timestamp, "stale_reason": reason})
                tasks.add(tid)
                for p_edge in snapshot.edges_to(tid, {"PLAN_HAS_TASK"}):
                    plan = snapshot.node(p_edge.source)
                    if has_label(plan, "Plan"):
                        pid = str(plan["id"])
                        upsert_node(self.client, "Plan", pid, {"planning_status": "REPLAN_REQUIRED", "stale_since": timestamp})
                        plans.add(pid)
        return {"tasks": sorted(tasks), "plans": sorted(plans)}

    def dependency_changed(self, source_id: str, target_id: str, *, change_type: str, actor_id: str | None = None, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        if not has_label(snapshot.node(source_id), "System") or not has_label(snapshot.node(target_id), "System"):
            raise ValueError("Dependency change requires two System entities")
        affected = self._mark_tasks_about_entities(snapshot, [source_id, target_id], timestamp, f"dependency {change_type}: {source_id}->{target_id}")
        self.events.record("KNOWLEDGE_STALE", about_ids=[source_id, target_id] + affected["tasks"] + affected["plans"], actor_id=actor_id,
                           summary=f"Dependency {change_type}: {source_id}->{target_id}", occurred_at=timestamp,
                           event_id=stable_id("EVT-P7-", "DEPENDENCY_CHANGED", source_id, target_id, change_type, timestamp), properties={"phase":"7","change_type":change_type})
        return {"trigger": [source_id, target_id], "change_type": change_type, "affected_tasks": affected["tasks"], "affected_plans": affected["plans"]}

    def entity_resolution_changed(self, source_record_id: str, *, old_entity_id: str | None, new_entity_id: str, actor_id: str | None = None, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        if not has_label(snapshot.node(source_record_id), "SourceRecord") or snapshot.node(new_entity_id) is None:
            raise ValueError("Entity-resolution change requires a SourceRecord and canonical target")
        affected = self._mark_tasks_about_entities(snapshot, [x for x in [old_entity_id, new_entity_id] if x], timestamp, f"entity resolution changed for {source_record_id}")
        self.events.record("KNOWLEDGE_STALE", about_ids=[source_record_id, new_entity_id] + ([old_entity_id] if old_entity_id else []) + affected["tasks"] + affected["plans"], actor_id=actor_id,
                           summary=f"Entity resolution changed for {source_record_id}", occurred_at=timestamp,
                           event_id=stable_id("EVT-P7-", "ENTITY_RESOLUTION_CHANGED", source_record_id, old_entity_id or "", new_entity_id, timestamp), properties={"phase":"7"})
        return {"source_record_id": source_record_id, "old_entity_id": old_entity_id, "new_entity_id": new_entity_id, "affected_tasks": affected["tasks"], "affected_plans": affected["plans"]}

    def process_outcome_feedback(self, outcome_id: str, *, actor_id: str | None = None, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        outcome = snapshot.node(outcome_id)
        if not has_label(outcome, "Outcome"):
            raise ValueError(f"Outcome not found: {outcome_id}")
        contradicted = [e.target for e in snapshot.edges_from(outcome_id, {"REFUTES"}) if has_label(snapshot.node(e.target), "Claim")]
        affected = []
        for claim_id in contradicted:
            upsert_node(self.client, "Claim", claim_id, {"status": "REQUIRES_REVALIDATION", "stale_since": timestamp})
            affected.append({"entity_id": claim_id, "status": "REQUIRES_REVALIDATION"})
            impact = self.get_impact(claim_id)
            for item in impact.get("affected", []):
                node = item["entity"]
                if has_label(node, "Decision"):
                    upsert_node(self.client, "Decision", str(node["id"]), {"applicability_status":"REQUIRES_REVIEW","stale_since":timestamp})
                    affected.append({"entity_id":node["id"],"status":"REQUIRES_REVIEW"})
                elif has_label(node, "Task") and status(node) not in {"COMPLETED","CANCELLED"}:
                    upsert_node(self.client, "Task", str(node["id"]), {"input_status":"STALE_INPUT","stale_since":timestamp})
                    affected.append({"entity_id":node["id"],"status":"STALE_INPUT"})
        if contradicted:
            self.events.record("REVALIDATION_REQUIRED", about_ids=[outcome_id] + contradicted, actor_id=actor_id,
                               summary=f"Observed outcome {outcome_id} contradicts assumptions", occurred_at=timestamp,
                               event_id=stable_id("EVT-P7-","OUTCOME_CONTRADICTION",outcome_id,timestamp), properties={"phase":"7"})
        return {"outcome_id":outcome_id,"contradicted_claims":contradicted,"affected":affected}

    def invalidate_policy(self, policy_id: str, *, replacement_policy_id: str | None = None, reason: str = "Policy superseded", timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        policy = snapshot.node(policy_id)
        if policy is None or not has_label(policy, "Policy"):
            raise ValueError(f"Policy not found: {policy_id}")
        upsert_node(self.client, "Policy", policy_id, {"status": "SUPERSEDED", "valid_until": timestamp, "invalidated_at": timestamp})
        affected = []
        paths = []
        for edge in snapshot.edges_from(policy_id, {"GOVERNS"}):
            target = snapshot.node(edge.target)
            if has_label(target, "Action"):
                upsert_node(self.client, "Action", str(target["id"]), {"governance_status": "REQUIRES_REVIEW", "stale_since": timestamp})
                affected.append({"entity_id": target["id"], "status": "REQUIRES_REVIEW"})
                paths.append([policy_id, "GOVERNS", target["id"]])
        for edge in snapshot.edges_to(policy_id, {"BASED_ON"}):
            decision = snapshot.node(edge.source)
            if has_label(decision, "Decision"):
                upsert_node(self.client, "Decision", str(decision["id"]), {"applicability_status": "REQUIRES_REVIEW", "stale_since": timestamp})
                affected.append({"entity_id": decision["id"], "status": "REQUIRES_REVIEW"})
                paths.append([policy_id, "BASED_ON", decision["id"]])
        return {"trigger": policy_id, "replacement_policy_id": replacement_policy_id, "affected": affected, "paths": paths, "reason": reason}

    def revalidate_claim(self, claim_id: str, evidence_id: str, *, validator_id: str | None = None, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        claim, evidence = snapshot.node(claim_id), snapshot.node(evidence_id)
        if claim is None or not has_label(claim, "Claim"):
            raise ValueError(f"Claim not found: {claim_id}")
        if evidence is None or not has_label(evidence, "Evidence") or status(evidence) in INVALID_STATES:
            return {"status": "NOT_READY", "reasons": ["VALID_EVIDENCE_REQUIRED"]}
        if not any(e.source == evidence_id for e in snapshot.edges_to(claim_id, {"SUPPORTS"})):
            return {"status": "NOT_READY", "reasons": ["EVIDENCE_DOES_NOT_SUPPORT_CLAIM"]}
        upsert_node(self.client, "Claim", claim_id, {"status": "VALIDATED", "revalidated_at": timestamp, "invalidated_at": None, "stale_since": None})
        self.events.record("KNOWLEDGE_REVALIDATED", about_ids=[claim_id, evidence_id], actor_id=validator_id,
                           summary=f"Claim {claim_id} revalidated with {evidence_id}", occurred_at=timestamp,
                           event_id=stable_id("EVT-P7-", "KNOWLEDGE_REVALIDATED", claim_id, evidence_id, timestamp), properties={"phase": "7"})
        return {"status": "VALIDATED", "claim_id": claim_id, "evidence_id": evidence_id, "revalidated_at": timestamp}

    def list_stale(self) -> dict[str, Any]:
        snapshot = GraphSnapshot.load(self.client)
        stale = []
        for node in snapshot.nodes.values():
            if status(node) in {"STALE", "INVALIDATED", "REQUIRES_REVALIDATION", "SUPERSEDED"} or str(node.get("input_status") or "") == "STALE_INPUT" or str(node.get("planning_status") or "") == "REPLAN_REQUIRED" or str(node.get("applicability_status") or "") == "REQUIRES_REVIEW":
                stale.append(node)
        return {"stale": sorted(stale, key=lambda n: str(n.get("id")))}
