from __future__ import annotations

import pytest

from backend.app.graph.mutations import delete_relationship, upsert_node, upsert_relationship
from backend.app.services.phase4_graph import GraphSnapshot
from backend.app.services.work_planning_service import WorkPlanningService


pytestmark = pytest.mark.integration

GOAL = "Resolve INC-001 safely with enough evidence to select remediation."


def _plan(service: WorkPlanningService):
    result = service.generate_plan("INC-001", GOAL)
    assert result is not None
    return result


def _task_by_semantic(plan, semantic_key: str):
    return next(item for item in plan["tasks"] if item["task"].get("semantic_key") == semantic_key)


def _task_by_type(plan, task_type: str):
    return next(item for item in plan["tasks"] if item["task"].get("task_type") == task_type)


def test_phase5_plan_and_tasks_are_persisted_in_falkordb(integration_client):
    service = WorkPlanningService(integration_client)
    plan = _plan(service)
    snapshot = GraphSnapshot.load(integration_client)
    plan_id = plan["plan"]["id"]
    assert "Plan" in set(snapshot.node(plan_id).get("_labels") or [])
    task_ids = {edge.target for edge in snapshot.edges_from(plan_id, {"PLAN_HAS_TASK"})}
    assert task_ids
    assert task_ids == {item["task"]["id"] for item in plan["tasks"]}
    assert all(snapshot.node(task_id).get("task_type") for task_id in task_ids)


def test_phase5_task_prerequisites_and_initial_readiness_are_graph_backed(integration_client):
    service = WorkPlanningService(integration_client)
    plan = _plan(service)
    conflict = _task_by_type(plan, "RESOLVE_CONFLICT")
    prerequisite_ids = {item["entity"]["id"] for item in conflict["prerequisites"]}
    assert len(prerequisite_ids) >= 3
    readiness = service.get_ready_tasks(plan["plan"]["id"])
    ready_ids = {item["task"]["id"] for item in readiness["ready_tasks"]}
    blocked_ids = {item["task"]["id"] for item in readiness["blocked_tasks"]}
    assert conflict["task"]["id"] in blocked_ids
    assert any(item["task"].get("task_type") in {"ACQUIRE_EVIDENCE", "INVESTIGATE"} for item in readiness["ready_tasks"])
    assert ready_ids.isdisjoint(blocked_ids)


def test_phase5_evidence_requirements_are_explicit_graph_links(integration_client):
    service = WorkPlanningService(integration_client)
    plan = _plan(service)
    q1 = _task_by_semantic(plan, "question:Q-001:ACQUIRE_EVIDENCE")
    addressed = {item["entity"]["id"] for item in q1["addresses"]}
    required = {item["entity"]["id"] for item in q1["required_entities"]}
    assert "Q-001" in addressed
    assert {"TOOL-DEPLOY-LOOKUP", "TOOL-GIT-LOOKUP"} <= required
    assert q1["task"]["expected_output_type"] == "EVIDENCE"
    assert q1["task"]["completion_condition"]


def test_phase5_pricing_db_expertise_ranks_riya_above_formal_owner_for_technical_task(integration_client):
    service = WorkPlanningService(integration_client)
    plan = _plan(service)
    q2 = _task_by_semantic(plan, "question:Q-002:INVESTIGATE")
    candidates = q2["candidate_assignees"]
    ids = [item["actor"]["id"] for item in candidates]
    assert "PERSON-RIYA" in ids
    assert "TEAM-PRICING" in ids
    riya = next(item for item in candidates if item["actor"]["id"] == "PERSON-RIYA")
    owner = next(item for item in candidates if item["actor"]["id"] == "TEAM-PRICING")
    assert "DOMAIN_EXPERT" in riya["roles"]
    assert "FORMAL_OWNER" in owner["roles"]
    assert riya["score"] > owner["score"]


def test_phase5_removing_expert_in_changes_candidate_ranking(integration_client):
    service = WorkPlanningService(integration_client)
    before = _plan(service)
    q2_before = _task_by_semantic(before, "question:Q-002:INVESTIGATE")
    riya_before = next(item for item in q2_before["candidate_assignees"] if item["actor"]["id"] == "PERSON-RIYA")
    props = {"valid_from": "2025-01-01T00:00:00+05:30", "confidence": 0.98}
    try:
        assert delete_relationship(integration_client, "PERSON-RIYA", "EXPERT_IN", "SYS-PRICING-DB") >= 1
        after = service.recompute_plan(before["plan"]["id"])
        q2_after = _task_by_semantic(after, "question:Q-002:INVESTIGATE")
        riya_after = next((item for item in q2_after["candidate_assignees"] if item["actor"]["id"] == "PERSON-RIYA"), None)
        assert riya_after is None or riya_after["score"] < riya_before["score"]
        assert q2_after["candidate_assignees"][0]["actor"]["id"] != "PERSON-RIYA"
    finally:
        upsert_relationship(integration_client, "PERSON-RIYA", "EXPERT_IN", "SYS-PRICING-DB", props)
        service.recompute_plan(before["plan"]["id"])


def test_phase5_same_state_same_goal_is_idempotent(integration_client):
    service = WorkPlanningService(integration_client)
    first = _plan(service)
    second = _plan(service)
    assert first["plan"]["id"] == second["plan"]["id"]
    assert {item["task"]["id"] for item in first["tasks"]} == {item["task"]["id"] for item in second["tasks"]}
    snapshot = GraphSnapshot.load(integration_client)
    plan_id = first["plan"]["id"]
    members = [edge.target for edge in snapshot.edges_from(plan_id, {"PLAN_HAS_TASK"})]
    assert len(members) == len(set(members)) == first["task_count"]




def test_phase5_recompute_preserves_explicit_plan_selection(integration_client):
    service = WorkPlanningService(integration_client)
    scoped = service.generate_plan(
        "INC-001",
        GOAL,
        selected_claims=["C-001"],
    )
    assert scoped is not None
    assert not any(item["task"].get("task_type") == "RESOLVE_CONFLICT" for item in scoped["tasks"])
    recomputed = service.recompute_plan(scoped["plan"]["id"])
    assert recomputed is not None
    assert recomputed["plan"]["id"] == scoped["plan"]["id"]
    assert not any(item["task"].get("task_type") == "RESOLVE_CONFLICT" for item in recomputed["tasks"])


def test_phase5_plan_creation_writes_structured_event_ledger_entries(integration_client):
    service = WorkPlanningService(integration_client)
    plan = _plan(service)
    snapshot = GraphSnapshot.load(integration_client)
    plan_id = plan["plan"]["id"]
    event = snapshot.node(f"EVT-{plan_id}-CREATED")
    assert event and event["event_type"] == "PLAN_CREATED"
    assert any(edge.target == plan_id for edge in snapshot.edges_from(event["id"], {"ABOUT"}))
    task_id = plan["tasks"][0]["task"]["id"]
    task_event = snapshot.node(f"EVT-{task_id}-CREATED")
    assert task_event and task_event["event_type"] == "TASK_CREATED"
    assert any(edge.target == task_id for edge in snapshot.edges_from(task_event["id"], {"ABOUT"}))


def test_phase5_cycle_validation_detects_real_graph_cycle(integration_client):
    service = WorkPlanningService(integration_client)
    plan = _plan(service)
    prepare = _task_by_type(plan, "PREPARE_ACTION")
    policy = _task_by_type(plan, "VALIDATE_POLICY")
    # Policy already REQUIRES prepare; adding the inverse creates a real cycle.
    try:
        upsert_relationship(integration_client, prepare["task"]["id"], "REQUIRES", policy["task"]["id"], {"required": True, "confidence": 1.0})
        validation = service.validate_plan(plan["plan"]["id"])
        assert validation["valid"] is False
        assert any(item["code"] == "TASK_CYCLE" for item in validation["errors"])
    finally:
        delete_relationship(integration_client, prepare["task"]["id"], "REQUIRES", policy["task"]["id"])


def test_phase5_graph_necessity_removing_question_membership_removes_gap_task(integration_client):
    service = WorkPlanningService(integration_client)
    plan = _plan(service)
    q1_before = _task_by_semantic(plan, "question:Q-001:ACQUIRE_EVIDENCE")
    q1_task_id = q1_before["task"]["id"]
    props = {"valid_from": "2026-10-16T14:12:00+05:30", "confidence": 1.0}
    restored = None
    try:
        assert delete_relationship(integration_client, "Q-001", "ABOUT", "INC-001") >= 1
        degraded = service.recompute_plan(plan["plan"]["id"])
        assert not any("Q-001" in {x["entity"]["id"] for x in item["addresses"]} for item in degraded["tasks"])
        conflict = _task_by_type(degraded, "RESOLVE_CONFLICT")
        assert q1_task_id not in {item["entity"]["id"] for item in conflict["prerequisites"]}
    finally:
        upsert_relationship(integration_client, "Q-001", "ABOUT", "INC-001", props)
        restored = service.recompute_plan(plan["plan"]["id"])

    q1_restored = _task_by_semantic(restored, "question:Q-001:ACQUIRE_EVIDENCE")
    assert q1_restored["task"]["id"] == q1_task_id
    assert q1_restored["task"]["status"] != "SUPERSEDED"
    conflict_restored = _task_by_type(restored, "RESOLVE_CONFLICT")
    assert q1_task_id in {item["entity"]["id"] for item in conflict_restored["prerequisites"]}


def test_phase5_graph_necessity_removing_policy_scope_removes_policy_task(integration_client):
    service = WorkPlanningService(integration_client)
    plan = _plan(service)
    assert any(item["task"].get("semantic_key") == "policy:POL-RECOVERY-01" for item in plan["tasks"])
    props = {"valid_from": "2026-10-16T14:16:00+05:30", "confidence": 1.0, "authoritative": True}
    try:
        assert delete_relationship(integration_client, "POL-RECOVERY-01", "GOVERNS", "ACT-ROLLBACK-MIG203") >= 1
        degraded = service.recompute_plan(plan["plan"]["id"])
        assert not any(item["task"].get("semantic_key") == "policy:POL-RECOVERY-01" for item in degraded["tasks"])
    finally:
        upsert_relationship(integration_client, "POL-RECOVERY-01", "GOVERNS", "ACT-ROLLBACK-MIG203", props)
        service.recompute_plan(plan["plan"]["id"])


def test_phase5_graph_necessity_removing_task_prerequisite_changes_readiness(integration_client):
    service = WorkPlanningService(integration_client)
    plan = _plan(service)
    policy = _task_by_type(plan, "VALIDATE_POLICY")
    prepare = _task_by_type(plan, "PREPARE_ACTION")
    original_status = prepare["task"].get("status") or "OPEN"
    upsert_node(integration_client, "Task", prepare["task"]["id"], {"status": "OPEN"})
    try:
        before = service.get_ready_tasks(plan["plan"]["id"])
        assert policy["task"]["id"] in {item["task"]["id"] for item in before["blocked_tasks"]}
        delete_relationship(integration_client, policy["task"]["id"], "REQUIRES", prepare["task"]["id"])
        after = service.get_ready_tasks(plan["plan"]["id"])
        assert policy["task"]["id"] in {item["task"]["id"] for item in after["ready_tasks"]}
    finally:
        upsert_relationship(integration_client, policy["task"]["id"], "REQUIRES", prepare["task"]["id"], {"required": True, "confidence": 1.0})
        upsert_node(integration_client, "Task", prepare["task"]["id"], {"status": original_status})


def test_phase5_historical_plan_does_not_use_future_reasoning_state(integration_client):
    service = WorkPlanningService(integration_client)
    historical = service.generate_plan(
        "INC-001",
        GOAL,
        as_of="2026-10-16T14:09:00+05:30",
    )
    assert historical is not None
    assert historical["task_count"] == 0
    current = _plan(service)
    assert historical["plan"]["id"] != current["plan"]["id"]


def test_phase5_completion_status_for_evidence_task_tracks_resolved_by_evidence(integration_client):
    service = WorkPlanningService(integration_client)
    plan = _plan(service)
    q1 = _task_by_semantic(plan, "question:Q-001:ACQUIRE_EVIDENCE")
    status = service.is_task_completion_satisfied(q1["task"]["id"])
    assert status["satisfied"] is False
    assert "Q-001" in status["missing_question_ids"]


def test_phase5_shared_equivalent_tasks_do_not_allow_scoped_plan_to_rewrite_default_prerequisites(integration_client):
    service = WorkPlanningService(integration_client)
    default = _plan(service)
    default_conflict = _task_by_type(default, "RESOLVE_CONFLICT")
    default_prereqs_before = {
        item["entity"]["id"] for item in default_conflict["prerequisites"]
    }

    # A different goal produces another Plan. Its equivalent gap Tasks may be shared safely,
    # but structurally different work must not rewrite the default Plan's task graph.
    scoped = service.generate_plan(
        "INC-001",
        GOAL + " Focus only on C-001.",
        selected_claims=["C-001"],
    )
    assert scoped is not None
    assert not any(item["task"].get("task_type") == "RESOLVE_CONFLICT" for item in scoped["tasks"])

    default_after = service.get_plan(default["plan"]["id"])
    default_conflict_after = _task_by_type(default_after, "RESOLVE_CONFLICT")
    assert {
        item["entity"]["id"] for item in default_conflict_after["prerequisites"]
    } == default_prereqs_before


def test_phase5_historical_plan_excludes_future_action_policy_relationships(integration_client):
    service = WorkPlanningService(integration_client)
    historical = service.generate_plan(
        "INC-001",
        GOAL + " before remediation decision",
        as_of="2026-10-16T14:15:59+05:30",
    )
    assert historical is not None
    task_types = {item["task"].get("task_type") for item in historical["tasks"]}
    assert "RESOLVE_CONFLICT" in task_types
    assert "PREPARE_ACTION" not in task_types
    assert "VALIDATE_POLICY" not in task_types
    assert "REQUEST_APPROVAL" not in task_types


def test_phase5_explicit_constraint_is_persisted_as_plan_graph_relationship(integration_client):
    service = WorkPlanningService(integration_client)
    constrained = service.generate_plan(
        "INC-001",
        GOAL + " while enforcing POL-DB-04 explicitly",
        constraints=["POL-DB-04"],
    )
    assert constrained is not None
    snapshot = GraphSnapshot.load(integration_client)
    plan_id = constrained["plan"]["id"]
    addressed = {edge.target for edge in snapshot.edges_from(plan_id, {"ADDRESSES"})}
    assert "INC-001" in addressed
    assert "POL-DB-04" in addressed
    assert constrained["plan"].get("constraint_refs_csv") == "POL-DB-04"


def test_phase5_historical_claim_supersession_respects_falkordb_edge_time(integration_client):
    service = WorkPlanningService(integration_client)
    upsert_node(
        integration_client,
        "Claim",
        "C-P5-SUPERSEDER",
        {
            "statement": "Replacement root-cause claim",
            "status": "OPEN",
            "created_at": "2026-10-16T14:20:00+05:30",
        },
    )
    upsert_relationship(
        integration_client,
        "C-P5-SUPERSEDER",
        "SUPERSEDES",
        "C-001",
        {"valid_from": "2026-10-16T14:20:00+05:30", "confidence": 1.0},
    )
    upsert_node(integration_client, "Claim", "C-001", {"status": "SUPERSEDED"})

    current = service.generate_plan("INC-001", GOAL + " after supersession")
    historical = service.generate_plan(
        "INC-001",
        GOAL + " immediately before supersession",
        as_of="2026-10-16T14:15:59+05:30",
    )
    assert current is not None and historical is not None
    assert not any(item["task"].get("task_type") == "RESOLVE_CONFLICT" for item in current["tasks"])
    assert any(
        {entity["entity"]["id"] for entity in item["addresses"]} == {"C-001", "C-002"}
        for item in historical["tasks"]
        if item["task"].get("task_type") == "RESOLVE_CONFLICT"
    )
