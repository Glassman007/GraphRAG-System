from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.graph.mutations import delete_relationship, upsert_node, upsert_relationship
from backend.app.ingestion.artifacts.local import LocalArtifactStore
from backend.app.ingestion.models import SourceConfig, TrustClass
from backend.app.ingestion.pipeline import IngestionPipeline
from backend.app.ingestion.registry import SourceRegistry, fixture_source_configs
from backend.app.services.blast_radius_service import BlastRadiusService
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.routing_service import ResponsibilityRoutingService

pytestmark = pytest.mark.integration


def _source(project_root: Path, client, source_type: str, suffix: str, *, fixture: Path | None = None, trust: TrustClass | None = None, authoritative_domains=None):
    base = {c.source_type: c for c in fixture_source_configs(project_root)}[source_type]
    cfg = base.model_copy(deep=True)
    cfg.id = f"DS-P9-{suffix}"
    cfg.source_instance = f"{base.source_instance}-{suffix.lower()}"
    if fixture is not None:
        cfg.fixture_path = str(fixture)
    if trust is not None:
        cfg.trust_class = trust
    if authoritative_domains is not None:
        cfg.authoritative_domains = list(authoritative_domains)
    reg = SourceRegistry(client)
    reg.register(cfg, persist=False)
    return cfg, reg


def _pipeline(project_root, integration_client, tmp_path, source_type, suffix, **kwargs):
    cfg, reg = _source(project_root, integration_client, source_type, suffix, **kwargs)
    return cfg, IngestionPipeline(integration_client, registry=reg, artifact_store=LocalArtifactStore(tmp_path / suffix))


def test_phase9_github_sync_persists_source_records_and_run(project_root, integration_client, tmp_path):
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "github", "GH-A")
    report = pipeline.sync(cfg.id, mode="full", max_records=10)
    assert report.status.value == "SUCCEEDED" and report.fetched == 3
    snapshot = GraphSnapshot.load(integration_client)
    assert has_label(snapshot.node(report.run_id), "IngestionRun")
    source_records = [n for n in snapshot.nodes.values() if has_label(n, "SourceRecord") and n.get("source_id") == cfg.id and n.get("record_type") != "identity_projection"]
    assert len(source_records) == 3
    assert all(any(e.target == cfg.id for e in snapshot.edges_from(str(n["id"]), {"DERIVED_FROM"})) for n in source_records)


def test_phase9_multisource_neha_resolves_to_one_person(project_root, integration_client, tmp_path):
    target_ids = []
    for source_type, suffix in [("github", "NEHA-GH"), ("jira", "NEHA-JIRA"), ("slack", "NEHA-SLACK")]:
        cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, source_type, suffix)
        pipeline.sync(cfg.id, mode="full", max_records=10)
    snapshot = GraphSnapshot.load(integration_client)
    identities = [n for n in snapshot.nodes.values() if has_label(n, "ExternalIdentity") and str(n.get("email") or "").lower() == "neha.verma@northstar.example"]
    assert len(identities) >= 3
    for identity in identities:
        edges = snapshot.edges_from(str(identity["id"]), {"RESOLVES_TO"})
        assert len(edges) == 1
        target_ids.append(edges[0].target)
    assert len(set(target_ids)) == 1
    person = snapshot.node(target_ids[0])
    assert has_label(person, "Person") and person.get("email") == "neha.verma@northstar.example"


def test_phase9_same_name_different_verified_email_does_not_merge(project_root, integration_client, tmp_path):
    fixture = tmp_path / "different-email.json"
    fixture.write_text(json.dumps({"records":[
        {"external_id":"u1","record_type":"user","observed_at":"2026-10-16T10:00:00+05:30","display_name":"Neha Varma","email":"neha.one@northstar.example","login":"neha-one"},
        {"external_id":"u2","record_type":"user","observed_at":"2026-10-16T10:01:00+05:30","display_name":"Neha Varma","email":"neha.two@northstar.example","login":"neha-two"}
    ]}), encoding="utf-8")
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "github", "DIFFEMAIL", fixture=fixture)
    pipeline.sync(cfg.id, mode="full", max_records=10)
    snapshot = GraphSnapshot.load(integration_client)
    people = [n for n in snapshot.nodes.values() if has_label(n, "Person") and n.get("name") == "Neha Varma" and str(n.get("email") or "").startswith("neha.")]
    assert len({n["id"] for n in people}) >= 2


def test_phase9_ambiguous_name_only_identity_is_quarantined(project_root, integration_client, tmp_path):
    fixture = tmp_path / "ambiguous.json"
    fixture.write_text(json.dumps({"records":[
        {"external_id":"seed","record_type":"user","observed_at":"2026-10-16T10:00:00+05:30","display_name":"Quinn Rao","email":"quinn@northstar.example","login":"quinn"},
        {"external_id":"amb","record_type":"user","observed_at":"2026-10-16T10:01:00+05:30","display_name":"Quinn Rao","login":"q-rao"}
    ]}), encoding="utf-8")
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "github", "AMB", fixture=fixture)
    report = pipeline.sync(cfg.id, mode="full", max_records=10)
    assert report.quarantined >= 1
    snapshot = GraphSnapshot.load(integration_client)
    assert any(has_label(n, "IngestionQuarantineRecord") and n.get("source_ref_id") == cfg.id and n.get("status") == "OPEN" for n in snapshot.nodes.values())


def test_phase9_provenance_chain_source_run_normalized_entity(project_root, integration_client, tmp_path):
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "github", "PROV")
    report = pipeline.sync(cfg.id, mode="full", max_records=1)
    snapshot = GraphSnapshot.load(integration_client)
    run = snapshot.node(report.run_id)
    ingested = snapshot.edges_from(report.run_id, {"INGESTED"})
    assert run and ingested
    source_record_id = ingested[0].target
    assert any(e.target == cfg.id for e in snapshot.edges_from(source_record_id, {"DERIVED_FROM"}))
    assert snapshot.edges_from(source_record_id, {"NORMALIZED_TO"})


def test_phase9_external_identity_retains_source_specific_id(project_root, integration_client, tmp_path):
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "github", "EXTID")
    pipeline.sync(cfg.id, mode="full", max_records=1)
    snapshot = GraphSnapshot.load(integration_client)
    ext = [n for n in snapshot.nodes.values() if has_label(n, "ExternalIdentity") and n.get("source_instance") == cfg.source_instance]
    assert ext and ext[0].get("external_id")
    assert snapshot.edges_from(str(ext[0]["id"]), {"RESOLVES_TO"})


def test_phase9_authoritative_ownership_has_relationship_provenance(project_root, integration_client, tmp_path):
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "internal_api", "OWNER")
    pipeline.sync(cfg.id, mode="full", max_records=10)
    snapshot = GraphSnapshot.load(integration_client)
    edges = [e for e in snapshot.edges_from("TEAM-PRICING", {"OWNS"}) if e.target == "SYS-PRICING-API" and e.properties.get("valid_until") is None]
    assert edges
    edge = edges[0]
    assert cfg.id in str(edge.properties.get("source_ref_id") or cfg.id) or edge.properties.get("source_record_ids_csv")
    assert edge.properties.get("source_record_ids_csv")


def test_phase9_untrusted_slack_does_not_write_ownership(project_root, integration_client, tmp_path):
    fixture = tmp_path / "slack-ownership.json"
    fixture.write_text(json.dumps({"records":[{"external_id":"m1","record_type":"message","observed_at":"2026-10-16T10:00:00+05:30","author":{"display_name":"Someone","email":"someone@northstar.example"},"text":"we own pricing","assertion":"Team Shadow owns Pricing API","about_system":"Pricing API","about_canonical_id":"SYS-PRICING-API"}]}), encoding="utf-8")
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "slack", "UNTRUST", fixture=fixture, trust=TrustClass.UNTRUSTED)
    pipeline.sync(cfg.id, mode="full", max_records=10)
    snapshot = GraphSnapshot.load(integration_client)
    claims = [n for n in snapshot.nodes.values() if has_label(n, "Claim") and n.get("statement") == "Team Shadow owns Pricing API"]
    assert claims and claims[0].get("status") == "UNVERIFIED"
    assert not any(has_label(n, "Team") and n.get("name") == "Team Shadow" for n in snapshot.nodes.values())


def test_phase9_large_artifact_externalized_and_graph_referenced(project_root, integration_client, tmp_path):
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "telemetry", "ART")
    report = pipeline.sync(cfg.id, mode="full", max_records=10)
    assert report.artifacts >= 1
    snapshot = GraphSnapshot.load(integration_client)
    artifacts = [n for n in snapshot.nodes.values() if has_label(n, "Artifact") and n.get("source_type") == "telemetry"]
    assert artifacts
    art = artifacts[0]
    assert art.get("sha256") and str(art.get("uri")).startswith("file:")
    assert any(e.target == art["id"] for n in snapshot.nodes.values() if has_label(n, "SourceRecord") for e in snapshot.edges_from(str(n["id"]), {"REFERENCES"}))


def test_phase9_telemetry_evidence_links_to_external_artifact(project_root, integration_client, tmp_path):
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "telemetry", "ARTLINK")
    pipeline.sync(cfg.id, mode="full", max_records=10)
    snapshot = GraphSnapshot.load(integration_client)
    evidence = [n for n in snapshot.nodes.values() if has_label(n, "Evidence") and n.get("source_ref_id") == cfg.id]
    assert evidence
    assert any(has_label(snapshot.node(e.target), "Artifact") for item in evidence for e in snapshot.edges_from(str(item["id"]), {"DERIVED_FROM"}))


def test_phase9_full_resync_is_idempotent(project_root, integration_client, tmp_path):
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "github", "IDEMP")
    pipeline.sync(cfg.id, mode="full", max_records=10)
    before = GraphSnapshot.load(integration_client)
    ids_before = {n["id"] for n in before.nodes.values() if n.get("source_id") == cfg.id or n.get("source_instance") == cfg.source_instance}
    pipeline.sync(cfg.id, mode="full", max_records=10)
    after = GraphSnapshot.load(integration_client)
    ids_after = {n["id"] for n in after.nodes.values() if n.get("source_id") == cfg.id or n.get("source_instance") == cfg.source_instance}
    assert ids_after == ids_before


def test_phase9_incremental_sync_advances_cursor_and_then_fetches_nothing(project_root, integration_client, tmp_path):
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "jira", "CURSOR")
    first = pipeline.sync(cfg.id, mode="incremental", max_records=10)
    second = pipeline.sync(cfg.id, mode="incremental", max_records=10)
    assert first.fetched == 2
    assert second.fetched == 0
    assert second.cursor_start == first.cursor_end


def test_phase9_crash_does_not_advance_cursor_beyond_committed_record(project_root, integration_client, tmp_path):
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "github", "CRASH")
    partial = pipeline.sync(cfg.id, mode="incremental", max_records=10, fail_after_committed=1)
    assert partial.status.value == "PARTIAL" and partial.cursor_end == "1"
    resumed = pipeline.sync(cfg.id, mode="incremental", max_records=10)
    assert resumed.fetched == 2
    snapshot = GraphSnapshot.load(integration_client)
    raw = [n for n in snapshot.nodes.values() if has_label(n, "SourceRecord") and n.get("source_id") == cfg.id and n.get("record_type") != "identity_projection"]
    assert len(raw) == 3


def test_phase9_updated_record_creates_version_chain(project_root, integration_client, tmp_path):
    fixture = tmp_path / "update.json"
    fixture.write_text(json.dumps({"records":[{"external_id":"repo","record_type":"repository","observed_at":"2026-10-16T10:00:00+05:30","name":"catalog-service","system_name":"Catalog API"}]}), encoding="utf-8")
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "github", "UPDATE", fixture=fixture)
    pipeline.sync(cfg.id, mode="full", max_records=10)
    fixture.write_text(json.dumps({"records":[{"external_id":"repo","record_type":"repository","observed_at":"2026-10-16T11:00:00+05:30","name":"catalog-service","system_name":"Catalog API","language":"Python"}]}), encoding="utf-8")
    pipeline.sync(cfg.id, mode="full", max_records=10)
    snapshot = GraphSnapshot.load(integration_client)
    records = [n for n in snapshot.nodes.values() if has_label(n, "SourceRecord") and n.get("source_key") == f"{cfg.id}:repo"]
    assert len(records) == 2
    newest = max(records, key=lambda n: str(n.get("observed_at")))
    assert snapshot.edges_from(str(newest["id"]), {"SUPERSEDES"})


def test_phase9_tombstone_creates_evidence_not_hard_delete(project_root, integration_client, tmp_path):
    fixture = tmp_path / "tombstone.json"
    fixture.write_text(json.dumps({"records":[{"external_id":"repo","record_type":"repository","observed_at":"2026-10-16T10:00:00+05:30","name":"old-service","system_name":"Old Service"}]}), encoding="utf-8")
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "github", "TOMB", fixture=fixture)
    pipeline.sync(cfg.id, mode="full", max_records=10)
    before = GraphSnapshot.load(integration_client)
    system_id = next(e.target for n in before.nodes.values() if has_label(n, "SourceRecord") and n.get("source_key") == f"{cfg.id}:repo" for e in before.edges_from(str(n["id"]), {"NORMALIZED_TO"}) if has_label(before.node(e.target), "System"))
    fixture.write_text(json.dumps({"records":[{"external_id":"repo","record_type":"repository","observed_at":"2026-10-16T12:00:00+05:30","deleted":True,"name":"old-service","system_name":"Old Service"}]}), encoding="utf-8")
    pipeline.sync(cfg.id, mode="full", max_records=10)
    after = GraphSnapshot.load(integration_client)
    assert after.node(system_id) is not None
    tombstones = [n for n in after.nodes.values() if has_label(n, "Evidence") and n.get("evidence_type") == "source_tombstone" and n.get("source_ref_id") == cfg.id]
    assert tombstones


def test_phase9_imported_ownership_is_consumed_by_existing_phase3_routing(project_root, integration_client, tmp_path):
    fixture = tmp_path / "owner.json"
    fixture.write_text(json.dumps({"records":[{"external_id":"svc-new","record_type":"service_record","observed_at":"2026-10-16T10:00:00+05:30","system":"Phase9 New API","owner_team":"Phase9 Platform","valid_from":"2026-10-16T10:00:00+05:30"}]}), encoding="utf-8")
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "internal_api", "ROUTE", fixture=fixture, trust=TrustClass.AUTHORITATIVE)
    pipeline.sync(cfg.id, mode="full", max_records=10)
    snapshot = GraphSnapshot.load(integration_client)
    system = next(n for n in snapshot.nodes.values() if has_label(n, "System") and n.get("name") == "Phase9 New API")
    result = ResponsibilityRoutingService(integration_client).find_owner(str(system["id"]))
    assert result["owners"] and result["owners"][0]["actor"]["name"] == "Phase9 Platform"


def test_phase9_imported_dependency_is_consumed_by_existing_blast_radius(project_root, integration_client, tmp_path):
    fixture = tmp_path / "deps.json"
    fixture.write_text(json.dumps({"records":[
        {"external_id":"db","record_type":"service_record","observed_at":"2026-10-16T10:00:00+05:30","system":"Phase9 DB","owner_team":"Phase9 Data"},
        {"external_id":"api","record_type":"service_record","observed_at":"2026-10-16T10:01:00+05:30","system":"Phase9 API","owner_team":"Phase9 Platform","depends_on":"Phase9 DB"}
    ]}), encoding="utf-8")
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "internal_api", "BLAST", fixture=fixture, trust=TrustClass.AUTHORITATIVE)
    pipeline.sync(cfg.id, mode="full", max_records=10)
    snapshot = GraphSnapshot.load(integration_client)
    db = next(n for n in snapshot.nodes.values() if has_label(n, "System") and n.get("name") == "Phase9 DB")
    api = next(n for n in snapshot.nodes.values() if has_label(n, "System") and n.get("name") == "Phase9 API")
    result = BlastRadiusService(integration_client).analyze(str(db["id"]))
    assert str(api["id"]) in {x["system"]["id"] for x in result["downstream_dependents"]}


def test_phase9_graph_necessity_provenance_break_is_detectable(project_root, integration_client, tmp_path):
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "github", "NEC-PROV")
    pipeline.sync(cfg.id, mode="full", max_records=1)
    snapshot = GraphSnapshot.load(integration_client)
    source_record = next(n for n in snapshot.nodes.values() if has_label(n, "SourceRecord") and n.get("source_id") == cfg.id and n.get("record_type") != "identity_projection")
    sid = str(source_record["id"])
    assert snapshot.edges_from(sid, {"NORMALIZED_TO"})
    targets = [e.target for e in snapshot.edges_from(sid, {"NORMALIZED_TO"})]
    try:
        for target in targets:
            delete_relationship(integration_client, sid, "NORMALIZED_TO", target)
        after = GraphSnapshot.load(integration_client)
        assert after.edges_from(sid, {"NORMALIZED_TO"}) == []
    finally:
        for target in targets:
            upsert_relationship(integration_client, sid, "NORMALIZED_TO", target, {"valid_from":"2026-10-16T16:00:00+05:30","confidence":1.0,"source_ref_id":cfg.id})


def test_phase9_graph_necessity_imported_dependency_changes_blast_radius(project_root, integration_client, tmp_path):
    fixture = tmp_path / "dep-nec.json"
    fixture.write_text(json.dumps({"records":[{"external_id":"api","record_type":"service_record","observed_at":"2026-10-16T10:00:00+05:30","system":"Nec API","owner_team":"Nec Team","depends_on":"Nec DB"}]}), encoding="utf-8")
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "internal_api", "NEC-DEP", fixture=fixture, trust=TrustClass.AUTHORITATIVE)
    pipeline.sync(cfg.id, mode="full", max_records=10)
    snapshot = GraphSnapshot.load(integration_client)
    api = next(n for n in snapshot.nodes.values() if has_label(n, "System") and n.get("name") == "Nec API")
    db = next(n for n in snapshot.nodes.values() if has_label(n, "System") and n.get("name") == "Nec DB")
    assert str(api["id"]) in {x["system"]["id"] for x in BlastRadiusService(integration_client).analyze(str(db["id"]))["downstream_dependents"]}
    props = next(e.properties for e in snapshot.edges_from(str(api["id"]), {"DEPENDS_ON"}) if e.target == db["id"])
    try:
        delete_relationship(integration_client, str(api["id"]), "DEPENDS_ON", str(db["id"]))
        assert str(api["id"]) not in {x["system"]["id"] for x in BlastRadiusService(integration_client).analyze(str(db["id"]))["downstream_dependents"]}
    finally:
        upsert_relationship(integration_client, str(api["id"]), "DEPENDS_ON", str(db["id"]), props)


def test_phase9_non_auto_authoritative_source_preserves_structural_assertion_as_claim(project_root, integration_client, tmp_path):
    fixture = tmp_path / "catalog-claim.json"
    fixture.write_text(json.dumps({"records":[{"external_id":"svc","record_type":"service_record","observed_at":"2026-10-16T10:00:00+05:30","system":"Claim Only API","owner_team":"Claim Only Team"}]}), encoding="utf-8")
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "database", "CLAIMONLY", fixture=fixture, trust=TrustClass.AUTHORITATIVE)
    pipeline.sync(cfg.id, mode="full", max_records=10)
    snapshot = GraphSnapshot.load(integration_client)
    system = next(n for n in snapshot.nodes.values() if has_label(n, "System") and n.get("name") == "Claim Only API")
    team = next(n for n in snapshot.nodes.values() if has_label(n, "Team") and n.get("name") == "Claim Only Team")
    assert not any(e.target == system["id"] for e in snapshot.edges_from(str(team["id"]), {"OWNS"}))
    claims = [n for n in snapshot.nodes.values() if has_label(n, "Claim") and n.get("source_ref_id") == cfg.id and n.get("assertion_kind") == "external_structural_assertion"]
    assert claims and claims[0]["status"] == "UNVERIFIED"


def test_phase9_multiple_sources_for_same_fact_do_not_duplicate_active_relationship(project_root, integration_client, tmp_path):
    fixture = tmp_path / "samefact.json"
    fixture.write_text(json.dumps({"records":[{"external_id":"svc","record_type":"service_record","observed_at":"2026-10-16T10:00:00+05:30","system":"Shared Fact API","owner_team":"Shared Fact Team"}]}), encoding="utf-8")
    source_records = []
    for suffix in ("FACT-A", "FACT-B"):
        cfg, reg = _source(project_root, integration_client, "internal_api", suffix, fixture=fixture, trust=TrustClass.AUTHORITATIVE)
        cfg.settings["auto_validate_ownership"] = True
        pipeline = IngestionPipeline(integration_client, registry=reg, artifact_store=LocalArtifactStore(tmp_path / suffix))
        pipeline.sync(cfg.id, mode="full", max_records=10)
    snapshot = GraphSnapshot.load(integration_client)
    system = next(n for n in snapshot.nodes.values() if has_label(n, "System") and n.get("name") == "Shared Fact API")
    team = next(n for n in snapshot.nodes.values() if has_label(n, "Team") and n.get("name") == "Shared Fact Team")
    edges = [e for e in snapshot.edges_from(str(team["id"]), {"OWNS"}) if e.target == system["id"] and e.properties.get("valid_until") is None]
    assert len(edges) == 1
    refs = set(str(edges[0].properties.get("source_record_ids_csv") or "").split(","))
    assert len({x for x in refs if x}) >= 2


def test_phase9_quarantine_can_be_manually_resolved_without_creating_duplicate_person(project_root, integration_client, tmp_path):
    fixture = tmp_path / "manual-q.json"
    fixture.write_text(json.dumps({"records":[
        {"external_id":"seed","record_type":"user","observed_at":"2026-10-16T10:00:00+05:30","display_name":"Manual Review Person","email":"manual@northstar.example","login":"manual"},
        {"external_id":"amb","record_type":"user","observed_at":"2026-10-16T10:01:00+05:30","display_name":"Manual Review Person","login":"manual-alt"}
    ]}), encoding="utf-8")
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "github", "MANUALQ", fixture=fixture)
    pipeline.sync(cfg.id, mode="full", max_records=10)
    from backend.app.ingestion.resolution.service import IngestionEntityResolutionService
    service = IngestionEntityResolutionService(integration_client)
    q = next(x for x in service.list_quarantine(status="OPEN") if x.get("source_ref_id") == cfg.id)
    snapshot = GraphSnapshot.load(integration_client)
    person = next(n for n in snapshot.nodes.values() if has_label(n, "Person") and n.get("email") == "manual@northstar.example")
    result = service.resolve_quarantine(str(q["id"]), str(person["id"]))
    assert result["status"] == "RESOLVED" and result["resolved_to"] == person["id"]


def test_phase9_tenant_scoping_prevents_cross_tenant_source_visibility(project_root, integration_client, tmp_path):
    from backend.app.config import Settings
    from backend.app.graph.client import FalkorGraphClient
    other_settings = Settings(
        falkordb_host=integration_client.settings.falkordb_host,
        falkordb_port=integration_client.settings.falkordb_port,
        falkordb_graph=integration_client.settings.falkordb_graph,
        falkordb_password=integration_client.settings.falkordb_password,
        tenant_id="other-tenant",
    )
    other = FalkorGraphClient(other_settings)
    fixture = tmp_path / "tenant.json"
    fixture.write_text(json.dumps({"records":[{"external_id":"repo","record_type":"repository","observed_at":"2026-10-16T10:00:00+05:30","name":"tenant-service","system_name":"Tenant Isolated API"}]}), encoding="utf-8")
    cfg, reg = _source(project_root, other, "github", "TENANT", fixture=fixture)
    IngestionPipeline(other, registry=reg, artifact_store=LocalArtifactStore(tmp_path / "tenant-art")).sync(cfg.id, mode="full", max_records=10)
    assert any(n.get("name") == "Tenant Isolated API" for n in GraphSnapshot.load(other).nodes.values())
    assert not any(n.get("name") == "Tenant Isolated API" for n in GraphSnapshot.load(integration_client).nodes.values())


def test_phase9_graph_necessity_external_identity_resolution_edge_is_load_bearing(project_root, integration_client, tmp_path):
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "github", "NEC-ID")
    pipeline.sync(cfg.id, mode="full", max_records=1)
    snapshot = GraphSnapshot.load(integration_client)
    identity = next(n for n in snapshot.nodes.values() if has_label(n, "ExternalIdentity") and n.get("source_instance") == cfg.source_instance)
    iid = str(identity["id"])
    edges = snapshot.edges_from(iid, {"RESOLVES_TO"})
    assert len(edges) == 1
    target, props = edges[0].target, dict(edges[0].properties)
    try:
        delete_relationship(integration_client, iid, "RESOLVES_TO", target)
        after = GraphSnapshot.load(integration_client)
        assert after.edges_from(iid, {"RESOLVES_TO"}) == []
    finally:
        upsert_relationship(integration_client, iid, "RESOLVES_TO", target, props)


def test_phase9_graph_necessity_imported_ownership_changes_existing_routing(project_root, integration_client, tmp_path):
    fixture = tmp_path / "owner-nec.json"
    fixture.write_text(json.dumps({"records":[{"external_id":"svc","record_type":"service_record","observed_at":"2026-10-16T10:00:00+05:30","system":"Nec Owner API","owner_team":"Nec Owner Team"}]}), encoding="utf-8")
    cfg, reg = _source(project_root, integration_client, "internal_api", "NEC-OWNER", fixture=fixture, trust=TrustClass.AUTHORITATIVE)
    cfg.settings["auto_validate_ownership"] = True
    pipeline = IngestionPipeline(integration_client, registry=reg, artifact_store=LocalArtifactStore(tmp_path / "owner-nec-art"))
    pipeline.sync(cfg.id, mode="full", max_records=10)
    snapshot = GraphSnapshot.load(integration_client)
    system = next(n for n in snapshot.nodes.values() if has_label(n, "System") and n.get("name") == "Nec Owner API")
    team = next(n for n in snapshot.nodes.values() if has_label(n, "Team") and n.get("name") == "Nec Owner Team")
    owner_edge = next(e for e in snapshot.edges_from(str(team["id"]), {"OWNS"}) if e.target == system["id"] and e.properties.get("valid_until") is None)
    assert ResponsibilityRoutingService(integration_client).find_owner(str(system["id"]))["owners"]
    props = dict(owner_edge.properties)
    try:
        delete_relationship(integration_client, str(team["id"]), "OWNS", str(system["id"]))
        assert ResponsibilityRoutingService(integration_client).find_owner(str(system["id"]))["owners"] == []
    finally:
        upsert_relationship(integration_client, str(team["id"]), "OWNS", str(system["id"]), props)


def test_phase9_graph_necessity_artifact_lineage_break_is_visible(project_root, integration_client, tmp_path):
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "telemetry", "NEC-ART")
    pipeline.sync(cfg.id, mode="full", max_records=10)
    snapshot = GraphSnapshot.load(integration_client)
    evidence = next(n for n in snapshot.nodes.values() if has_label(n, "Evidence") and n.get("source_ref_id") == cfg.id and any(has_label(snapshot.node(e.target), "Artifact") for e in snapshot.edges_from(str(n["id"]), {"DERIVED_FROM"})))
    edge = next(e for e in snapshot.edges_from(str(evidence["id"]), {"DERIVED_FROM"}) if has_label(snapshot.node(e.target), "Artifact"))
    props = dict(edge.properties)
    try:
        delete_relationship(integration_client, str(evidence["id"]), "DERIVED_FROM", edge.target)
        after = GraphSnapshot.load(integration_client)
        assert not any(has_label(after.node(e.target), "Artifact") for e in after.edges_from(str(evidence["id"]), {"DERIVED_FROM"}))
    finally:
        upsert_relationship(integration_client, str(evidence["id"]), "DERIVED_FROM", edge.target, props)


def test_phase9_conflicting_structural_source_assertions_feed_company_brain_conflict_model(project_root, integration_client, tmp_path):
    fixture_a = tmp_path / "conflict-a.json"
    fixture_b = tmp_path / "conflict-b.json"
    fixture_a.write_text(json.dumps({"records":[{"external_id":"svc-a","record_type":"service_record","observed_at":"2026-10-16T10:00:00+05:30","system":"Conflict API","owner_team":"Conflict Team A"}]}), encoding="utf-8")
    fixture_b.write_text(json.dumps({"records":[{"external_id":"svc-b","record_type":"service_record","observed_at":"2026-10-16T10:05:00+05:30","system":"Conflict API","owner_team":"Conflict Team B"}]}), encoding="utf-8")
    for suffix, fixture in (("CONFLICT-A", fixture_a), ("CONFLICT-B", fixture_b)):
        cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "database", suffix, fixture=fixture, trust=TrustClass.AUTHORITATIVE)
        pipeline.sync(cfg.id, mode="full", max_records=10)
    snapshot = GraphSnapshot.load(integration_client)
    claims = [n for n in snapshot.nodes.values() if has_label(n, "Claim") and n.get("assertion_kind") == "external_structural_assertion" and n.get("fact_rel_type") == "OWNS"]
    target_groups = {}
    for claim in claims:
        target_groups.setdefault(claim.get("fact_target_id"), []).append(claim)
    pair = next(group for group in target_groups.values() if len({x.get("fact_source_id") for x in group}) >= 2)
    left, right = pair[0], pair[1]
    assert any(e.target == right["id"] for e in snapshot.edges_from(str(left["id"]), {"CONTRADICTS"})) or any(e.target == left["id"] for e in snapshot.edges_from(str(right["id"]), {"CONTRADICTS"}))


def test_phase9_graph_necessity_imported_policy_requirement_drives_drift(project_root, integration_client, tmp_path):
    from backend.app.services.policy_drift_service import PolicyDriftService
    fixture = tmp_path / "policy-nec.json"
    fixture.write_text(json.dumps({"records":[{
        "external_id":"P9-POL-DOC","record_type":"policy_document","observed_at":"2026-10-16T09:00:00+05:30","title":"Phase9 Required Verification Policy",
        "policy":{"policy_id":"P9-POL-NEC","name":"Phase9 Required Verification Policy","status":"ACTIVE","valid_from":"2026-10-16T09:00:00+05:30","requirements":[{"id":"P9-ACT-VERIFY","code":"VERIFY","name":"Perform Phase9 verification","action_type":"verification"}]}
    }]}), encoding="utf-8")
    cfg, pipeline = _pipeline(project_root, integration_client, tmp_path, "documents", "NEC-POL", fixture=fixture, trust=TrustClass.AUTHORITATIVE)
    pipeline.sync(cfg.id, mode="full", max_records=10)
    upsert_node(integration_client, "Incident", "P9-INC-POL", {"name":"Phase9 policy scope", "status":"OPEN", "created_at":"2026-10-16T10:00:00+05:30"})
    upsert_node(integration_client, "Event", "P9-EVT-POL", {"name":"Phase9 policy event", "event_type":"INCIDENT_DETECTED", "occurred_at":"2026-10-16T10:00:00+05:30", "created_at":"2026-10-16T10:00:00+05:30"})
    upsert_relationship(integration_client, "P9-EVT-POL", "ABOUT", "P9-INC-POL", {"valid_from":"2026-10-16T10:00:00+05:30"})
    before = PolicyDriftService(integration_client).analyze("P9-INC-POL", "P9-POL-NEC")
    assert before and any(x["classification"] == "MISSING_REQUIRED_STEP" for x in before["drift"])
    snapshot = GraphSnapshot.load(integration_client)
    req = next(e for e in snapshot.edges_from("P9-POL-NEC", {"REQUIRES"}) if e.target == "P9-ACT-VERIFY")
    props = dict(req.properties)
    try:
        delete_relationship(integration_client, "P9-POL-NEC", "REQUIRES", "P9-ACT-VERIFY")
        after = PolicyDriftService(integration_client).analyze("P9-INC-POL", "P9-POL-NEC")
        assert after and not any(x.get("expected_requirement", {}).get("id") == "P9-ACT-VERIFY" for x in after["drift"])
    finally:
        upsert_relationship(integration_client, "P9-POL-NEC", "REQUIRES", "P9-ACT-VERIFY", props)
