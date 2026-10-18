from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.services.phase4_graph import GraphEdge, GraphSnapshot
from backend.app.services.process_reconstruction_service import OrganizationalProcessReconstructionService
from backend.app.services.policy_drift_service import PolicyDriftService
from backend.app.services.commitment_service import CommitmentTrackingService
from backend.app.services.initiative_collision_service import InitiativeCollisionService
from backend.app.services.bus_factor_service import BusFactorService
from backend.app.services.organizational_network_service import OrganizationalNetworkAnalysisService


def node(node_id: str, label: str, **props):
    return {"id": node_id, "tenant_id": "northstar", "_labels": ["Entity", label], **props}


def edge(source: str, rel: str, target: str, **props):
    return GraphEdge(source, rel, target, props)


def dummy_client():
    return SimpleNamespace(settings=SimpleNamespace(tenant_id="northstar"))


def process_snapshot(*, with_trigger=True, with_dependency=True, equal_times=False, with_cause=False):
    t2 = "2026-10-16T14:00:00+05:30" if equal_times else "2026-10-16T14:01:00+05:30"
    nodes = {
        "I": node("I", "Incident", status="OPEN", created_at="2026-10-16T14:00:00+05:30"),
        "E1": node("E1", "Event", event_type="SITUATION_CREATED", occurred_at="2026-10-16T14:00:00+05:30", summary="incident"),
        "E2": node("E2", "Event", event_type="TASK_CREATED", occurred_at=t2, summary="task"),
        "T1": node("T1", "Task", status="OPEN", created_at="2026-10-16T14:01:00+05:30"),
        "T2": node("T2", "Task", status="OPEN", created_at="2026-10-16T14:02:00+05:30"),
        "A": node("A", "Person", name="Actor"),
    }
    edges = [edge("E1", "ABOUT", "I"), edge("E2", "ABOUT", "I"), edge("E2", "ABOUT", "T1"), edge("E1", "PERFORMED_BY", "A"), edge("T1", "ABOUT", "I"), edge("T2", "ABOUT", "I"), edge("E1", "BEFORE", "E2")]
    if with_trigger:
        edges.append(edge("E1", "TRIGGERED", "E2"))
    if with_dependency:
        edges.append(edge("T2", "REQUIRES", "T1"))
    if with_cause:
        nodes.update({
            "C": node("C", "Claim", status="VALIDATED"),
            "EV": node("EV", "Evidence", status="VALIDATED"),
        })
        edges.extend([edge("I", "ROOT_CAUSE", "C"), edge("EV", "SUPPORTS", "C")])
    return GraphSnapshot(nodes, edges)


def test_process_reconstructs_event_workflow():
    result = OrganizationalProcessReconstructionService.reconstruct_from_snapshot(process_snapshot(), "I")
    assert [s["event"]["id"] for s in result["steps"]] == ["E1", "E2"]


def test_process_temporal_order_is_chronological():
    result = OrganizationalProcessReconstructionService.reconstruct_from_snapshot(process_snapshot(), "I")
    assert result["steps"][0]["occurred_at"] < result["steps"][1]["occurred_at"]


def test_process_explicit_trigger_is_preserved():
    result = OrganizationalProcessReconstructionService.reconstruct_from_snapshot(process_snapshot(), "I")
    assert result["trigger_edges"][0]["relationship"] == "TRIGGERED"


def test_process_dependency_is_distinct_from_trigger():
    result = OrganizationalProcessReconstructionService.reconstruct_from_snapshot(process_snapshot(), "I")
    assert any(x["relationship"] == "REQUIRES" for x in result["dependency_edges"])
    assert all(x["relationship"] != "REQUIRES" for x in result["trigger_edges"])


def test_process_validated_root_cause_is_causal():
    result = OrganizationalProcessReconstructionService.reconstruct_from_snapshot(process_snapshot(with_cause=True), "I")
    assert result["causal_edges"][0]["basis"] == "VALIDATED_ROOT_CAUSE_CLAIM"
    assert result["causal_edges"][0]["supporting_evidence"] == ["EV"]


def test_before_alone_does_not_imply_cause():
    result = OrganizationalProcessReconstructionService.reconstruct_from_snapshot(process_snapshot(with_cause=False), "I")
    assert result["temporal_edges"] and result["causal_edges"] == []


def test_equal_event_times_without_order_are_ambiguous():
    snap = process_snapshot(equal_times=True)
    snap.remove_edges(lambda e: e.type == "BEFORE")
    result = OrganizationalProcessReconstructionService.reconstruct_from_snapshot(snap, "I")
    assert result["ambiguities"][0]["reason"] == "EQUAL_TIMESTAMP_WITHOUT_ORDER_EDGE"


def test_process_steps_include_provenance_paths():
    result = OrganizationalProcessReconstructionService.reconstruct_from_snapshot(process_snapshot(), "I")
    assert any("ABOUT" in path for step in result["steps"] for path in step["provenance_paths"])


def policy_snapshot(*, action_status="SKIPPED", optional=False, requires_approval=False):
    nodes = {
        "I": node("I", "Incident", created_at="2026-10-16T14:00:00+05:30"),
        "EV": node("EV", "Event", event_type="SITUATION_CREATED", occurred_at="2026-10-16T14:00:00+05:30"),
        "P": node("P", "Policy", name="Policy", status="ACTIVE", valid_from="2026-01-01T00:00:00+05:30", requires_approval=requires_approval),
        "A": node("A", "Action", status=action_status, created_at="2026-10-16T13:00:00+05:30"),
        "M": node("M", "Change", created_at="2026-10-16T13:00:00+05:30"),
    }
    edges = [edge("EV", "ABOUT", "I"), edge("A", "ABOUT", "I"), edge("P", "REQUIRES", "A", required=not optional, optional=optional), edge("P", "GOVERNS", "M")]
    return GraphSnapshot(nodes, edges)


def test_policy_expected_process_comes_from_require_edges():
    result = PolicyDriftService.analyze_from_snapshot(policy_snapshot(), "I", "P")
    assert result["expected_process"]["requirements"][0]["entity"]["id"] == "A"


def test_policy_observed_process_comes_from_events():
    snap = policy_snapshot(action_status="SUCCEEDED")
    snap.nodes["EA"] = node("EA", "Event", event_type="ACTION_SUCCEEDED", occurred_at="2026-10-16T14:02:00+05:30")
    snap.add_edge("EA", "ABOUT", "A")
    result = PolicyDriftService.analyze_from_snapshot(snap, "I", "P")
    assert any(step["event"]["id"] == "EA" for step in result["observed_process"]["steps"])


def test_policy_missing_required_step_detected():
    result = PolicyDriftService.analyze_from_snapshot(policy_snapshot(action_status="SKIPPED"), "I", "P")
    assert any(x["classification"] == "MISSING_REQUIRED_STEP" and x["status"] == "VIOLATION" for x in result["drift"])


def test_policy_order_violation_detected():
    snap = policy_snapshot(action_status="SUCCEEDED")
    snap.nodes["B"] = node("B", "Action", status="SUCCEEDED", created_at="2026-10-16T12:00:00+05:30")
    snap.add_edge("B", "ABOUT", "I")
    snap.add_edge("P", "REQUIRES", "B", {"required": True})
    snap.add_edge("B", "REQUIRES", "A")  # A must happen before B, but B timestamp is earlier.
    result = PolicyDriftService.analyze_from_snapshot(snap, "I", "P")
    assert any(x["classification"] == "ORDER_VIOLATION" for x in result["drift"])


def test_policy_missing_approval_detected():
    result = PolicyDriftService.analyze_from_snapshot(policy_snapshot(requires_approval=True), "I", "P")
    assert any(x["classification"] == "MISSING_APPROVAL" for x in result["drift"])


def approval_window_snapshot(*, approval_at="2026-10-16T14:01:00+05:30", governs_from="2026-10-16T14:02:00+05:30", governs_until=None):
    t0 = "2026-10-16T14:00:00+05:30"
    t2 = "2026-10-16T14:02:00+05:30"
    t3 = "2026-10-16T14:04:00+05:30"
    nodes = {
        "I": node("I", "Incident", created_at=t0),
        "E0": node("E0", "Event", event_type="PROCESS_STARTED", occurred_at=t0),
        "E2": node("E2", "Event", event_type="DEPLOYMENT_STARTED", occurred_at=t2),
        "E3": node("E3", "Event", event_type="PROCESS_CONTINUED", occurred_at=t3),
        "P": node("P", "Policy", name="Policy", status="ACTIVE", valid_from="2026-01-01T00:00:00+05:30", requires_owner_approval=True),
        "M": node("M", "Change", status="DEPLOYED", created_at="2026-10-16T13:50:00+05:30", applied_at=t2),
        "D": node("D", "Deployment", status="IN_PROGRESS", created_at="2026-10-16T13:55:00+05:30", deployed_at=t2),
        "A": node("A", "Person"),
    }
    edges = [
        edge("E0", "ABOUT", "I"),
        edge("E2", "ABOUT", "I"),
        edge("E2", "ABOUT", "D"),
        edge("E2", "ABOUT", "M"),
        edge("E3", "ABOUT", "I"),
        edge("D", "CONTAINS", "M", valid_from=t2),
        edge("P", "GOVERNS", "M", valid_from=governs_from, **({"valid_until": governs_until} if governs_until else {})),
    ]
    if approval_at is not None:
        edges.append(edge("D", "APPROVED_BY", "A", valid_from=approval_at))
    return GraphSnapshot(nodes, edges)


def test_policy_process_window_counts_container_approval_before_governed_change():
    result = PolicyDriftService.analyze_from_snapshot(approval_window_snapshot(), "I", "P")
    assert result["process_start"] == "2026-10-16T14:00:00+05:30"
    assert result["process_end"] == "2026-10-16T14:04:00+05:30"
    assert [x["id"] for x in result["expected_process"]["governed_targets"]] == ["M"]
    assert not any(x["classification"] == "MISSING_APPROVAL" for x in result["drift"])
    assert result["expected_process"]["approval_observations"][0]["approvals"] == ["D-[:APPROVED_BY]->A"]


def test_policy_process_window_without_approval_still_reports_missing_approval():
    result = PolicyDriftService.analyze_from_snapshot(approval_window_snapshot(approval_at=None), "I", "P")
    item = next(x for x in result["drift"] if x["classification"] == "MISSING_APPROVAL")
    assert item["expected_requirement"]["scope"] == ["M"]


def test_policy_approval_after_governed_operation_does_not_retroactively_satisfy():
    result = PolicyDriftService.analyze_from_snapshot(
        approval_window_snapshot(approval_at="2026-10-16T14:03:00+05:30"), "I", "P"
    )
    item = next(x for x in result["drift"] if x["classification"] == "MISSING_APPROVAL")
    assert item["observed_behavior"]["approvals"] == []
    assert item["observed_behavior"]["late_or_inapplicable_approvals"] == ["D-[:APPROVED_BY]->A"]


def test_policy_governs_completely_outside_process_window_is_not_scope():
    result = PolicyDriftService.analyze_from_snapshot(
        approval_window_snapshot(governs_from="2026-10-16T15:00:00+05:30"), "I", "P"
    )
    assert result["expected_process"]["governed_targets"] == []
    assert not any(x["classification"] == "MISSING_APPROVAL" for x in result["drift"])


def test_policy_governs_partial_overlap_is_in_scope():
    result = PolicyDriftService.analyze_from_snapshot(
        approval_window_snapshot(governs_from="2026-10-16T14:03:00+05:30", governs_until="2026-10-16T14:03:30+05:30"),
        "I",
        "P",
    )
    assert [x["id"] for x in result["expected_process"]["governed_targets"]] == ["M"]


def test_policy_historical_as_of_before_approval_cannot_use_future_approval():
    result = PolicyDriftService.analyze_from_snapshot(
        approval_window_snapshot(), "I", "P", as_of="2026-10-16T14:00:30+05:30"
    )
    assert result["process_end"] == "2026-10-16T14:00:00+05:30"
    assert result["expected_process"]["governed_targets"] == []
    assert result["expected_process"]["approval_observations"] == []


def test_policy_historical_as_of_after_approval_and_governed_action_sees_approval():
    result = PolicyDriftService.analyze_from_snapshot(
        approval_window_snapshot(), "I", "P", as_of="2026-10-16T14:02:30+05:30"
    )
    assert [x["id"] for x in result["expected_process"]["governed_targets"]] == ["M"]
    assert result["expected_process"]["approval_observations"][0]["approvals"] == ["D-[:APPROVED_BY]->A"]
    assert not any(x["classification"] == "MISSING_APPROVAL" for x in result["drift"])


def test_policy_permitted_variation_not_violation():
    result = PolicyDriftService.analyze_from_snapshot(policy_snapshot(optional=True), "I", "P")
    item = next(x for x in result["drift"] if x["classification"] == "OPTIONAL_VARIATION")
    assert item["status"] == "PERMITTED_VARIATION"


def test_policy_historical_version_selected_for_old_process():
    snap = policy_snapshot()
    snap.nodes["P"]["name"] = "Compat Policy"; snap.nodes["P"]["valid_from"] = "2026-11-01T00:00:00+05:30"
    snap.nodes["P1"] = node("P1", "Policy", name="Compat Policy", status="SUPERSEDED", valid_from="2026-01-01T00:00:00+05:30", valid_until="2026-11-01T00:00:00+05:30")
    result = PolicyDriftService.analyze_from_snapshot(snap, "I", "P")
    assert result["policy"]["id"] == "P1"
    assert result["policy_selection"] == "HISTORICAL_VERSION_SELECTED"


def test_policy_missing_evidence_has_distinct_classification():
    snap = policy_snapshot(action_status="SUCCEEDED")
    snap.nodes["EVID"] = node("EVID", "Evidence", status="MISSING", created_at="2026-10-16T13:00:00+05:30")
    snap.add_edge("P", "REQUIRES", "EVID", {"required": True})
    result = PolicyDriftService.analyze_from_snapshot(snap, "I", "P")
    assert any(x["classification"] == "MISSING_EVIDENCE" for x in result["drift"])


def test_policy_unauthorized_actor_detected():
    snap = policy_snapshot(action_status="SUCCEEDED")
    snap.nodes["EA"] = node("EA", "Event", event_type="ACTION_SUCCEEDED", occurred_at="2026-10-16T14:02:00+05:30")
    snap.nodes["GOOD"] = node("GOOD", "Person"); snap.nodes["BAD"] = node("BAD", "Person")
    snap.add_edge("EA", "ABOUT", "A"); snap.add_edge("EA", "PERFORMED_BY", "BAD")
    # Replace requirement edge with actor authorization metadata.
    snap.remove_edges(lambda e: e.source == "P" and e.type == "REQUIRES" and e.target == "A")
    snap.add_edge("P", "REQUIRES", "A", {"required": True, "authorized_actor_ids": ["GOOD"]})
    result = PolicyDriftService.analyze_from_snapshot(snap, "I", "P")
    assert any(x["classification"] == "UNAUTHORIZED_ACTOR" for x in result["drift"])


def test_policy_bypassed_control_detected_from_explicit_allowed_false():
    snap = policy_snapshot(action_status="SUCCEEDED")
    snap.nodes["EA"] = node("EA", "Event", event_type="ACTION_SUCCEEDED", occurred_at="2026-10-16T14:02:00+05:30")
    snap.add_edge("EA", "ABOUT", "A")
    snap.add_edge("P", "GOVERNS", "A", {"allowed": False})
    result = PolicyDriftService.analyze_from_snapshot(snap, "I", "P")
    assert any(x["classification"] == "BYPASSED_CONTROL" for x in result["drift"])


def commitment_snapshot(status="ACTIVE", due="2026-10-16T18:00:00+05:30"):
    nodes = {
        "C": node("C", "Commitment", status=status, due_at=due, created_at="2026-10-15T09:00:00+05:30"),
        "P": node("P", "Team"), "R": node("R", "Team"), "S": node("S", "System"),
    }
    edges = [edge("C", "PROMISED_BY", "P", valid_from="2026-10-15T09:00:00+05:30"), edge("C", "OWED_TO", "R", valid_from="2026-10-15T09:00:00+05:30"), edge("C", "COMMITTED_TO", "S", valid_from="2026-10-15T09:00:00+05:30")]
    return GraphSnapshot(nodes, edges)


def test_commitment_open_query():
    result = CommitmentTrackingService.inspect_from_snapshot(commitment_snapshot(), "C", as_of="2026-10-15T10:00:00+05:30")
    assert result["status"] == "OPEN"


def test_commitment_fulfilled_by_evidence():
    snap = commitment_snapshot(); snap.nodes["E"] = node("E", "Evidence", observed_at="2026-10-16T12:00:00+05:30")
    snap.add_edge("C", "SATISFIED_BY", "E", {"valid_from": "2026-10-16T12:00:00+05:30"})
    assert CommitmentTrackingService.inspect_from_snapshot(snap, "C", as_of="2026-10-16T13:00:00+05:30")["status"] == "FULFILLED"


def test_commitment_breached_by_evidence():
    snap = commitment_snapshot(); snap.nodes["E"] = node("E", "Evidence", observed_at="2026-10-16T12:00:00+05:30")
    snap.add_edge("C", "BREACHED_BY", "E", {"valid_from": "2026-10-16T12:00:00+05:30"})
    assert CommitmentTrackingService.inspect_from_snapshot(snap, "C", as_of="2026-10-16T13:00:00+05:30")["status"] == "BREACHED"


def test_commitment_overdue_is_not_automatically_breached():
    result = CommitmentTrackingService.inspect_from_snapshot(commitment_snapshot(), "C", as_of="2026-10-16T20:00:00+05:30")
    assert result["status"] == "OVERDUE"


def test_commitment_provenance_contains_source_paths():
    result = CommitmentTrackingService.inspect_from_snapshot(commitment_snapshot(), "C", as_of="2026-10-16T10:00:00+05:30")
    assert any("PROMISED_BY" in x for x in result["provenance_paths"])


def test_commitment_promisor_reconstructed():
    result = CommitmentTrackingService.inspect_from_snapshot(commitment_snapshot(), "C", as_of="2026-10-16T10:00:00+05:30")
    assert result["promisors"][0]["entity"]["id"] == "P"


def test_commitment_promisee_reconstructed():
    result = CommitmentTrackingService.inspect_from_snapshot(commitment_snapshot(), "C", as_of="2026-10-16T10:00:00+05:30")
    assert result["promisees"][0]["entity"]["id"] == "R"


def test_commitment_downstream_consequence_requires_dependency_edge():
    snap = commitment_snapshot(); snap.nodes["T"] = node("T", "Task", status="OPEN")
    snap.add_edge("T", "DEPENDS_ON", "C")
    result = CommitmentTrackingService.inspect_from_snapshot(snap, "C", as_of="2026-10-16T10:00:00+05:30")
    assert result["downstream_consequences"][0]["entity"]["id"] == "T"
    snap.remove_edges(lambda e: e.type == "DEPENDS_ON")
    assert CommitmentTrackingService.inspect_from_snapshot(snap, "C", as_of="2026-10-16T10:00:00+05:30")["downstream_consequences"] == []


def test_commitment_historical_query_excludes_future_fulfillment():
    snap = commitment_snapshot(); snap.nodes["E"] = node("E", "Evidence", observed_at="2026-10-16T17:00:00+05:30", created_at="2026-10-16T17:00:00+05:30")
    snap.add_edge("C", "SATISFIED_BY", "E", {"valid_from": "2026-10-16T17:00:00+05:30"})
    assert CommitmentTrackingService.inspect_from_snapshot(snap, "C", as_of="2026-10-16T16:00:00+05:30")["status"] != "FULFILLED"


def collision_snapshot():
    nodes = {
        "A": node("A", "Project", goal="automate refund eligibility and execution"),
        "B": node("B", "Project", goal="automate refund eligibility and execution"),
        "C": node("C", "Project", goal="audit disputes manually"),
        "S": node("S", "System"), "D": node("D", "DataSource"), "R": node("R", "Policy"),
        "T1": node("T1", "Team"), "T2": node("T2", "Team"),
    }
    edges = [
        edge("A", "DEPENDS_ON", "S"), edge("B", "DEPENDS_ON", "S"), edge("C", "DEPENDS_ON", "S"),
        edge("A", "DEPENDS_ON", "D"), edge("B", "DEPENDS_ON", "D"),
        edge("A", "REQUIRES", "R"), edge("B", "REQUIRES", "R"),
        edge("T1", "OWNS", "A"), edge("T2", "OWNS", "B"),
    ]
    return GraphSnapshot(nodes, edges)


def collision_service():
    return InitiativeCollisionService(dummy_client())


def test_collision_high_overlap_detected():
    result = collision_service().score_pair_from_snapshot(collision_snapshot(), "A", "B")
    assert result["classification"] == "HIGH_COLLISION" and result["score"] >= 0.7


def test_collision_unrelated_projects_not_generated_without_shared_neighborhood():
    snap = collision_snapshot(); snap.nodes["X"] = node("X", "Project", goal="design hiring portal")
    pairs = InitiativeCollisionService._candidate_pairs(snap, ["A", "X"])
    assert pairs == []


def test_collision_shared_system_alone_not_high_collision():
    result = collision_service().score_pair_from_snapshot(collision_snapshot(), "A", "C")
    assert result["classification"] == "LOW_OVERLAP"


def test_collision_collaboration_changes_classification():
    snap = collision_snapshot(); snap.add_edge("A", "COLLABORATES_WITH", "B")
    result = collision_service().score_pair_from_snapshot(snap, "A", "B")
    assert result["classification"] == "INTENTIONAL_COLLABORATION"


def test_collision_dimensions_are_explainable():
    result = collision_service().score_pair_from_snapshot(collision_snapshot(), "A", "B")
    assert set(result["overlap_dimensions"]) == {"goal_overlap", "system_overlap", "dataset_overlap", "stakeholder_overlap", "requirement_overlap", "dependency_overlap"}
    assert result["explanation_paths"]


def test_collision_removing_shared_graph_relations_lowers_score():
    snap = collision_snapshot(); service = collision_service()
    before = service.score_pair_from_snapshot(snap, "A", "B")["score"]
    snap.remove_edges(lambda e: e.source == "B" and e.target in {"D", "R"})
    after = service.score_pair_from_snapshot(snap, "A", "B")["score"]
    assert after < before


def bus_snapshot():
    nodes = {"S": node("S", "System", criticality="HIGH"), "P": node("P", "Person"), "T": node("T", "Team")}
    edges = [edge("T", "OWNS", "S"), edge("P", "EXPERT_IN", "S")]
    return GraphSnapshot(nodes, edges)


def test_bus_factor_sole_expert_risk_detected():
    result = BusFactorService.resource_coverage_from_snapshot(bus_snapshot(), "S")
    assert result["coverage"]["expertise"]["count"] == 1 and result["bus_factor"] == 1


def test_bus_factor_redundant_expertise_lowers_dimension_risk():
    snap = bus_snapshot(); snap.nodes["P2"] = node("P2", "Person"); snap.add_edge("P2", "EXPERT_IN", "S")
    result = BusFactorService.resource_coverage_from_snapshot(snap, "S")
    assert result["coverage"]["expertise"]["count"] == 2


def test_bus_factor_sole_approval_authority_detected():
    snap = bus_snapshot(); snap.nodes["A"] = node("A", "Action"); snap.add_edge("A", "ABOUT", "S"); snap.add_edge("A", "APPROVED_BY", "P")
    result = BusFactorService.resource_coverage_from_snapshot(snap, "S")
    assert result["coverage"]["approval"]["count"] == 1


def test_bus_factor_sole_operational_responsibility_detected():
    snap = bus_snapshot(); snap.add_edge("P", "RESPONSIBLE_FOR", "S")
    result = BusFactorService.resource_coverage_from_snapshot(snap, "S")
    assert result["coverage"]["responsibility"]["count"] == 1


def test_bus_factor_loss_simulation_does_not_mutate_snapshot():
    snap = bus_snapshot(); original_edges = list(snap.edges)
    result = BusFactorService.simulate_loss_from_snapshot(snap, ["P"])
    assert result["canonical_graph_mutated"] is False and snap.edges == original_edges


def test_bus_factor_loss_simulation_creates_expected_expertise_gap():
    result = BusFactorService.simulate_loss_from_snapshot(bus_snapshot(), ["P"])
    item = next(x for x in result["affected_resources"] if x["resource"]["id"] == "S")
    assert "expertise" in item["lost_dimensions"]


def test_bus_factor_historical_coverage_respects_validity_interval():
    snap = bus_snapshot(); snap.remove_edges(lambda e: e.source == "P" and e.type == "EXPERT_IN")
    snap.add_edge("P", "EXPERT_IN", "S", {"valid_from": "2026-01-01T00:00:00+05:30", "valid_until": "2026-10-01T00:00:00+05:30"})
    before = BusFactorService.resource_coverage_from_snapshot(snap, "S", as_of="2026-09-01T00:00:00+05:30")
    after = BusFactorService.resource_coverage_from_snapshot(snap, "S", as_of="2026-10-02T00:00:00+05:30")
    assert before["coverage"]["expertise"]["count"] == 1 and after["coverage"]["expertise"]["count"] == 0


def line_snapshot(redundant=False):
    nodes = {x: node(x, "Team") for x in ["A", "B", "C"]}
    nodes["P1"] = node("P1", "Project"); nodes["P2"] = node("P2", "Project")
    edges = [edge("A", "OWNS", "P1"), edge("B", "RESPONSIBLE_FOR", "P1"), edge("B", "OWNS", "P2"), edge("C", "RESPONSIBLE_FOR", "P2")]
    if redundant:
        nodes["P3"] = node("P3", "Project"); edges.extend([edge("A", "RESPONSIBLE_FOR", "P3"), edge("C", "OWNS", "P3")])
    return GraphSnapshot(nodes, edges)


def test_network_articulation_point_detected():
    result = OrganizationalNetworkAnalysisService.analyze_projection(line_snapshot(), "collaboration")
    assert [x["node"]["id"] for x in result["articulation_points"]] == ["B"]


def test_network_redundant_path_removes_articulation_risk():
    result = OrganizationalNetworkAnalysisService.analyze_projection(line_snapshot(redundant=True), "collaboration")
    assert result["articulation_points"] == []


def test_network_bridge_edges_detected():
    result = OrganizationalNetworkAnalysisService.analyze_projection(line_snapshot(), "collaboration")
    assert len(result["bridges"]) == 2


def test_network_extra_edge_removes_bridge_classification():
    result = OrganizationalNetworkAnalysisService.analyze_projection(line_snapshot(redundant=True), "collaboration")
    assert result["bridges"] == []


def test_network_centrality_is_deterministic():
    snap = line_snapshot()
    one = OrganizationalNetworkAnalysisService.analyze_projection(snap, "collaboration")["centrality"]
    two = OrganizationalNetworkAnalysisService.analyze_projection(snap, "collaboration")["centrality"]
    assert one == two and one[0]["node"]["id"] == "B"


def test_network_high_centrality_alone_is_not_overload():
    result = OrganizationalNetworkAnalysisService.analyze_projection(line_snapshot(), "collaboration")
    assert result["overloaded_nodes"] == []


def test_network_overload_requires_load_evidence_too():
    snap = line_snapshot()
    for i in range(3):
        cid = f"COM{i}"; snap.nodes[cid] = node(cid, "Commitment"); snap.add_edge(cid, "PROMISED_BY", "B")
    result = OrganizationalNetworkAnalysisService.analyze_projection(snap, "collaboration")
    assert result["overloaded_nodes"][0]["node"]["id"] == "B"


def test_network_single_path_risk_matches_bridge_edges():
    result = OrganizationalNetworkAnalysisService.analyze_projection(line_snapshot(), "collaboration")
    assert result["single_path_risks"] == result["bridges"]


def test_network_projection_excludes_irrelevant_relationship_types():
    snap = line_snapshot(); snap.nodes["E"] = node("E", "Evidence"); snap.add_edge("E", "SUPPORTS", "A")
    result = OrganizationalNetworkAnalysisService.analyze_projection(snap, "collaboration")
    assert "E" not in {x["node"]["id"] for x in result["centrality"]}
