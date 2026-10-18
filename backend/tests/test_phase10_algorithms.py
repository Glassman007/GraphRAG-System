from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
import json
import pytest

from backend.app.retrieval.models import IndexedDocument, RetrievalMode, RetrievalRequest, GraphScope, RetrievalResult
from backend.app.retrieval.utils import content_hash, temporal_visible
from backend.app.retrieval.lexical import BM25LexicalIndex
from backend.app.retrieval.vector import HashingEmbeddingProvider, LocalVectorIndex
from backend.app.retrieval.chunking import DocumentChunker, ChunkingConfig
from backend.app.retrieval.graph_scope import GraphScopeResolver
from backend.app.retrieval.planner import RetrievalPlanner
from backend.app.retrieval.fusion import reciprocal_rank_fusion
from backend.app.services.phase4_graph import GraphSnapshot, GraphEdge
from backend.app.graph.schema import validate_label, validate_relationship


def node(i,label,**props): return {"id":i,"tenant_id":"northstar","_labels":["Entity",label],**props}
def edge(a,r,b,**props): return GraphEdge(a,r,b,props)

def doc(i,text,*,tenant="northstar",entities=None,source=None,artifact=None,observed=None,valid_until=None,kind="CHUNK"):
    return IndexedDocument(document_id=i,text=text,tenant_id=tenant,entity_ids=list(entities or []),data_source_id=source,artifact_id=artifact,observed_at=observed,valid_until=valid_until,document_type=kind,content_hash=content_hash(text))


def scope_snapshot():
    nodes={
        "INC":node("INC","Incident",name="Checkout outage"),
        "CHECKOUT":node("CHECKOUT","System",name="Checkout"),
        "PRICING":node("PRICING","System",name="Pricing API"),
        "DPL":node("DPL","Deployment",name="DPL-882"),
        "MIG":node("MIG","Change",name="MIG-203"),
        "SR":node("SR","SourceRecord",source_type="telemetry",observed_at="2026-10-16T14:08:14+05:30"),
        "DS":node("DS","DataSource",source_type="telemetry"),
        "ART":node("ART","Artifact",name="pricing-error.log"),
        "DOC":node("DOC","Document",name="Migration notes"),
        "CH":node("CH","Chunk",name="chunk"),
        "OTHER":node("OTHER","System",name="Unrelated Search"),
        "SR-OTHER":node("SR-OTHER","SourceRecord",source_type="slack"),
        "DS-OTHER":node("DS-OTHER","DataSource",source_type="slack"),
        "ART-OTHER":node("ART-OTHER","Artifact",name="distractor"),
    }
    edges=[
        edge("INC","AFFECTS","CHECKOUT"),edge("CHECKOUT","DEPENDS_ON","PRICING"),edge("DPL","CONTAINS","MIG"),edge("MIG","AFFECTS","PRICING"),
        edge("SR","NORMALIZED_TO","PRICING"),edge("SR","DERIVED_FROM","DS"),edge("SR","REFERENCES","ART"),edge("DOC","HAS_ARTIFACT","ART"),edge("CH","PART_OF","ART"),
        edge("SR-OTHER","NORMALIZED_TO","OTHER"),edge("SR-OTHER","DERIVED_FROM","DS-OTHER"),edge("SR-OTHER","REFERENCES","ART-OTHER"),
    ]
    return GraphSnapshot(nodes,edges)


def request(**kwargs):
    base=dict(query="Why did Checkout fail during DPL-882?",tenant_id="northstar",seed_entity_ids=["INC"],max_graph_hops=4,writeback=False)
    base.update(kwargs);return RetrievalRequest(**base)

# ---------------- lexical ----------------

def test_lexical_index_stores_chunk():
    idx=BM25LexicalIndex(); idx.index_document(doc("A","region_scope cannot be null")); assert idx.health_check()["documents"]==1

def test_lexical_exact_phrase_retrieval():
    idx=BM25LexicalIndex();idx.index_document(doc("A","ERROR region_scope cannot be null")); assert idx.search("region_scope cannot be null",tenant_id="northstar")[0].document_id=="A"

def test_lexical_identifier_ranks_correctly():
    idx=BM25LexicalIndex();idx.index_document(doc("A","migration MIG-203 details"));idx.index_document(doc("B","migration general details"));assert idx.search("MIG-203",tenant_id="northstar")[0].document_id=="A"

def test_lexical_graph_scope_excludes_keyword_heavy_distractor():
    idx=BM25LexicalIndex();idx.index_document(doc("GOOD","region_scope cannot be null",entities=["PRICING"]));idx.index_document(doc("BAD","region_scope cannot be null "*30,entities=["OTHER"]));out=idx.search("region_scope cannot be null",tenant_id="northstar",allowed_entity_ids={"PRICING"});assert [x.document_id for x in out]==["GOOD"]

def test_lexical_source_scope_filter():
    idx=BM25LexicalIndex();idx.index_document(doc("A","error",source="DS"));idx.index_document(doc("B","error",source="OTHER"));assert [x.document_id for x in idx.search("error",tenant_id="northstar",allowed_source_ids={"DS"})]==["A"]

def test_lexical_tenant_isolation():
    idx=BM25LexicalIndex();idx.index_document(doc("A","secret error",tenant="a"));idx.index_document(doc("B","secret error",tenant="b"));assert [x.document_id for x in idx.search("secret error",tenant_id="a")]==["A"]

def test_lexical_temporal_future_excluded():
    idx=BM25LexicalIndex();idx.index_document(doc("E3","region error",observed="2026-10-16T14:08:14+05:30"));idx.index_document(doc("E4","region error",observed="2026-10-16T14:12:00+05:30"));ids=[x.document_id for x in idx.search("region error",tenant_id="northstar",as_of="2026-10-16T14:09:00+05:30")];assert ids==["E3"]

def test_lexical_superseded_current_content_excluded():
    idx=BM25LexicalIndex();idx.index_document(doc("OLD","legacy wording",valid_until="2026-10-16T15:00:00+05:30"));assert idx.search("legacy",tenant_id="northstar")==[]



def test_lexical_same_content_updates_temporal_metadata():
    idx=BM25LexicalIndex(); original=doc("A","legacy wording")
    idx.index_document(original)
    idx.index_document(original.model_copy(update={"valid_until":"2026-10-16T15:00:00+05:30"}))
    assert idx.search("legacy",tenant_id="northstar")==[]
    assert idx.search("legacy",tenant_id="northstar",as_of="2026-10-16T14:30:00+05:30")

def test_lexical_persists_and_reloads(tmp_path):
    p=tmp_path/"lex.json";a=BM25LexicalIndex(p);a.index_document(doc("A","hello graph"));b=BM25LexicalIndex(p);assert b.search("graph",tenant_id="northstar")[0].document_id=="A"

# ---------------- vector ----------------

def test_embedding_is_deterministic():
    p=HashingEmbeddingProvider();assert p.embed("schema migration")==p.embed("schema migration")

def test_embedding_dimensions_fixed(): assert len(HashingEmbeddingProvider(64).embed("x"))==64

def test_vector_index_persists_vector():
    idx=LocalVectorIndex();idx.index_document(doc("A","schema migration"));assert "A" in idx.vectors

def test_vector_semantic_paraphrase_retrieval():
    idx=LocalVectorIndex();idx.index_document(doc("HIST","old worker rejected after database constraint migration",entities=["INC-074"]));idx.index_document(doc("X","quarterly marketing planning",entities=["OTHER"]));out=idx.search("schema compatibility during mixed rollout",tenant_id="northstar",allowed_entity_ids={"INC-074"});assert out and out[0].document_id=="HIST"

def test_vector_graph_scope_excludes_semantic_distractor():
    idx=LocalVectorIndex();idx.index_document(doc("GOOD","old worker rejected after database constraint migration",entities=["INC-074"]));idx.index_document(doc("BAD","legacy client incompatible with schema deployment migration",entities=["OTHER"]));ids=[x.document_id for x in idx.search("schema compatibility during deployment",tenant_id="northstar",allowed_entity_ids={"INC-074"})];assert ids==["GOOD"]

def test_vector_tenant_isolation():
    idx=LocalVectorIndex();idx.index_document(doc("A","schema migration",tenant="a"));idx.index_document(doc("B","schema migration",tenant="b"));assert [x.document_id for x in idx.search("schema migration",tenant_id="a")]==["A"]

def test_vector_temporal_future_excluded():
    idx=LocalVectorIndex();idx.index_document(doc("E3","schema error",observed="2026-10-16T14:08:14+05:30"));idx.index_document(doc("E4","schema error",observed="2026-10-16T14:12:00+05:30"));assert [x.document_id for x in idx.search("schema error",tenant_id="northstar",as_of="2026-10-16T14:09:00+05:30")]==["E3"]



def test_vector_same_content_updates_temporal_metadata_without_reembedding():
    class P(HashingEmbeddingProvider):
        def __init__(self):super().__init__();self.calls=0
        def embed(self,text):self.calls+=1;return super().embed(text)
    p=P();idx=LocalVectorIndex(p);original=doc("A","schema migration")
    idx.index_document(original)
    idx.index_document(original.model_copy(update={"valid_until":"2026-10-16T15:00:00+05:30"}))
    assert p.calls==1
    assert idx.search("schema migration",tenant_id="northstar")==[]
    assert idx.search("schema migration",tenant_id="northstar",as_of="2026-10-16T14:30:00+05:30")

def test_vector_persists_and_reloads(tmp_path):
    p=tmp_path/"vec.json";a=LocalVectorIndex(path=p);a.index_document(doc("A","schema migration"));b=LocalVectorIndex(path=p);assert b.search("schema migration",tenant_id="northstar")[0].document_id=="A"

def test_vector_unchanged_document_not_reembedded():
    class P(HashingEmbeddingProvider):
        def __init__(self):super().__init__();self.calls=0
        def embed(self,text):self.calls+=1;return super().embed(text)
    p=P();idx=LocalVectorIndex(p);d=doc("A","schema migration");idx.index_document(d);idx.index_document(d);assert p.calls==1

# ---------------- document/chunk ----------------

def test_markdown_chunking_preserves_heading():
    chunks=DocumentChunker().chunk(document_id="D",text="# Compatibility\nBackward compatibility is required.",tenant_id="northstar");assert chunks[0].metadata["heading"]=="Compatibility"

def test_chunk_ids_are_stable():
    c=DocumentChunker();a=c.chunk(document_id="D",text="hello world",tenant_id="northstar");b=c.chunk(document_id="D",text="hello world",tenant_id="northstar");assert [x.document_id for x in a]==[x.document_id for x in b]

def test_chunk_ids_change_when_content_changes():
    c=DocumentChunker();a=c.chunk(document_id="D",text="hello world",tenant_id="northstar")[0];b=c.chunk(document_id="D",text="hello changed",tenant_id="northstar")[0];assert a.document_id!=b.document_id

def test_long_document_uses_overlap():
    c=DocumentChunker(ChunkingConfig(max_chars=20,overlap_chars=5));parts=c.chunk(document_id="D",text="x"*50,tenant_id="northstar");assert len(parts)>=3 and parts[1].metadata["char_start"]<parts[0].metadata["char_end"]

def test_json_chunking_uses_top_level_keys():
    parts=DocumentChunker().chunk(document_id="D",text=json.dumps({"errors":[1,2],"service":"pricing"}),tenant_id="northstar",document_type="JSON");assert {p.metadata["heading"] for p in parts}=={"errors","service"}

def test_chunk_preserves_artifact_provenance():
    p=DocumentChunker().chunk(document_id="D",text="hello",tenant_id="northstar",artifact_id="ART",source_record_id="SR",data_source_id="DS")[0];assert (p.artifact_id,p.source_record_id,p.data_source_id)==("ART","SR","DS")

def test_chunk_preserves_entity_scope():
    p=DocumentChunker().chunk(document_id="D",text="hello",tenant_id="northstar",entity_ids=["SYS"])[0];assert p.entity_ids==["SYS"]

def test_chunk_body_hash_is_deterministic():
    p=DocumentChunker().chunk(document_id="D",text="hello",tenant_id="northstar")[0];assert p.content_hash==content_hash("hello")

# ---------------- graph first ----------------

def test_graph_scope_resolves_seed_entity():
    s=GraphScopeResolver.resolve_snapshot(scope_snapshot(),request());assert s.seed_entities==["INC"] and "INC" in s.entities

def test_graph_scope_bounded_neighborhood():
    s=GraphScopeResolver.resolve_snapshot(scope_snapshot(),request(max_graph_hops=1));assert "CHECKOUT" in s.entities and "PRICING" not in s.entities

def test_graph_scope_source_selection_is_graph_derived():
    s=GraphScopeResolver.resolve_snapshot(scope_snapshot(),request(max_graph_hops=5));assert "DS" in s.data_sources and "DS-OTHER" not in s.data_sources

def test_graph_scope_artifact_selection_is_graph_derived():
    s=GraphScopeResolver.resolve_snapshot(scope_snapshot(),request(max_graph_hops=5));assert "ART" in s.artifacts and "ART-OTHER" not in s.artifacts

def test_graph_scope_chunk_discovered_through_artifact():
    s=GraphScopeResolver.resolve_snapshot(scope_snapshot(),request(max_graph_hops=6));assert "CH" in s.chunks

def test_graph_scope_expands_direct_chunk_when_artifact_is_at_hop_boundary():
    s=GraphScopeResolver.resolve_snapshot(scope_snapshot(),request(max_graph_hops=4))
    assert "ART" in s.artifacts
    assert "CH" in s.chunks
    assert "ART-OTHER" not in s.artifacts and "SR-OTHER" not in s.source_records

def test_remove_incident_system_relation_changes_scope():
    snap=scope_snapshot();before=GraphScopeResolver.resolve_snapshot(snap,request(max_graph_hops=5));snap.remove_edges(lambda e:e.source=="INC" and e.type=="AFFECTS");after=GraphScopeResolver.resolve_snapshot(snap,request(max_graph_hops=5));assert "ART" in before.artifacts and "ART" not in after.artifacts

def test_remove_source_artifact_provenance_changes_scope():
    snap=scope_snapshot();before=GraphScopeResolver.resolve_snapshot(snap,request(max_graph_hops=5));snap.remove_edges(lambda e:e.source=="SR" and e.type=="REFERENCES");after=GraphScopeResolver.resolve_snapshot(snap,request(max_graph_hops=5));assert "ART" in before.artifacts and "ART" not in after.artifacts

def test_graph_scope_excludes_unrelated_source():
    s=GraphScopeResolver.resolve_snapshot(scope_snapshot(),request(max_graph_hops=5));assert "SR-OTHER" not in s.source_records

def test_graph_scope_filters_allowed_source_types():
    s=GraphScopeResolver.resolve_snapshot(scope_snapshot(),request(max_graph_hops=5,allowed_source_types=["telemetry"]));assert s.data_sources==["DS"]

def test_graph_scope_query_entity_discovery_without_seed():
    r=request(seed_entity_ids=[],query="What happened to Checkout?");s=GraphScopeResolver.resolve_snapshot(scope_snapshot(),r);assert "CHECKOUT" in s.seed_entities

def test_graph_scope_invalid_seed_is_ignored():
    s=GraphScopeResolver.resolve_snapshot(scope_snapshot(),request(seed_entity_ids=["NOPE"]));assert s.seed_entities==[]

def test_graph_scope_paths_are_explainable():
    s=GraphScopeResolver.resolve_snapshot(scope_snapshot(),request(max_graph_hops=3));assert any(p["node_ids"][:2]==["INC","CHECKOUT"] for p in s.paths)



def test_retrieval_plan_scope_hash_ignores_runtime_writeback_noise():
    planner=RetrievalPlanner();req=request(retrieval_modes=[RetrievalMode.LEXICAL])
    base=GraphScope(seed_entities=["INC"],entities=["INC","SYS","SR","ART","CH"],data_sources=["DS"],source_types={"DS":"telemetry"},source_records=["SR"],artifacts=["ART"],chunks=["CH"],temporal_scope={"as_of":None})
    noisy=base.model_copy(update={
        "entities":base.entities+["EVID-RET-X","RET-X"],
        "relationships":[{"source":"EVID-RET-X","type":"ABOUT","target":"INC"}],
        "paths":[{"node_ids":["INC","EVID-RET-X"],"edges":[]}],
    })
    assert planner.plan(req,base).graph_scope_hash==planner.plan(req,noisy).graph_scope_hash

# ---------------- routing ----------------

@pytest.mark.parametrize("query,expected",[
    ("region_scope cannot be null",RetrievalMode.LEXICAL),
    ("MIG-203",RetrievalMode.LEXICAL),
    ('"exact policy wording"',RetrievalMode.LEXICAL),
    ("Have we seen a similar failure before?",RetrievalMode.VECTOR),
    ("Why did checkout fail?",RetrievalMode.VECTOR),
])
def test_planner_routes_expected_modes(query,expected):
    p=RetrievalPlanner().plan(request(query=query),GraphScope(seed_entities=["INC"]));assert expected in p.modes

def test_planner_known_artifact_routes_document():
    s=GraphScope(seed_entities=["INC"],artifacts=["ART"]);assert RetrievalMode.DOCUMENT in RetrievalPlanner().plan(request(),s).modes

def test_planner_metadata_query_routes_metadata():
    assert RetrievalMode.METADATA in RetrievalPlanner().plan(request(query="When was this source created?"),GraphScope(seed_entities=["INC"])).modes

def test_planner_explicit_modes_override_inference():
    p=RetrievalPlanner().plan(request(retrieval_modes=[RetrievalMode.LEXICAL]),GraphScope(seed_entities=["INC"],artifacts=["ART"]));assert p.modes==[RetrievalMode.LEXICAL]

def test_planner_returns_reason_for_each_mode():
    p=RetrievalPlanner().plan(request(query="MIG-203"),GraphScope(seed_entities=["INC"]));assert all(m.value in p.reasons for m in p.modes)

def test_planner_scope_hash_deterministic():
    s=GraphScope(seed_entities=["INC"]);p=RetrievalPlanner();assert p.plan(request(),s).graph_scope_hash==p.plan(request(),s).graph_scope_hash

# ---------------- hybrid ----------------

def rr(i,method,score,rank,docid):
    return RetrievalResult(result_id=i,retrieval_method=method,score=score,text="x",retrieved_at="2026-10-16T00:00:00+05:30",query="q",rank=rank,document_id=docid)

def test_rrf_fuses_deterministically():
    a=[rr("1",RetrievalMode.LEXICAL,2,1,"A"),rr("2",RetrievalMode.LEXICAL,1,2,"B")];b=[rr("3",RetrievalMode.VECTOR,.9,1,"B"),rr("4",RetrievalMode.VECTOR,.8,2,"A")];x=reciprocal_rank_fusion([a,b]);y=reciprocal_rank_fusion([a,b]);assert [(r.document_id,r.score) for r in x]==[(r.document_id,r.score) for r in y]

def test_rrf_deduplicates_same_document():
    out=reciprocal_rank_fusion([[rr("1",RetrievalMode.LEXICAL,2,1,"A")],[rr("2",RetrievalMode.VECTOR,.8,1,"A")]]);assert len(out)==1

def test_rrf_rewards_multiretriever_presence():
    out=reciprocal_rank_fusion([[rr("1",RetrievalMode.LEXICAL,2,1,"A"),rr("2",RetrievalMode.LEXICAL,1,2,"B")],[rr("3",RetrievalMode.VECTOR,.8,1,"B")]]);assert out[0].document_id=="B"

def test_rrf_limit_respected():
    out=reciprocal_rank_fusion([[rr(str(i),RetrievalMode.LEXICAL,1,i,f"D{i}") for i in range(1,6)]],limit=2);assert len(out)==2

# ---------------- temporal/security/schema ----------------

def test_temporal_visible_e003_at_1409(): assert temporal_visible("2026-10-16T14:08:14+05:30",None,None,"2026-10-16T14:09:00+05:30")
def test_temporal_invisible_e004_at_1409(): assert not temporal_visible("2026-10-16T14:12:00+05:30",None,None,"2026-10-16T14:09:00+05:30")
def test_temporal_current_excludes_closed_version(): assert not temporal_visible(None,None,"2026-10-16T14:00:00+05:30",None)
def test_schema_accepts_chunk_label(): assert validate_label("Chunk")=="Chunk"
def test_schema_accepts_retrieval_execution_label(): assert validate_label("RetrievalExecution")=="RetrievalExecution"
@pytest.mark.parametrize("rel",["REQUESTED_BY","FOR_TASK","USED_SOURCE","RETURNED","HAS_RETRIEVAL","DOCUMENTED_BY","HAS_ARTIFACT"])
def test_schema_accepts_phase10_relationships(rel): assert validate_relationship(rel)==rel

def test_graph_scope_current_hides_artifact_whose_only_source_record_is_superseded_tombstone():
    snap=scope_snapshot()
    snap.nodes["SR-NEW"]=node("SR-NEW","SourceRecord",source_type="telemetry",observed_at="2026-10-16T15:00:00+05:30",deleted=True,status="TOMBSTONED")
    snap.add_edge("SR-NEW","SUPERSEDES","SR",{"valid_from":"2026-10-16T15:00:00+05:30"})
    current=GraphScopeResolver.resolve_snapshot(snap,request(max_graph_hops=6))
    assert "SR" not in current.source_records
    assert "ART" not in current.artifacts


def test_graph_scope_historical_as_of_uses_source_observation_for_ingestion_provenance():
    snap=scope_snapshot()
    # Reproduce Phase 9 behavior where provenance edges can be created at ingestion time
    # after the source observation they represent.
    snap.remove_edges(lambda e:e.source=="SR" and e.type in {"NORMALIZED_TO","DERIVED_FROM","REFERENCES"})
    late_ingestion="2026-10-16T23:00:00+05:30"
    snap.add_edge("SR","NORMALIZED_TO","PRICING",{"valid_from":late_ingestion})
    snap.add_edge("SR","DERIVED_FROM","DS",{"valid_from":late_ingestion})
    snap.add_edge("SR","REFERENCES","ART",{"valid_from":late_ingestion})
    snap.nodes["SR-NEW"]=node("SR-NEW","SourceRecord",source_type="telemetry",observed_at="2026-10-16T15:00:00+05:30",deleted=True,status="TOMBSTONED")
    # The supersession relationship itself was persisted later at ingestion time;
    # source observation time still controls retrieval history.
    snap.add_edge("SR-NEW","SUPERSEDES","SR",{"valid_from":"2026-10-16T23:00:00+05:30"})
    historical=GraphScopeResolver.resolve_snapshot(snap,request(max_graph_hops=6,as_of="2026-10-16T14:09:00+05:30"))
    assert "SR" in historical.source_records
    assert "ART" in historical.artifacts
    after_source_tombstone=GraphScopeResolver.resolve_snapshot(snap,request(max_graph_hops=6,as_of="2026-10-16T16:00:00+05:30"))
    assert "SR" not in after_source_tombstone.source_records
    assert "ART" not in after_source_tombstone.artifacts

@pytest.mark.parametrize("mode,source_type",[(RetrievalMode.SQL,"database"),(RetrievalMode.API,"internal_api")])
def test_configured_specialized_retriever_can_refresh_only_graph_selected_server_configured_source(tmp_path,mode,source_type):
    from backend.app.ingestion.models import SourceConfig, TrustClass
    from backend.app.ingestion.registry import SourceRegistry
    from backend.app.retrieval.retrievers import ConfiguredSourceRetriever

    fixture=tmp_path/f"{source_type}.json"
    fixture.write_text(json.dumps({"records":[{"external_id":"row-1","record_type":"record","observed_at":"2026-10-16T14:00:00+05:30","detail":"pricing compatibility evidence"}]}),encoding="utf-8")
    cfg=SourceConfig(id="DS-CONFIGURED",source_type=source_type,name="configured",source_instance="configured-instance",trust_class=TrustClass.STRONG,fixture_path=str(fixture))
    registry=SourceRegistry();registry.register(cfg,persist=False)
    snap=GraphSnapshot({"DS-CONFIGURED":node("DS-CONFIGURED","DataSource",source_type=source_type),"SYS":node("SYS","System",name="Pricing")},[])
    scope=GraphScope(seed_entities=["SYS"],entities=["SYS","DS-CONFIGURED"],data_sources=["DS-CONFIGURED"],source_types={"DS-CONFIGURED":source_type})
    req=request(seed_entity_ids=["SYS"],retrieval_modes=[mode],metadata_filters={"refresh_external":True})
    out=ConfiguredSourceRetriever(snap,mode,{source_type},registry).retrieve(req,scope)
    assert out and out[0].source_id=="DS-CONFIGURED"
    assert out[0].metadata["external_refresh"] is True
    assert "pricing compatibility evidence" in out[0].text

def test_direct_document_lookup_reads_only_graph_selected_artifact():
    from backend.app.retrieval.document import DocumentRetriever
    snap=GraphSnapshot({
        "ART-IN":node("ART-IN","Artifact",name="selected",content="backward compatibility policy"),
        "ART-OUT":node("ART-OUT","Artifact",name="unrelated",content="backward compatibility policy repeated repeated"),
    },[])
    scope=GraphScope(seed_entities=["POL"],entities=["POL","ART-IN"],artifacts=["ART-IN"])
    out=DocumentRetriever(snap).retrieve(request(seed_entity_ids=["POL"],query="backward compatibility"),scope)
    assert [r.artifact_id for r in out]==["ART-IN"]


def test_graph_scope_temporal_scope_echoes_as_of():
    point="2026-10-16T14:09:00+05:30"
    scope=GraphScopeResolver.resolve_snapshot(scope_snapshot(),request(as_of=point,max_graph_hops=5))
    assert scope.temporal_scope["as_of"]==point


def test_deterministic_rerank_prefers_closer_graph_match_when_retrieval_score_ties():
    from backend.app.retrieval.rerank import deterministic_rerank
    snap=GraphSnapshot({"DS":node("DS","DataSource",trust_class="STANDARD")},[])
    scope=GraphScope(seed_entities=["INC"],retrieval_candidates=[{"entity_id":"NEAR","graph_distance":1},{"entity_id":"FAR","graph_distance":4}])
    near=RetrievalResult(result_id="near",retrieval_method=RetrievalMode.LEXICAL,score=1.0,source_id="DS",text="x",retrieved_at="2026-10-16T00:00:00+05:30",query="q",rank=2,matched_entity_ids=["NEAR"])
    far=RetrievalResult(result_id="far",retrieval_method=RetrievalMode.LEXICAL,score=1.0,source_id="DS",text="x",retrieved_at="2026-10-16T00:00:00+05:30",query="q",rank=1,matched_entity_ids=["FAR"])
    out=deterministic_rerank([far,near],scope,snap)
    assert [r.result_id for r in out]==["near","far"]


def test_deterministic_rerank_uses_authority_as_tiebreak_without_dropping_lower_authority():
    from backend.app.retrieval.rerank import deterministic_rerank
    snap=GraphSnapshot({
        "DS-HI":node("DS-HI","DataSource",trust_class="AUTHORITATIVE"),
        "DS-LO":node("DS-LO","DataSource",trust_class="UNTRUSTED"),
    },[])
    scope=GraphScope(seed_entities=["INC"])
    hi=RetrievalResult(result_id="hi",retrieval_method=RetrievalMode.LEXICAL,score=1.0,source_id="DS-HI",text="supports",retrieved_at="2026-10-16T00:00:00+05:30",query="q",rank=2)
    lo=RetrievalResult(result_id="lo",retrieval_method=RetrievalMode.LEXICAL,score=1.0,source_id="DS-LO",text="contradicts",retrieved_at="2026-10-16T00:00:00+05:30",query="q",rank=1)
    out=deterministic_rerank([lo,hi],scope,snap)
    assert [r.result_id for r in out]==["hi","lo"]
    assert {r.result_id for r in out}=={"hi","lo"}

def test_graph_scope_source_type_restriction_also_filters_artifacts_and_chunks():
    snap=scope_snapshot()
    # Connect the unrelated Slack provenance into the same neighborhood so source-type
    # filtering, rather than disconnected topology, is what excludes it.
    snap.add_edge("SR-OTHER","NORMALIZED_TO","PRICING")
    snap.nodes["CH-OTHER"]=node("CH-OTHER","Chunk",name="other chunk")
    snap.add_edge("CH-OTHER","PART_OF","ART-OTHER")
    scoped=GraphScopeResolver.resolve_snapshot(snap,request(max_graph_hops=6,allowed_source_types=["telemetry"]))
    assert "DS" in scoped.data_sources and "DS-OTHER" not in scoped.data_sources
    assert "ART" in scoped.artifacts and "ART-OTHER" not in scoped.artifacts
    assert "CH" in scoped.chunks and "CH-OTHER" not in scoped.chunks

def test_derived_indexes_can_be_cleared_before_rebuild():
    lex=BM25LexicalIndex();vec=LocalVectorIndex();d=doc("STALE","stale orphaned content")
    lex.index_document(d);vec.index_document(d)
    lex.clear();vec.clear()
    assert lex.documents=={}
    assert vec.documents=={} and vec.vectors=={}
