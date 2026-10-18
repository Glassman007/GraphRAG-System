from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.app.api_v1.router as v1_router
from backend.app.main import app

pytestmark=pytest.mark.integration
ADMIN={"Authorization":"Bearer test-admin-token","X-Tenant-ID":"northstar"}
READER={"Authorization":"Bearer test-reader-token","X-Tenant-ID":"northstar"}

@pytest.fixture
def phase13_api(integration_client,monkeypatch,tmp_path):
    monkeypatch.setattr(v1_router,"client_for",lambda principal:integration_client)
    monkeypatch.setenv("GRAPH_HACKS_CREDENTIAL_ROOT",str(tmp_path/"credentials"))
    monkeypatch.setenv("GRAPH_HACKS_ARTIFACT_ROOT",str(tmp_path/"artifacts"))
    monkeypatch.setenv("GRAPH_HACKS_RETRIEVAL_ROOT",str(tmp_path/"retrieval"))
    return TestClient(app)


def create_fixture_source(api,name="Phase13 GitHub"):
    r=api.post("/api/v1/sources",headers=ADMIN,json={"display_name":name,"connector_type":"github","connection_mode":"fixture","scope_config":{"repositories":["pricing-service"]},"expected_sync_interval_minutes":60})
    assert r.status_code==201,r.text
    return r.json()["source_id"]


def test_phase13_connector_definitions(phase13_api):
    r=phase13_api.get("/api/v1/connectors",headers=ADMIN);assert r.status_code==200
    assert {x["connector_type"] for x in r.json()["items"]}>={"github","jira","slack","database","documents","telemetry"}


def test_phase13_reader_cannot_manage_sources(phase13_api):
    assert phase13_api.get("/api/v1/sources",headers=READER).status_code==403


def test_phase13_create_source_never_echoes_secret(phase13_api):
    r=phase13_api.post("/api/v1/sources",headers=ADMIN,json={"display_name":"Secret GitHub","connector_type":"github","connection_mode":"fixture","credentials":{"token":"do-not-return"}})
    assert r.status_code==201
    assert "do-not-return" not in r.text
    assert r.json()["credential"]["configured"] is True


def test_phase13_test_connection_does_not_ingest(phase13_api,integration_client):
    sid=create_fixture_source(phase13_api,"Connection Test GitHub")
    before=integration_client.read("MATCH (n:Entity {tenant_id:$tenant_id}) RETURN count(n)",{"tenant_id":"northstar"}).result_set[0][0]
    r=phase13_api.post(f"/api/v1/sources/{sid}/test",headers=ADMIN);assert r.status_code==200;assert r.json()["status"]=="HEALTHY"
    after=integration_client.read("MATCH (n:Entity {tenant_id:$tenant_id}) RETURN count(n)",{"tenant_id":"northstar"}).result_set[0][0]
    # Connection audit/source health may update existing nodes, but no SourceRecord should be created.
    sr=integration_client.read("MATCH (n:Entity:SourceRecord {tenant_id:$tenant_id,source_id:$sid}) RETURN count(n)",{"tenant_id":"northstar","sid":sid}).result_set[0][0]
    assert sr==0 and after>=before


def test_phase13_preview_is_write_free_for_canonical_source_records(phase13_api,integration_client):
    sid=create_fixture_source(phase13_api,"Preview GitHub")
    before=integration_client.read("MATCH (n:Entity:SourceRecord {tenant_id:$tenant_id,source_id:$sid}) RETURN count(n)",{"tenant_id":"northstar","sid":sid}).result_set[0][0]
    r=phase13_api.post(f"/api/v1/sources/{sid}/preview",headers=ADMIN,json={"max_records":3});assert r.status_code==200
    assert r.json()["dry_run"] is True and r.json()["canonical_graph_mutated"] is False
    after=integration_client.read("MATCH (n:Entity:SourceRecord {tenant_id:$tenant_id,source_id:$sid}) RETURN count(n)",{"tenant_id":"northstar","sid":sid}).result_set[0][0]
    assert before==after==0


def test_phase13_manual_sync_and_run_history(phase13_api):
    sid=create_fixture_source(phase13_api,"Sync GitHub")
    r=phase13_api.post(f"/api/v1/sources/{sid}/sync",headers=ADMIN,json={"mode":"full","max_records":3});assert r.status_code==200,r.text
    assert r.json()["status"] in {"SUCCEEDED","PARTIAL"}
    runs=phase13_api.get(f"/api/v1/sources/{sid}/runs",headers=ADMIN).json()["items"]
    assert runs and runs[0]["source_ref_id"]==sid
    detail=phase13_api.get(f"/api/v1/sources/runs/{runs[0]['id']}",headers=ADMIN);assert detail.status_code==200;assert "funnel" in detail.json()


def test_phase13_source_records_are_human_browseable(phase13_api):
    sid=create_fixture_source(phase13_api,"Records GitHub");phase13_api.post(f"/api/v1/sources/{sid}/sync",headers=ADMIN,json={"mode":"full","max_records":3})
    r=phase13_api.get(f"/api/v1/sources/{sid}/records",headers=ADMIN);assert r.status_code==200
    assert r.json()["items"] and "interpreted_as" in r.json()["items"][0]


def test_phase13_disable_preserves_source_records(phase13_api):
    sid=create_fixture_source(phase13_api,"Disable GitHub");phase13_api.post(f"/api/v1/sources/{sid}/sync",headers=ADMIN,json={"mode":"full","max_records":3})
    before=phase13_api.get(f"/api/v1/sources/{sid}/records",headers=ADMIN).json()["total"]
    r=phase13_api.post(f"/api/v1/sources/{sid}/disable",headers=ADMIN);assert r.status_code==200 and r.json()["enabled"] is False
    after=phase13_api.get(f"/api/v1/sources/{sid}/records",headers=ADMIN).json()["total"]
    assert after==before and before>0
    assert phase13_api.post(f"/api/v1/sources/{sid}/sync",headers=ADMIN,json={"mode":"incremental","max_records":3}).status_code==422


def test_phase13_enable_after_disable(phase13_api):
    sid=create_fixture_source(phase13_api,"Enable GitHub");phase13_api.post(f"/api/v1/sources/{sid}/disable",headers=ADMIN)
    r=phase13_api.post(f"/api/v1/sources/{sid}/enable",headers=ADMIN);assert r.status_code==200;assert r.json()["enabled"] is True


def test_phase13_entity_lineage_after_sync(phase13_api):
    sid=create_fixture_source(phase13_api,"Lineage GitHub");phase13_api.post(f"/api/v1/sources/{sid}/sync",headers=ADMIN,json={"mode":"full","max_records":3})
    r=phase13_api.get("/api/v1/lineage/entities/SYS-PRICING-API",headers=READER);assert r.status_code==200
    assert r.json()["complete"] is True
    assert any(x["source"]["id"]==sid for x in r.json()["lineage"])


def test_phase13_mapping_preview(phase13_api):
    sid=create_fixture_source(phase13_api,"Mapping GitHub")
    r=phase13_api.get(f"/api/v1/sources/{sid}/mapping",headers=ADMIN);assert r.status_code==200
    assert any(x["external"]=="Repository" and x["canonical"]=="System" for x in r.json()["mappings"])
