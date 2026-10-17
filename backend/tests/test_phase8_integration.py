from __future__ import annotations

import uuid

import pytest

from backend.app.graph.mutations import delete_relationship, upsert_node, upsert_relationship
from backend.app.services.phase4_graph import GraphSnapshot
from backend.app.services.process_reconstruction_service import OrganizationalProcessReconstructionService
from backend.app.services.policy_drift_service import PolicyDriftService
from backend.app.services.commitment_service import CommitmentTrackingService
from backend.app.services.initiative_collision_service import InitiativeCollisionService
from backend.app.services.bus_factor_service import BusFactorService
from backend.app.services.organizational_network_service import OrganizationalNetworkAnalysisService

pytestmark = pytest.mark.integration


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def test_phase8_inc001_process_reconstruction_recovers_explicit_trigger(integration_client):
    result = OrganizationalProcessReconstructionService(integration_client).reconstruct("INC-001")
    assert result is not None
    assert {x["event"]["id"] for x in result["steps"]} >= {"EVT-INC-001", "EVT-TASK-INV", "EVT-ROLLBACK-EXEC"}
    assert any(x["source"] == "EVT-INC-001" and x["target"] == "EVT-TASK-INV" for x in result["trigger_edges"])


def test_phase8_before_edges_do_not_create_causal_edges(integration_client):
    result = OrganizationalProcessReconstructionService(integration_client).reconstruct("INC-001")
    assert result["temporal_edges"]
    # Canonical baseline has no validated ROOT_CAUSE relation yet; BEFORE alone must not invent causality.
    assert result["causal_edges"] == []


def test_phase8_graph_necessity_trigger_edge(integration_client):
    service = OrganizationalProcessReconstructionService(integration_client)
    props = {"valid_from": "2026-10-16T14:08:00+05:30", "confidence": 1.0, "source_ref_id": "event-ledger"}
    assert service.reconstruct("INC-001")["trigger_edges"]
    try:
        delete_relationship(integration_client, "EVT-INC-001", "TRIGGERED", "EVT-TASK-INV")
        degraded = service.reconstruct("INC-001")
        assert not any(x["source"] == "EVT-INC-001" and x["target"] == "EVT-TASK-INV" for x in degraded["trigger_edges"])
        assert degraded["temporal_edges"]  # chronology remains, but trigger semantics disappear.
    finally:
        upsert_relationship(integration_client, "EVT-INC-001", "TRIGGERED", "EVT-TASK-INV", props)


def test_phase8_pol_db_04_drift_detects_skipped_compatibility_controls(integration_client):
    result = PolicyDriftService(integration_client).analyze("INC-001", "POL-DB-04")
    by_target = {x.get("affected_process_step"): x for x in result["drift"]}
    assert by_target["ACT-COMPAT-TEST"]["classification"] == "MISSING_REQUIRED_STEP"
    assert by_target["ACT-DOWNSTREAM-VERIFY"]["classification"] == "MISSING_REQUIRED_STEP"
    assert not any(x["classification"] == "MISSING_APPROVAL" for x in result["drift"])


def test_phase8_policy_drift_process_window_accepts_pre_action_container_approval(integration_client):
    incident_id, policy_id = uid("INC-WINDOW"), uid("POL-WINDOW")
    change_id, deployment_id, actor_id = uid("CHG-WINDOW"), uid("DPL-WINDOW"), uid("PERSON-WINDOW")
    e0, e2, e3 = uid("EVT-WINDOW"), uid("EVT-WINDOW"), uid("EVT-WINDOW")
    t0 = "2026-10-16T14:00:00+05:30"
    t1 = "2026-10-16T14:01:00+05:30"
    t2 = "2026-10-16T14:02:00+05:30"
    t3 = "2026-10-16T14:04:00+05:30"
    for label, node_id, props in [
        ("Incident", incident_id, {"status": "OPEN", "created_at": t0}),
        ("Policy", policy_id, {"name": "Window Approval Policy", "status": "ACTIVE", "valid_from": "2026-01-01T00:00:00+05:30", "requires_owner_approval": True}),
        ("Change", change_id, {"status": "DEPLOYED", "created_at": "2026-10-16T13:50:00+05:30", "applied_at": t2}),
        ("Deployment", deployment_id, {"status": "IN_PROGRESS", "created_at": "2026-10-16T13:55:00+05:30", "deployed_at": t2}),
        ("Person", actor_id, {"name": "Approver"}),
        ("Event", e0, {"event_type": "PROCESS_STARTED", "occurred_at": t0, "created_at": t0}),
        ("Event", e2, {"event_type": "DEPLOYMENT_STARTED", "occurred_at": t2, "created_at": t2}),
        ("Event", e3, {"event_type": "PROCESS_CONTINUED", "occurred_at": t3, "created_at": t3}),
    ]:
        upsert_node(integration_client, label, node_id, props)
    for source, rel, target, props in [
        (e0, "ABOUT", incident_id, {"valid_from": t0}),
        (e2, "ABOUT", incident_id, {"valid_from": t2}),
        (e2, "ABOUT", deployment_id, {"valid_from": t2}),
        (e2, "ABOUT", change_id, {"valid_from": t2}),
        (e3, "ABOUT", incident_id, {"valid_from": t3}),
        (policy_id, "GOVERNS", change_id, {"valid_from": t2}),
        (deployment_id, "CONTAINS", change_id, {"valid_from": t2}),
        (deployment_id, "APPROVED_BY", actor_id, {"valid_from": t1}),
    ]:
        upsert_relationship(integration_client, source, rel, target, props)

    result = PolicyDriftService(integration_client).analyze(incident_id, policy_id)
    assert [x["id"] for x in result["expected_process"]["governed_targets"]] == [change_id]
    assert not any(x["classification"] == "MISSING_APPROVAL" for x in result["drift"])
    assert result["expected_process"]["approval_observations"][0]["approvals"] == [f"{deployment_id}-[:APPROVED_BY]->{actor_id}"]


def test_phase8_graph_necessity_policy_requirement_edge(integration_client):
    service = PolicyDriftService(integration_client)
    props = {"valid_from": "2026-01-15T00:00:00+05:30", "confidence": 1.0, "authoritative": True}
    before = service.analyze("INC-001", "POL-DB-04")
    assert any(x.get("affected_process_step") == "ACT-COMPAT-TEST" for x in before["drift"])
    try:
        delete_relationship(integration_client, "POL-DB-04", "REQUIRES", "ACT-COMPAT-TEST")
        after = service.analyze("INC-001", "POL-DB-04")
        assert not any(x.get("affected_process_step") == "ACT-COMPAT-TEST" for x in after["drift"])
    finally:
        upsert_relationship(integration_client, "POL-DB-04", "REQUIRES", "ACT-COMPAT-TEST", props)


def test_phase8_com017_breach_promisor_promisee_and_consequence(integration_client):
    result = CommitmentTrackingService(integration_client).get("COM-017", as_of="2026-10-16T15:00:00+05:30")
    assert result["status"] == "BREACHED"
    assert [x["entity"]["id"] for x in result["promisors"]] == ["TEAM-PRICING"]
    assert [x["entity"]["id"] for x in result["promisees"]] == ["TEAM-PAYMENTS"]
    assert "E-003" in {x["id"] for x in result["breach_evidence"]}
    assert "DPL-882" in {x["entity"]["id"] for x in result["downstream_consequences"]}


def test_phase8_commitment_history_before_breach_remains_non_breached(integration_client):
    result = CommitmentTrackingService(integration_client).get("COM-017", as_of="2026-10-16T14:10:00+05:30")
    assert result["status"] != "BREACHED"
    assert result["breach_evidence"] == []


def test_phase8_com099_is_overdue_not_fabricated_breach(integration_client):
    result = CommitmentTrackingService(integration_client).get("COM-099", as_of="2026-10-16T01:00:00+05:30")
    assert result["status"] == "OVERDUE"
    assert result["breach_evidence"] == []


def test_phase8_graph_necessity_commitment_owed_to(integration_client):
    service = CommitmentTrackingService(integration_client)
    props = {"valid_from": "2026-10-13T10:00:00+05:30", "confidence": 1.0}
    assert service.get("COM-017")["promisees"]
    try:
        delete_relationship(integration_client, "COM-017", "OWED_TO", "TEAM-PAYMENTS")
        assert service.get("COM-017")["promisees"] == []
    finally:
        upsert_relationship(integration_client, "COM-017", "OWED_TO", "TEAM-PAYMENTS", props)


def test_phase8_high_collision_pair_and_negative_case(integration_client):
    service = InitiativeCollisionService(integration_client)
    result = service.analyze(min_score=0.0)
    pairs = {(x["project_a"]["id"], x["project_b"]["id"]): x for x in result["collisions"]}
    ab = pairs.get(("PROJ-REFUND-A", "PROJ-REFUND-B")) or pairs.get(("PROJ-REFUND-B", "PROJ-REFUND-A"))
    ac = pairs.get(("PROJ-REFUND-A", "PROJ-REFUND-C")) or pairs.get(("PROJ-REFUND-C", "PROJ-REFUND-A"))
    assert ab and ab["classification"] == "HIGH_COLLISION"
    assert ac and ac["classification"] == "LOW_OVERLAP"


def test_phase8_graph_necessity_collision_shared_relations_lower_score(integration_client):
    service = InitiativeCollisionService(integration_client)
    snap = GraphSnapshot.load(integration_client)
    before = service.score_pair_from_snapshot(snap, "PROJ-REFUND-A", "PROJ-REFUND-B")["score"]
    props_ds = {"valid_from": "2026-09-15T00:00:00+05:30", "confidence": 1.0}
    props_req = {"valid_from": "2026-09-15T00:00:00+05:30", "confidence": 1.0}
    try:
        delete_relationship(integration_client, "PROJ-REFUND-B", "DEPENDS_ON", "DS-REFUND-TELEMETRY")
        delete_relationship(integration_client, "PROJ-REFUND-B", "REQUIRES", "POL-REFUND-AUTO-01")
        after = service.score_pair_from_snapshot(GraphSnapshot.load(integration_client), "PROJ-REFUND-A", "PROJ-REFUND-B")["score"]
        assert after < before
    finally:
        upsert_relationship(integration_client, "PROJ-REFUND-B", "DEPENDS_ON", "DS-REFUND-TELEMETRY", props_ds)
        upsert_relationship(integration_client, "PROJ-REFUND-B", "REQUIRES", "POL-REFUND-AUTO-01", props_req)


def test_phase8_bus_factor_single_expert_fixture(integration_client):
    result = BusFactorService(integration_client).organization_summary()
    ledger = next(x for x in result["resources"] if x["resource"]["id"] == "SYS-LEDGER-EXPORT")
    assert ledger["coverage"]["expertise"]["count"] == 1
    assert ledger["risk"] == "HIGH"


def test_phase8_bus_factor_actor_loss_is_non_mutating(integration_client):
    before = GraphSnapshot.load(integration_client)
    assert any(e.source == "PERSON-ISHA" and e.type == "EXPERT_IN" and e.target == "SYS-LEDGER-EXPORT" for e in before.edges)
    result = BusFactorService(integration_client).simulate_loss(["PERSON-ISHA"])
    assert any("expertise" in x["lost_dimensions"] for x in result["affected_resources"] if x["resource"]["id"] == "SYS-LEDGER-EXPORT")
    after = GraphSnapshot.load(integration_client)
    assert any(e.source == "PERSON-ISHA" and e.type == "EXPERT_IN" and e.target == "SYS-LEDGER-EXPORT" for e in after.edges)


def test_phase8_graph_necessity_bus_factor_redundant_expert_reduces_concentration(integration_client):
    person = uid("P8-EXPERT")
    upsert_node(integration_client, "Person", person, {"name": "Backup Expert", "status": "ACTIVE", "created_at": "2026-10-16T00:00:00+05:30"})
    props = {"valid_from": "2026-10-16T00:00:00+05:30", "confidence": 0.95}
    try:
        before = BusFactorService.resource_coverage_from_snapshot(GraphSnapshot.load(integration_client), "SYS-LEDGER-EXPORT")
        upsert_relationship(integration_client, person, "EXPERT_IN", "SYS-LEDGER-EXPORT", props)
        after = BusFactorService.resource_coverage_from_snapshot(GraphSnapshot.load(integration_client), "SYS-LEDGER-EXPORT")
        assert before["coverage"]["expertise"]["count"] == 1
        assert after["coverage"]["expertise"]["count"] == 2
    finally:
        delete_relationship(integration_client, person, "EXPERT_IN", "SYS-LEDGER-EXPORT")


def test_phase8_bridge_fixture_detects_person_dev_as_articulation(integration_client):
    result = OrganizationalNetworkAnalysisService(integration_client).analyze("collaboration")
    ids = {x["node"]["id"] for x in result["articulation_points"]}
    assert "PERSON-DEV" in ids
    assert any("PERSON-DEV" in {x["source"]["id"], x["target"]["id"]} for x in result["bridges"])


def test_phase8_graph_necessity_redundant_collaboration_path_removes_dev_articulation_for_fixture_subgraph(integration_client):
    service = OrganizationalNetworkAnalysisService(integration_client)
    props = {"valid_from": "2026-10-16T00:00:00+05:30", "confidence": 1.0}
    before = service.analyze("collaboration")
    assert "PERSON-DEV" in {x["node"]["id"] for x in before["articulation_points"]}
    try:
        upsert_relationship(integration_client, "TEAM-SECURITY", "COLLABORATES_WITH", "TEAM-PLATFORM", props)
        after = service.analyze("collaboration")
        assert "PERSON-DEV" not in {x["node"]["id"] for x in after["articulation_points"]}
    finally:
        delete_relationship(integration_client, "TEAM-SECURITY", "COLLABORATES_WITH", "TEAM-PLATFORM")


def test_phase8_invalid_process_scope_returns_none(integration_client):
    assert OrganizationalProcessReconstructionService(integration_client).reconstruct("NO-SUCH-SCOPE") is None
