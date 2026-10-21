"""Targeted regressions for VERINEX graph ingestion and tenant isolation.

Run from the repository root after applying the two replacement files:
    python -m pytest -q backend/tests/test_company_brain_graph_regressions.py --tb=short
No FalkorDB server is required: mutations and graph writer calls are mocked.
"""

from types import SimpleNamespace as NS

import pytest

from backend.app.graph.mutations import upsert_node
from backend.app.ingestion import graph_writer as gw


class RecordingClient:
    def __init__(self):
        self.settings = NS(tenant_id="TENANT-A")
        self.calls = []

    def query(self, cypher, params=None):
        self.calls.append((cypher, params))
        return NS(result_set=[[{"id": "node"}]])


def _writer(monkeypatch, nodes=None, edges=None):
    calls = []
    monkeypatch.setattr(gw, "upsert_node", lambda _client, label, node_id, props: calls.append(("node", label, node_id, dict(props))))
    monkeypatch.setattr(gw, "upsert_relationship", lambda _client, source, kind, target, props: calls.append(("rel", source, kind, target, dict(props))))
    snapshot = NS(nodes=nodes or {}, edges_from=lambda _source, _types: edges or [])
    monkeypatch.setattr(gw.GraphSnapshot, "load", lambda _client: snapshot)
    monkeypatch.setattr(gw, "has_label", lambda n, label: label in n.get("labels", []))
    instance = gw.IngestionGraphWriter.__new__(gw.IngestionGraphWriter)
    instance.client = RecordingClient()
    return instance, calls


def _config(**settings):
    return NS(id="SRC-1", settings=settings)


def test_mutations_reject_other_tenant_and_keep_current_scope():
    client = RecordingClient()
    with pytest.raises(ValueError, match="tenant_id"):
        upsert_node(client, "Person", "P-1", {"tenant_id": "TENANT-B"})
    assert not client.calls, "Cross-tenant write must be rejected before querying the database"
    upsert_node(client, "Person", "P-1", {"name": "Engineer"})
    assert client.calls[0][1]["props"]["tenant_id"] == "TENANT-A"


def test_multiple_source_actors_get_distinct_structural_evidence(monkeypatch):
    writer, calls = _writer(monkeypatch)
    for actor in ("ACTOR-A", "ACTOR-B"):
        writer._write_structural_assertion_claim(
            config=_config(), source_record_id="REC-1", actor_id=actor,
            rel_type="DEPENDS_ON", target_id="SYSTEM-1", observed_at="2026-01-01",
        )
    evidence_ids = [row[2] for row in calls if row[0] == "node" and row[1] == "Evidence"]
    assert len(evidence_ids) == 2
    assert len(set(evidence_ids)) == 2, "Distinct facts cannot share the same evidence identity"


def test_shared_dependency_target_does_not_create_false_conflict(monkeypatch):
    old_claim = {
        "id": "CLAIM-OLD", "labels": ["Claim"],
        "assertion_kind": "external_structural_assertion", "fact_rel_type": "DEPENDS_ON",
        "fact_target_id": "SYSTEM-1", "fact_source_id": "ACTOR-A", "confidence": 0.8,
    }
    writer, calls = _writer(monkeypatch, nodes={"CLAIM-OLD": old_claim})
    writer._write_structural_assertion_claim(
        config=_config(), source_record_id="REC-2", actor_id="ACTOR-B",
        rel_type="DEPENDS_ON", target_id="SYSTEM-1", observed_at="2026-01-01",
    )
    assert not any(row[0] == "rel" and row[2] == "CONTRADICTS" for row in calls)


def test_explicitly_exclusive_ownership_can_create_a_conflict(monkeypatch):
    old_claim = {
        "id": "CLAIM-OLD", "labels": ["Claim"],
        "assertion_kind": "external_structural_assertion", "fact_rel_type": "OWNS",
        "fact_target_id": "SYSTEM-1", "fact_source_id": "ACTOR-A", "confidence": 0.8,
    }
    writer, calls = _writer(monkeypatch, nodes={"CLAIM-OLD": old_claim})
    writer._write_structural_assertion_claim(
        config=_config(exclusive_structural_relationship_types=["OWNS"]),
        source_record_id="REC-2", actor_id="ACTOR-B", rel_type="OWNS",
        target_id="SYSTEM-1", observed_at="2026-01-01",
    )
    assert any(row[0] == "rel" and row[2] == "CONTRADICTS" for row in calls)


def test_low_trust_source_adds_lineage_without_downgrading_authority(monkeypatch):
    edge = NS(target="SYSTEM-1", properties={
        "edge_id": "EDGE-AUTH", "source_ref_id": "SRC-AUTH",
        "source_record_id": "REC-AUTH", "source_record_ids_csv": "REC-AUTH",
        "authoritative": True, "authority": "authoritative", "confidence": 0.99,
        "valid_from": "2026-01-01",
    })
    writer, calls = _writer(monkeypatch, edges=[edge])
    writer._upsert_canonical_relationship(
        "ACTOR-A", "DEPENDS_ON", "SYSTEM-1",
        {"source_ref_id": "SRC-LOW", "source_record_id": "REC-LOW",
         "authoritative": False, "authority": "untrusted", "confidence": 0.1,
         "valid_from": "2026-01-10"},
        source_record_id="REC-LOW",
    )
    written = next(row[4] for row in calls if row[0] == "rel")
    assert written["authoritative"] is True
    assert written["source_ref_id"] == "SRC-AUTH"
    assert written["source_record_id"] == "REC-AUTH"
    assert written["confidence"] == 0.99
    assert set(written["source_record_ids_csv"].split(",")) == {"REC-AUTH", "REC-LOW"}


def test_authoritative_upgrade_updates_source_attribution(monkeypatch):
    edge = NS(target="SYSTEM-1", properties={
        "edge_id": "EDGE-LOW", "source_ref_id": "SRC-LOW",
        "source_record_id": "REC-LOW", "source_record_ids_csv": "REC-LOW",
        "authoritative": False, "authority": "untrusted", "confidence": 0.2,
    })
    writer, calls = _writer(monkeypatch, edges=[edge])
    writer._upsert_canonical_relationship(
        "ACTOR-A", "DEPENDS_ON", "SYSTEM-1",
        {"source_ref_id": "SRC-AUTH", "source_record_id": "REC-AUTH",
         "authoritative": True, "authority": "authoritative", "confidence": 0.99},
        source_record_id="REC-AUTH",
    )
    written = next(row[4] for row in calls if row[0] == "rel")
    assert written["source_ref_id"] == "SRC-AUTH"
    assert written["authoritative"] is True


def test_validated_authoritative_evidence_is_fact_specific(monkeypatch):
    writer, calls = _writer(monkeypatch)
    ids = [writer._validated_source_evidence(
        source_record_id="REC-1", source_id="SRC-1", actor_id=actor,
        subject_id="SYSTEM-1", fact_type="OWNS", observed_at="2026-01-01",
    ) for actor in ("ACTOR-A", "ACTOR-B")]
    assert len(set(ids)) == 2
    evidence = [row[3] for row in calls if row[0] == "node" and row[1] == "Evidence"]
    assert {item["fact_source_id"] for item in evidence} == {"ACTOR-A", "ACTOR-B"}
