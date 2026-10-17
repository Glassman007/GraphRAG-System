from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.ingestion.adapters.base import checksum_payload
from backend.app.ingestion.artifacts.local import LocalArtifactStore
from backend.app.ingestion.models import ArtifactPayload, ArtifactType, SourceConfig, TrustClass
from backend.app.ingestion.normalization.mappings import mapping_catalog, normalizer_for
from backend.app.ingestion.pipeline import IngestionPipeline
from backend.app.ingestion.provenance.service import IngestionProvenanceService
from backend.app.ingestion.registry import SourceRegistry, build_default_registry, fixture_source_configs


class _Result:
    def __init__(self, rows=None):
        self.result_set = rows or []


class ReadOnlyEmptyClient:
    def __init__(self):
        self.settings = SimpleNamespace(tenant_id="northstar")
        self.query_calls = 0

    def read(self, cypher, params=None):
        if "RETURN n ORDER BY n.id" in cypher or "RETURN a.id, type(r), r, b.id" in cypher:
            return _Result([])
        raise AssertionError(cypher)

    def query(self, cypher, params=None):
        self.query_calls += 1
        raise AssertionError("dry run attempted a graph mutation")


def _registry(project_root: Path):
    return build_default_registry(None, root=project_root, persist=False)


def _fetch(project_root: Path, source_id: str, limit: int = 100):
    reg = _registry(project_root)
    cfg, adapter = reg.get(source_id)
    return cfg, adapter.fetch(limit=limit)


@pytest.mark.parametrize("source_id,source_type", [
    ("DS-ING-GITHUB", "github"), ("DS-ING-JIRA", "jira"), ("DS-ING-SLACK", "slack"),
    ("DS-ING-TEAMS", "teams"), ("DS-ING-DOCS", "documents"), ("DS-ING-TELEMETRY", "telemetry"),
    ("DS-ING-DATABASE", "database"), ("DS-ING-INTERNAL", "internal_api"),
])
def test_phase9_fixture_adapters_fetch_realistic_source_records(project_root, source_id, source_type):
    cfg, page = _fetch(project_root, source_id)
    assert cfg.source_type == source_type
    assert page.records
    assert all(r.source_type == source_type for r in page.records)
    assert all(r.external_id and r.checksum for r in page.records)


def test_phase9_adapter_cursor_is_incremental(project_root):
    reg = _registry(project_root)
    _, adapter = reg.get("DS-ING-GITHUB")
    first = adapter.fetch(cursor="0", limit=1)
    second = adapter.fetch(cursor=first.next_cursor, limit=1)
    assert first.records[0].external_id != second.records[0].external_id
    assert first.next_cursor == "1" and second.next_cursor == "2"


def test_phase9_source_config_redacts_secret_like_settings():
    cfg = SourceConfig(id="x", source_type="github", name="x", source_instance="x", settings={"token_env": "SECRET", "org": "northstar", "password": "never"})
    public = cfg.public_dict()
    assert public["settings"]["org"] == "northstar"
    assert public["settings"]["token_env"] == "<redacted-config-reference>"
    assert public["settings"]["password"] == "<redacted-config-reference>"
    assert "never" not in json.dumps(public)


def test_phase9_github_pr_normalization_contains_change_people_and_migration(project_root):
    cfg, page = _fetch(project_root, "DS-ING-GITHUB")
    record = next(r for r in page.records if r.record_type == "pull_request")
    out = normalizer_for(cfg).normalize("SRC-X", record)
    labels = {e.ontology_type for e in out.entities}
    assert {"Change", "Person", "System"} <= labels
    rels = {r.rel_type for r in out.relations}
    assert {"PRODUCED", "AFFECTS", "CONTAINS", "CHANGED"} <= rels
    assert out.mapping_rule == "github:pull_request"


def test_phase9_jira_issue_normalization_is_graph_structured(project_root):
    cfg, page = _fetch(project_root, "DS-ING-JIRA")
    record = next(r for r in page.records if r.record_type == "issue")
    out = normalizer_for(cfg).normalize("SRC-X", record)
    assert any(e.ontology_type == "Task" for e in out.entities)
    assert {"ASSIGNED_TO", "MEMBER_OF", "ABOUT", "DEPENDS_ON", "PART_OF"} <= {r.rel_type for r in out.relations}


def test_phase9_slack_assertion_remains_unverified(project_root):
    cfg, page = _fetch(project_root, "DS-ING-SLACK")
    record = next(r for r in page.records if r.record_type == "message")
    out = normalizer_for(cfg).normalize("SRC-X", record)
    claim = next(e for e in out.entities if e.ontology_type == "Claim")
    assert claim.properties["status"] == "UNVERIFIED"
    assert claim.properties["confidence"] < 1.0
    assert any(r.rel_type == "ASSERTED_BY" for r in out.relations)


def test_phase9_document_policy_normalization_produces_expected_process_graph(project_root):
    cfg, page = _fetch(project_root, "DS-ING-DOCS")
    out = normalizer_for(cfg).normalize("SRC-X", page.records[0])
    assert any(e.ontology_type == "Policy" for e in out.entities)
    assert len([e for e in out.entities if e.ontology_type == "Action"]) == 2
    assert any(r.rel_type == "GOVERNS" for r in out.relations)
    assert len([r for r in out.relations if r.rel_type == "REQUIRES"]) == 2
    assert all(r.requires_authoritative_source for r in out.relations if r.rel_type in {"GOVERNS", "REQUIRES"})


def test_phase9_telemetry_preserves_source_event_time(project_root):
    cfg, page = _fetch(project_root, "DS-ING-TELEMETRY")
    out = normalizer_for(cfg).normalize("SRC-X", page.records[0])
    event = next(e for e in out.entities if e.ontology_type == "Event")
    evidence = next(e for e in out.entities if e.ontology_type == "Evidence")
    assert event.properties["occurred_at"] == page.records[0].observed_at
    assert evidence.properties["observed_at"] == page.records[0].observed_at
    assert page.records[0].fetched_at != ""  # distinct ingestion/fetch time exists


@pytest.mark.parametrize("source_id", ["DS-ING-DATABASE", "DS-ING-INTERNAL"])
def test_phase9_catalog_normalization_marks_structural_facts_authoritative_only(project_root, source_id):
    cfg, page = _fetch(project_root, source_id)
    out = normalizer_for(cfg).normalize("SRC-X", page.records[0])
    rels = {r.rel_type: r for r in out.relations}
    assert rels["OWNS"].requires_authoritative_source is True
    assert rels["DEPENDS_ON"].requires_authoritative_source is True


def test_phase9_unknown_record_is_not_silently_mapped(project_root):
    cfg, page = _fetch(project_root, "DS-ING-GITHUB")
    r = page.records[0].model_copy(update={"record_type": "future_unknown_type"})
    out = normalizer_for(cfg).normalize("SRC-X", r)
    assert out.entities == []
    assert out.warnings == ["UNMAPPED_GITHUB_RECORD_TYPE:future_unknown_type"]


def test_phase9_unknown_schema_version_is_rejected(project_root):
    cfg, page = _fetch(project_root, "DS-ING-JIRA")
    record = page.records[0].model_copy(update={"schema_version": "999"})
    with pytest.raises(ValueError, match="Unsupported jira schema_version"):
        normalizer_for(cfg).normalize("SRC-X", record)


def test_phase9_mapping_catalog_has_every_supported_source():
    names = {x["source_type"] for x in mapping_catalog()}
    assert {"github", "jira", "slack", "teams", "documents", "telemetry", "database", "internal_api"} <= names


def test_phase9_content_checksum_is_order_stable():
    assert checksum_payload({"a": 1, "b": 2}) == checksum_payload({"b": 2, "a": 1})


def test_phase9_source_record_identity_is_stable_for_unchanged_version(project_root):
    cfg, page = _fetch(project_root, "DS-ING-GITHUB")
    r = page.records[0]
    one = IngestionProvenanceService.source_record_id(cfg.id, r)
    two = IngestionProvenanceService.source_record_id(cfg.id, r)
    changed = r.model_copy(update={"checksum": "0" * 64})
    assert one == two
    assert one != IngestionProvenanceService.source_record_id(cfg.id, changed)


def test_phase9_local_artifact_store_hashes_and_deduplicates(tmp_path):
    store = LocalArtifactStore(tmp_path)
    payload = ArtifactPayload(name="x.log", content="same content", mime_type="text/plain", artifact_type=ArtifactType.LOG)
    one = store.put(payload, tenant_id="northstar", source_type="telemetry", source_record_id="S1")
    two = store.put(payload, tenant_id="northstar", source_type="telemetry", source_record_id="S2")
    assert one.artifact_id == two.artifact_id
    assert one.sha256 == two.sha256
    assert len(list(tmp_path.rglob("payload.bin"))) == 1
    assert store.get(one.artifact_id) == b"same content"


def test_phase9_artifact_metadata_has_integrity_fields(tmp_path):
    store = LocalArtifactStore(tmp_path)
    meta = store.put(ArtifactPayload(name="doc", content="abc", artifact_type=ArtifactType.DOCUMENT), tenant_id="northstar", source_type="documents", source_record_id="SRC")
    loaded = store.metadata(meta.artifact_id)
    assert loaded and loaded.size_bytes == 3 and len(loaded.sha256) == 64
    assert loaded.uri.startswith("file:")


def test_phase9_small_structured_metadata_is_not_implicitly_externalized(project_root, tmp_path):
    client = ReadOnlyEmptyClient()
    pipeline = IngestionPipeline(client, registry=_registry(project_root), artifact_store=LocalArtifactStore(tmp_path))
    report = pipeline.sync("DS-ING-JIRA", mode="full", max_records=1, dry_run=True)
    assert report.artifacts == 0
    assert list(tmp_path.rglob("payload.bin")) == []


def test_phase9_dry_run_fetch_normalize_resolve_without_graph_mutation(project_root, tmp_path):
    client = ReadOnlyEmptyClient()
    pipeline = IngestionPipeline(client, registry=_registry(project_root), artifact_store=LocalArtifactStore(tmp_path))
    report = pipeline.sync("DS-ING-GITHUB", mode="full", max_records=3, dry_run=True)
    assert report.status.value == "DRY_RUN"
    assert report.fetched == 3 and report.normalized == 3
    assert report.proposed_mutations
    assert client.query_calls == 0


def test_phase9_dry_run_unknown_source_is_rejected(project_root, tmp_path):
    pipeline = IngestionPipeline(ReadOnlyEmptyClient(), registry=_registry(project_root), artifact_store=LocalArtifactStore(tmp_path))
    with pytest.raises(ValueError, match="Unknown ingestion source"):
        pipeline.sync("DS-NOT-REAL", dry_run=True)


def test_phase9_source_registry_lists_no_credentials(project_root):
    values = _registry(project_root).public_sources()
    text = json.dumps(values).lower()
    assert "ghp_" not in text and "xoxb-" not in text
    assert len(values) == 8


def test_phase9_fixture_health_is_explicitly_not_live(project_root):
    reg = _registry(project_root)
    for cfg in reg.configs():
        _, adapter = reg.get(cfg.id)
        health = adapter.health_check()
        assert health["ok"] is True
        assert health["live"] is False


def test_phase9_artifact_store_threshold_is_explicit_configuration(tmp_path):
    store = LocalArtifactStore(tmp_path, inline_threshold_bytes=4096)
    assert store.inline_threshold_bytes == 4096


def test_phase9_fixture_source_configs_have_explicit_trust(project_root):
    configs = fixture_source_configs(project_root)
    by_type = {c.source_type: c for c in configs}
    assert by_type["documents"].trust_class == TrustClass.AUTHORITATIVE
    assert by_type["internal_api"].trust_class == TrustClass.AUTHORITATIVE
    assert by_type["slack"].trust_class == TrustClass.UNTRUSTED

@pytest.mark.parametrize("source_id", [
    "DS-ING-GITHUB", "DS-ING-JIRA", "DS-ING-SLACK", "DS-ING-TEAMS",
    "DS-ING-DOCS", "DS-ING-TELEMETRY", "DS-ING-DATABASE", "DS-ING-INTERNAL",
])
def test_phase9_adapter_records_keep_fetch_observation_and_cursor_distinct(project_root, source_id):
    _, page = _fetch(project_root, source_id, limit=1)
    record = page.records[0]
    assert record.fetched_at
    assert record.cursor is not None
    assert record.checksum
    # observed_at is source semantics; fetched_at is ingestion transport time.
    assert "T" in record.fetched_at


def test_phase9_github_repository_normalizes_to_existing_ontology_system(project_root):
    cfg, page = _fetch(project_root, "DS-ING-GITHUB")
    repo = next(r for r in page.records if r.record_type == "repository")
    out = normalizer_for(cfg).normalize("SRC", repo)
    assert len(out.entities) == 1
    assert out.entities[0].ontology_type == "System"
    assert out.entities[0].properties["system_type"] == "software_service"


def test_phase9_github_user_exposes_resolution_identity(project_root):
    cfg, page = _fetch(project_root, "DS-ING-GITHUB")
    user = next(r for r in page.records if r.record_type == "user")
    entity = normalizer_for(cfg).normalize("SRC", user).entities[0]
    assert entity.requires_resolution is True
    assert entity.identity["email"] == "neha.verma@northstar.example"


def test_phase9_jira_user_exposes_same_verified_email_for_cross_source_resolution(project_root):
    cfg, page = _fetch(project_root, "DS-ING-JIRA")
    user = next(r for r in page.records if r.record_type == "user")
    entity = normalizer_for(cfg).normalize("SRC", user).entities[0]
    assert entity.identity["email"] == "neha.verma@northstar.example"


def test_phase9_teams_contract_uses_person_not_source_specific_person_type(project_root):
    cfg, page = _fetch(project_root, "DS-ING-TEAMS")
    entity = normalizer_for(cfg).normalize("SRC", page.records[0]).entities[0]
    assert entity.ontology_type == "Person"
    assert "TeamsPerson" not in entity.ontology_type


def test_phase9_document_artifact_is_preserved_as_artifact_payload(project_root):
    cfg, page = _fetch(project_root, "DS-ING-DOCS")
    out = normalizer_for(cfg).normalize("SRC", page.records[0])
    assert len(out.artifacts) == 1
    assert out.artifacts[0].artifact_type == ArtifactType.DOCUMENT


def test_phase9_policy_mapping_keeps_owner_approval_requirement(project_root):
    cfg, page = _fetch(project_root, "DS-ING-DOCS")
    out = normalizer_for(cfg).normalize("SRC", page.records[0])
    policy = next(e for e in out.entities if e.ontology_type == "Policy")
    assert policy.properties["requires_owner_approval"] is True


def test_phase9_telemetry_creates_event_and_evidence_not_giant_log_node(project_root):
    cfg, page = _fetch(project_root, "DS-ING-TELEMETRY")
    out = normalizer_for(cfg).normalize("SRC", page.records[-1])
    assert {e.ontology_type for e in out.entities} >= {"Event", "Evidence", "System", "Incident"}
    assert all(e.ontology_type != "Log" for e in out.entities)


def test_phase9_database_mapping_uses_team_and_system_not_vendor_types(project_root):
    cfg, page = _fetch(project_root, "DS-ING-DATABASE")
    out = normalizer_for(cfg).normalize("SRC", page.records[0])
    assert {e.ontology_type for e in out.entities} == {"System", "Team"}


def test_phase9_internal_api_mapping_produces_dependency_candidate(project_root):
    cfg, page = _fetch(project_root, "DS-ING-INTERNAL")
    out = normalizer_for(cfg).normalize("SRC", page.records[0])
    assert any(r.rel_type == "DEPENDS_ON" for r in out.relations)


def test_phase9_normalized_record_carries_mapping_and_trust_versions(project_root):
    cfg, page = _fetch(project_root, "DS-ING-GITHUB")
    out = normalizer_for(cfg).normalize("SRC", page.records[0])
    assert out.mapping_version.startswith("github-map-")
    assert out.trust_metadata["trust_class"] == cfg.trust_class.value


def test_phase9_pipeline_rejects_unbounded_max_records(project_root, tmp_path):
    pipeline = IngestionPipeline(ReadOnlyEmptyClient(), registry=_registry(project_root), artifact_store=LocalArtifactStore(tmp_path))
    with pytest.raises(ValueError, match="max_records"):
        pipeline.sync("DS-ING-GITHUB", max_records=10001, dry_run=True)


def test_phase9_pipeline_rejects_unbounded_batch_size(project_root, tmp_path):
    pipeline = IngestionPipeline(ReadOnlyEmptyClient(), registry=_registry(project_root), artifact_store=LocalArtifactStore(tmp_path))
    with pytest.raises(ValueError, match="batch_size"):
        pipeline.sync("DS-ING-GITHUB", batch_size=501, dry_run=True)


def test_phase9_adapter_fetch_respects_limit(project_root):
    _, page = _fetch(project_root, "DS-ING-GITHUB", limit=2)
    assert len(page.records) == 2 and page.has_more is True


def test_phase9_artifact_delete_if_safe_removes_physical_payload(tmp_path):
    store = LocalArtifactStore(tmp_path)
    meta = store.put(ArtifactPayload(name="x", content="delete-me"), tenant_id="northstar", source_type="docs", source_record_id="S")
    assert store.exists(meta.artifact_id)
    assert store.delete_if_safe(meta.artifact_id) is True
    assert store.exists(meta.artifact_id) is False


def test_phase9_source_registry_rejects_unsupported_adapter_type():
    registry = SourceRegistry(None)
    cfg = SourceConfig(id="bad", source_type="ftp_magic", name="bad", source_instance="bad")
    with pytest.raises(ValueError, match="Unsupported source type"):
        registry.register(cfg, persist=False)


def test_phase9_record_checksum_changes_when_source_payload_changes(project_root):
    reg = _registry(project_root)
    _, adapter = reg.get("DS-ING-GITHUB")
    first = adapter.fetch(limit=1).records[0]
    changed = first.model_copy(update={"raw_metadata": {**first.raw_metadata, "display_name": "Changed Name"}})
    assert checksum_payload(changed.raw_metadata) != checksum_payload(first.raw_metadata)


def test_phase9_dry_run_proposes_existing_ontology_labels_only(project_root, tmp_path):
    from backend.app.graph.schema import NODE_LABELS
    pipeline = IngestionPipeline(ReadOnlyEmptyClient(), registry=_registry(project_root), artifact_store=LocalArtifactStore(tmp_path))
    report = pipeline.sync("DS-ING-JIRA", mode="full", max_records=2, dry_run=True)
    labels = {m.label_or_type for m in report.proposed_mutations if m.kind == "node"}
    assert labels <= NODE_LABELS


def test_phase9_dry_run_does_not_write_artifact_payloads(project_root, tmp_path):
    pipeline = IngestionPipeline(ReadOnlyEmptyClient(), registry=_registry(project_root), artifact_store=LocalArtifactStore(tmp_path))
    report = pipeline.sync("DS-ING-DOCS", mode="full", max_records=1, dry_run=True)
    assert report.status.value == "DRY_RUN"
    assert not list(tmp_path.rglob("payload.bin"))


def test_phase9_slack_normalizer_never_marks_claim_validated(project_root):
    cfg, page = _fetch(project_root, "DS-ING-SLACK")
    for record in [r for r in page.records if r.record_type == "message"]:
        claim = next(e for e in normalizer_for(cfg).normalize("SRC", record).entities if e.ontology_type == "Claim")
        assert claim.properties["status"] == "UNVERIFIED"


def test_phase9_database_adapter_contract_is_read_only(project_root):
    reg = _registry(project_root)
    _, adapter = reg.get("DS-ING-DATABASE")
    health = adapter.health_check()
    # fixture mode is not live; live implementation is explicitly read-only.
    assert health["live"] is False
    assert not hasattr(adapter, "execute_write")


def test_phase9_internal_api_has_no_user_supplied_url_in_sync_contract(project_root):
    cfg = next(c for c in fixture_source_configs(project_root) if c.source_type == "internal_api")
    assert cfg.base_url is None  # fixture verification
    assert "url" not in cfg.settings


def test_phase9_api_routes_exist_without_arbitrary_sql_or_url_ingestion():
    from backend.app.main import app
    paths = {route.path for route in app.routes}
    assert {"/ingestion/sources", "/ingestion/sources/{source_id}/sync", "/ingestion/runs", "/ingestion/quarantine", "/ingestion/artifacts/{artifact_id}"} <= paths
    assert all("sql" not in path.lower() and "url" not in path.lower() for path in paths if path.startswith("/ingestion"))


def test_apply_schema_script_uses_configured_falkordb_graph(monkeypatch, capsys):
    from types import SimpleNamespace
    from scripts import apply_schema as apply_schema_script

    class FakeClient:
        def __init__(self):
            self.settings = SimpleNamespace(falkordb_graph="phase9_test_graph", tenant_id="northstar")

    monkeypatch.setattr(apply_schema_script, "FalkorGraphClient", FakeClient)
    monkeypatch.setattr(apply_schema_script, "apply_schema", lambda client: None)

    apply_schema_script.main()

    assert capsys.readouterr().out.strip() == (
        "Schema applied to graph=phase9_test_graph tenant=northstar"
    )


def test_phase9_generated_source_record_ids_are_tenant_namespaced(project_root):
    cfg, page = _fetch(project_root, "DS-ING-GITHUB", limit=1)
    record = page.records[0]
    northstar = IngestionProvenanceService.source_record_id(cfg.id, record, tenant_id="northstar")
    other = IngestionProvenanceService.source_record_id(cfg.id, record, tenant_id="other-tenant")
    assert northstar != other
    assert northstar == IngestionProvenanceService.source_record_id(cfg.id, record, tenant_id="northstar")


def test_phase9_run_api_source_id_can_be_derived_from_provenance_edge():
    from backend.app.services.phase4_graph import GraphEdge, GraphSnapshot

    snapshot = GraphSnapshot(
        {
            "RUN-1": {"id": "RUN-1", "_labels": ["Entity", "IngestionRun"], "source_ref_id": "DS-1"},
            "DS-1": {"id": "DS-1", "_labels": ["Entity", "DataSource"]},
        },
        [GraphEdge("RUN-1", "DERIVED_FROM", "DS-1", {"valid_from": "2026-10-16T10:00:00+05:30"})],
    )
    result = IngestionPipeline._public_run(snapshot, snapshot.node("RUN-1"))
    assert result["source_id"] == "DS-1"
