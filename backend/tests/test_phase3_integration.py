from __future__ import annotations

import pytest

from backend.app.graph.mutations import delete_relationship, upsert_node, upsert_relationship
from backend.app.services.authority_resolution_service import AuthorityResolutionService
from backend.app.services.claim_memory_service import ClaimMemoryService
from backend.app.services.graph_service import GraphService
from backend.app.services.ownership_gap_service import OwnershipGapService
from backend.app.services.routing_service import ResponsibilityRoutingService

pytestmark = pytest.mark.integration


def test_phase3_conflict_memory_preserves_claims_contradiction_and_separate_evidence(integration_client):
    memory = ClaimMemoryService(integration_client)
    c1 = memory.get_claim("C-001")
    c2 = memory.get_claim("C-002")
    assert c1["claim"]["id"] == "C-001"
    assert c2["claim"]["id"] == "C-002"
    assert c1["claim"]["statement"] != c2["claim"]["statement"]
    assert c1["memory_state"] == "UNRESOLVED"
    assert c2["memory_state"] == "UNRESOLVED"

    conflict_set = memory.get_conflict_set("INC-001")
    pairs = {(item["claim_a_id"], item["claim_b_id"]) for item in conflict_set["conflicts"]}
    assert ("C-001", "C-002") in pairs

    c1_evidence = {item["evidence"]["id"] for item in c1["evidence"]["supporting"]}
    c2_evidence = {item["evidence"]["id"] for item in c2["evidence"]["supporting"]}
    assert c1_evidence == {"E-004"}
    assert {"E-001", "E-002", "E-003", "E-006"} <= c2_evidence
    assert "E-004" not in c2_evidence


def test_phase3_authority_resolution_is_explainable_for_canonical_conflict(integration_client):
    result = AuthorityResolutionService(integration_client).resolve_subject_conflicts(
        "INC-001", as_of="2026-10-16T14:20:00+05:30"
    )
    assert result["status"] == "RESOLVED"
    assert result["selected_claim_id"] == "C-002"
    assert len(result["candidates"]) == 2
    selected = next(item for item in result["candidates"] if item["claim"]["id"] == "C-002")
    assert selected["score"]["components"]["supporting_evidence"] > 0
    assert selected["graph_paths"]["evidence"]
    assert selected["evidence_factors"]["authoritative_sources"]
    assert result["rule_set"]["forced_winner"] is False


def test_phase3_authority_resolution_can_return_unresolved_for_equal_support(integration_client):
    upsert_node(integration_client, "Incident", "INC-TIE", {
        "title": "Tie", "status": "OPEN", "severity": "SEV-3", "created_at": "2026-10-16T15:00:00+05:30"
    })
    for claim_id, created_at in (("C-TIE-A", "2026-10-16T15:01:00+05:30"), ("C-TIE-B", "2026-10-16T15:02:00+05:30")):
        upsert_node(integration_client, "Claim", claim_id, {
            "statement": claim_id, "status": "OPEN", "confidence": 0.8, "created_at": created_at, "assertion_kind": "human"
        })
        upsert_relationship(integration_client, claim_id, "ABOUT", "INC-TIE", {"valid_from": created_at, "confidence": 1.0})
    upsert_relationship(integration_client, "C-TIE-A", "CONTRADICTS", "C-TIE-B", {
        "valid_from": "2026-10-16T15:02:00+05:30", "confidence": 1.0
    })
    for evidence_id, claim_id in (("E-TIE-A", "C-TIE-A"), ("E-TIE-B", "C-TIE-B")):
        upsert_node(integration_client, "Evidence", evidence_id, {
            "name": evidence_id, "evidence_type": "log", "observed_at": "2026-10-16T15:03:00+05:30",
            "created_at": "2026-10-16T15:03:00+05:30", "confidence": 1.0,
        })
        upsert_relationship(integration_client, evidence_id, "SUPPORTS", claim_id, {
            "valid_from": "2026-10-16T15:03:00+05:30", "confidence": 1.0
        })
        upsert_relationship(integration_client, evidence_id, "DERIVED_FROM", "DS-LOG", {
            "valid_from": "2026-10-16T15:03:00+05:30", "confidence": 1.0, "source_ref_id": "DS-LOG"
        })
        upsert_relationship(integration_client, evidence_id, "ABOUT", "INC-TIE", {
            "valid_from": "2026-10-16T15:03:00+05:30", "confidence": 1.0
        })
    result = AuthorityResolutionService(integration_client).resolve_subject_conflicts(
        "INC-TIE", as_of="2026-10-16T15:10:00+05:30"
    )
    assert result["status"] == "UNRESOLVED"
    assert result["selected_claim_id"] is None
    assert "margin" in result["reason"]


def test_phase3_clear_authority_winner_and_graph_necessity(integration_client):
    upsert_node(integration_client, "System", "SYS-AUTH-TEST", {"name": "Authority Test", "status": "ACTIVE"})
    upsert_node(integration_client, "Person", "PERSON-AUTH", {"name": "Authority Person", "status": "ACTIVE"})
    upsert_node(integration_client, "Person", "PERSON-NONAUTH", {"name": "Non Authority Person", "status": "ACTIVE"})
    for claim_id, actor_id, created_at in (
        ("C-AUTH-A", "PERSON-AUTH", "2026-10-16T16:00:00+05:30"),
        ("C-AUTH-B", "PERSON-NONAUTH", "2026-10-16T16:01:00+05:30"),
    ):
        upsert_node(integration_client, "Claim", claim_id, {
            "statement": claim_id, "status": "OPEN", "confidence": 0.8, "created_at": created_at, "assertion_kind": "human"
        })
        upsert_relationship(integration_client, claim_id, "ABOUT", "SYS-AUTH-TEST", {"valid_from": created_at, "confidence": 1.0})
        upsert_relationship(integration_client, claim_id, "ASSERTED_BY", actor_id, {"valid_from": created_at, "confidence": 1.0})
    upsert_relationship(integration_client, "C-AUTH-A", "CONTRADICTS", "C-AUTH-B", {
        "valid_from": "2026-10-16T16:01:00+05:30", "confidence": 1.0
    })
    for evidence_id, claim_id in (("E-AUTH-A", "C-AUTH-A"), ("E-AUTH-B", "C-AUTH-B")):
        upsert_node(integration_client, "Evidence", evidence_id, {
            "name": evidence_id, "evidence_type": "log", "observed_at": "2026-10-16T16:02:00+05:30",
            "created_at": "2026-10-16T16:02:00+05:30", "confidence": 1.0,
        })
        upsert_relationship(integration_client, evidence_id, "SUPPORTS", claim_id, {
            "valid_from": "2026-10-16T16:02:00+05:30", "confidence": 1.0
        })
        upsert_relationship(integration_client, evidence_id, "DERIVED_FROM", "DS-LOG", {
            "valid_from": "2026-10-16T16:02:00+05:30", "confidence": 1.0, "source_ref_id": "DS-LOG"
        })
        upsert_relationship(integration_client, evidence_id, "ABOUT", "SYS-AUTH-TEST", {
            "valid_from": "2026-10-16T16:02:00+05:30", "confidence": 1.0
        })
    authority_props = {"valid_from": "2026-10-16T15:00:00+05:30", "confidence": 1.0}
    upsert_relationship(integration_client, "PERSON-AUTH", "RESPONSIBLE_FOR", "SYS-AUTH-TEST", authority_props)

    service = AuthorityResolutionService(integration_client)
    resolved = service.resolve_subject_conflicts("SYS-AUTH-TEST", as_of="2026-10-16T16:10:00+05:30")
    assert resolved["status"] == "RESOLVED"
    assert resolved["selected_claim_id"] == "C-AUTH-A"

    try:
        assert delete_relationship(integration_client, "PERSON-AUTH", "RESPONSIBLE_FOR", "SYS-AUTH-TEST") >= 1
        degraded = service.resolve_subject_conflicts("SYS-AUTH-TEST", as_of="2026-10-16T16:10:00+05:30")
        assert degraded["status"] == "UNRESOLVED"
    finally:
        upsert_relationship(integration_client, "PERSON-AUTH", "RESPONSIBLE_FOR", "SYS-AUTH-TEST", authority_props)


def test_phase3_current_ownership_respects_time_and_historical_owner_is_reconstructable(integration_client):
    routing = ResponsibilityRoutingService(integration_client)
    current = routing.find_owner("SYS-LEGACY-PROMO", as_of="2026-10-16T17:00:00+05:30")
    assert current["owners"] == []
    historical = routing.find_owner("SYS-LEGACY-PROMO", as_of="2026-06-01T00:00:00+05:30")
    assert [item["actor"]["id"] for item in historical["owners"]] == ["TEAM-GROWTH"]


def test_phase3_expertise_formal_responsibility_and_ownership_remain_distinct(integration_client):
    routing = ResponsibilityRoutingService(integration_client)
    db_owner = routing.find_owner("SYS-PRICING-DB", as_of="2026-10-16T17:00:00+05:30")
    assert db_owner["owners"][0]["actor"]["id"] == "TEAM-PRICING"

    db_responsibility = routing.find_responsible_actor("SYS-PRICING-DB", as_of="2026-10-16T17:00:00+05:30")
    assert "PERSON-RIYA" not in {item["actor"]["id"] for item in db_responsibility["responsible"]}

    experts = routing.find_experts("SYS-PRICING-DB", as_of="2026-10-16T17:00:00+05:30")
    assert experts["current_experts"][0]["actor"]["id"] == "PERSON-RIYA"
    assert experts["current_experts"][0]["role"] == "DOMAIN_EXPERT"

    api_responsibility = routing.find_responsible_actor("SYS-PRICING-API", as_of="2026-10-16T17:00:00+05:30")
    assert "PERSON-ARJUN" in {item["actor"]["id"] for item in api_responsibility["responsible"]}


def test_phase3_responder_ranking_exposes_escalation_paths(integration_client):
    routing = ResponsibilityRoutingService(integration_client)
    result = routing.rank_candidate_responders("SYS-PRICING-DB", as_of="2026-10-16T17:00:00+05:30")
    ids = [item["actor"]["id"] for item in result["ranked_candidates"]]
    assert "TEAM-PRICING" in ids
    assert "PERSON-RIYA" in ids
    riya = next(item for item in result["ranked_candidates"] if item["actor"]["id"] == "PERSON-RIYA")
    assert "DOMAIN_EXPERT" in riya["roles"]
    assert riya["paths"]


def test_phase3_legacy_promo_is_orphaned_with_historical_owner(integration_client):
    service = OwnershipGapService(integration_client)
    result = service.inspect_resource("SYS-LEGACY-PROMO", as_of="2026-10-16T17:00:00+05:30")
    assert result["orphaned"] is True
    assert "OWNER_RELATIONSHIP_EXPIRED" in result["reasons"]
    assert result["historical_owner"]["actor"]["id"] == "TEAM-GROWTH"
    all_orphans = service.detect_orphaned_resources(as_of="2026-10-16T17:00:00+05:30")
    assert "SYS-LEGACY-PROMO" in {item["resource"]["id"] for item in all_orphans["resources"]}


def test_phase3_ambiguous_owners_and_orphan_dependency_risk(integration_client):
    upsert_node(integration_client, "System", "SYS-AMB-OWNER", {"name": "Ambiguous Owner", "status": "ACTIVE"})
    upsert_node(integration_client, "Team", "TEAM-AMB-A", {"name": "A", "status": "ACTIVE"})
    upsert_node(integration_client, "Team", "TEAM-AMB-B", {"name": "B", "status": "ACTIVE"})
    props = {"valid_from": "2026-10-16T00:00:00+05:30", "confidence": 1.0, "authoritative": True}
    upsert_relationship(integration_client, "TEAM-AMB-A", "OWNS", "SYS-AMB-OWNER", props)
    upsert_relationship(integration_client, "TEAM-AMB-B", "OWNS", "SYS-AMB-OWNER", props)
    finding = OwnershipGapService(integration_client).inspect_resource("SYS-AMB-OWNER", as_of="2026-10-16T17:00:00+05:30")
    assert finding["ambiguous"] is True
    assert "AMBIGUOUS_SIMULTANEOUS_OWNERS" in finding["reasons"]

    upsert_node(integration_client, "System", "SYS-ORPHAN-CRITICAL", {"name": "Critical Orphan", "status": "ACTIVE"})
    upsert_node(integration_client, "System", "SYS-DEPENDENT-CRITICAL", {"name": "Dependent", "status": "ACTIVE"})
    upsert_relationship(integration_client, "SYS-DEPENDENT-CRITICAL", "DEPENDS_ON", "SYS-ORPHAN-CRITICAL", {
        "valid_from": "2026-10-16T00:00:00+05:30", "confidence": 1.0, "criticality": "HIGH"
    })
    orphan = OwnershipGapService(integration_client).inspect_resource("SYS-ORPHAN-CRITICAL", as_of="2026-10-16T17:00:00+05:30")
    assert orphan["orphaned"] is True
    assert orphan["dependent_systems"][0]["system"]["id"] == "SYS-DEPENDENT-CRITICAL"
    assert orphan["severity"] == "CRITICAL"


def test_phase3_graph_necessity_conflict_edge(integration_client):
    memory = ClaimMemoryService(integration_client)
    assert memory.get_conflict_set("INC-001")["conflict_count"] >= 1
    props = {"valid_from": "2026-10-16T14:11:00+05:30", "confidence": 1.0}
    try:
        assert delete_relationship(integration_client, "C-001", "CONTRADICTS", "C-002") >= 1
        assert memory.get_conflict_set("INC-001")["conflict_count"] == 0
    finally:
        upsert_relationship(integration_client, "C-001", "CONTRADICTS", "C-002", props)


def test_phase3_graph_necessity_routing_expertise_edge(integration_client):
    routing = ResponsibilityRoutingService(integration_client)
    before = {item["actor"]["id"] for item in routing.find_experts("SYS-PRICING-DB", as_of="2026-10-16T17:00:00+05:30")["current_experts"]}
    assert "PERSON-RIYA" in before
    props = {"valid_from": "2025-01-01T00:00:00+05:30", "confidence": 0.98}
    try:
        assert delete_relationship(integration_client, "PERSON-RIYA", "EXPERT_IN", "SYS-PRICING-DB") >= 1
        after = {item["actor"]["id"] for item in routing.find_experts("SYS-PRICING-DB", as_of="2026-10-16T17:00:00+05:30")["current_experts"]}
        assert "PERSON-RIYA" not in after
    finally:
        upsert_relationship(integration_client, "PERSON-RIYA", "EXPERT_IN", "SYS-PRICING-DB", props)


def test_phase3_graph_necessity_orphan_history_edge(integration_client):
    service = OwnershipGapService(integration_client)
    before = service.inspect_resource("SYS-LEGACY-PROMO", as_of="2026-10-16T17:00:00+05:30")
    assert before["historical_owner"]["actor"]["id"] == "TEAM-GROWTH"
    props = {
        "valid_from": "2024-02-01T00:00:00+05:30", "valid_until": "2026-07-01T00:00:00+05:30",
        "confidence": 1.0, "source_ref_id": "DS-CHAT", "authoritative": True,
    }
    try:
        assert delete_relationship(integration_client, "TEAM-GROWTH", "OWNS", "SYS-LEGACY-PROMO") >= 1
        degraded = service.inspect_resource("SYS-LEGACY-PROMO", as_of="2026-10-16T17:00:00+05:30")
        assert degraded["orphaned"] is True
        assert degraded["historical_owner"] is None
        assert "OWNER_RELATIONSHIP_EXPIRED" not in degraded["reasons"]
    finally:
        upsert_relationship(integration_client, "TEAM-GROWTH", "OWNS", "SYS-LEGACY-PROMO", props)


def test_phase3_existing_canonical_incident_context_is_not_broken(integration_client):
    context = GraphService(integration_client).get_incident_context("INC-001")
    assert context["incident"]["id"] == "INC-001"
    assert {row[0]["id"] for row in context["claims"]} >= {"C-001", "C-002"}
    assert context["conflicts"]
