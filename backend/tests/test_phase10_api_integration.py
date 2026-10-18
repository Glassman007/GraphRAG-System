from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import main as main_module
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.retrieval.models import IndexedDocument
from backend.app.retrieval.lexical import BM25LexicalIndex
from backend.app.retrieval.vector import LocalVectorIndex
from backend.app.retrieval.service import RetrievalService
from backend.app.retrieval.utils import content_hash

pytestmark = pytest.mark.integration


def _seed(client):
    upsert_node(client,"Incident","INC-P10-API",{"name":"Checkout failure","created_at":"2026-10-16T14:00:00+05:30"})
    upsert_node(client,"System","SYS-P10-API",{"name":"Pricing API"})
    upsert_node(client,"DataSource","DS-P10-API",{"name":"Pricing logs","source_type":"telemetry","trust_class":"STRONG"})
    upsert_node(client,"SourceRecord","SR-P10-API",{"name":"log record","source_type":"telemetry","source_id":"DS-P10-API","observed_at":"2026-10-16T14:08:14+05:30","raw_metadata":"region_scope cannot be null"})
    upsert_node(client,"Artifact","ART-P10-API",{"name":"pricing.log","sha256":content_hash("pricing.log"),"mime_type":"text/plain"})
    upsert_node(client,"Chunk","CH-P10-API",{"name":"error chunk","content_hash":content_hash("chunk")})
    upsert_relationship(client,"INC-P10-API","AFFECTS","SYS-P10-API",{"valid_from":"2026-10-16T14:00:00+05:30"})
    upsert_relationship(client,"SR-P10-API","NORMALIZED_TO","SYS-P10-API",{"valid_from":"2026-10-16T14:08:14+05:30"})
    upsert_relationship(client,"SR-P10-API","DERIVED_FROM","DS-P10-API",{"valid_from":"2026-10-16T14:08:14+05:30"})
    upsert_relationship(client,"SR-P10-API","REFERENCES","ART-P10-API",{"valid_from":"2026-10-16T14:08:14+05:30"})
    upsert_relationship(client,"CH-P10-API","PART_OF","ART-P10-API",{"valid_from":"2026-10-16T14:08:14+05:30"})


@pytest.fixture
def api(integration_client,monkeypatch):
    _seed(integration_client)
    lex=BM25LexicalIndex();vec=LocalVectorIndex();d=IndexedDocument(document_id="CH-P10-API",text="region_scope cannot be null after MIG-203",tenant_id=integration_client.settings.tenant_id,artifact_id="ART-P10-API",source_record_id="SR-P10-API",data_source_id="DS-P10-API",entity_ids=["SYS-P10-API"],document_type="CHUNK",observed_at="2026-10-16T14:08:14+05:30",content_hash=content_hash("api text"));lex.index_document(d);vec.index_document(d)
    service=RetrievalService(integration_client,lexical=lex,vector=vec)
    monkeypatch.setattr(main_module,"_client",lambda:integration_client)
    monkeypatch.setattr(main_module,"_retrieval_service",lambda:service)
    return TestClient(main_module.app)


def test_phase10_api_graph_scope_endpoint(api):
    r=api.post("/retrieval/graph-scope",json={"query":"Why fail?","seed_entity_ids":["INC-P10-API"],"writeback":False});assert r.status_code==200 and "SYS-P10-API" in r.json()["entities"]

def test_phase10_api_search_endpoint_exposes_scope_and_provenance(api):
    r=api.post("/retrieval/search",json={"query":"region_scope cannot be null","seed_entity_ids":["INC-P10-API"],"retrieval_modes":["LEXICAL"],"writeback":False});assert r.status_code==200;payload=r.json();assert payload["graph_required"] is True and payload["results"][0]["artifact_id"]=="ART-P10-API"

def test_phase10_api_lexical_endpoint(api):
    r=api.post("/retrieval/lexical",json={"query":"MIG-203","seed_entity_ids":["INC-P10-API"],"writeback":False});assert r.status_code==200 and r.json()["retrievers_used"][0]["retriever"]=="LEXICAL"

def test_phase10_api_vector_endpoint(api):
    r=api.post("/retrieval/vector",json={"query":"schema compatibility rollout","seed_entity_ids":["INC-P10-API"],"writeback":False});assert r.status_code==200 and r.json()["retrievers_used"][0]["retriever"]=="VECTOR"

def test_phase10_api_invalid_seed_returns_404(api):
    r=api.post("/retrieval/search",json={"query":"x","seed_entity_ids":["NO-SUCH-SEED"],"writeback":False});assert r.status_code==404

def test_phase10_api_tenant_mismatch_returns_422(api):
    r=api.post("/retrieval/search",json={"query":"x","tenant_id":"other","seed_entity_ids":["INC-P10-API"],"writeback":False});assert r.status_code==422

def test_phase10_api_max_result_validation(api):
    r=api.post("/retrieval/search",json={"query":"x","seed_entity_ids":["INC-P10-API"],"max_results":51});assert r.status_code==422

def test_phase10_api_execution_and_evidence_lookup(api):
    r=api.post("/retrieval/search",json={"query":"region_scope cannot be null","seed_entity_ids":["INC-P10-API"],"retrieval_modes":["LEXICAL"],"investigation_id":"INC-P10-API","writeback":True});assert r.status_code==200;payload=r.json();assert payload["execution_id"] and payload["evidence_ids"]
    assert api.get(f"/retrieval/executions/{payload['execution_id']}").status_code==200
    assert api.get(f"/retrieval/evidence/{payload['evidence_ids'][0]}").status_code==200

def test_phase10_api_index_rebuild_reads_phase9_artifact_store(integration_client, tmp_path, monkeypatch):
    from backend.app.ingestion.artifacts.local import LocalArtifactStore
    from backend.app.ingestion.models import ArtifactPayload, ArtifactType

    _seed(integration_client)
    artifact_root = tmp_path / "artifacts"
    retrieval_root = tmp_path / "retrieval"
    store = LocalArtifactStore(artifact_root)
    meta = store.put(
        ArtifactPayload(
            name="pricing-rebuild.log",
            content="14:08:14 ERROR region_scope cannot be null after MIG-203",
            mime_type="text/plain",
            artifact_type=ArtifactType.LOG,
        ),
        tenant_id=integration_client.settings.tenant_id,
        source_type="telemetry",
        source_record_id="SR-P10-API",
    )
    upsert_node(integration_client, "Artifact", meta.artifact_id, meta.model_dump(mode="json"))
    upsert_relationship(
        integration_client,
        "SR-P10-API",
        "REFERENCES",
        meta.artifact_id,
        {"valid_from": "2026-10-16T14:08:14+05:30"},
    )
    monkeypatch.setenv("GRAPH_HACKS_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setenv("GRAPH_HACKS_RETRIEVAL_ROOT", str(retrieval_root))
    monkeypatch.setattr(main_module, "_client", lambda: integration_client)
    api = TestClient(main_module.app)

    response = api.post("/retrieval/index/rebuild")
    assert response.status_code == 200
    assert response.json()["chunks_indexed"] >= 1

    rebuilt = BM25LexicalIndex(retrieval_root / integration_client.settings.tenant_id / "lexical.json")
    results = rebuilt.search(
        "region_scope cannot be null",
        tenant_id=integration_client.settings.tenant_id,
        allowed_artifact_ids={meta.artifact_id},
        limit=5,
    )
    assert results
    assert results[0].artifact_id == meta.artifact_id
    rebuilt_vector = LocalVectorIndex(path=retrieval_root / integration_client.settings.tenant_id / "vector.json")
    vector_results = rebuilt_vector.search(
        "schema field missing after migration",
        tenant_id=integration_client.settings.tenant_id,
        allowed_artifact_ids={meta.artifact_id},
        limit=5,
    )
    assert vector_results
    assert vector_results[0].artifact_id == meta.artifact_id
