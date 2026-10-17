from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.graph.temporal import to_epoch_us
from backend.app.services.event_ledger_service import EventLedgerService
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase6_utils import now_iso, stable_id
from backend.app.services.phase7_utils import INVALID_STATES, VALIDATED_STATES, evidence_for_artifact, status, validators_for


class MemoryPromotionService:
    MIN_CONFIDENCE = 0.65

    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self.events = EventLedgerService(client)

    @staticmethod
    def _independent_evidence(snapshot: GraphSnapshot, artifact_id: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        independent = []
        for item in evidence:
            eid = str(item.get("id"))
            # Reject self-reinforcement: artifact cannot be the producer/derivation source of its own evidence.
            self_loop = any(e.target == eid for e in snapshot.edges_from(artifact_id, {"PRODUCED"}))
            reverse_loop = any(e.target == artifact_id for e in snapshot.edges_from(eid, {"DERIVED_FROM", "SUPPORTS"}))
            if not self_loop and not reverse_loop and status(item) not in INVALID_STATES:
                independent.append(item)
        return independent

    def evaluate_artifact(self, artifact_id: str) -> dict[str, Any]:
        snapshot = GraphSnapshot.load(self.client)
        artifact = snapshot.node(artifact_id)
        if artifact is None or not (has_label(artifact, "Finding") or has_label(artifact, "Hypothesis")):
            return {"artifact_id": artifact_id, "status": "REJECTED", "reasons": ["UNSUPPORTED_ARTIFACT_TYPE"]}
        validators = validators_for(snapshot, artifact_id)
        evidence = evidence_for_artifact(snapshot, artifact_id)
        independent = self._independent_evidence(snapshot, artifact_id, evidence)
        reasons = []
        if status(artifact) not in VALIDATED_STATES:
            reasons.append("ARTIFACT_NOT_VALIDATED")
        if float(artifact.get("confidence") or 0.0) < self.MIN_CONFIDENCE:
            reasons.append("CONFIDENCE_BELOW_THRESHOLD")
        if not validators:
            reasons.append("MISSING_VALIDATOR")
        if not evidence:
            reasons.append("MISSING_EVIDENCE")
        elif not independent:
            reasons.append("NO_INDEPENDENT_GROUNDING")
        blockers = [snapshot.node(e.target) for e in snapshot.edges_from(artifact_id, {"BLOCKED_BY"}) if snapshot.node(e.target) and status(snapshot.node(e.target)) not in {"RESOLVED", "CLOSED"}]
        if blockers:
            reasons.append("UNRESOLVED_BLOCKER")
        contradictions = [e.target for e in snapshot.edges_from(artifact_id, {"CONTRADICTS"})]
        if contradictions:
            reasons.append("UNRESOLVED_CRITICAL_CONTRADICTION")
        return {
            "artifact_id": artifact_id,
            "status": "PROMOTED" if not reasons else "NOT_READY",
            "reasons": reasons,
            "validators": validators,
            "evidence": evidence,
            "independent_evidence": independent,
            "confidence": float(artifact.get("confidence") or 0.0),
        }

    def promote_artifact(self, artifact_id: str, *, subject_ids: list[str] | None = None, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        evaluation = self.evaluate_artifact(artifact_id)
        if evaluation["status"] != "PROMOTED":
            return evaluation
        snapshot = GraphSnapshot.load(self.client)
        artifact = snapshot.node(artifact_id) or {}
        existing = [snapshot.node(e.target) for e in snapshot.edges_from(artifact_id, {"PROMOTED_TO"}) if has_label(snapshot.node(e.target), "Claim")]
        if existing:
            return {**evaluation, "status": "PROMOTED", "claim": existing[0], "reused": True}
        subjects = list(subject_ids or [])
        if not subjects:
            subjects = [e.target for e in snapshot.edges_from(artifact_id, {"ABOUT"})]
        claim_id = stable_id("C-P7-PROM-", artifact_id, *sorted(subjects))
        statement = str(artifact.get("statement") or artifact.get("name") or artifact_id)
        upsert_node(self.client, "Claim", claim_id, {
            "statement": statement,
            "name": statement[:120],
            "status": "VALIDATED",
            "confidence": evaluation["confidence"],
            "created_at": timestamp,
            "valid_from": timestamp,
            "promoted_at": timestamp,
            "promotion_rule": "phase7-validated-artifact-v1",
            "phase": "7",
        })
        upsert_relationship(self.client, artifact_id, "PROMOTED_TO", claim_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_relationship(self.client, claim_id, "DERIVED_FROM", artifact_id, {"valid_from": timestamp, "confidence": 1.0})
        for sid in dict.fromkeys(subjects):
            upsert_relationship(self.client, claim_id, "ABOUT", sid, {"valid_from": timestamp, "confidence": 1.0})
        for evidence in evaluation["independent_evidence"]:
            upsert_relationship(self.client, str(evidence["id"]), "SUPPORTS", claim_id, {"valid_from": timestamp, "confidence": float(evidence.get("confidence") or 1.0)})
        for validator in evaluation["validators"]:
            upsert_relationship(self.client, claim_id, "VALIDATED_BY", str(validator["id"]), {"valid_from": timestamp, "confidence": 1.0})
        upsert_node(self.client, "Finding" if has_label(artifact, "Finding") else "Hypothesis", artifact_id, {"status": "PROMOTED", "promoted_at": timestamp})
        event_type = "HYPOTHESIS_PROMOTED" if has_label(artifact, "Hypothesis") else "CLAIM_PROMOTED"
        self.events.record(event_type, about_ids=[artifact_id, claim_id], summary=f"{artifact_id} promoted to {claim_id}", occurred_at=timestamp,
                           event_id=stable_id("EVT-P7-", event_type, artifact_id, claim_id), properties={"phase": "7", "promotion_rule": "phase7-validated-artifact-v1"})
        return {**evaluation, "status": "PROMOTED", "claim_id": claim_id, "reused": False}

    def precedent_eligibility(self, incident_id: str) -> dict[str, Any]:
        snapshot = GraphSnapshot.load(self.client)
        incident = snapshot.node(incident_id)
        if incident is None or not has_label(incident, "Incident"):
            return {"incident_id": incident_id, "status": "NOT_ELIGIBLE", "reasons": ["INCIDENT_NOT_FOUND"]}
        reasons = []
        if status(incident) not in {"CLOSED", "RESOLVED", "HISTORICAL"}:
            reasons.append("INCIDENT_NOT_CLOSED")
        root_claims = [snapshot.node(e.target) for e in snapshot.edges_from(incident_id, {"ROOT_CAUSE"}) if has_label(snapshot.node(e.target), "Claim")]
        validated_roots = [c for c in root_claims if status(c) == "VALIDATED"]
        if not validated_roots:
            reasons.append("NO_VALIDATED_ROOT_CAUSE")
        task_ids = [e.source for e in snapshot.edges_to(incident_id, {"ABOUT"}) if has_label(snapshot.node(e.source), "Task")]
        action_ids = []
        for tid in task_ids:
            action_ids += [e.target for e in snapshot.edges_from(tid, {"PROPOSED_ACTION"}) if has_label(snapshot.node(e.target), "Action")]
        outcomes = []
        for aid in action_ids:
            outcomes += [snapshot.node(e.target) for e in snapshot.edges_from(aid, {"HAS_OUTCOME", "PRODUCED"}) if has_label(snapshot.node(e.target), "Outcome")]
        if not outcomes:
            reasons.append("NO_OBSERVED_OUTCOME")
        decisions = [snapshot.node(e.source) for c in validated_roots for e in snapshot.edges_to(str(c.get("id")), {"BASED_ON"}) if has_label(snapshot.node(e.source), "Decision")]
        if not decisions:
            reasons.append("NO_DECISION_GENEALOGY")
        return {
            "incident_id": incident_id,
            "status": "PRECEDENT_ELIGIBLE" if not reasons else "NOT_ELIGIBLE",
            "reasons": reasons,
            "root_causes": validated_roots,
            "actions": [snapshot.node(x) for x in action_ids if snapshot.node(x)],
            "outcomes": outcomes,
            "decisions": decisions,
        }

    def promote_incident_precedent(self, incident_id: str, *, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        eligibility = self.precedent_eligibility(incident_id)
        if eligibility["status"] != "PRECEDENT_ELIGIBLE":
            return eligibility
        upsert_node(self.client, "Incident", incident_id, {"status": "HISTORICAL", "precedent_eligible": True, "promoted_at": timestamp})
        for root in eligibility["root_causes"]:
            upsert_relationship(self.client, incident_id, "ROOT_CAUSE", str(root["id"]), {"valid_from": timestamp, "confidence": 1.0})
        self.events.record("INCIDENT_PROMOTED_TO_PRECEDENT", about_ids=[incident_id], summary=f"Incident {incident_id} promoted to historical precedent", occurred_at=timestamp,
                           event_id=stable_id("EVT-P7-", "INCIDENT_PROMOTED_TO_PRECEDENT", incident_id), properties={"phase": "7"})
        return {**eligibility, "status": "PROMOTED", "promoted_at": timestamp}

    def promote_responsibility(self, *, actor_id: str, resource_id: str, relation_type: str = "OWNS", verification_id: str, authority_id: str | None = None, effective_at: str | None = None) -> dict[str, Any]:
        effective_at = effective_at or now_iso()
        if relation_type not in {"OWNS", "RESPONSIBLE_FOR"}:
            raise ValueError("Phase 7 responsibility promotion supports OWNS or RESPONSIBLE_FOR")
        snapshot = GraphSnapshot.load(self.client)
        actor = snapshot.node(actor_id)
        resource = snapshot.node(resource_id)
        if actor is None or not any(has_label(actor, label) for label in ("Person", "Team", "Agent")):
            return {"status": "NOT_READY", "reasons": ["ACTOR_NOT_FOUND"]}
        if resource is None:
            return {"status": "NOT_READY", "reasons": ["RESOURCE_NOT_FOUND"]}
        verification = snapshot.node(verification_id)
        if verification is None or status(verification) not in VALIDATED_STATES:
            return {"status": "NOT_READY", "reasons": ["VERIFICATION_NOT_VALIDATED"]}
        validators = validators_for(snapshot, verification_id)
        if authority_id:
            authorized = any(str(v.get("id")) == authority_id for v in validators)
            if not authorized:
                return {"status": "NOT_READY", "reasons": ["AUTHORITY_NOT_VERIFIED"]}
        elif not validators:
            return {"status": "NOT_READY", "reasons": ["MISSING_VALIDATOR"]}
        # Close all currently-active competing relationships without deleting history.
        cypher = f"""
        MATCH (old:Entity {{tenant_id:$tenant_id}})-[r:{relation_type}]->(resource:Entity {{tenant_id:$tenant_id,id:$resource_id}})
        WHERE old.id <> $actor_id AND r.valid_until IS NULL
        SET r.valid_until=$effective_at, r._ts_valid_until_us=$effective_us, r.superseded_by=$actor_id
        RETURN old.id
        """
        from backend.app.graph.temporal import to_epoch_us
        rows = self.client.query(cypher, {"tenant_id": self.client.settings.tenant_id, "resource_id": resource_id, "actor_id": actor_id, "effective_at": effective_at, "effective_us": to_epoch_us(effective_at)}).result_set
        old_actors = [str(r[0]) for r in rows]
        upsert_relationship(self.client, actor_id, relation_type, resource_id, {"valid_from": effective_at, "confidence": 1.0, "source_ref_id": verification_id, "authoritative": True})
        upsert_relationship(self.client, verification_id, "ABOUT", resource_id, {"valid_from": effective_at, "confidence": 1.0})
        affected_tasks = []
        affected_plans = []
        for old_actor in old_actors:
            for edge in snapshot.edges_from(old_actor, {"CANDIDATE_FOR"}):
                task = snapshot.node(edge.target)
                if not has_label(task, "Task") or status(task) in {"COMPLETED", "CANCELLED"}:
                    continue
                tid = str(task["id"])
                upsert_node(self.client, "Task", tid, {"input_status": "STALE_INPUT", "stale_since": effective_at, "stale_reason": f"{relation_type} changed for {resource_id}"})
                affected_tasks.append(tid)
                for p_edge in snapshot.edges_to(tid, {"PLAN_HAS_TASK"}):
                    plan = snapshot.node(p_edge.source)
                    if has_label(plan, "Plan"):
                        pid = str(plan["id"])
                        upsert_node(self.client, "Plan", pid, {"planning_status": "REPLAN_REQUIRED", "stale_since": effective_at})
                        affected_plans.append(pid)
        self.events.record("RESPONSIBILITY_PROMOTED", about_ids=[resource_id, verification_id, actor_id] + old_actors + affected_tasks + affected_plans, actor_id=authority_id,
                           summary=f"{actor_id} {relation_type} {resource_id}", occurred_at=effective_at,
                           event_id=stable_id("EVT-P7-", "RESPONSIBILITY_PROMOTED", actor_id, relation_type, resource_id, effective_at), properties={"phase": "7"})
        return {"status": "PROMOTED", "relation_type": relation_type, "actor_id": actor_id, "resource_id": resource_id, "old_actors": old_actors, "effective_at": effective_at, "affected_tasks": sorted(set(affected_tasks)), "affected_plans": sorted(set(affected_plans))}

    def record_expertise_evidence(self, *, actor_id: str, domain_id: str, task_id: str, finding_id: str, verifier_id: str, confidence: float, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        task, finding = snapshot.node(task_id), snapshot.node(finding_id)
        if not task or status(task) != "COMPLETED" or not finding or status(finding) not in VALIDATED_STATES:
            return {"status": "NOT_READY", "reasons": ["COMPLETED_TASK_AND_VALIDATED_FINDING_REQUIRED"]}
        if not any(e.target == verifier_id for e in snapshot.edges_from(finding_id, {"VALIDATED_BY"})):
            return {"status": "NOT_READY", "reasons": ["VERIFIER_NOT_LINKED"]}
        eid = stable_id("EXP-EVID-P7-", actor_id, domain_id, task_id, finding_id)
        upsert_node(self.client, "ExpertiseEvidence", eid, {"status": "VALIDATED", "confidence": confidence, "created_at": timestamp, "task_id": task_id, "finding_id": finding_id, "actor_id": actor_id, "domain_id": domain_id, "verifier_id": verifier_id})
        upsert_relationship(self.client, eid, "ABOUT", domain_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_relationship(self.client, eid, "DERIVED_FROM", task_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_relationship(self.client, eid, "DERIVED_FROM", finding_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_relationship(self.client, eid, "VALIDATED_BY", verifier_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_relationship(self.client, actor_id, "CANDIDATE_EXPERT", domain_id, {"valid_from": timestamp, "confidence": confidence, "source_ref_id": eid})
        return {"status": "RECORDED", "expertise_evidence_id": eid, "canonical_expertise_changed": False, "candidate_expert": {"actor_id": actor_id, "domain_id": domain_id, "confidence": confidence}}
