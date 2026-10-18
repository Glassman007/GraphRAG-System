from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.graph.schema import apply_schema
from backend.app.graph.mutations import upsert_node, upsert_relationship, delete_relationship
from backend.app.services.graph_service import GraphService
from backend.app.services.provenance_service import ProvenanceService
from backend.app.services.temporal_service import TemporalService
from scripts.seed_lib import seed_all

pytestmark = pytest.mark.integration


def _count(client, label=None):
    if label:
        result = client.read(f"MATCH (n:Entity:{label} {{tenant_id:$tenant_id}}) RETURN count(n)", {"tenant_id": client.settings.tenant_id})
    else:
        result = client.read("MATCH (n:Entity {tenant_id:$tenant_id}) RETURN count(n)", {"tenant_id": client.settings.tenant_id})
    return int(result.result_set[0][0])


def test_falkordb_connectivity(integration_client):
    assert integration_client.health_check()["ok"] is True


def test_graph_health_check(integration_client):
    health = integration_client.health_check()
    assert health["graph"].startswith("company_brain_test_")


def test_schema_and_index_creation(integration_client):
    apply_schema(integration_client)
    indices = integration_client.graph.list_indices().result_set
    assert indices is not None


def test_deterministic_reseed_is_idempotent(integration_client):
    before = _count(integration_client)
    seed_all(integration_client)
    after = _count(integration_client)
    assert before == after


def test_node_creation(integration_client):
    upsert_node(integration_client, "System", "SYS-TEST-NODE", {"name": "Test Node", "status": "ACTIVE"})
    service = GraphService(integration_client)
    assert service.get_entity("SYS-TEST-NODE")["name"] == "Test Node"


def test_relationship_creation(integration_client):
    upsert_node(integration_client, "System", "SYS-TEST-A", {"name": "A"})
    upsert_node(integration_client, "System", "SYS-TEST-B", {"name": "B"})
    upsert_relationship(integration_client, "SYS-TEST-A", "DEPENDS_ON", "SYS-TEST-B", {"valid_from": "2026-10-16T00:00:00+05:30", "confidence": 1.0})
    service = GraphService(integration_client)
    deps = service.get_dependencies("SYS-TEST-A")
    assert any(row[0]["id"] == "SYS-TEST-B" for row in deps)


def test_dependency_traversal(integration_client):
    service = GraphService(integration_client)
    deps = service.get_dependencies("SYS-CHECKOUT", max_depth=3)
    ids = {row[0]["id"] for row in deps}
    assert {"SYS-PRICING-API", "SYS-PRICING-DB"} <= ids


def test_blast_radius_dependents(integration_client):
    service = GraphService(integration_client)
    rows = service.get_dependents("SYS-PRICING-DB", max_depth=3)
    ids = {row[0]["id"] for row in rows}
    assert {"SYS-PRICING-API", "SYS-CHECKOUT", "SYS-MOBILE-OFFERS", "SYS-LEGACY-PROMO", "SYS-PRICING-ANALYTICS"} <= ids


def test_ownership_traversal_and_orphan(integration_client):
    service = GraphService(integration_client)
    owner = service.get_owner("SYS-PRICING-API")
    assert owner and owner[0][0]["id"] == "TEAM-PRICING"
    orphan = service.get_owner("SYS-LEGACY-PROMO")
    assert orphan == []


def test_historical_ownership_lookup(integration_client):
    service = GraphService(integration_client)
    old_owner = service.get_owner("SYS-LEGACY-PROMO", as_of="2026-06-01T00:00:00+05:30")
    assert old_owner and old_owner[0][0]["id"] == "TEAM-GROWTH"


def test_claim_evidence_traversal(integration_client):
    provenance = ProvenanceService(integration_client).get_entity_provenance("C-002")
    evidence_ids = {e["id"] for e in provenance["evidence"]}
    assert {"E-001", "E-002", "E-003", "E-006"} <= evidence_ids


def test_contradiction_detection(integration_client):
    conflicts = GraphService(integration_client).get_conflicts("INC-001")
    pairs = {(row[0]["id"], row[2]["id"]) for row in conflicts}
    assert ("C-001", "C-002") in pairs or ("C-002", "C-001") in pairs


def test_temporal_history_lookup(integration_client):
    service = TemporalService(integration_client)

    # Evidence and events must use chronological comparison, not ISO-string ordering.
    state = service.incident_state_at("INC-001", "2026-10-16T14:09:00+05:30")
    evidence_ids = {e["id"] for e in state["evidence"]}
    event_ids = {e["id"] for e in state["events"]}
    assert "E-003" in evidence_ids
    assert "E-004" not in evidence_ids  # CPU 91% evidence observed later at 14:12
    assert "EVT-ERRORS" in event_ids
    assert "EVT-CPU91" not in event_ids

    # Claims use the same temporal representation. C-001 is 14:10, C-002 is 14:11.
    claim_state = service.incident_state_at("INC-001", "2026-10-16T14:10:30+05:30")
    claim_ids = {c["id"] for c in claim_state["claims"]}
    assert "C-001" in claim_ids
    assert "C-002" not in claim_ids

    # valid_until is exclusive: the legacy owner is valid immediately before 1 July, not at/after it.
    before_expiry = service.relationship_at(
        "TEAM-GROWTH", "OWNS", "SYS-LEGACY-PROMO", "2026-06-30T23:59:59+05:30"
    )
    at_expiry = service.relationship_at(
        "TEAM-GROWTH", "OWNS", "SYS-LEGACY-PROMO", "2026-07-01T00:00:00+05:30"
    )
    assert before_expiry
    assert at_expiry == []

    # Same instant expressed with a different timezone must produce the same state.
    utc_state = service.incident_state_at("INC-001", "2026-10-16T08:39:00Z")
    assert {e["id"] for e in utc_state["evidence"]} == evidence_ids
    assert {e["id"] for e in utc_state["events"]} == event_ids


def test_provenance_lookup(integration_client):
    provenance = ProvenanceService(integration_client).get_entity_provenance("E-003")
    assert provenance["entity"]["id"] == "E-003"
    assert any(s["id"] == "DS-LOG" for s in provenance["sources"])


def test_event_reconstruction(integration_client):
    timeline = TemporalService(integration_client).reconstruct_incident_timeline("INC-001")
    ids = [event["id"] for event in timeline]
    assert ids.index("EVT-INC-001") < ids.index("EVT-ERRORS") < ids.index("EVT-RETRIES") < ids.index("EVT-CPU91")


def test_graph_necessity_dependency_edge_foundation(integration_client):
    service = GraphService(integration_client)
    baseline = {row[0]["id"] for row in service.get_dependencies("SYS-CHECKOUT", 3)}
    assert "SYS-PRICING-DB" in baseline

    removed = delete_relationship(integration_client, "SYS-CHECKOUT", "DEPENDS_ON", "SYS-PRICING-API")
    assert removed >= 1
    degraded = {row[0]["id"] for row in service.get_dependencies("SYS-CHECKOUT", 3)}
    assert "SYS-PRICING-DB" not in degraded

    upsert_relationship(integration_client, "SYS-CHECKOUT", "DEPENDS_ON", "SYS-PRICING-API", {
        "valid_from": "2024-02-01T00:00:00+05:30", "confidence": 1.0, "source_ref_id": "DS-DEPLOY"
    })
