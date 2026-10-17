from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.services.phase4_graph import GraphEdge, GraphSnapshot
from backend.app.services.memory_promotion_service import MemoryPromotionService
from backend.app.services.knowledge_invalidation_service import KnowledgeInvalidationService
from backend.app.services.phase7_utils import active_evidence, evidence_for_artifact


def node(node_id: str, label: str, **props):
    return {"id": node_id, "tenant_id": "northstar", "_labels": ["Entity", label], **props}


def edge(source: str, rel: str, target: str, **props):
    return GraphEdge(source, rel, target, props)


def dummy_client():
    return SimpleNamespace(settings=SimpleNamespace(tenant_id="northstar"))


def patch_snapshot(monkeypatch, snapshot):
    monkeypatch.setattr("backend.app.services.memory_promotion_service.GraphSnapshot.load", lambda _client: snapshot)
    monkeypatch.setattr("backend.app.services.knowledge_invalidation_service.GraphSnapshot.load", lambda _client: snapshot)


def promotable_snapshot(status="VERIFIED", confidence=0.9, with_validator=True, with_evidence=True, self_loop=False):
    nodes = {
        "F": node("F", "Finding", status=status, confidence=confidence, statement="Schema incompatibility caused outage"),
        "V": node("V", "Agent", agent_type="VERIFIER", status="ACTIVE"),
        "E": node("E", "Evidence", status="VALIDATED", confidence=0.95),
        "I": node("I", "Incident", status="OPEN"),
    }
    edges = [edge("F", "ABOUT", "I")]
    if with_validator:
        edges.append(edge("F", "VALIDATED_BY", "V"))
    if with_evidence:
        edges.append(edge("F", "DERIVED_FROM", "E"))
    if self_loop:
        edges.append(edge("F", "PRODUCED", "E"))
    return GraphSnapshot(nodes, edges)


def test_promotion_accepts_verified_finding_with_independent_evidence(monkeypatch):
    snap = promotable_snapshot()
    patch_snapshot(monkeypatch, snap)
    result = MemoryPromotionService(dummy_client()).evaluate_artifact("F")
    assert result["status"] == "PROMOTED"
    assert [e["id"] for e in result["independent_evidence"]] == ["E"]


def test_unverified_finding_cannot_promote(monkeypatch):
    snap = promotable_snapshot(status="OPEN")
    patch_snapshot(monkeypatch, snap)
    result = MemoryPromotionService(dummy_client()).evaluate_artifact("F")
    assert result["status"] == "NOT_READY"
    assert "ARTIFACT_NOT_VALIDATED" in result["reasons"]


def test_low_confidence_finding_cannot_promote(monkeypatch):
    snap = promotable_snapshot(confidence=0.2)
    patch_snapshot(monkeypatch, snap)
    assert "CONFIDENCE_BELOW_THRESHOLD" in MemoryPromotionService(dummy_client()).evaluate_artifact("F")["reasons"]


def test_promotion_requires_validator(monkeypatch):
    snap = promotable_snapshot(with_validator=False)
    patch_snapshot(monkeypatch, snap)
    assert "MISSING_VALIDATOR" in MemoryPromotionService(dummy_client()).evaluate_artifact("F")["reasons"]


def test_promotion_requires_evidence(monkeypatch):
    snap = promotable_snapshot(with_evidence=False)
    patch_snapshot(monkeypatch, snap)
    assert "MISSING_EVIDENCE" in MemoryPromotionService(dummy_client()).evaluate_artifact("F")["reasons"]


def test_self_reinforcing_evidence_does_not_validate_promotion(monkeypatch):
    snap = promotable_snapshot(self_loop=True)
    patch_snapshot(monkeypatch, snap)
    result = MemoryPromotionService(dummy_client()).evaluate_artifact("F")
    assert "NO_INDEPENDENT_GROUNDING" in result["reasons"]


def test_unresolved_contradiction_blocks_promotion(monkeypatch):
    snap = promotable_snapshot()
    snap.nodes["F2"] = node("F2", "Finding", status="VERIFIED")
    snap.add_edge("F", "CONTRADICTS", "F2")
    patch_snapshot(monkeypatch, snap)
    assert "UNRESOLVED_CRITICAL_CONTRADICTION" in MemoryPromotionService(dummy_client()).evaluate_artifact("F")["reasons"]


def test_evidence_for_artifact_uses_graph_lineage():
    snap = promotable_snapshot()
    assert [x["id"] for x in evidence_for_artifact(snap, "F")] == ["E"]


def test_active_evidence_excludes_invalidated():
    snap = GraphSnapshot(
        {"C": node("C", "Claim"), "E1": node("E1", "Evidence", status="VALIDATED"), "E2": node("E2", "Evidence", status="INVALIDATED")},
        [edge("E1", "SUPPORTS", "C"), edge("E2", "SUPPORTS", "C")],
    )
    assert [x["id"] for x in active_evidence(snap, "C")] == ["E1"]


def invalidation_snapshot(include_decision=True, include_task=True, include_plan=True):
    nodes = {
        "E": node("E", "Evidence", status="VALIDATED"),
        "C": node("C", "Claim", status="VALIDATED"),
        "U": node("U", "Claim", status="VALIDATED"),
        "D": node("D", "Decision", status="ACTIVE"),
        "T": node("T", "Task", status="IN_PROGRESS"),
        "P": node("P", "Plan", status="READY"),
    }
    edges = [edge("E", "SUPPORTS", "C")]
    if include_decision:
        edges.append(edge("D", "BASED_ON", "C"))
    if include_task:
        edges.append(edge("T", "ADDRESSES", "C"))
    if include_plan:
        edges.append(edge("P", "PLAN_HAS_TASK", "T"))
    return GraphSnapshot(nodes, edges)


def test_invalidation_impact_follows_only_defined_dependency_edges():
    result = KnowledgeInvalidationService.impact_from_snapshot(invalidation_snapshot(), "E")
    ids = {x["entity"]["id"] for x in result["affected"]}
    assert {"C", "D", "T", "P"}.issubset(ids)
    assert "U" not in ids


def test_removing_support_edge_stops_stale_claim_propagation():
    snap = invalidation_snapshot()
    snap.remove_edges(lambda e: e.source == "E" and e.type == "SUPPORTS")
    assert KnowledgeInvalidationService.impact_from_snapshot(snap, "E")["affected"] == []


def test_removing_based_on_edge_stops_decision_impact():
    snap = invalidation_snapshot()
    snap.remove_edges(lambda e: e.type == "BASED_ON")
    ids = {x["entity"]["id"] for x in KnowledgeInvalidationService.impact_from_snapshot(snap, "E")["affected"]}
    assert "C" in ids
    assert "D" not in ids


def test_removing_task_derivation_stops_task_impact():
    snap = invalidation_snapshot()
    snap.remove_edges(lambda e: e.type == "ADDRESSES")
    ids = {x["entity"]["id"] for x in KnowledgeInvalidationService.impact_from_snapshot(snap, "E")["affected"]}
    assert "T" not in ids and "P" not in ids


def test_plan_impact_requires_plan_has_task_edge():
    snap = invalidation_snapshot(include_plan=False)
    ids = {x["entity"]["id"] for x in KnowledgeInvalidationService.impact_from_snapshot(snap, "E")["affected"]}
    assert "T" in ids and "P" not in ids


def test_policy_governance_change_impacts_action_only():
    snap = GraphSnapshot(
        {"POL": node("POL", "Policy"), "ACT": node("ACT", "Action"), "SYS": node("SYS", "System")},
        [edge("POL", "GOVERNS", "ACT"), edge("POL", "ABOUT", "SYS")],
    )
    result = KnowledgeInvalidationService.impact_from_snapshot(snap, "POL")
    assert [x["entity"]["id"] for x in result["affected"]] == ["ACT"]


def test_candidate_assignment_change_can_mark_task_affected():
    snap = GraphSnapshot(
        {"TEAM": node("TEAM", "Team"), "T": node("T", "Task"), "P": node("P", "Plan")},
        [edge("TEAM", "CANDIDATE_FOR", "T"), edge("P", "PLAN_HAS_TASK", "T")],
    )
    ids = {x["entity"]["id"] for x in KnowledgeInvalidationService.impact_from_snapshot(snap, "TEAM")["affected"]}
    assert ids == {"T", "P"}


def test_precedent_eligibility_rejects_open_incident(monkeypatch):
    snap = GraphSnapshot({"I": node("I", "Incident", status="OPEN")}, [])
    patch_snapshot(monkeypatch, snap)
    result = MemoryPromotionService(dummy_client()).precedent_eligibility("I")
    assert result["status"] == "NOT_ELIGIBLE"
    assert "INCIDENT_NOT_CLOSED" in result["reasons"]


def test_precedent_requires_root_cause_outcome_and_decision(monkeypatch):
    snap = GraphSnapshot({"I": node("I", "Incident", status="CLOSED")}, [])
    patch_snapshot(monkeypatch, snap)
    reasons = MemoryPromotionService(dummy_client()).precedent_eligibility("I")["reasons"]
    assert {"NO_VALIDATED_ROOT_CAUSE", "NO_OBSERVED_OUTCOME", "NO_DECISION_GENEALOGY"}.issubset(set(reasons))


def test_precedent_eligible_when_learning_structure_is_complete(monkeypatch):
    nodes = {
        "I": node("I", "Incident", status="CLOSED"), "C": node("C", "Claim", status="VALIDATED"),
        "D": node("D", "Decision", status="ACTIVE"), "T": node("T", "Task", status="COMPLETED"),
        "A": node("A", "Action", status="SUCCEEDED"), "O": node("O", "Outcome", status="OBSERVED"),
    }
    edges = [edge("I", "ROOT_CAUSE", "C"), edge("D", "BASED_ON", "C"), edge("T", "ABOUT", "I"), edge("T", "PROPOSED_ACTION", "A"), edge("A", "HAS_OUTCOME", "O")]
    snap = GraphSnapshot(nodes, edges)
    patch_snapshot(monkeypatch, snap)
    assert MemoryPromotionService(dummy_client()).precedent_eligibility("I")["status"] == "PRECEDENT_ELIGIBLE"


def test_promotion_rejects_unsupported_artifact_type(monkeypatch):
    snap = GraphSnapshot({"X": node("X", "Task", status="COMPLETED")}, [])
    patch_snapshot(monkeypatch, snap)
    result = MemoryPromotionService(dummy_client()).evaluate_artifact("X")
    assert result["status"] == "REJECTED"


def test_invalidated_evidence_cannot_ground_promotion(monkeypatch):
    snap = promotable_snapshot()
    snap.nodes["E"]["status"] = "INVALIDATED"
    patch_snapshot(monkeypatch, snap)
    result = MemoryPromotionService(dummy_client()).evaluate_artifact("F")
    assert "NO_INDEPENDENT_GROUNDING" in result["reasons"]


def test_open_blocker_blocks_promotion(monkeypatch):
    snap = promotable_snapshot()
    snap.nodes["B"] = node("B", "Blocker", status="OPEN")
    snap.add_edge("F", "BLOCKED_BY", "B")
    patch_snapshot(monkeypatch, snap)
    assert "UNRESOLVED_BLOCKER" in MemoryPromotionService(dummy_client()).evaluate_artifact("F")["reasons"]


def test_resolved_blocker_does_not_block_promotion(monkeypatch):
    snap = promotable_snapshot()
    snap.nodes["B"] = node("B", "Blocker", status="RESOLVED")
    snap.add_edge("F", "BLOCKED_BY", "B")
    patch_snapshot(monkeypatch, snap)
    assert MemoryPromotionService(dummy_client()).evaluate_artifact("F")["status"] == "PROMOTED"


def test_random_neighbor_does_not_propagate_staleness():
    snap = GraphSnapshot(
        {"E": node("E", "Evidence"), "C": node("C", "Claim"), "SYS": node("SYS", "System")},
        [edge("E", "SUPPORTS", "C"), edge("C", "ABOUT", "SYS")],
    )
    ids = {x["entity"]["id"] for x in KnowledgeInvalidationService.impact_from_snapshot(snap, "E")["affected"]}
    assert ids == {"C"}


def test_invalidation_depth_is_bounded():
    snap = invalidation_snapshot()
    result = KnowledgeInvalidationService.impact_from_snapshot(snap, "E", max_depth=1)
    assert {x["entity"]["id"] for x in result["affected"]} == {"C"}


def test_retracted_evidence_is_not_active_support():
    snap = GraphSnapshot({"C": node("C", "Claim"), "E": node("E", "Evidence", status="RETRACTED")}, [edge("E", "SUPPORTS", "C")])
    assert active_evidence(snap, "C") == []


def test_hypothesis_uses_same_guarded_promotion_rules(monkeypatch):
    snap = promotable_snapshot()
    snap.nodes["F"]["_labels"] = ["Entity", "Hypothesis"]
    patch_snapshot(monkeypatch, snap)
    assert MemoryPromotionService(dummy_client()).evaluate_artifact("F")["status"] == "PROMOTED"
