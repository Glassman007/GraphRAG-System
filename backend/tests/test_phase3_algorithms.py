from __future__ import annotations

from backend.app.main import app
from backend.app.services.authority_resolution_service import AuthorityResolutionService
from backend.app.services.claim_memory_service import ClaimMemoryService
from backend.app.services.ownership_gap_service import OwnershipGapService


def _candidate(
    claim_id: str,
    *,
    state: str = "ACTIVE",
    support: float = 0.8,
    refute: float = 0.0,
    responsibility: bool = False,
    owner: bool = False,
    expert: float = 0.0,
    approval: bool = False,
    source_ratio: float = 0.0,
    policy: bool = False,
    provenance: float = 1.0,
    recency: float = 0.0,
    stale: bool = False,
):
    return {
        "claim": {"id": claim_id},
        "memory_state": state,
        "authority_factors": {
            "actor_attributed": True,
            "direct_responsibility": responsibility,
            "owner_scope": owner,
            "expertise_confidence": expert,
            "explicit_approval": approval,
            "authoritative_source_ratio": source_ratio,
            "authoritative_policy_scope": policy,
        },
        "evidence_factors": {
            "support_strength": support,
            "refute_strength": refute,
            "provenance_ratio": provenance,
        },
        "temporal_factors": {"recency_rank": recency, "stale": stale},
        "graph_paths": {},
    }


def test_claim_memory_state_distinguishes_required_states():
    assert ClaimMemoryService.normalize_state("OPEN", superseded=False, has_conflict=False) == "ACTIVE"
    assert ClaimMemoryService.normalize_state("OPEN", superseded=False, has_conflict=True) == "UNRESOLVED"
    assert ClaimMemoryService.normalize_state("OPEN", superseded=True, has_conflict=True) == "SUPERSEDED"
    assert ClaimMemoryService.normalize_state("REJECTED", superseded=False, has_conflict=True) == "REJECTED"


def test_authority_clear_winner():
    result = AuthorityResolutionService.resolve_candidates([
        _candidate("C-A", responsibility=True, owner=True, source_ratio=1.0, support=0.85),
        _candidate("C-B", support=0.45, recency=1.0),
    ])
    assert result["status"] == "RESOLVED"
    assert result["selected_claim_id"] == "C-A"
    assert result["candidates"][0]["score"]["components"]["direct_responsibility"] > 0


def test_newer_non_authoritative_claim_does_not_win_on_recency_alone():
    result = AuthorityResolutionService.resolve_candidates([
        _candidate("C-AUTH", responsibility=True, owner=True, source_ratio=1.0, support=0.75, recency=0.0),
        _candidate("C-NEW", support=0.75, recency=1.0),
    ])
    assert result["status"] == "RESOLVED"
    assert result["selected_claim_id"] == "C-AUTH"


def test_authoritative_but_stale_claim_is_ineligible():
    result = AuthorityResolutionService.resolve_candidates([
        _candidate(
            "C-STALE", state="SUPERSEDED", responsibility=True, owner=True,
            source_ratio=1.0, support=0.95, stale=True,
        ),
        _candidate("C-CURRENT", responsibility=True, support=0.75, recency=1.0),
    ])
    assert result["status"] == "RESOLVED"
    assert result["selected_claim_id"] == "C-CURRENT"
    stale = next(item for item in result["candidates"] if item["claim"]["id"] == "C-STALE")
    assert stale["score"]["eligible"] is False


def test_equally_supported_conflicting_claims_remain_unresolved():
    result = AuthorityResolutionService.resolve_candidates([
        _candidate("C-A", responsibility=True, source_ratio=1.0, support=0.9, recency=0.0),
        _candidate("C-B", responsibility=True, source_ratio=1.0, support=0.9, recency=1.0),
    ])
    assert result["status"] == "UNRESOLVED"
    assert result["selected_claim_id"] is None
    assert "margin" in result["reason"]


def test_insufficient_evidence_remains_unresolved_even_with_authority():
    result = AuthorityResolutionService.resolve_candidates([
        _candidate("C-A", responsibility=True, owner=True, support=0.0),
        _candidate("C-B", support=0.0, recency=1.0),
    ])
    assert result["status"] == "UNRESOLVED"
    assert result["selected_claim_id"] is None
    assert "support strength" in result["reason"]


def test_orphan_risk_escalates_when_active_dependents_exist():
    resource = {"id": "SYS-X", "status": "ACTIVE"}
    severity, basis = OwnershipGapService._severity(
        resource,
        [{"system": {"id": "SYS-Y"}, "criticality": "HIGH"}],
        ["NO_CURRENT_OWNER"],
    )
    assert severity == "CRITICAL"
    assert any("dependent" in item for item in basis)


def test_phase3_api_routes_are_registered_without_raw_cypher_endpoint():
    paths = {route.path for route in app.routes}
    required = {
        "/claims/{claim_id}",
        "/incidents/{incident_id}/conflicts",
        "/subjects/{entity_id}/claims",
        "/conflicts/{entity_id}/resolve",
        "/entities/{entity_id}/owner",
        "/entities/{entity_id}/experts",
        "/entities/{entity_id}/responsibility",
        "/entities/{entity_id}/responders",
        "/organization/orphaned-resources",
    }
    assert required <= paths
    assert not any("cypher" in path.lower() for path in paths)
