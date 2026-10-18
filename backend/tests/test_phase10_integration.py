from __future__ import annotations

import json
from pathlib import Path
import pytest

from backend.app.graph.mutations import upsert_node, upsert_relationship, delete_relationship
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.retrieval.models import IndexedDocument, RetrievalMode, RetrievalRequest
from backend.app.retrieval.lexical import BM25LexicalIndex
from backend.app.retrieval.vector import LocalVectorIndex
from backend.app.retrieval.service import RetrievalService
from backend.app.retrieval.indexing import RetrievalIndexer
from backend.app.retrieval.chunking import DocumentChunker
from backend.app.retrieval.utils import content_hash
from backend.app.ingestion.artifacts.local import LocalArtifactStore
from backend.app.ingestion.models import ArtifactPayload, ArtifactType, SourceConfig, TrustClass
from backend.app.ingestion.pipeline import IngestionPipeline
from backend.app.ingestion.registry import SourceRegistry, fixture_source_configs

pytestmark = pytest.mark.integration


def _seed_scope(client, prefix="P10", *, observed_at="2026-10-16T14:08:14+05:30", source_type="telemetry", trust="STRONG"):
    incident=f"INC-{prefix}";system=f"SYS-{prefix}";source=f"DS-{prefix}";record=f"SR-{prefix}";artifact=f"ART-{prefix}";chunk=f"CH-{prefix}"
    upsert_node(client,"Incident",incident,{"name":f"{prefix} incident","created_at":"2026-10-16T14:00:00+05:30"})
    upsert_node(client,"System",system,{"name":f"{prefix} system"})
    upsert_node(client,"DataSource",source,{"name":f"{prefix} source","source_type":source_type,"trust_class":trust})
    upsert_node(client,"SourceRecord",record,{"name":f"{prefix} record","source_type":source_type,"source_id":source,"record_type":"log","observed_at":observed_at,"raw_metadata":"region_scope cannot be null after MIG-203"})
    upsert_node(client,"Artifact",artifact,{"name":f"{prefix}.log","mime_type":"text/plain","sha256":content_hash(prefix),"source_record_id":record})
    upsert_node(client,"Chunk",chunk,{"name":"error chunk","content_hash":content_hash(prefix+"chunk"),"created_at":observed_at})
    upsert_relationship(client,incident,"AFFECTS",system,{"valid_from":"2026-10-16T14:00:00+05:30"})
    upsert_relationship(client,record,"NORMALIZED_TO",system,{"valid_from":observed_at})
    upsert_relationship(client,record,"DERIVED_FROM",source,{"valid_from":observed_at})
    upsert_relationship(client,record,"REFERENCES",artifact,{"valid_from":observed_at})
    upsert_relationship(client,chunk,"PART_OF",artifact,{"valid_from":observed_at})
    return {"incident":incident,"system":system,"source":source,"record":record,"artifact":artifact,"chunk":chunk}


def _indexes(ids, *, tenant="northstar", text="region_scope cannot be null after MIG-203", observed="2026-10-16T14:08:14+05:30"):
    lex=BM25LexicalIndex();vec=LocalVectorIndex()
    d=IndexedDocument(document_id=ids["chunk"],text=text,tenant_id=tenant,artifact_id=ids["artifact"],source_record_id=ids["record"],data_source_id=ids["source"],entity_ids=[ids["system"]],document_type="CHUNK",observed_at=observed,content_hash=content_hash(text),metadata={"trust_class":"STRONG"})
    lex.index_document(d);vec.index_document(d);return lex,vec


def _request(client, ids, **kwargs):
    base=dict(query="region_scope cannot be null",tenant_id=client.settings.tenant_id,seed_entity_ids=[ids["incident"]],max_graph_hops=5,max_results=10,writeback=False)
    base.update(kwargs);return RetrievalRequest(**base)


def test_phase10_graph_scope_uses_falkordb_paths(integration_client):
    ids=_seed_scope(integration_client,"SCOPE")
    scope=RetrievalService(integration_client,lexical=BM25LexicalIndex(),vector=LocalVectorIndex()).graph_scope(_request(integration_client,ids))
    assert ids["system"] in scope.entities and ids["artifact"] in scope.artifacts and ids["source"] in scope.data_sources and ids["chunk"] in scope.chunks


def test_phase10_lexical_graph_scope_excludes_out_of_scope_exact_distractor(integration_client):
    ids=_seed_scope(integration_client,"LEXGOOD");other=_seed_scope(integration_client,"LEXBAD")
    lex,vec=_indexes(ids)
    bad=IndexedDocument(document_id=other["chunk"],text="region_scope cannot be null "*30,tenant_id=integration_client.settings.tenant_id,artifact_id=other["artifact"],source_record_id=other["record"],data_source_id=other["source"],entity_ids=[other["system"]],document_type="CHUNK",content_hash=content_hash("bad"))
    lex.index_document(bad);vec.index_document(bad)
    out=RetrievalService(integration_client,lexical=lex,vector=vec).search(_request(integration_client,ids,retrieval_modes=[RetrievalMode.LEXICAL]))
    assert [r.document_id for r in out.results]==[ids["chunk"]]


def test_phase10_vector_graph_scope_excludes_semantic_distractor(integration_client):
    ids=_seed_scope(integration_client,"VGOOD");other=_seed_scope(integration_client,"VBAD")
    lex=BM25LexicalIndex();vec=LocalVectorIndex()
    good=IndexedDocument(document_id=ids["chunk"],text="old worker rejected after database constraint migration",tenant_id=integration_client.settings.tenant_id,artifact_id=ids["artifact"],source_record_id=ids["record"],data_source_id=ids["source"],entity_ids=[ids["system"]],document_type="CHUNK",content_hash=content_hash("good"))
    bad=IndexedDocument(document_id=other["chunk"],text="legacy client incompatible with schema rollout migration",tenant_id=integration_client.settings.tenant_id,artifact_id=other["artifact"],source_record_id=other["record"],data_source_id=other["source"],entity_ids=[other["system"]],document_type="CHUNK",content_hash=content_hash("bad2"))
    for d in (good,bad):lex.index_document(d);vec.index_document(d)
    req=_request(integration_client,ids,query="schema compatibility during mixed rollout",retrieval_modes=[RetrievalMode.VECTOR])
    out=RetrievalService(integration_client,lexical=lex,vector=vec).search(req)
    assert out.results and out.results[0].document_id==ids["chunk"] and all(r.document_id!=other["chunk"] for r in out.results)


def test_phase10_remove_graph_relationship_removes_artifact_scope(integration_client):
    ids=_seed_scope(integration_client,"NECESSITY")
    service=RetrievalService(integration_client,lexical=BM25LexicalIndex(),vector=LocalVectorIndex())
    assert ids["artifact"] in service.graph_scope(_request(integration_client,ids)).artifacts
    assert delete_relationship(integration_client,ids["record"],"REFERENCES",ids["artifact"])>=1
    assert ids["artifact"] not in service.graph_scope(_request(integration_client,ids)).artifacts


def test_phase10_remove_incident_system_relation_materially_changes_scope(integration_client):
    ids=_seed_scope(integration_client,"NECESSITY2")
    service=RetrievalService(integration_client,lexical=BM25LexicalIndex(),vector=LocalVectorIndex())
    assert ids["source"] in service.graph_scope(_request(integration_client,ids)).data_sources
    assert delete_relationship(integration_client,ids["incident"],"AFFECTS",ids["system"])>=1
    assert ids["source"] not in service.graph_scope(_request(integration_client,ids)).data_sources


def test_phase10_temporal_e003_visible_e004_invisible_at_1409(integration_client):
    a=_seed_scope(integration_client,"T3",observed_at="2026-10-16T14:08:14+05:30")
    b=_seed_scope(integration_client,"T4",observed_at="2026-10-16T14:12:00+05:30")
    # Connect both records to one historical query incident/system scope.
    upsert_relationship(integration_client,b["record"],"NORMALIZED_TO",a["system"],{"valid_from":"2026-10-16T14:12:00+05:30"})
    lex,vec=_indexes(a,observed="2026-10-16T14:08:14+05:30")
    future=IndexedDocument(document_id=b["chunk"],text="region_scope cannot be null later",tenant_id=integration_client.settings.tenant_id,artifact_id=b["artifact"],source_record_id=b["record"],data_source_id=b["source"],entity_ids=[a["system"]],document_type="CHUNK",observed_at="2026-10-16T14:12:00+05:30",content_hash=content_hash("future"));lex.index_document(future);vec.index_document(future)
    req=_request(integration_client,a,as_of="2026-10-16T14:09:00+05:30",retrieval_modes=[RetrievalMode.LEXICAL])
    ids=[r.document_id for r in RetrievalService(integration_client,lexical=lex,vector=vec).search(req).results]
    assert a["chunk"] in ids and b["chunk"] not in ids


def test_phase10_retrieved_evidence_written_back_with_provenance(integration_client):
    ids=_seed_scope(integration_client,"WB");lex,vec=_indexes(ids)
    upsert_node(integration_client,"Task","TASK-P10-WB",{"name":"retrieve","status":"OPEN","created_at":"2026-10-16T14:00:00+05:30"})
    upsert_node(integration_client,"Agent","AGENT-P10-WB",{"name":"retriever","status":"ACTIVE"})
    req=_request(integration_client,ids,task_id="TASK-P10-WB",investigation_id=ids["incident"],requesting_agent_id="AGENT-P10-WB",writeback=True,retrieval_modes=[RetrievalMode.LEXICAL])
    out=RetrievalService(integration_client,lexical=lex,vector=vec).search(req)
    assert out.execution_id and out.evidence_ids
    snap=GraphSnapshot.load(integration_client);eid=out.evidence_ids[0]
    assert has_label(snap.node(out.execution_id),"RetrievalExecution") and has_label(snap.node(eid),"Evidence")
    assert (snap.node(eid) or {}).get("status")=="UNVERIFIED"
    assert any(e.target==ids["chunk"] for e in snap.edges_from(eid,{"DERIVED_FROM"}))
    assert any(e.target==ids["artifact"] for e in snap.edges_from(eid,{"DERIVED_FROM"}))
    assert any(e.target==ids["record"] for e in snap.edges_from(eid,{"DERIVED_FROM"}))
    assert any(e.target==ids["source"] for e in snap.edges_from(eid,{"DERIVED_FROM"}))
    assert any(e.target=="TASK-P10-WB" for e in snap.edges_from(eid,{"ABOUT"}))
    assert any(e.target==ids["incident"] for e in snap.edges_from(eid,{"ABOUT"}))
    assert any(e.target=="AGENT-P10-WB" for e in snap.edges_from(out.execution_id,{"REQUESTED_BY"}))
    assert any(e.target==eid for e in snap.edges_from("AGENT-P10-WB",{"PRODUCED"}))


def test_phase10_duplicate_retrieval_writeback_is_idempotent(integration_client):
    ids=_seed_scope(integration_client,"IDEMP");lex,vec=_indexes(ids);service=RetrievalService(integration_client,lexical=lex,vector=vec)
    req=_request(integration_client,ids,investigation_id=ids["incident"],writeback=True,retrieval_modes=[RetrievalMode.LEXICAL])
    a=service.search(req);b=service.search(req)
    assert a.execution_id==b.execution_id and a.evidence_ids==b.evidence_ids
    snap=GraphSnapshot.load(integration_client)
    assert len([n for n in snap.nodes.values() if has_label(n,"RetrievalExecution") and n.get("id")==a.execution_id])==1
    assert len(snap.edges_from(a.execution_id,{"RETURNED"}))==len(a.evidence_ids)
    assert len([e for e in snap.edges_from(ids["incident"],{"HAS_RETRIEVAL"}) if e.target==a.execution_id])==1
    for eid in a.evidence_ids:
        assert len([e for e in snap.edges_from(eid,{"ABOUT"}) if e.target==ids["incident"]])==1


def test_phase10_retrieval_evidence_does_not_auto_validate_claim(integration_client):
    ids=_seed_scope(integration_client,"TRUST");lex,vec=_indexes(ids)
    upsert_node(integration_client,"Claim","CLAIM-P10",{"statement":"migration caused outage","status":"OPEN","created_at":"2026-10-16T14:00:00+05:30"})
    RetrievalService(integration_client,lexical=lex,vector=vec).search(_request(integration_client,ids,writeback=True,retrieval_modes=[RetrievalMode.LEXICAL]))
    assert (GraphSnapshot.load(integration_client).node("CLAIM-P10") or {}).get("status")=="OPEN"


def test_phase10_sql_routing_requires_graph_selected_database_source(integration_client):
    ids=_seed_scope(integration_client,"SQL",source_type="database",trust="AUTHORITATIVE");lex,vec=_indexes(ids)
    req=_request(integration_client,ids,query="What status is recorded?",writeback=False)
    out=RetrievalService(integration_client,lexical=lex,vector=vec).search(req)
    assert any(x["retriever"]=="SQL" for x in out.retrievers_used)


def test_phase10_api_routing_requires_graph_selected_api_source(integration_client):
    ids=_seed_scope(integration_client,"API",source_type="internal_api",trust="AUTHORITATIVE");lex,vec=_indexes(ids)
    out=RetrievalService(integration_client,lexical=lex,vector=vec).search(_request(integration_client,ids,query="What status is recorded?",writeback=False))
    assert any(x["retriever"]=="API" for x in out.retrievers_used)


def test_phase10_hybrid_results_are_deduplicated(integration_client):
    ids=_seed_scope(integration_client,"HYBRID");lex,vec=_indexes(ids)
    req=_request(integration_client,ids,query="Why did region scope migration fail?",retrieval_modes=[RetrievalMode.LEXICAL,RetrievalMode.VECTOR])
    out=RetrievalService(integration_client,lexical=lex,vector=vec).search(req)
    keys=[r.document_id for r in out.results];assert len(keys)==len(set(keys))


def test_phase10_authority_tiebreak_does_not_hide_lower_authority(integration_client):
    a=_seed_scope(integration_client,"AUTH-A",trust="AUTHORITATIVE");b=_seed_scope(integration_client,"AUTH-B",trust="UNTRUSTED")
    # Attach both source records to A's system so both are graph relevant.
    upsert_relationship(integration_client,b["record"],"NORMALIZED_TO",a["system"],{"valid_from":"2026-10-16T14:08:14+05:30"})
    lex=BM25LexicalIndex();vec=LocalVectorIndex()
    for ids in (a,b):
        d=IndexedDocument(document_id=ids["chunk"],text="same contradictory error evidence",tenant_id=integration_client.settings.tenant_id,artifact_id=ids["artifact"],source_record_id=ids["record"],data_source_id=ids["source"],entity_ids=[a["system"]],document_type="CHUNK",content_hash=content_hash(ids["chunk"]));lex.index_document(d);vec.index_document(d)
    out=RetrievalService(integration_client,lexical=lex,vector=vec).search(_request(integration_client,a,query="same contradictory error evidence",retrieval_modes=[RetrievalMode.LEXICAL]))
    assert {r.document_id for r in out.results}=={a["chunk"],b["chunk"]}
    assert out.results[0].source_id==a["source"]


def test_phase10_indexer_creates_chunk_nodes_and_indexes_artifact(integration_client,tmp_path):
    payload=ArtifactPayload(name="policy.md",content="# Compatibility\nBackward compatibility required\nregion_scope cannot be null",mime_type="text/markdown",artifact_type=ArtifactType.DOCUMENT)
    store=LocalArtifactStore(tmp_path/"art")
    meta=store.put(payload,tenant_id=integration_client.settings.tenant_id,source_type="documents",source_record_id="SR-P10-IDX")
    upsert_node(integration_client,"DataSource","DS-P10-IDX",{"name":"docs","source_type":"documents"})
    upsert_node(integration_client,"SourceRecord","SR-P10-IDX",{"name":"doc","source_type":"documents","source_id":"DS-P10-IDX","observed_at":"2026-10-16T10:00:00+05:30","raw_metadata":"policy"})
    upsert_node(integration_client,"Artifact",meta.artifact_id,meta.model_dump(mode="json"))
    upsert_relationship(integration_client,"SR-P10-IDX","DERIVED_FROM","DS-P10-IDX",{"valid_from":"2026-10-16T10:00:00+05:30"})
    upsert_relationship(integration_client,"SR-P10-IDX","REFERENCES",meta.artifact_id,{"valid_from":"2026-10-16T10:00:00+05:30"})
    lex=BM25LexicalIndex();vec=LocalVectorIndex();indexer=RetrievalIndexer(integration_client,lexical=lex,vector=vec,artifact_store=store)
    chunks=indexer.index_artifact(meta.artifact_id);assert chunks and all(ch in lex.documents and ch in vec.documents for ch in chunks)
    snap=GraphSnapshot.load(integration_client);assert all(has_label(snap.node(ch),"Chunk") and any(e.target==meta.artifact_id for e in snap.edges_from(ch,{"PART_OF"})) for ch in chunks)


def test_phase10_phase9_ingestion_can_auto_index_artifacts(project_root,integration_client,tmp_path):
    base={c.source_type:c for c in fixture_source_configs(project_root)}["telemetry"].model_copy(deep=True);base.id="DS-P10-AUTOINDEX";base.source_instance="p10-auto"
    reg=SourceRegistry(integration_client);reg.register(base,persist=False)
    store=LocalArtifactStore(tmp_path/"auto-art");lex=BM25LexicalIndex();vec=LocalVectorIndex();indexer=RetrievalIndexer(integration_client,lexical=lex,vector=vec,artifact_store=store)
    report=IngestionPipeline(integration_client,registry=reg,artifact_store=store,retrieval_indexer=indexer).sync(base.id,mode="full",max_records=10)
    assert report.status.value=="SUCCEEDED" and report.artifacts>=1 and any(d.artifact_id for d in lex.documents.values())


def test_phase10_phase9_unchanged_reingestion_does_not_duplicate_index(project_root,integration_client,tmp_path):
    base={c.source_type:c for c in fixture_source_configs(project_root)}["telemetry"].model_copy(deep=True);base.id="DS-P10-REINDEX";base.source_instance="p10-reindex"
    reg=SourceRegistry(integration_client);reg.register(base,persist=False);store=LocalArtifactStore(tmp_path/"re-art");lex=BM25LexicalIndex();vec=LocalVectorIndex();idx=RetrievalIndexer(integration_client,lexical=lex,vector=vec,artifact_store=store);pipe=IngestionPipeline(integration_client,registry=reg,artifact_store=store,retrieval_indexer=idx)
    pipe.sync(base.id,mode="full",max_records=10);before=set(lex.documents);pipe.sync(base.id,mode="full",max_records=10);assert set(lex.documents)==before


def test_phase10_source_update_preserves_historical_index_version(integration_client):
    ids=_seed_scope(integration_client,"VERS");lex,vec=_indexes(ids);old=lex.documents[ids["chunk"]];lex.index_document(old.model_copy(update={"valid_until":"2026-10-16T15:00:00+05:30"}));vec.index_document(old.model_copy(update={"valid_until":"2026-10-16T15:00:00+05:30"}))
    assert lex.search("region_scope",tenant_id=integration_client.settings.tenant_id)==[]
    assert lex.search("region_scope",tenant_id=integration_client.settings.tenant_id,as_of="2026-10-16T14:30:00+05:30")


def test_phase10_execution_exposes_used_source(integration_client):
    ids=_seed_scope(integration_client,"USEDSOURCE");lex,vec=_indexes(ids);out=RetrievalService(integration_client,lexical=lex,vector=vec).search(_request(integration_client,ids,writeback=True,retrieval_modes=[RetrievalMode.LEXICAL]));snap=GraphSnapshot.load(integration_client);assert any(e.target==ids["source"] for e in snap.edges_from(out.execution_id,{"USED_SOURCE"}))


def test_phase10_graph_scope_tenant_mismatch_rejected(integration_client):
    ids=_seed_scope(integration_client,"TENANT")
    req=_request(integration_client,ids,tenant_id="other-tenant")
    with pytest.raises(ValueError,match="tenant_id"):
        RetrievalService(integration_client,lexical=BM25LexicalIndex(),vector=LocalVectorIndex()).graph_scope(req)


def test_phase10_max_results_respected(integration_client):
    ids=_seed_scope(integration_client,"LIMIT");lex,vec=_indexes(ids)
    for i in range(5):
        d=IndexedDocument(document_id=f"EXTRA-{i}",text="region_scope cannot be null",tenant_id=integration_client.settings.tenant_id,artifact_id=ids["artifact"],source_record_id=ids["record"],data_source_id=ids["source"],entity_ids=[ids["system"]],content_hash=content_hash(str(i)));lex.index_document(d)
    out=RetrievalService(integration_client,lexical=lex,vector=vec).search(_request(integration_client,ids,max_results=2,retrieval_modes=[RetrievalMode.LEXICAL]));assert len(out.results)<=2


def test_phase10_knowledge_gap_can_flow_into_active_retrieval(integration_client):
    from backend.app.services.knowledge_gap_service import KnowledgeGapService
    from backend.app.services.evidence_acquisition_service import EvidenceAcquisitionService
    ids=_seed_scope(integration_client,"KG")
    upsert_node(integration_client,"Question","Q-P10-KG",{"text":"Was backward compatibility testing performed?","status":"OPEN","created_at":"2026-10-16T14:00:00+05:30"})
    upsert_relationship(integration_client,"Q-P10-KG","ABOUT",ids["incident"],{"valid_from":"2026-10-16T14:00:00+05:30"})
    upsert_relationship(integration_client,"Q-P10-KG","ABOUT",ids["system"],{"valid_from":"2026-10-16T14:00:00+05:30"})
    upsert_relationship(integration_client,"Q-P10-KG","REQUIRES",ids["source"],{"valid_from":"2026-10-16T14:00:00+05:30","capability":"lexical"})
    gaps=KnowledgeGapService(integration_client).detect_for_incident(ids["incident"])
    assert any((g.get("question") or {}).get("id")=="Q-P10-KG" for g in gaps["gaps"])
    lex,vec=_indexes(ids,text="backward compatibility test was skipped")
    bridge=EvidenceAcquisitionService(integration_client,retrieval_service=RetrievalService(integration_client,lexical=lex,vector=vec))
    result=bridge.retrieve_question("Q-P10-KG",max_results=5,writeback=True)
    assert result["phase10_retrieval"]["evidence_ids"]


def test_phase10_retrieved_evidence_can_be_consumed_by_existing_relational_investigation(integration_client):
    from backend.app.services.investigation_service import RelationalInvestigationService
    incident="INC-P10-INV";s1="SYS-P10-INV-A";s2="SYS-P10-INV-B";change="CHG-P10-INV"
    upsert_node(integration_client,"Incident",incident,{"name":"retrieval investigation","created_at":"2026-10-16T14:00:00+05:30"})
    upsert_node(integration_client,"System",s1,{"name":"frontend"});upsert_node(integration_client,"System",s2,{"name":"database"});upsert_node(integration_client,"Change",change,{"name":"schema migration"})
    upsert_relationship(integration_client,s1,"DEPENDS_ON",s2,{"valid_from":"2026-10-16T13:00:00+05:30"});upsert_relationship(integration_client,change,"AFFECTS",s2,{"valid_from":"2026-10-16T14:00:00+05:30"})
    ids=_seed_scope(integration_client,"INV")
    # Re-point retrieval material to the custom incident/system.
    upsert_relationship(integration_client,incident,"AFFECTS",s1,{"valid_from":"2026-10-16T14:00:00+05:30"});upsert_relationship(integration_client,ids["record"],"NORMALIZED_TO",s1,{"valid_from":"2026-10-16T14:08:14+05:30"})
    lex=BM25LexicalIndex();vec=LocalVectorIndex();text="schema migration broke region_scope compatibility"
    d=IndexedDocument(document_id=ids["chunk"],text=text,tenant_id=integration_client.settings.tenant_id,artifact_id=ids["artifact"],source_record_id=ids["record"],data_source_id=ids["source"],entity_ids=[s1,change],document_type="CHUNK",content_hash=content_hash(text));lex.index_document(d);vec.index_document(d)
    req=RetrievalRequest(query="schema migration compatibility",tenant_id=integration_client.settings.tenant_id,seed_entity_ids=[incident],investigation_id=incident,max_graph_hops=5,retrieval_modes=[RetrievalMode.LEXICAL],writeback=True)
    out=RetrievalService(integration_client,lexical=lex,vector=vec).search(req);assert out.evidence_ids
    result=RelationalInvestigationService(integration_client).investigate_incident(incident)
    assert result and any(out.evidence_ids[0] in {e["id"] for e in path["evidence"]} for path in result["candidate_paths"])


def test_phase10_phase7_can_later_promote_validated_work_grounded_in_retrieved_evidence(integration_client):
    from backend.app.services.memory_promotion_service import MemoryPromotionService
    ids=_seed_scope(integration_client,"P7");lex,vec=_indexes(ids)
    out=RetrievalService(integration_client,lexical=lex,vector=vec).search(_request(integration_client,ids,writeback=True,retrieval_modes=[RetrievalMode.LEXICAL]));eid=out.evidence_ids[0]
    upsert_node(integration_client,"Finding","F-P10-P7",{"statement":"retrieved compatibility evidence supports root cause","status":"VALIDATED","confidence":0.9,"created_at":"2026-10-16T14:20:00+05:30"})
    upsert_node(integration_client,"Person","P-P10-VERIFIER",{"name":"Verifier"})
    upsert_relationship(integration_client,"F-P10-P7","DERIVED_FROM",eid,{"valid_from":"2026-10-16T14:20:00+05:30"})
    upsert_relationship(integration_client,"F-P10-P7","VALIDATED_BY","P-P10-VERIFIER",{"valid_from":"2026-10-16T14:20:00+05:30"})
    upsert_relationship(integration_client,"F-P10-P7","ABOUT",ids["system"],{"valid_from":"2026-10-16T14:20:00+05:30"})
    result=MemoryPromotionService(integration_client).promote_artifact("F-P10-P7")
    assert result["status"]=="PROMOTED" and result["claim_id"]


def test_phase10_remove_evidence_provenance_breaks_explanation_path(integration_client):
    ids=_seed_scope(integration_client,"EVIDNEC");lex,vec=_indexes(ids)
    out=RetrievalService(integration_client,lexical=lex,vector=vec).search(_request(integration_client,ids,investigation_id=ids["incident"],writeback=True,retrieval_modes=[RetrievalMode.LEXICAL]));eid=out.evidence_ids[0]
    snap=GraphSnapshot.load(integration_client);assert any(e.target==ids["artifact"] for e in snap.edges_from(eid,{"DERIVED_FROM"}))
    assert delete_relationship(integration_client,eid,"DERIVED_FROM",ids["artifact"])>=1
    snap=GraphSnapshot.load(integration_client);assert not any(e.target==ids["artifact"] for e in snap.edges_from(eid,{"DERIVED_FROM"}))

def test_phase10_tombstoned_source_is_removed_from_current_retrieval_but_kept_historically(integration_client, tmp_path):
    fixture=tmp_path/"p10-tombstone.json"
    first={"records":[{
        "external_id":"p10-tomb","record_type":"log_observation","observed_at":"2026-10-16T14:08:14+05:30",
        "name":"Pricing historical error","message":"region_scope cannot be null before tombstone",
        "system":"Pricing Tombstone API","system_canonical_id":"SYS-P10-TOMB",
        "incident_canonical_id":"INC-P10-TOMB","incident_name":"Tombstone retrieval incident",
        "artifacts":[{"name":"p10-tomb.log","content":"14:08:14 region_scope cannot be null before tombstone","mime_type":"text/plain","artifact_type":"LOG"}]
    }]}
    fixture.write_text(json.dumps(first),encoding="utf-8")
    cfg=SourceConfig(id="DS-P10-TOMB",source_type="telemetry",name="P10 tombstone telemetry",source_instance="p10-tomb",trust_class=TrustClass.STRONG,fixture_path=str(fixture))
    registry=SourceRegistry(integration_client);registry.register(cfg,persist=True)
    store=LocalArtifactStore(tmp_path/"p10-tomb-art");lex=BM25LexicalIndex();vec=LocalVectorIndex();indexer=RetrievalIndexer(integration_client,lexical=lex,vector=vec,artifact_store=store)
    pipeline=IngestionPipeline(integration_client,registry=registry,artifact_store=store,retrieval_indexer=indexer)
    assert pipeline.sync(cfg.id,mode="full",max_records=10).status.value=="SUCCEEDED"
    req=RetrievalRequest(query="region_scope cannot be null",tenant_id=integration_client.settings.tenant_id,seed_entity_ids=["INC-P10-TOMB"],max_graph_hops=6,max_results=10,retrieval_modes=[RetrievalMode.LEXICAL],writeback=False)
    service=RetrievalService(integration_client,lexical=lex,vector=vec,artifact_store=store)
    assert service.search(req).results

    second={"records":[{
        "external_id":"p10-tomb","record_type":"log_observation","observed_at":"2026-10-16T15:00:00+05:30",
        "deleted":True,"name":"Pricing historical error","message":"record removed",
        "system":"Pricing Tombstone API","system_canonical_id":"SYS-P10-TOMB",
        "incident_canonical_id":"INC-P10-TOMB","incident_name":"Tombstone retrieval incident"
    }]}
    fixture.write_text(json.dumps(second),encoding="utf-8")
    assert pipeline.sync(cfg.id,mode="full",max_records=10).status.value=="SUCCEEDED"
    assert service.search(req).results==[]
    historical=service.search(req.model_copy(update={"as_of":"2026-10-16T14:30:00+05:30"}))
    assert historical.results
    assert any("before tombstone" in r.text for r in historical.results)

def test_phase10_different_retrieval_plans_have_distinct_executions_but_reuse_same_source_evidence(integration_client):
    ids=_seed_scope(integration_client,"PLANPROV");lex,vec=_indexes(ids);service=RetrievalService(integration_client,lexical=lex,vector=vec)
    base=dict(investigation_id=ids["incident"],writeback=True)
    lexical=service.search(_request(integration_client,ids,retrieval_modes=[RetrievalMode.LEXICAL],**base))
    vector=service.search(_request(integration_client,ids,retrieval_modes=[RetrievalMode.VECTOR],**base))
    assert lexical.execution_id!=vector.execution_id
    assert lexical.evidence_ids and vector.evidence_ids
    assert set(lexical.evidence_ids)&set(vector.evidence_ids)
    shared=next(iter(set(lexical.evidence_ids)&set(vector.evidence_ids)))
    snap=GraphSnapshot.load(integration_client)
    incoming=[e.source for e in snap.edges_to(shared,{"RETURNED"})]
    assert lexical.execution_id in incoming and vector.execution_id in incoming

def test_phase10_rebuild_keeps_superseded_source_historical_regardless_of_node_iteration_order(integration_client):
    upsert_node(integration_client,"DataSource","DS-P10-REBUILD-VERS",{"name":"versioned source","source_type":"telemetry"})
    upsert_node(integration_client,"SourceRecord","SR-P10-Z-OLD",{"name":"old","source_type":"telemetry","source_id":"DS-P10-REBUILD-VERS","source_entity_id":"same","observed_at":"2026-10-16T14:00:00+05:30","raw_metadata":"legacy region_scope evidence","checksum":"old"})
    upsert_node(integration_client,"SourceRecord","SR-P10-A-NEW",{"name":"new","source_type":"telemetry","source_id":"DS-P10-REBUILD-VERS","source_entity_id":"same","observed_at":"2026-10-16T15:00:00+05:30","raw_metadata":"replacement region_scope evidence","checksum":"new"})
    upsert_relationship(integration_client,"SR-P10-Z-OLD","DERIVED_FROM","DS-P10-REBUILD-VERS",{"valid_from":"2026-10-16T14:00:00+05:30"})
    upsert_relationship(integration_client,"SR-P10-A-NEW","DERIVED_FROM","DS-P10-REBUILD-VERS",{"valid_from":"2026-10-16T15:00:00+05:30"})
    upsert_relationship(integration_client,"SR-P10-A-NEW","SUPERSEDES","SR-P10-Z-OLD",{"valid_from":"2026-10-16T23:00:00+05:30"})
    lex=BM25LexicalIndex();vec=LocalVectorIndex();RetrievalIndexer(integration_client,lexical=lex,vector=vec).rebuild()
    current=[r.document_id for r in lex.search("legacy region_scope",tenant_id=integration_client.settings.tenant_id)]
    historical=[r.document_id for r in lex.search("legacy region_scope",tenant_id=integration_client.settings.tenant_id,as_of="2026-10-16T14:30:00+05:30")]
    assert "SR-P10-Z-OLD" not in current
    assert "SR-P10-Z-OLD" in historical
