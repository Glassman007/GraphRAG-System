from __future__ import annotations

import uuid

import pytest

from backend.app.graph.mutations import upsert_node, upsert_relationship, delete_relationship
from backend.app.services.learning_writeback_service import LearningWritebackService
from backend.app.services.memory_promotion_service import MemoryPromotionService
from backend.app.services.knowledge_invalidation_service import KnowledgeInvalidationService
from backend.app.services.closed_loop_learning_service import ClosedLoopLearningService
from backend.app.services.phase4_graph import GraphSnapshot
from backend.app.services.precedent_service import StructuralPrecedentService
from backend.app.services.routing_service import ResponsibilityRoutingService
from backend.app.services.phase6_utils import now_iso

pytestmark = pytest.mark.integration


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def make_agent(client, agent_id=None, agent_type="VERIFIER"):
    agent_id = agent_id or uid("AG-P7")
    upsert_node(client, "Agent", agent_id, {"name": agent_id, "agent_type": agent_type, "status": "ACTIVE", "availability": "AVAILABLE", "created_at": now_iso()})
    return agent_id


def make_task_execution(client, *, status="COMPLETED", situation_id=None):
    task_id, execution_id = uid("TASK-P7"), uid("EXEC-P7")
    upsert_node(client, "Task", task_id, {"name": "Phase 7 task", "task_type": "INVESTIGATE", "status": status, "created_at": now_iso(), "completion_condition": "test", "expected_output_type": "EVIDENCE"})
    upsert_node(client, "Execution", execution_id, {"task_id": task_id, "status": status, "created_at": now_iso(), "completed_at": now_iso() if status == "COMPLETED" else None})
    upsert_relationship(client, task_id, "HAS_EXECUTION", execution_id, {"valid_from": now_iso()})
    if situation_id:
        upsert_relationship(client, task_id, "ABOUT", situation_id, {"valid_from": now_iso()})
    return task_id, execution_id


def make_promotable_finding(client, *, subject_id="INC-001", status="VERIFIED", confidence=0.9, self_loop=False):
    verifier = make_agent(client)
    producer = make_agent(client, agent_type="INVESTIGATOR")
    task_id, execution_id = make_task_execution(client, situation_id=subject_id)
    evidence_id = uid("E-P7")
    finding_id = uid("FIND-P7")
    upsert_node(client, "Evidence", evidence_id, {"name": "independent deployment evidence", "status": "VALIDATED", "confidence": 0.95, "observed_at": now_iso(), "created_at": now_iso()})
    upsert_node(client, "Finding", finding_id, {"name": "validated finding", "statement": "Schema incompatibility caused the outage", "status": status, "confidence": confidence, "task_id": task_id, "created_at": now_iso(), "created_by": producer})
    upsert_relationship(client, finding_id, "ABOUT", subject_id, {"valid_from": now_iso()})
    upsert_relationship(client, finding_id, "DERIVED_FROM", evidence_id, {"valid_from": now_iso()})
    upsert_relationship(client, finding_id, "VALIDATED_BY", verifier, {"valid_from": now_iso()})
    upsert_relationship(client, task_id, "PRODUCED", finding_id, {"valid_from": now_iso()})
    if self_loop:
        upsert_relationship(client, finding_id, "PRODUCED", evidence_id, {"valid_from": now_iso()})
    return finding_id, evidence_id, verifier, producer, task_id, execution_id


def test_phase7_writeback_evidence_is_idempotent_and_keeps_provenance(integration_client):
    agent = make_agent(integration_client, agent_type="INVESTIGATOR")
    task, execution = make_task_execution(integration_client, situation_id="INC-001")
    service = LearningWritebackService(integration_client)
    kwargs = dict(source_ref="ci:run:991", content="Compatibility test failed for v4.1", evidence_type="CI_ARTIFACT", agent_id=agent, task_id=task, execution_id=execution, situation_id="INC-001", confidence=0.97)
    first = service.write_evidence(**kwargs)
    second = service.write_evidence(**kwargs)
    assert first["entity"]["id"] == second["entity"]["id"]
    snapshot = GraphSnapshot.load(integration_client)
    eid = first["entity"]["id"]
    assert any(e.source == agent and e.target == eid and e.type == "PRODUCED" for e in snapshot.edges)
    assert any(e.source == task and e.target == eid and e.type == "PRODUCED" for e in snapshot.edges)
    assert any(e.source == execution and e.target == eid and e.type == "PRODUCED" for e in snapshot.edges)


def test_phase7_unvalidated_finding_cannot_promote(integration_client):
    finding, *_ = make_promotable_finding(integration_client, status="OPEN")
    result = MemoryPromotionService(integration_client).promote_artifact(finding, subject_ids=["INC-001"])
    assert result["status"] == "NOT_READY"


def test_phase7_validated_finding_promotes_without_destroying_source(integration_client):
    finding, evidence, *_ = make_promotable_finding(integration_client)
    result = MemoryPromotionService(integration_client).promote_artifact(finding, subject_ids=["INC-001"])
    assert result["status"] == "PROMOTED"
    snapshot = GraphSnapshot.load(integration_client)
    claim_id = result["claim_id"]
    assert snapshot.node(finding) is not None
    assert snapshot.node(claim_id)["status"] == "VALIDATED"
    assert any(e.source == finding and e.type == "PROMOTED_TO" and e.target == claim_id for e in snapshot.edges)
    assert any(e.source == evidence and e.type == "SUPPORTS" and e.target == claim_id for e in snapshot.edges)


def test_phase7_promotion_is_idempotent(integration_client):
    finding, *_ = make_promotable_finding(integration_client)
    service = MemoryPromotionService(integration_client)
    first = service.promote_artifact(finding, subject_ids=["INC-001"])
    second = service.promote_artifact(finding, subject_ids=["INC-001"])
    assert first["claim_id"] == second["claim"]["id"]
    assert second["reused"] is True


def test_phase7_self_reinforcing_evidence_blocks_promotion(integration_client):
    finding, *_ = make_promotable_finding(integration_client, self_loop=True)
    result = MemoryPromotionService(integration_client).promote_artifact(finding, subject_ids=["INC-001"])
    assert result["status"] == "NOT_READY"
    assert "NO_INDEPENDENT_GROUNDING" in result["reasons"]


def test_phase7_evidence_invalidation_propagates_to_claim_decision_task_plan_only(integration_client):
    e, c, d, t, p, unrelated = (uid(x) for x in ("E", "C", "D", "T", "P", "C-U"))
    upsert_node(integration_client, "Evidence", e, {"status": "VALIDATED", "observed_at": now_iso(), "created_at": now_iso()})
    upsert_node(integration_client, "Claim", c, {"status": "VALIDATED", "statement": "supported claim", "created_at": now_iso()})
    upsert_node(integration_client, "Claim", unrelated, {"status": "VALIDATED", "statement": "unrelated", "created_at": now_iso()})
    upsert_node(integration_client, "Decision", d, {"status": "ACTIVE", "created_at": now_iso()})
    upsert_node(integration_client, "Task", t, {"status": "IN_PROGRESS", "created_at": now_iso(), "completion_condition": "x"})
    upsert_node(integration_client, "Plan", p, {"status": "IN_PROGRESS", "created_at": now_iso(), "goal": "x"})
    upsert_relationship(integration_client, e, "SUPPORTS", c, {"valid_from": now_iso()})
    upsert_relationship(integration_client, d, "BASED_ON", c, {"valid_from": now_iso()})
    upsert_relationship(integration_client, t, "ADDRESSES", c, {"valid_from": now_iso()})
    upsert_relationship(integration_client, p, "PLAN_HAS_TASK", t, {"valid_from": now_iso()})
    result = KnowledgeInvalidationService(integration_client).invalidate_evidence(e, reason="source retracted")
    snap = GraphSnapshot.load(integration_client)
    assert snap.node(c)["status"] == "INVALIDATED"
    assert snap.node(d)["applicability_status"] == "REQUIRES_REVIEW"
    assert snap.node(t)["input_status"] == "STALE_INPUT"
    assert snap.node(p)["planning_status"] == "REPLAN_REQUIRED"
    assert snap.node(unrelated)["status"] == "VALIDATED"
    assert any(path[:3] == [e, "SUPPORTS", c] for path in result["paths"])


def test_phase7_graph_necessity_removing_support_prevents_claim_invalidation(integration_client):
    e, c = uid("E"), uid("C")
    upsert_node(integration_client, "Evidence", e, {"status": "VALIDATED", "observed_at": now_iso()})
    upsert_node(integration_client, "Claim", c, {"status": "VALIDATED", "statement": "x", "created_at": now_iso()})
    upsert_relationship(integration_client, e, "SUPPORTS", c, {"valid_from": now_iso()})
    delete_relationship(integration_client, e, "SUPPORTS", c)
    KnowledgeInvalidationService(integration_client).invalidate_evidence(e, reason="retracted")
    assert GraphSnapshot.load(integration_client).node(c)["status"] == "VALIDATED"


def test_phase7_revalidation_restores_claim_with_new_valid_evidence(integration_client):
    e1, e2, c = uid("E1"), uid("E2"), uid("C")
    for eid in (e1, e2):
        upsert_node(integration_client, "Evidence", eid, {"status": "VALIDATED", "observed_at": now_iso()})
    upsert_node(integration_client, "Claim", c, {"status": "VALIDATED", "statement": "x", "created_at": now_iso()})
    upsert_relationship(integration_client, e1, "SUPPORTS", c, {"valid_from": now_iso()})
    KnowledgeInvalidationService(integration_client).invalidate_evidence(e1, reason="retracted")
    upsert_relationship(integration_client, e2, "SUPPORTS", c, {"valid_from": now_iso()})
    result = KnowledgeInvalidationService(integration_client).revalidate_claim(c, e2)
    assert result["status"] == "VALIDATED"
    assert GraphSnapshot.load(integration_client).node(c)["revalidated_at"]


def test_phase7_responsibility_promotion_closes_old_interval_and_changes_current_routing(integration_client):
    system, old_team, new_team = uid("SYS"), uid("TEAM-OLD"), uid("TEAM-NEW")
    verifier = make_agent(integration_client)
    finding = uid("FIND")
    upsert_node(integration_client, "System", system, {"status": "ACTIVE", "name": "owned service"})
    upsert_node(integration_client, "Team", old_team, {"status": "ACTIVE", "name": "old"})
    upsert_node(integration_client, "Team", new_team, {"status": "ACTIVE", "name": "new"})
    upsert_node(integration_client, "Finding", finding, {"status": "VERIFIED", "confidence": 0.95, "created_at": "2026-10-16T12:00:00+05:30"})
    upsert_relationship(integration_client, finding, "VALIDATED_BY", verifier, {"valid_from": "2026-10-16T12:00:00+05:30"})
    upsert_relationship(integration_client, old_team, "OWNS", system, {"valid_from": "2026-10-16T10:00:00+05:30", "confidence": 1.0})
    result = MemoryPromotionService(integration_client).promote_responsibility(actor_id=new_team, resource_id=system, verification_id=finding, effective_at="2026-10-16T13:00:00+05:30")
    assert result["status"] == "PROMOTED"
    current = ResponsibilityRoutingService(integration_client).find_owner(system, as_of="2026-10-16T14:00:00+05:30")
    historic = ResponsibilityRoutingService(integration_client).find_owner(system, as_of="2026-10-16T12:30:00+05:30")
    assert [x["actor"]["id"] for x in current["owners"]] == [new_team]
    assert [x["actor"]["id"] for x in historic["owners"]] == [old_team]


def test_phase7_unverified_responsibility_cannot_promote(integration_client):
    system, team, finding = uid("SYS"), uid("TEAM"), uid("FIND")
    upsert_node(integration_client, "System", system, {"status": "ACTIVE"})
    upsert_node(integration_client, "Team", team, {"status": "ACTIVE"})
    upsert_node(integration_client, "Finding", finding, {"status": "OPEN", "confidence": 0.9})
    result = MemoryPromotionService(integration_client).promote_responsibility(actor_id=team, resource_id=system, verification_id=finding)
    assert result["status"] == "NOT_READY"


def test_phase7_expertise_learning_records_evidence_not_canonical_expertise(integration_client):
    actor, domain, task, finding, verifier = uid("PERSON"), uid("SYS"), uid("TASK"), uid("FIND"), make_agent(integration_client)
    upsert_node(integration_client, "Person", actor, {"status": "ACTIVE"})
    upsert_node(integration_client, "System", domain, {"status": "ACTIVE"})
    upsert_node(integration_client, "Task", task, {"status": "COMPLETED", "completed_at": now_iso()})
    upsert_node(integration_client, "Finding", finding, {"status": "VERIFIED", "confidence": 0.9})
    upsert_relationship(integration_client, finding, "VALIDATED_BY", verifier, {"valid_from": now_iso()})
    result = MemoryPromotionService(integration_client).record_expertise_evidence(actor_id=actor, domain_id=domain, task_id=task, finding_id=finding, verifier_id=verifier, confidence=0.8)
    assert result["canonical_expertise_changed"] is False
    snap = GraphSnapshot.load(integration_client)
    assert not any(e.source == actor and e.type == "EXPERT_IN" and e.target == domain for e in snap.edges)


def test_phase7_completed_execution_process_promotes_verified_findings(integration_client):
    finding, _, _, _, task, execution = make_promotable_finding(integration_client)
    # make_promotable_finding created completed execution and task
    result = ClosedLoopLearningService(integration_client).process_completed_execution(execution)
    assert result["status"] == "PROCESSED"
    assert any(x.get("status") == "PROMOTED" for x in result["promoted"])


def test_phase7_precedent_promotion_becomes_visible_to_existing_precedent_reasoning(integration_client):
    historical, current = uid("INC-HIST"), uid("INC-CUR")
    for iid in (historical, current):
        upsert_node(integration_client, "Incident", iid, {"status": "CLOSED" if iid == historical else "OPEN", "severity": "SEV1", "title": "schema incompatibility"})
        sys = uid("SYS")
        change = uid("CHG")
        ev = uid("E")
        upsert_node(integration_client, "System", sys, {"status": "ACTIVE", "system_type": "database"})
        upsert_node(integration_client, "Change", change, {"status": "ACTIVE", "change_type": "migration"})
        upsert_node(integration_client, "Evidence", ev, {"status": "VALIDATED", "evidence_type": "LOG"})
        upsert_relationship(integration_client, ev, "ABOUT", iid, {"valid_from": now_iso()})
        upsert_relationship(integration_client, ev, "ABOUT", change, {"valid_from": now_iso()})
        upsert_relationship(integration_client, change, "CHANGED", sys, {"valid_from": now_iso()})
    claim, decision, task, action, outcome = uid("C"), uid("D"), uid("T"), uid("A"), uid("O")
    upsert_node(integration_client, "Claim", claim, {"status": "VALIDATED", "statement": "root", "created_at": now_iso()})
    upsert_node(integration_client, "Decision", decision, {"status": "ACTIVE"})
    upsert_node(integration_client, "Task", task, {"status": "COMPLETED"})
    upsert_node(integration_client, "Action", action, {"status": "SUCCEEDED", "action_type": "rollback"})
    upsert_node(integration_client, "Outcome", outcome, {"status": "OBSERVED", "result": "SUCCESS"})
    upsert_relationship(integration_client, historical, "ROOT_CAUSE", claim, {"valid_from": now_iso()})
    upsert_relationship(integration_client, decision, "BASED_ON", claim, {"valid_from": now_iso()})
    upsert_relationship(integration_client, task, "ABOUT", historical, {"valid_from": now_iso()})
    upsert_relationship(integration_client, task, "PROPOSED_ACTION", action, {"valid_from": now_iso()})
    upsert_relationship(integration_client, action, "HAS_OUTCOME", outcome, {"valid_from": now_iso()})
    promoted = MemoryPromotionService(integration_client).promote_incident_precedent(historical)
    assert promoted["status"] == "PROMOTED"
    precedents = StructuralPrecedentService(integration_client).find_precedents(current)
    assert any(x["incident"]["id"] == historical for x in precedents["precedents"])


def test_phase7_decision_writeback_preserves_genealogy(integration_client):
    actor = make_agent(integration_client)
    task, _ = make_task_execution(integration_client)
    claim, evidence, policy, action = uid("C"), uid("E"), uid("POL"), uid("A")
    upsert_node(integration_client, "Claim", claim, {"status":"VALIDATED","statement":"x","created_at":now_iso()})
    upsert_node(integration_client, "Evidence", evidence, {"status":"VALIDATED","observed_at":now_iso()})
    upsert_node(integration_client, "Policy", policy, {"status":"ACTIVE","valid_from":now_iso()})
    upsert_node(integration_client, "Action", action, {"status":"PROPOSED","action_type":"rollback"})
    decision = uid("DEC")
    result = LearningWritebackService(integration_client).write_decision(decision, summary="Rollback safely", actor_id=actor, task_id=task, claim_ids=[claim], evidence_ids=[evidence], policy_ids=[policy], action_ids=[action])
    assert result["entity"]["id"] == decision
    snap = GraphSnapshot.load(integration_client)
    based = {(e.type, e.target) for e in snap.edges_from(decision)}
    assert ("BASED_ON", claim) in based and ("BASED_ON", evidence) in based and ("BASED_ON", policy) in based
    assert ("PRODUCED", action) in based


def test_phase7_action_outcome_is_distinct_from_execution_success(integration_client):
    action, system = uid("A"), uid("SYS")
    upsert_node(integration_client, "Action", action, {"status":"SUCCEEDED","action_type":"rollback"})
    upsert_node(integration_client, "System", system, {"status":"ACTIVE"})
    result = LearningWritebackService(integration_client).write_outcome(action, observed_effect="error rate fell", expected_effect="error rate falls", result="SUCCESS", affected_ids=[system])
    oid = result["entity"]["id"]
    snap = GraphSnapshot.load(integration_client)
    assert snap.node(oid)["status"] == "OBSERVED"
    assert any(e.source == action and e.type == "HAS_OUTCOME" and e.target == oid for e in snap.edges)


def test_phase7_source_authority_drop_requires_revalidation(integration_client):
    source, evidence, claim = uid("SRC"), uid("E"), uid("C")
    upsert_node(integration_client, "DataSource", source, {"status":"ACTIVE","authoritative":True})
    upsert_node(integration_client, "Evidence", evidence, {"status":"VALIDATED","observed_at":now_iso()})
    upsert_node(integration_client, "Claim", claim, {"status":"VALIDATED","statement":"x","created_at":now_iso()})
    upsert_relationship(integration_client, evidence, "DERIVED_FROM", source, {"valid_from":now_iso()})
    upsert_relationship(integration_client, evidence, "SUPPORTS", claim, {"valid_from":now_iso()})
    result = KnowledgeInvalidationService(integration_client).source_authority_changed(source, authoritative=False, authority_score=0.1)
    assert any(x["entity_id"] == claim for x in result["affected"])
    assert GraphSnapshot.load(integration_client).node(claim)["status"] == "REQUIRES_REVALIDATION"


def test_phase7_claim_supersession_preserves_old_claim_and_marks_dependents(integration_client):
    old, new, decision = uid("C-OLD"), uid("C-NEW"), uid("DEC")
    upsert_node(integration_client, "Claim", old, {"status":"VALIDATED","statement":"old","created_at":now_iso()})
    upsert_node(integration_client, "Claim", new, {"status":"VALIDATED","statement":"new","created_at":now_iso()})
    upsert_node(integration_client, "Decision", decision, {"status":"ACTIVE"})
    upsert_relationship(integration_client, decision, "BASED_ON", old, {"valid_from":now_iso()})
    result = KnowledgeInvalidationService(integration_client).supersede_claim(old, new)
    snap = GraphSnapshot.load(integration_client)
    assert snap.node(old)["status"] == "SUPERSEDED"
    assert snap.node(new)["status"] == "VALIDATED"
    assert snap.node(decision)["applicability_status"] == "REQUIRES_REVIEW"
    assert any(e.source == new and e.type == "SUPERSEDES" and e.target == old for e in snap.edges)


def test_phase7_ownership_change_marks_old_candidate_work_stale(integration_client):
    system, old_team, new_team, task, plan = uid("SYS"), uid("OLD"), uid("NEW"), uid("T"), uid("P")
    verifier = make_agent(integration_client)
    finding = uid("F")
    for team in (old_team, new_team):
        upsert_node(integration_client, "Team", team, {"status":"ACTIVE"})
    upsert_node(integration_client, "System", system, {"status":"ACTIVE"})
    upsert_node(integration_client, "Finding", finding, {"status":"VERIFIED","confidence":0.9})
    upsert_node(integration_client, "Task", task, {"status":"READY","completion_condition":"x"})
    upsert_node(integration_client, "Plan", plan, {"status":"READY","goal":"x"})
    upsert_relationship(integration_client, finding, "VALIDATED_BY", verifier, {"valid_from":now_iso()})
    upsert_relationship(integration_client, old_team, "OWNS", system, {"valid_from":"2026-10-16T10:00:00+05:30"})
    upsert_relationship(integration_client, old_team, "CANDIDATE_FOR", task, {"valid_from":now_iso()})
    upsert_relationship(integration_client, plan, "PLAN_HAS_TASK", task, {"valid_from":now_iso()})
    result = MemoryPromotionService(integration_client).promote_responsibility(actor_id=new_team, resource_id=system, verification_id=finding, effective_at="2026-10-16T13:00:00+05:30")
    assert task in result["affected_tasks"] and plan in result["affected_plans"]
    snap = GraphSnapshot.load(integration_client)
    assert snap.node(task)["input_status"] == "STALE_INPUT"
    assert snap.node(plan)["planning_status"] == "REPLAN_REQUIRED"


def test_phase7_duplicate_invalidation_does_not_duplicate_equivalent_event(integration_client):
    evidence = uid("E")
    upsert_node(integration_client, "Evidence", evidence, {"status":"VALIDATED","observed_at":now_iso()})
    svc = KnowledgeInvalidationService(integration_client)
    svc.invalidate_evidence(evidence, reason="same correction")
    svc.invalidate_evidence(evidence, reason="same correction")
    snap = GraphSnapshot.load(integration_client)
    events = [n for n in snap.nodes.values() if "Event" in set(n.get("_labels") or []) and n.get("event_type") == "KNOWLEDGE_INVALIDATED"]
    related = [ev for ev in events if any(e.source == ev["id"] and e.type == "ABOUT" and e.target == evidence for e in snap.edges)]
    assert len(related) == 1


def test_phase7_dependency_change_marks_related_active_work_stale(integration_client):
    s1, s2, task, plan = uid("SYS-A"), uid("SYS-B"), uid("TASK"), uid("PLAN")
    upsert_node(integration_client, "System", s1, {"status":"ACTIVE"})
    upsert_node(integration_client, "System", s2, {"status":"ACTIVE"})
    upsert_node(integration_client, "Task", task, {"status":"READY","completion_condition":"x"})
    upsert_node(integration_client, "Plan", plan, {"status":"READY","goal":"x"})
    upsert_relationship(integration_client, task, "ABOUT", s1, {"valid_from":now_iso()})
    upsert_relationship(integration_client, plan, "PLAN_HAS_TASK", task, {"valid_from":now_iso()})
    result = KnowledgeInvalidationService(integration_client).dependency_changed(s1, s2, change_type="REMOVED")
    assert task in result["affected_tasks"] and plan in result["affected_plans"]


def test_phase7_entity_resolution_change_marks_identity_dependent_work_stale(integration_client):
    record, old, new, task = uid("SRCREC"), uid("PERSON-OLD"), uid("PERSON-NEW"), uid("TASK")
    upsert_node(integration_client, "SourceRecord", record, {"status":"ACTIVE","source_entity_id":"x"})
    upsert_node(integration_client, "Person", old, {"status":"ACTIVE"})
    upsert_node(integration_client, "Person", new, {"status":"ACTIVE"})
    upsert_node(integration_client, "Task", task, {"status":"READY","completion_condition":"x"})
    upsert_relationship(integration_client, task, "ABOUT", old, {"valid_from":now_iso()})
    result = KnowledgeInvalidationService(integration_client).entity_resolution_changed(record, old_entity_id=old, new_entity_id=new)
    assert task in result["affected_tasks"]
    assert GraphSnapshot.load(integration_client).node(task)["input_status"] == "STALE_INPUT"


def test_phase7_contradictory_outcome_requires_claim_revalidation(integration_client):
    outcome, claim, decision = uid("OUT"), uid("C"), uid("D")
    upsert_node(integration_client, "Outcome", outcome, {"status":"OBSERVED","result":"FAILURE","observed_at":now_iso()})
    upsert_node(integration_client, "Claim", claim, {"status":"VALIDATED","statement":"rollback will reduce errors","created_at":now_iso()})
    upsert_node(integration_client, "Decision", decision, {"status":"ACTIVE"})
    upsert_relationship(integration_client, outcome, "REFUTES", claim, {"valid_from":now_iso()})
    upsert_relationship(integration_client, decision, "BASED_ON", claim, {"valid_from":now_iso()})
    result = KnowledgeInvalidationService(integration_client).process_outcome_feedback(outcome)
    snap = GraphSnapshot.load(integration_client)
    assert claim in result["contradicted_claims"]
    assert snap.node(claim)["status"] == "REQUIRES_REVALIDATION"
    assert snap.node(decision)["applicability_status"] == "REQUIRES_REVIEW"
