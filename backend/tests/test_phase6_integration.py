from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import uuid

import pytest

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import delete_relationship, upsert_node, upsert_relationship
from backend.app.services.action_coordination_service import ActionCoordinationService, MockActionExecutor
from backend.app.services.agent_registry_service import AgentRegistryService
from backend.app.services.branch_service import BranchMemoryService
from backend.app.services.coordination_risk_service import CoordinationRiskService
from backend.app.services.coordination_service import CoordinationService
from backend.app.services.governance_service import GovernanceService
from backend.app.services.handoff_service import HandoffService
from backend.app.services.memory_compaction_service import MemoryCompactionService
from backend.app.services.phase4_graph import GraphSnapshot
from backend.app.services.phase6_utils import add_seconds, now_iso


pytestmark = pytest.mark.integration

INVESTIGATOR = "AGENT-P6-INVESTIGATOR"
VERIFIER = "AGENT-P6-VERIFIER"
DEPENDENCY = "AGENT-P6-DEPENDENCY"
REMEDIATION = "AGENT-P6-REMEDIATION"


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _ensure_agents(client):
    return AgentRegistryService(client).ensure_default_agents()


def _task(client, task_type: str = "INVESTIGATE", *, status: str = "OPEN", priority: str = "P2") -> str:
    task_id = _uid("TASK-P6-TEST")
    upsert_node(
        client,
        "Task",
        task_id,
        {
            "name": f"Phase 6 integration {task_type}",
            "title": f"Phase 6 integration {task_type}",
            "task_type": task_type,
            "objective": "Exercise persistent Phase 6 coordination semantics",
            "status": status,
            "priority": priority,
            "created_at": now_iso(),
            "expected_output_type": "INVESTIGATION_RESULT" if task_type == "INVESTIGATE" else "ACTION_PROPOSAL",
            "completion_condition": "Durable graph-backed test condition is satisfied",
        },
    )
    return task_id


def _claimed_execution(client, *, agent_id: str = INVESTIGATOR, task_type: str = "INVESTIGATE"):
    _ensure_agents(client)
    task_id = _task(client, task_type)
    coord = CoordinationService(client)
    coord.claim_task(task_id, agent_id)
    started = coord.start_execution(task_id, agent_id)
    return coord, task_id, started["execution"]["id"]


def _remediation_action(client, *, approval_required: bool = False, executor: MockActionExecutor | None = None, target_id: str | None = None):
    _ensure_agents(client)
    task_id = _task(client, "PREPARE_ACTION")
    coord = CoordinationService(client)
    coord.claim_task(task_id, REMEDIATION)
    coord.start_execution(task_id, REMEDIATION)
    target_id = target_id or _uid("SYS-P6-SANDBOX")
    if GraphSnapshot.load(client).node(target_id) is None:
        upsert_node(client, "System", target_id, {"name": "Phase 6 sandbox target", "status": "ACTIVE", "created_at": now_iso()})
        upsert_relationship(client, "TEAM-PRICING", "OWNS", target_id, {"valid_from": now_iso(), "confidence": 1.0})
    service = ActionCoordinationService(client, executor=executor)
    key = _uid("IDEMP")
    proposed = service.propose_action(
        task_id,
        REMEDIATION,
        name="Sandbox rollback test",
        action_type="rollback",
        target_ids=[target_id],
        idempotency_key=key,
        approval_required=approval_required,
    )
    return service, task_id, proposed["action"]["id"], key


def test_phase6_agent_registry_persists_and_does_not_reset_runtime_state(integration_client):
    service = AgentRegistryService(integration_client)
    service.ensure_default_agents()
    upsert_node(integration_client, "Agent", INVESTIGATOR, {"availability": "BUSY"})
    try:
        reloaded = AgentRegistryService(integration_client)
        reloaded.ensure_default_agents()
        assert reloaded.get_agent(INVESTIGATOR)["availability"] == "BUSY"
        assert reloaded.get_agent(INVESTIGATOR)["agent_type"] == "INVESTIGATOR"
    finally:
        upsert_node(integration_client, "Agent", INVESTIGATOR, {"availability": "AVAILABLE", "status": "ACTIVE"})


def test_phase6_task_owner_claim_persists_across_service_reconstruction(integration_client):
    _ensure_agents(integration_client)
    task_id = _task(integration_client)
    CoordinationService(integration_client).claim_task(task_id, INVESTIGATOR)
    owner = CoordinationService(integration_client).get_task_owner(task_id)
    assert owner and owner["owner"]["id"] == INVESTIGATOR
    assert owner["conflict"] is False


def test_phase6_second_worker_cannot_claim_owned_task(integration_client):
    _ensure_agents(integration_client)
    task_id = _task(integration_client)
    coord = CoordinationService(integration_client)
    coord.claim_task(task_id, INVESTIGATOR)
    with pytest.raises(ValueError):
        coord.claim_task(task_id, DEPENDENCY)
    assert coord.get_task_owner(task_id)["owner"]["id"] == INVESTIGATOR


def test_phase6_checkpoint_survives_restart_and_resume_starts_after_latest_step(integration_client):
    coord, task_id, execution_id = _claimed_execution(integration_client)
    coord.save_checkpoint(execution_id, INVESTIGATOR, step_index=1, current_step="inspect incident", completed_steps=["step 1"], pending_steps=["step 2", "step 3"])
    coord.save_checkpoint(execution_id, INVESTIGATOR, step_index=2, current_step="collect topology", completed_steps=["step 1", "step 2"], pending_steps=["step 3"])
    restarted = CoordinationService(integration_client)
    state = restarted.get_execution_state(execution_id)
    assert state["latest_checkpoint"]["step_index"] == 2
    resumed = restarted.resume_execution(execution_id, INVESTIGATOR)
    assert resumed["resume_from_step"] == 3
    assert [cp["step_index"] for cp in resumed["checkpoints"]] == [1, 2]
    assert restarted.get_task_owner(task_id)["owner"]["id"] == INVESTIGATOR


def test_phase6_another_eligible_agent_can_resume_and_prior_artifacts_remain(integration_client):
    coord, task_id, execution_id = _claimed_execution(integration_client)
    coord.save_checkpoint(execution_id, INVESTIGATOR, step_index=2, current_step="topology analyzed", completed_steps=["1", "2"], pending_steps=["3"])
    finding = coord.add_finding(task_id, INVESTIGATOR, statement="Pricing API depends on Pricing DB", confidence=0.91)
    resumed = CoordinationService(integration_client).resume_execution(execution_id, DEPENDENCY)
    assert resumed["resume_from_step"] == 3
    assert resumed["owner"]["id"] == DEPENDENCY
    assert any(item["id"] == finding["finding"]["id"] for item in CoordinationService(integration_client).get_recent_findings(task_id))


def test_phase6_ineligible_agent_cannot_resume_execution(integration_client):
    coord, _, execution_id = _claimed_execution(integration_client)
    coord.save_checkpoint(execution_id, INVESTIGATOR, step_index=1, current_step="started")
    with pytest.raises(ValueError, match="cannot resume"):
        CoordinationService(integration_client).resume_execution(execution_id, VERIFIER)


def test_phase6_unresolved_blocker_persists_and_prevents_resume(integration_client):
    coord, task_id, execution_id = _claimed_execution(integration_client)
    blocker = coord.add_blocker(task_id, INVESTIGATOR, reason="Awaiting deployment record")
    restarted = CoordinationService(integration_client)
    assert any(item["id"] == blocker["blocker"]["id"] for item in restarted.get_unresolved_blockers(task_id))
    with pytest.raises(ValueError, match="unresolved blockers"):
        restarted.resume_execution(execution_id, INVESTIGATOR)


def test_phase6_shared_evidence_and_findings_are_visible_to_other_agents(integration_client):
    coord, task_id, _ = _claimed_execution(integration_client)
    finding = coord.add_finding(task_id, INVESTIGATOR, statement="Compatibility check is relevant", confidence=0.88, evidence_ids=["E-003"])
    coord.add_shared_evidence(task_id, INVESTIGATOR, "E-003")
    view = CoordinationService(integration_client).get_task_blackboard(task_id)
    assert any(item["id"] == finding["finding"]["id"] for item in view["findings"])
    assert any(item["id"] == "E-003" for item in view["shared_evidence"])
    verified = CoordinationService(integration_client).verify_finding(finding["finding"]["id"], VERIFIER, result="VERIFIED", rationale="Evidence is sufficient")
    assert verified["finding"]["status"] == "VERIFIED"


def test_phase6_graph_necessity_blackboard_loses_finding_when_about_link_removed(integration_client):
    coord, task_id, _ = _claimed_execution(integration_client)
    finding = coord.add_finding(task_id, INVESTIGATOR, statement="Graph linked finding", confidence=0.8)
    finding_id = finding["finding"]["id"]
    assert any(x["id"] == finding_id for x in coord.get_recent_findings(task_id))
    assert delete_relationship(integration_client, finding_id, "ABOUT", task_id) >= 1
    assert not any(x["id"] == finding_id for x in coord.get_recent_findings(task_id))


def test_phase6_valid_handoff_is_accepted_and_persisted(integration_client):
    coord, task_id, _ = _claimed_execution(integration_client)
    finding = coord.add_finding(task_id, INVESTIGATOR, statement="Root-cause candidate", confidence=0.9, evidence_ids=["E-003"])
    handoffs = HandoffService(integration_client)
    transfer = handoffs.create_handoff(task_id, INVESTIGATOR, VERIFIER, artifact_ids=[finding["finding"]["id"], "E-003"])
    handoff_id = transfer["handoff"]["id"]
    assert handoffs.validate_handoff(handoff_id)["valid"] is True
    accepted = handoffs.accept_handoff(handoff_id, VERIFIER)
    assert accepted["handoff"]["status"] == "ACCEPTED"


def test_phase6_handoff_missing_evidence_is_rejected(integration_client):
    coord, task_id, _ = _claimed_execution(integration_client)
    finding = coord.add_finding(task_id, INVESTIGATOR, statement="Finding without transfer evidence", confidence=0.9)
    handoffs = HandoffService(integration_client)
    transfer = handoffs.create_handoff(task_id, INVESTIGATOR, VERIFIER, artifact_ids=[finding["finding"]["id"]])
    result = handoffs.validate_handoff(transfer["handoff"]["id"])
    assert result["valid"] is False
    assert "EVIDENCE" in result["missing_evidence"]


def test_phase6_handoff_reports_unresolved_blocker_and_low_confidence(integration_client):
    coord, task_id, _ = _claimed_execution(integration_client)
    finding = coord.add_finding(task_id, INVESTIGATOR, statement="Weak hypothesis", confidence=0.4, evidence_ids=["E-003"])
    coord.add_blocker(task_id, INVESTIGATOR, reason="Need second source")
    handoffs = HandoffService(integration_client)
    transfer = handoffs.create_handoff(task_id, INVESTIGATOR, VERIFIER, artifact_ids=[finding["finding"]["id"], "E-003"], confidence_threshold=0.8)
    result = handoffs.validate_handoff(transfer["handoff"]["id"])
    assert result["valid"] is False
    assert result["unresolved_blockers"]
    assert result["confidence_failures"]


def test_phase6_graph_necessity_handoff_requires_artifact_edges(integration_client):
    coord, task_id, _ = _claimed_execution(integration_client)
    finding = coord.add_finding(task_id, INVESTIGATOR, statement="Complete handoff", confidence=0.9, evidence_ids=["E-003"])
    service = HandoffService(integration_client)
    transfer = service.create_handoff(task_id, INVESTIGATOR, VERIFIER, artifact_ids=[finding["finding"]["id"], "E-003"])
    hid = transfer["handoff"]["id"]
    assert service.validate_handoff(hid)["valid"] is True
    assert delete_relationship(integration_client, hid, "REQUIRES", "E-003") >= 1
    assert service.validate_handoff(hid)["valid"] is False


def test_phase6_branch_isolation_and_validated_merge(integration_client):
    coord, task_id, execution_id = _claimed_execution(integration_client)
    service = BranchMemoryService(integration_client)
    branch = service.create_branch(execution_id, INVESTIGATOR, purpose="Database saturation alternative")
    branch_id = branch["branch"]["id"]
    local = service.add_branch_finding(branch_id, INVESTIGATOR, statement="Database saturation is causal", confidence=0.92, evidence_ids=["E-003"])
    assert local["finding"]["scope"] == "BRANCH"
    assert not any(x["id"] == local["finding"]["id"] for x in coord.get_recent_findings(task_id))
    assert service.validate_branch(branch_id)["valid"] is True
    merged = service.merge_branch(branch_id, INVESTIGATOR)
    assert merged["branch"]["status"] == "MERGED"
    assert any(x["id"] in merged["promoted_finding_ids"] for x in coord.get_recent_findings(task_id))


def test_phase6_rejected_branch_remains_queryable_and_does_not_promote(integration_client):
    _, _, execution_id = _claimed_execution(integration_client)
    service = BranchMemoryService(integration_client)
    branch = service.create_branch(execution_id, INVESTIGATOR, purpose="Rejected alternative")
    branch_id = branch["branch"]["id"]
    service.add_branch_finding(branch_id, INVESTIGATOR, statement="Rejected hypothesis", confidence=0.7, evidence_ids=["E-003"])
    rejected = service.reject_branch(branch_id, INVESTIGATOR, reason="Contradicted by stronger evidence")
    assert rejected["branch"]["status"] == "REJECTED"
    assert service.get_branch(branch_id)["findings"]
    snapshot = GraphSnapshot.load(integration_client)
    assert not any(
        "Finding" in set(node.get("_labels") or []) and node.get("merged_from_branch") == branch_id
        for node in snapshot.nodes.values()
    )


def test_phase6_graph_necessity_branch_merge_requires_parent_execution(integration_client):
    _, _, execution_id = _claimed_execution(integration_client)
    service = BranchMemoryService(integration_client)
    branch = service.create_branch(execution_id, INVESTIGATOR, purpose="Provenance edge test")
    branch_id = branch["branch"]["id"]
    service.add_branch_finding(branch_id, INVESTIGATOR, statement="Valid evidence-backed branch", confidence=0.9, evidence_ids=["E-003"])
    assert service.validate_branch(branch_id)["valid"] is True
    assert delete_relationship(integration_client, branch_id, "PART_OF", execution_id) >= 1
    degraded = service.validate_branch(branch_id)
    assert degraded["valid"] is False
    assert "MISSING_BRANCH_PROVENANCE" in degraded["errors"]


def test_phase6_deadlock_cycle_and_graph_necessity(integration_client):
    t1, t2 = _task(integration_client), _task(integration_client)
    upsert_relationship(integration_client, t1, "BLOCKED_BY", t2, {"confidence": 1.0})
    upsert_relationship(integration_client, t2, "BLOCKED_BY", t1, {"confidence": 1.0})
    service = CoordinationRiskService(integration_client)
    before = service.detect_deadlocks()
    assert any(set(item["tasks"]) == {t1, t2} for item in before["deadlocks"])
    assert delete_relationship(integration_client, t2, "BLOCKED_BY", t1) >= 1
    after = service.detect_deadlocks()
    assert not any(set(item["tasks"]) == {t1, t2} for item in after["deadlocks"])


def test_phase6_conflicting_ownership_is_detected(integration_client):
    _ensure_agents(integration_client)
    task_id = _task(integration_client)
    ts = now_iso()
    upsert_relationship(integration_client, task_id, "CLAIMED_BY", INVESTIGATOR, {"valid_from": ts, "confidence": 1.0})
    upsert_relationship(integration_client, task_id, "CLAIMED_BY", DEPENDENCY, {"valid_from": ts, "confidence": 1.0})
    result = CoordinationRiskService(integration_client).detect_contention()
    item = next(x for x in result["conflicting_ownership"] if x["task_id"] == task_id)
    assert {x["id"] for x in item["owners"]} == {INVESTIGATOR, DEPENDENCY}


def test_phase6_expired_lock_is_detected_as_abandoned(integration_client):
    _ensure_agents(integration_client)
    lock_id = _uid("LOCK-P6-TEST")
    now = now_iso()
    expired = add_seconds(now, -5)
    upsert_node(integration_client, "Lock", lock_id, {"status": "ACTIVE", "created_at": add_seconds(now, -30), "lease_until": expired, "owner_agent_id": REMEDIATION})
    upsert_relationship(integration_client, lock_id, "LOCKS", "SYS-PRICING-DB", {"valid_from": add_seconds(now, -30), "confidence": 1.0})
    result = CoordinationRiskService(integration_client).detect_contention(as_of=now)
    assert any(item["lock"]["id"] == lock_id and item["reason"] == "LEASE_EXPIRED" for item in result["abandoned_locks"])


def test_phase6_starvation_heuristic_is_explainable(integration_client):
    task_id = _task(integration_client, priority="HIGH")
    now = now_iso()
    upsert_node(integration_client, "Task", task_id, {"ready_since": add_seconds(now, -4000), "claim_attempts": 4, "status": "READY"})
    result = CoordinationRiskService(integration_client).detect_contention(as_of=now, starvation_age_seconds=1800, min_claim_attempts=3)
    item = next(x for x in result["starvation"] if x["task"]["id"] == task_id)
    assert item["claim_attempts"] == 4
    assert "READY task" in item["reason"]


def test_phase6_governance_allows_authorized_remediation_action(integration_client):
    service, _, action_id, _ = _remediation_action(integration_client)
    result = GovernanceService(integration_client).evaluate_action(action_id, agent_id=REMEDIATION)
    assert result["decision"] == "ALLOW"
    assert result["ownership_paths"]
    assert "EXECUTE_SANDBOX_ACTION" in result["permissions"]


def test_phase6_governance_denies_unauthorized_agent_even_if_action_exists(integration_client):
    _, _, action_id, _ = _remediation_action(integration_client)
    result = GovernanceService(integration_client).evaluate_action(action_id, agent_id=VERIFIER)
    assert result["decision"] == "DENY"
    assert "AGENT_EXECUTION_PERMISSION_MISSING" in result["missing_requirements"]


def test_phase6_missing_required_approval_prevents_execution(integration_client):
    service, _, action_id, _ = _remediation_action(integration_client, approval_required=True)
    result = service.execute_action(action_id, REMEDIATION)
    assert result["status"] == "NOT_EXECUTED"
    assert result["governance"]["decision"] == "REQUIRES_APPROVAL"
    assert service.executor.invocation_count() == 0


def test_phase6_agent_cannot_override_explicit_policy_denial(integration_client):
    executor = MockActionExecutor()
    service, _, action_id, _ = _remediation_action(integration_client, executor=executor)
    policy_id = _uid("POL-P6-DENY")
    upsert_node(integration_client, "Policy", policy_id, {"name": "Integration deny", "status": "ACTIVE", "authoritative": True, "effect": "DENY", "created_at": now_iso()})
    upsert_relationship(integration_client, policy_id, "GOVERNS", action_id, {"valid_from": now_iso(), "confidence": 1.0, "authoritative": True})
    result = service.execute_action(action_id, REMEDIATION)
    assert result["status"] == "NOT_EXECUTED"
    assert result["governance"]["decision"] == "DENY"
    assert executor.invocation_count() == 0


def test_phase6_graph_necessity_removing_approval_changes_governance(integration_client):
    service, _, action_id, _ = _remediation_action(integration_client, approval_required=True)
    upsert_relationship(integration_client, action_id, "APPROVED_BY", "PERSON-MAYA", {"valid_from": now_iso(), "confidence": 1.0})
    assert GovernanceService(integration_client).evaluate_action(action_id, agent_id=REMEDIATION)["decision"] == "ALLOW"
    assert delete_relationship(integration_client, action_id, "APPROVED_BY", "PERSON-MAYA") >= 1
    assert GovernanceService(integration_client).evaluate_action(action_id, agent_id=REMEDIATION)["decision"] == "REQUIRES_APPROVAL"


def test_phase6_duplicate_logical_action_executes_mock_side_effect_once(integration_client):
    executor = MockActionExecutor()
    service, _, action_id, key = _remediation_action(integration_client, executor=executor)
    first = service.execute_action(action_id, REMEDIATION)
    second = service.execute_action(action_id, REMEDIATION)
    assert first["status"] == "SUCCEEDED"
    assert second["status"] == "ALREADY_COMPLETED"
    assert executor.invocation_count(key) == 1


def test_phase6_concurrent_duplicate_attempts_do_not_execute_twice(integration_client):
    executor = MockActionExecutor()
    service, _, action_id, key = _remediation_action(integration_client, executor=executor)

    def run_once():
        # Distinct client/service objects simulate independent workers sharing FalkorDB.
        worker_client = FalkorGraphClient(integration_client.settings)
        return ActionCoordinationService(worker_client, executor=executor).execute_action(action_id, REMEDIATION)["status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: run_once(), range(2)))
    assert "SUCCEEDED" in statuses
    assert set(statuses) <= {"SUCCEEDED", "ALREADY_RUNNING", "ALREADY_COMPLETED"}
    assert executor.invocation_count(key) == 1


def test_phase6_crash_before_external_call_can_be_recovered_safely(integration_client):
    executor = MockActionExecutor()
    service, _, action_id, key = _remediation_action(integration_client, executor=executor)
    started = service.execute_action(action_id, REMEDIATION, lease_seconds=1, simulate_crash="before_external")
    assert started["status"] == "CRASH_SIMULATED_BEFORE_EXTERNAL"
    attempt = started["attempt"]
    recovery_time = add_seconds(str(attempt["lease_until"]), 1)
    recovered = service.recover_action(action_id, REMEDIATION, as_of=recovery_time)
    assert recovered["status"] == "SAFE_TO_RETRY"
    assert executor.invocation_count(key) == 0
    retry = service.execute_action(action_id, REMEDIATION, timestamp=recovery_time)
    assert retry["status"] == "SUCCEEDED"
    assert executor.invocation_count(key) == 1


def test_phase6_uncertain_external_result_becomes_unknown_and_is_not_blindly_retried(integration_client):
    executor = MockActionExecutor()
    service, _, action_id, key = _remediation_action(integration_client, executor=executor)
    started = service.execute_action(action_id, REMEDIATION, lease_seconds=1, simulate_crash="after_external_success")
    assert started["status"] == "CRASH_SIMULATED_WITH_UNCERTAIN_EXTERNAL_RESULT"
    recovery_time = add_seconds(str(started["attempt"]["lease_until"]), 1)
    recovered = service.recover_action(action_id, REMEDIATION, as_of=recovery_time, reconcile_external=False)
    assert recovered["status"] == "UNKNOWN"
    again = service.execute_action(action_id, REMEDIATION, timestamp=add_seconds(recovery_time, 1))
    assert again["status"] == "UNKNOWN"
    assert executor.invocation_count(key) == 1


def test_phase6_uncertain_result_can_reconcile_via_idempotent_sink_lookup(integration_client):
    executor = MockActionExecutor()
    service, _, action_id, key = _remediation_action(integration_client, executor=executor)
    started = service.execute_action(action_id, REMEDIATION, lease_seconds=1, simulate_crash="during_external")
    recovery_time = add_seconds(str(started["attempt"]["lease_until"]), 1)
    recovered = service.recover_action(action_id, REMEDIATION, as_of=recovery_time, reconcile_external=True)
    assert recovered["status"] == "SUCCEEDED"
    assert recovered["reconciled"] is True
    assert executor.invocation_count(key) == 1


def test_phase6_compaction_archives_old_checkpoints_but_keeps_latest(integration_client):
    coord, _, execution_id = _claimed_execution(integration_client)
    for step in range(1, 4):
        coord.save_checkpoint(execution_id, INVESTIGATOR, step_index=step, current_step=f"step {step}", completed_steps=[str(i) for i in range(1, step + 1)])
    result = MemoryCompactionService(integration_client).compact_execution(execution_id, keep_latest=1, actor_id=INVESTIGATOR)
    assert len(result["archived_checkpoint_ids"]) == 2
    assert len(result["retained_checkpoint_ids"]) == 1
    assert result["validation"]["valid"] is True
    state = CoordinationService(integration_client).get_execution_state(execution_id)
    assert len(state["checkpoints"]) == 1


def test_phase6_compaction_preserves_evidence_branch_and_action_lineage(integration_client):
    coord, task_id, execution_id = _claimed_execution(integration_client)
    coord.save_checkpoint(execution_id, INVESTIGATOR, step_index=1, current_step="one")
    coord.save_checkpoint(execution_id, INVESTIGATOR, step_index=2, current_step="two")
    coord.add_shared_evidence(task_id, INVESTIGATOR, "E-003")
    finding = coord.add_finding(task_id, INVESTIGATOR, statement="Durable finding", confidence=0.9, evidence_ids=["E-003"])
    branch = BranchMemoryService(integration_client).create_branch(execution_id, INVESTIGATOR, purpose="Retained rejected branch")
    BranchMemoryService(integration_client).add_branch_finding(branch["branch"]["id"], INVESTIGATOR, statement="Branch memory", confidence=0.8, evidence_ids=["E-003"])
    BranchMemoryService(integration_client).reject_branch(branch["branch"]["id"], INVESTIGATOR, reason="Not selected")
    result = MemoryCompactionService(integration_client).compact_execution(execution_id, keep_latest=1, actor_id=INVESTIGATOR)
    assert result["validation"]["valid"] is True
    view = CoordinationService(integration_client).get_task_blackboard(task_id)
    assert any(x["id"] == "E-003" for x in view["shared_evidence"])
    assert any(x["id"] == finding["finding"]["id"] for x in view["findings"])
    assert any(x["id"] == branch["branch"]["id"] and x["status"] == "REJECTED" for x in view["branches"])


def test_phase6_graph_necessity_compaction_validation_fails_when_evidence_lineage_removed(integration_client):
    coord, task_id, execution_id = _claimed_execution(integration_client)
    coord.save_checkpoint(execution_id, INVESTIGATOR, step_index=1, current_step="one")
    coord.add_shared_evidence(task_id, INVESTIGATOR, "E-003")
    result = MemoryCompactionService(integration_client).compact_execution(execution_id, keep_latest=1, actor_id=INVESTIGATOR)
    compaction_id = result["compaction"]["id"]
    assert result["validation"]["valid"] is True
    assert delete_relationship(integration_client, "E-003", "ABOUT", task_id) >= 1
    degraded = MemoryCompactionService(integration_client).validate_compaction(compaction_id)
    assert degraded["valid"] is False
    assert any(code.startswith("ARTIFACT_TASK_LINEAGE_BROKEN:E-003") for code in degraded["errors"])


def test_phase6_event_ledger_records_coordination_transitions(integration_client):
    coord, task_id, execution_id = _claimed_execution(integration_client)
    checkpoint = coord.save_checkpoint(execution_id, INVESTIGATOR, step_index=1, current_step="persist transition")
    finding = coord.add_finding(task_id, INVESTIGATOR, statement="Ledger transition", confidence=0.8)
    snapshot = GraphSnapshot.load(integration_client)
    related_types = set()
    for event_id, event in snapshot.nodes.items():
        if "Event" not in set(event.get("_labels") or []):
            continue
        targets = {edge.target for edge in snapshot.edges_from(event_id, {"ABOUT"})}
        if task_id in targets or execution_id in targets or checkpoint["checkpoint"]["id"] in targets or finding["finding"]["id"] in targets:
            related_types.add(str(event.get("event_type")))
    assert {"TASK_CLAIMED", "TASK_STARTED", "CHECKPOINT_SAVED", "FINDING_CREATED"} <= related_types


def test_phase6_specialist_investigator_runs_only_supported_owned_work(integration_client):
    from backend.app.services.specialist_agent_service import SpecialistAgentService

    _ensure_agents(integration_client)
    task_id = _task(integration_client, "INVESTIGATE")
    upsert_relationship(integration_client, task_id, "ABOUT", "INC-001", {"valid_from": now_iso(), "confidence": 1.0})
    coord = CoordinationService(integration_client)
    coord.claim_task(task_id, INVESTIGATOR)
    result = SpecialistAgentService(integration_client).run_investigator_step(task_id, INVESTIGATOR)
    assert result["agent_type"] == "INVESTIGATOR"
    assert result["investigation"]["candidate_paths"]
    with pytest.raises(ValueError):
        SpecialistAgentService(integration_client).run_investigator_step(task_id, VERIFIER)


def test_phase6_specialist_dependency_analyst_runs_graph_blast_radius(integration_client):
    from backend.app.services.specialist_agent_service import SpecialistAgentService

    _ensure_agents(integration_client)
    task_id = _task(integration_client, "INVESTIGATE")
    upsert_relationship(integration_client, task_id, "ABOUT", "SYS-PRICING-DB", {"valid_from": now_iso(), "confidence": 1.0})
    coord = CoordinationService(integration_client)
    coord.claim_task(task_id, DEPENDENCY)
    result = SpecialistAgentService(integration_client).run_dependency_step(task_id, DEPENDENCY)
    assert result["agent_type"] == "DEPENDENCY_ANALYST"
    assert any(x["system"]["id"] == "SYS-CHECKOUT" for x in result["analysis"]["downstream_dependents"])


def test_phase6_specialist_verifier_updates_shared_finding(integration_client):
    from backend.app.services.specialist_agent_service import SpecialistAgentService

    coord, task_id, _ = _claimed_execution(integration_client)
    finding = coord.add_finding(task_id, INVESTIGATOR, statement="Verifier integration finding", confidence=0.9, evidence_ids=["E-003"])
    result = SpecialistAgentService(integration_client).verify_finding(finding["finding"]["id"], VERIFIER, result="VERIFIED", rationale="Traceable evidence")
    assert result["finding"]["status"] == "VERIFIED"
    assert result["finding"]["verified_by"] == VERIFIER


def test_phase6_remediation_worker_can_prepare_but_governance_remains_final(integration_client):
    from backend.app.services.specialist_agent_service import SpecialistAgentService

    _ensure_agents(integration_client)
    task_id = _task(integration_client, "PREPARE_ACTION")
    coord = CoordinationService(integration_client)
    coord.claim_task(task_id, REMEDIATION)
    assert SpecialistAgentService(integration_client).remediation_capability(task_id, REMEDIATION)["allowed"] is True
    executor = MockActionExecutor()
    action_service = ActionCoordinationService(integration_client, executor=executor)
    proposed = action_service.propose_action(task_id, REMEDIATION, name="Governed remediation", action_type="rollback", target_ids=["SYS-PRICING-DB"], idempotency_key=_uid("remediation-governance"), approval_required=True)
    denied = action_service.execute_action(proposed["action"]["id"], REMEDIATION)
    assert denied["status"] == "NOT_EXECUTED"
    assert denied["governance"]["decision"] == "REQUIRES_APPROVAL"
    assert executor.invocation_count() == 0


def test_phase6_compaction_preserves_decision_explanation_relationships(integration_client):
    coord, task_id, execution_id = _claimed_execution(integration_client)
    coord.save_checkpoint(execution_id, INVESTIGATOR, step_index=1, current_step="decision context")
    coord.save_checkpoint(execution_id, INVESTIGATOR, step_index=2, current_step="decision context complete")
    decision_id = _uid("DEC-P6-TEST")
    upsert_node(integration_client, "Decision", decision_id, {"name": "Compaction decision", "status": "ACTIVE", "created_at": now_iso()})
    upsert_relationship(integration_client, task_id, "ADDRESSES", decision_id, {"valid_from": now_iso(), "confidence": 1.0})
    upsert_relationship(integration_client, decision_id, "BASED_ON", "E-003", {"valid_from": now_iso(), "confidence": 1.0})
    result = MemoryCompactionService(integration_client).compact_execution(execution_id, keep_latest=1, actor_id=INVESTIGATOR)
    assert result["validation"]["valid"] is True
    snapshot = GraphSnapshot.load(integration_client)
    assert any(edge.target == decision_id for edge in snapshot.edges_from(task_id, {"ADDRESSES"}))
    assert any(edge.target == "E-003" for edge in snapshot.edges_from(decision_id, {"BASED_ON"}))


def test_phase6_compaction_keeps_action_outcome_reconstructable(integration_client):
    executor = MockActionExecutor()
    service, task_id, action_id, _ = _remediation_action(integration_client, executor=executor)
    board = CoordinationService(integration_client).get_task_blackboard(task_id)
    execution_id = board["executions"][0]["id"]
    coord = CoordinationService(integration_client)
    coord.save_checkpoint(execution_id, REMEDIATION, step_index=1, current_step="prepared")
    coord.save_checkpoint(execution_id, REMEDIATION, step_index=2, current_step="executing")
    assert service.execute_action(action_id, REMEDIATION)["status"] == "SUCCEEDED"
    result = MemoryCompactionService(integration_client).compact_execution(execution_id, keep_latest=1, actor_id=REMEDIATION)
    assert result["validation"]["valid"] is True
    action_state = ActionCoordinationService(integration_client, executor=executor).get_action(action_id)
    assert action_state["action"]["status"] == "SUCCEEDED"
    assert action_state["attempt"]["execution_state"] == "SUCCEEDED"


def test_phase6_different_actions_cannot_hold_same_resource_lease_concurrently(integration_client):
    executor = MockActionExecutor()
    target_id = _uid("SYS-P6-CONTENDED")
    upsert_node(integration_client, "System", target_id, {"name": "Contended sandbox system", "status": "ACTIVE", "created_at": now_iso()})
    upsert_relationship(integration_client, "TEAM-PRICING", "OWNS", target_id, {"valid_from": now_iso(), "confidence": 1.0})
    first, _, first_action, _ = _remediation_action(integration_client, executor=executor, target_id=target_id)
    second, _, second_action, _ = _remediation_action(integration_client, executor=executor, target_id=target_id)
    held = first.execute_action(first_action, REMEDIATION, lease_seconds=60, simulate_crash="before_external")
    assert held["status"] == "CRASH_SIMULATED_BEFORE_EXTERNAL"
    with pytest.raises(ValueError, match="Resource contention detected"):
        second.execute_action(second_action, REMEDIATION)
    risks = CoordinationRiskService(integration_client).detect_contention()
    assert any(item["event_type"] == "CONTENTION_DETECTED" for item in GraphSnapshot.load(integration_client).nodes.values() if "Event" in set(item.get("_labels") or []))


def test_phase6_task_completion_requires_existing_phase5_completion_contract(integration_client):
    _ensure_agents(integration_client)
    task_id = _task(integration_client, "PREPARE_ACTION")
    coord = CoordinationService(integration_client)
    coord.claim_task(task_id, REMEDIATION)
    execution_id = coord.start_execution(task_id, REMEDIATION)["execution"]["id"]
    action_id = _uid("ACT-P6-COMPLETE")
    upsert_node(
        integration_client,
        "Action",
        action_id,
        {"name": "Prepared sandbox action", "action_type": "rollback", "status": "PROPOSED", "created_at": now_iso()},
    )
    upsert_relationship(integration_client, task_id, "ADDRESSES", action_id, {"valid_from": now_iso(), "confidence": 1.0})

    result = coord.complete_execution(execution_id, REMEDIATION)
    assert result["status"] == "COMPLETED"
    snapshot = GraphSnapshot.load(integration_client)
    assert snapshot.node(task_id)["status"] == "COMPLETED"
    assert snapshot.node(execution_id)["status"] == "COMPLETED"
    owner = CoordinationService(integration_client).get_task_owner(task_id)
    assert owner and owner["owner"] is None and owner["active_claims"] == []


def test_phase6_task_completion_cannot_bypass_unsatisfied_graph_condition(integration_client):
    coord, task_id, execution_id = _claimed_execution(integration_client, agent_id=INVESTIGATOR, task_type="INVESTIGATE")
    with pytest.raises(ValueError, match="completion condition is not satisfied"):
        coord.complete_execution(execution_id, INVESTIGATOR)
    snapshot = GraphSnapshot.load(integration_client)
    assert snapshot.node(task_id)["status"] == "IN_PROGRESS"
    assert snapshot.node(execution_id)["status"] == "RUNNING"
